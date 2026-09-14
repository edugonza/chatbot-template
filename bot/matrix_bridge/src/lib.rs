//! Python bindings over matrix-rust-sdk, shaped for bots.
//!
//! The Rust side owns everything protocol-heavy — sync, E2EE, cross-signing
//! and the SAS verification state machine — and exposes a small async surface
//! to Python through pyo3-async-runtimes. Python receives raw event JSON and
//! makes decisions through a handler object; `python/matrix_bridge/client.py`
//! is the typed wrapper bot code is meant to use.

// matrix-sdk's futures nest deeply enough that proving they're `Send` exceeds
// the default trait-solver recursion limit.
#![recursion_limit = "256"]

use std::{
    io::IsTerminal,
    str::FromStr,
    sync::{Arc, Mutex, Once},
    time::Duration,
};

use futures_util::StreamExt;
use matrix_sdk::{
    Client, Room, RoomState,
    authentication::matrix::MatrixSession,
    config::SyncSettings,
    encryption::{
        CrossSigningResetAuthType,
        verification::{SasState, SasVerification, VerificationRequest, VerificationRequestState},
    },
    event_handler::RawEvent,
    media::{MediaFormat, MediaRequestParameters},
    ruma::{
        OwnedEventId, OwnedRoomId,
        api::client::uiaa,
        events::{
            key::verification::request::ToDeviceKeyVerificationRequestEvent,
            room::{
                MediaSource,
                member::{MembershipState, StrippedRoomMemberEvent},
                message::{MessageType, OriginalSyncRoomMessageEvent},
            },
        },
    },
    store::RoomLoadSettings,
};
use pyo3::{
    create_exception,
    exceptions::PyException,
    prelude::*,
    types::{PyBytes, PyTuple},
};
use pyo3_async_runtimes::{TaskLocals, tokio::future_into_py};
use tracing::{level_filters::LevelFilter, warn};
use tracing_subscriber::{filter::Targets, layer::SubscriberExt, util::SubscriberInitExt};

create_exception!(matrix_bridge, MatrixError, PyException);

fn to_py_err(err: impl std::fmt::Display) -> PyErr {
    MatrixError::new_err(err.to_string())
}

/// Builds the positional arguments of a Python callback once attached to the interpreter.
trait PyArgs: for<'py> FnOnce(Python<'py>) -> PyResult<Bound<'py, PyTuple>> + Send + 'static {}
impl<F> PyArgs for F where F: for<'py> FnOnce(Python<'py>) -> PyResult<Bound<'py, PyTuple>> + Send + 'static {}

struct Inner {
    client: Client,
    /// The Python object whose async methods receive events (see `_Dispatcher`).
    handler: Mutex<Option<Py<PyAny>>>,
    /// The asyncio loop the handler's coroutines run on, captured when syncing starts.
    locals: Mutex<Option<TaskLocals>>,
}

impl Inner {
    /// Call `handler.<method>(*args)` on the asyncio loop and await the coroutine.
    ///
    /// Returns `None` when no handler is registered or no loop is known yet.
    async fn call(&self, method: &'static str, args: impl PyArgs) -> PyResult<Option<Py<PyAny>>> {
        let future = Python::attach(|py| -> PyResult<_> {
            let handler = self.handler.lock().unwrap().as_ref().map(|h| h.clone_ref(py));
            let locals = self.locals.lock().unwrap().clone();
            let (Some(handler), Some(locals)) = (handler, locals) else {
                return Ok(None);
            };
            let coroutine = handler.bind(py).call_method1(method, args(py)?)?;
            pyo3_async_runtimes::into_future_with_locals(&locals, coroutine).map(Some)
        })?;

        match future {
            Some(future) => future.await.map(Some),
            None => Ok(None),
        }
    }

    /// Fire-and-forget a callback so a slow Python handler never blocks the sync loop.
    fn spawn_call(self: &Arc<Self>, method: &'static str, args: impl PyArgs) {
        let inner = self.clone();
        tokio::spawn(async move {
            if let Err(err) = inner.call(method, args).await {
                report(method, err);
            }
        });
    }

