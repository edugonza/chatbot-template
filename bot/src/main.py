"""Entrypoint: restores the Matrix session, wires up the model, and runs the sync loop."""

from __future__ import annotations

import asyncio
import logging
import os
import signal

from matrix_bridge import MatrixClient

from .config import Settings
from .handlers import BotHandlers
from .history import ConversationHistory
from .llm import Responder
from .verification import VerificationPolicy

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
# httpx (used by google-genai) logs every request at INFO.
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


async def run() -> None:
    settings = Settings.from_env()

    client = await MatrixClient.restore(
        homeserver=settings.matrix_homeserver,
        user_id=settings.matrix_user_id,
        device_id=settings.matrix_device_id,
        access_token=settings.matrix_access_token,
        store_path=settings.matrix_store_path,
        store_passphrase=settings.matrix_store_passphrase,
    )

    status = await client.cross_signing_status()
    if not status.is_complete:
        logger.warning(
            "This device doesn't hold the cross-signing keys (%s), so clients will show the "
            "bot as unverified. Re-run `python -m scripts.login` to fix it.",
            status,
        )

    history = ConversationHistory(
        db_path=settings.history_db_path,
        context_turns=settings.history_context_turns,
        context_batch=settings.history_context_batch,
    )
    responder = Responder(
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
        history=history,
    )
    client.set_handlers(
        events=BotHandlers(client, settings, responder, history),
        verification=VerificationPolicy(client, settings),
    )

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)

    logger.info("Logged in as %s (device %s), starting sync loop", client.user_id, client.device_id)
    sync_task = asyncio.create_task(client.sync_forever())
    stop_task = asyncio.create_task(stop_event.wait())

    try:
        done, _ = await asyncio.wait({sync_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
        if sync_task in done:
            sync_task.result()  # surface the error that ended the sync loop
    finally:
        sync_task.cancel()
        stop_task.cancel()
        await asyncio.gather(sync_task, stop_task, return_exceptions=True)
        logger.info("Shut down cleanly")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