    /// Ask Python a yes/no question; anything but a truthy answer means no.
    async fn decide(&self, method: &'static str, args: impl PyArgs) -> bool {
        match self.call(method, args).await {
            Ok(Some(answer)) => Python::attach(|py| answer.bind(py).is_truthy()).unwrap_or(false),
            Ok(None) => false,
            Err(err) => {
                report(method, err);
                false
            }
        }
    }
}

fn report(method: &str, err: PyErr) {
    warn!("Python handler `{method}` raised an exception");
    Python::attach(|py| err.print(py));
}

fn args2(a: String, b: Option<String>) -> impl PyArgs {
    move |py| Ok((a, b).into_pyobject(py)?)
}

fn register_event_handlers(inner: &Arc<Inner>) {
    // Handlers are owned by the client, which `Inner` owns: hold a weak
    // reference so the two don't keep each other alive.
    let weak = Arc::downgrade(inner);
    inner.client.add_event_handler(
        move |event: StrippedRoomMemberEvent, room: Room, client: Client| {
            let weak = weak.clone();
            async move {
                let Some(inner) = weak.upgrade() else { return };
                if event.content.membership != MembershipState::Invite
                    || client.user_id() != Some(&*event.state_key)
                {
                    return;
                }
                let room_id = room.room_id().to_string();
                let sender = event.sender.to_string();
                inner.spawn_call("on_invite", move |py| Ok((room_id, sender).into_pyobject(py)?));
            }
        },
    );

    let weak = Arc::downgrade(inner);
    inner.client.add_event_handler(
        move |event: OriginalSyncRoomMessageEvent, room: Room, raw: RawEvent, client: Client| {
            let weak = weak.clone();
            async move {
                let Some(inner) = weak.upgrade() else { return };

                // In-room verification requests (what Element X sends when you
                // verify a user from a DM) arrive as room messages.
                if let MessageType::VerificationRequest(_) = &event.content.msgtype {
                    let request = client
                        .encryption()
                        .get_verification_request(&event.sender, &event.event_id)
                        .await;
                    match request {
                        Some(request) => {
                            tokio::spawn(handle_verification_request(inner, request));
                        }
                        None => warn!("No verification request found for {}", event.event_id),
                    }
                    return;
                }

                if room.state() != RoomState::Joined {
                    return;
                }
                let room_id = room.room_id().to_string();
                let json = raw.0.get().to_owned();
                inner.spawn_call("on_message", move |py| Ok((room_id, json).into_pyobject(py)?));
            }
        },
    );

    let weak = Arc::downgrade(inner);
    inner.client.add_event_handler(
        move |event: ToDeviceKeyVerificationRequestEvent, client: Client| {
            let weak = weak.clone();
            async move {
                let Some(inner) = weak.upgrade() else { return };
                let request = client
                    .encryption()
                    .get_verification_request(&event.sender, &event.content.transaction_id)
                    .await;
                match request {
                    Some(request) => {
                        tokio::spawn(handle_verification_request(inner, request));
                    }
                    None => warn!("No verification request found for {}", event.content.transaction_id),
                }
            }
        },
    );
}

async fn handle_verification_request(inner: Arc<Inner>, request: VerificationRequest) {
    let user_id = request.other_user_id().to_string();
    let room_id = request.room_id().map(|id| id.to_string());

    let accepted = inner
        .decide("on_verification_request", args2(user_id.clone(), room_id.clone()))
        .await;
    if !accepted {
        if let Err(err) = request.cancel().await {
            warn!("Failed to cancel verification request from {user_id}: {err}");
        }
        return;
    }

    // Subscribe before accepting so the transition to SAS can't be missed.
    let mut changes = request.changes();
    if let Err(err) = request.accept().await {
        warn!("Failed to accept verification request from {user_id}: {err}");
        return;
    }

    while let Some(state) = changes.next().await {
        match state {
            VerificationRequestState::Transitioned { verification } => {
                match verification.sas() {
                    Some(sas) => handle_sas(inner, sas, user_id, room_id).await,
                    None => {
                        warn!("Unsupported verification method from {user_id}, cancelling");
                        let _ = request.cancel().await;
                    }
                }
                return;
            }
            VerificationRequestState::Cancelled(info) => {
                let reason = info.reason().to_owned();
                inner.spawn_call("on_verification_cancelled", move |py| {
                    Ok((user_id, room_id, reason).into_pyobject(py)?)
                });
                return;
            }
            VerificationRequestState::Done => return,
            _ => {}
        }
    }
}

async fn handle_sas(
    inner: Arc<Inner>,
    sas: SasVerification,
    user_id: String,
    room_id: Option<String>,
) {
    let mut changes = sas.changes();
    if !sas.we_started() {
        if let Err(err) = sas.accept().await {
            warn!("Failed to accept SAS verification from {user_id}: {err}");
            return;
        }
    }

    while let Some(state) = changes.next().await {
        match state {
            SasState::KeysExchanged { emojis: Some(emojis), .. } => {
                let emojis: Vec<(String, String)> = emojis
                    .emojis
                    .iter()
                    .map(|emoji| (emoji.symbol.to_owned(), emoji.description.to_owned()))
                    .collect();
                let (inner, sas, user_id, room_id) =
                    (inner.clone(), sas.clone(), user_id.clone(), room_id.clone());
                // Decide off the state loop so a cancellation that arrives
                // while Python is deciding is still observed.
                tokio::spawn(async move {
                    let confirmed = inner
                        .decide("on_verification_emojis", move |py| {
                            Ok((user_id, room_id, emojis).into_pyobject(py)?)
                        })
                        .await;
                    let result = if confirmed { sas.confirm().await } else { sas.cancel().await };
                    if let Err(err) = result {
                        warn!("Failed to answer SAS verification: {err}");
                    }
                });
            }
            SasState::KeysExchanged { emojis: None, .. } => {
                warn!("SAS verification from {user_id} doesn't support emojis, cancelling");
                let _ = sas.cancel().await;
            }
            SasState::Done { .. } => {
                inner.spawn_call("on_verification_done", args2(user_id, room_id));
                return;
            }
            SasState::Cancelled(info) => {
                let reason = info.reason().to_owned();
                inner.spawn_call("on_verification_cancelled", move |py| {
                    Ok((user_id, room_id, reason).into_pyobject(py)?)
                });
                return;
            }
            _ => {}
        }
    }
}

async fn build_client(
    homeserver: String,
    store_path: String,
    store_passphrase: Option<String>,
) -> PyResult<Client> {
    Client::builder()
        .server_name_or_homeserver_url(homeserver)
        .sqlite_store(store_path, store_passphrase.as_deref())
        .build()
        .await
        .map_err(to_py_err)
}

async fn cross_signing_status(client: &Client) -> (bool, bool, bool) {
    client
        .encryption()
        .cross_signing_status()
        .await
        .map(|status| (status.has_master, status.has_self_signing, status.has_user_signing))
        .unwrap_or_default()
}

fn password_auth(
    client: &Client,
    password: Option<String>,
    session: Option<String>,
) -> PyResult<uiaa::AuthData> {
    let password = password
        .ok_or_else(|| MatrixError::new_err("the homeserver requires the account password"))?;
    let user_id =
        client.user_id().ok_or_else(|| MatrixError::new_err("the client is not logged in"))?;
    let mut auth = uiaa::Password::new(user_id.to_owned().into(), password);
    auth.session = session;
    Ok(uiaa::AuthData::Password(auth))
}

fn init_logging() {
    static INIT: Once = Once::new();
    INIT.call_once(|| {
        let configured = std::env::var("MATRIX_SDK_LOG_LEVEL")
            .ok()
            .and_then(|level| LevelFilter::from_str(&level).ok());
        let mut filter = Targets::new().with_default(configured.unwrap_or(LevelFilter::WARN));
        if configured.is_none() {
            // The HTTP client logs every non-2xx response as an error, including
            // expected 404s during login; failures that matter reach Python as
            // exceptions anyway. Key backup isn't set up, so the backups module
            // would warn on every message.
            filter = filter
                .with_target("matrix_sdk::http_client", LevelFilter::OFF)
                .with_target("matrix_sdk_crypto::backups", LevelFilter::ERROR);
        }
        let _ = tracing_subscriber::registry()
            .with(
                tracing_subscriber::fmt::layer()
                    .with_writer(std::io::stderr)
                    .with_ansi(std::io::stderr().is_terminal()),
            )
            .with(filter)
            .try_init();
    });
}

#[pyclass(module = "matrix_bridge._native", frozen)]
struct NativeClient {
    // Always `Some` until dropped; see `Drop`.
    inner: Option<Arc<Inner>>,
}

impl Drop for NativeClient {
    fn drop(&mut self) {
        // Python drops the client on its own thread, outside Tokio, but the
        // SDK's store connection pools need a runtime to shut down.
        if let Some(inner) = Option::take(&mut self.inner) {
            let _runtime = pyo3_async_runtimes::tokio::get_runtime().enter();
            drop(inner);
        }
    }
}

impl NativeClient {
    fn new(client: Client) -> Self {
        let inner =
            Arc::new(Inner { client, handler: Mutex::new(None), locals: Mutex::new(None) });
        register_event_handlers(&inner);
        Self { inner: Some(inner) }
    }

    fn inner(&self) -> &Arc<Inner> {
        Option::as_ref(&self.inner).expect("NativeClient used after drop")
    }

    fn remember_event_loop(&self, py: Python<'_>) -> PyResult<()> {
        let locals = pyo3_async_runtimes::tokio::get_current_locals(py)?;
        *self.inner().locals.lock().unwrap() = Some(locals);
        Ok(())
    }

    fn room(&self, room_id: &str) -> PyResult<Room> {
        let room_id = OwnedRoomId::try_from(room_id).map_err(to_py_err)?;
        self.inner()
            .client
            .get_room(&room_id)
            .ok_or_else(|| MatrixError::new_err(format!("unknown room {room_id}")))
    }
}

#[pymethods]
impl NativeClient {
    #[staticmethod]
    #[pyo3(signature = (homeserver, user_id, password, store_path, store_passphrase, device_name))]
    fn login(
        py: Python<'_>,
        homeserver: String,
        user_id: String,
        password: String,
        store_path: String,
        store_passphrase: Option<String>,
        device_name: String,
    ) -> PyResult<Bound<'_, PyAny>> {
        init_logging();
        future_into_py(py, async move {
            let client = build_client(homeserver, store_path, store_passphrase).await?;
            client
                .matrix_auth()
                .login_username(&user_id, &password)
                .initial_device_display_name(&device_name)
                .await
                .map_err(to_py_err)?;
            Ok(NativeClient::new(client))
        })
    }

    #[staticmethod]
    #[pyo3(signature = (homeserver, user_id, device_id, access_token, store_path, store_passphrase))]
    fn restore(
        py: Python<'_>,
        homeserver: String,
        user_id: String,
        device_id: String,
        access_token: String,
        store_path: String,
        store_passphrase: Option<String>,
    ) -> PyResult<Bound<'_, PyAny>> {
        init_logging();
        let session: MatrixSession = serde_json::from_value(serde_json::json!({
            "user_id": user_id,
            "device_id": device_id,
            "access_token": access_token,
        }))
        .map_err(to_py_err)?;

        future_into_py(py, async move {
            let client = build_client(homeserver, store_path, store_passphrase).await?;
            client
                .matrix_auth()
                .restore_session(session, RoomLoadSettings::default())
                .await
                .map_err(to_py_err)?;
            Ok(NativeClient::new(client))
        })
    }

    #[getter]
    fn user_id(&self) -> String {
        self.inner().client.user_id().map(|id| id.to_string()).unwrap_or_default()
    }

    #[getter]
    fn device_id(&self) -> String {
        self.inner().client.device_id().map(|id| id.to_string()).unwrap_or_default()
    }

    #[getter]
    fn access_token(&self) -> String {
        self.inner().client.access_token().unwrap_or_default()
    }

    fn set_handler(&self, handler: Py<PyAny>) {
        *self.inner().handler.lock().unwrap() = Some(handler);
    }

    fn sync_forever<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        self.remember_event_loop(py)?;
        let client = self.inner().client.clone();
        future_into_py(py, async move {
            let settings = SyncSettings::default().timeout(Duration::from_secs(30));
            client.sync(settings).await.map_err(to_py_err)
        })
    }

    fn sync_once<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        self.remember_event_loop(py)?;
        let client = self.inner().client.clone();
        future_into_py(py, async move {
            client.sync_once(SyncSettings::default()).await.map_err(to_py_err)?;
            Ok(())
        })
    }

    fn join_room<'py>(&self, py: Python<'py>, room_id: String) -> PyResult<Bound<'py, PyAny>> {
        let room_id = OwnedRoomId::try_from(room_id).map_err(to_py_err)?;
        let client = self.inner().client.clone();
        future_into_py(py, async move {
            client.join_room_by_id(&room_id).await.map_err(to_py_err)?;
            Ok(())
        })
    }

    fn send<'py>(
        &self,
        py: Python<'py>,
        room_id: String,
        event_type: String,
        content_json: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        let room = self.room(&room_id)?;
        let content: serde_json::Value = serde_json::from_str(&content_json).map_err(to_py_err)?;
        future_into_py(py, async move {
            let result = room.send_raw(&event_type, content).await.map_err(to_py_err)?;
            Ok(result.response.event_id.to_string())
        })
    }

    fn typing<'py>(
        &self,
        py: Python<'py>,
        room_id: String,
        typing: bool,
    ) -> PyResult<Bound<'py, PyAny>> {
        let room = self.room(&room_id)?;
        future_into_py(py, async move { room.typing_notice(typing).await.map_err(to_py_err) })
    }

    fn get_event<'py>(
        &self,
        py: Python<'py>,
        room_id: String,
        event_id: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        let room = self.room(&room_id)?;
        let event_id = OwnedEventId::try_from(event_id).map_err(to_py_err)?;
        future_into_py(py, async move {
            let event = room.event(&event_id, None).await.map_err(to_py_err)?;
            Ok(event.raw().json().get().to_owned())
        })
    }

    fn download_media<'py>(
        &self,
        py: Python<'py>,
        content_json: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        let source: MediaSource = serde_json::from_str(&content_json).map_err(to_py_err)?;
        let client = self.inner().client.clone();
        future_into_py(py, async move {
            let request = MediaRequestParameters { source, format: MediaFormat::File };
            let data = client.media().get_media_content(&request, true).await.map_err(to_py_err)?;
            Ok(Python::attach(|py| PyBytes::new(py, &data).unbind()))
        })
    }

    fn cross_signing_status<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let client = self.inner().client.clone();
        future_into_py(py, async move { Ok(cross_signing_status(&client).await) })
    }

    #[pyo3(signature = (password=None))]
    fn bootstrap_cross_signing<'py>(
        &self,
        py: Python<'py>,
        password: Option<String>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let client = self.inner().client.clone();
        future_into_py(py, async move {
            let encryption = client.encryption();
            // Servers implementing MSC3967 allow the first upload without auth;
            // otherwise we get a UIAA challenge and retry with the password.
            if let Err(err) = encryption.bootstrap_cross_signing_if_needed(None).await {
                let session = err.as_uiaa_response().map(|info| info.session.clone());
                let Some(session) = session else {
                    return Err(to_py_err(err));
                };
                let auth = password_auth(&client, password, session)?;
                encryption.bootstrap_cross_signing(Some(auth)).await.map_err(to_py_err)?;
            }
            Ok(cross_signing_status(&client).await)
        })
    }

    #[pyo3(signature = (password=None, on_approval_url=None))]
    fn reset_cross_signing<'py>(
        &self,
        py: Python<'py>,
        password: Option<String>,
        on_approval_url: Option<Py<PyAny>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let client = self.inner().client.clone();
        future_into_py(py, async move {
            let handle = client.encryption().reset_cross_signing().await.map_err(to_py_err)?;
            if let Some(handle) = handle {
                let auth = match handle.auth_type() {
                    CrossSigningResetAuthType::Uiaa(info) => {
                        password_auth(&client, password, info.session.clone())?
                    }
                    CrossSigningResetAuthType::OAuth(info) => {
                        let url = info.approval_url.to_string();
                        match &on_approval_url {
                            Some(callback) => {
                                Python::attach(|py| callback.call1(py, (url,)).map(drop))?
                            }
                            None => warn!("Approve the cross-signing reset at {url}"),
                        }
                        let mut oauth = uiaa::OAuth::new();
                        oauth.session = info.session.clone();
                        uiaa::AuthData::OAuth(oauth)
                    }
                };
                handle.auth(Some(auth)).await.map_err(to_py_err)?;
            }
            Ok(cross_signing_status(&client).await)
        })
    }
}

#[pymodule]
fn _native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("MatrixError", m.py().get_type::<MatrixError>())?;
    m.add_class::<NativeClient>()?;
    Ok(())
}
