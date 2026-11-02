# Bootstrap and deployment

Step-by-step instructions are in the [top-level README](../README.md). This doc
explains what each piece does and why.

## `scripts/login.py`: one-time device bootstrap

A Matrix *device* is a login session with its own E2EE keys. The bot needs
exactly one long-lived device whose keys live in the same store the running
bot uses. So the script runs **on the deployment host**, inside the bot image,
writing into the `bot-store` volume.

Steps:

1. Read the homeserver, user ID, password (prompted, never persisted), store
   path/passphrase and device name.
2. `MatrixClient.login(...)`: creates the device and the local crypto store.
3. `sync_once()`: uploads the device keys and one-time keys.
4. `bootstrap_cross_signing(password)`: creates master, self-signing and
   user-signing keys and signs this device, if the account has none.
5. If the account **already** has an identity (e.g. someone logged in with
   Element before), this device can't sign itself. The script offers
   `reset_cross_signing`:
   - UIAA homeservers: authenticates with the password.
   - OAuth / MAS homeservers: prints an approval URL and waits for the reset
     to be approved in a browser.
   - Resetting means anyone who verified the bot must verify it again.
6. Print `MATRIX_ACCESS_TOKEN`, `MATRIX_DEVICE_ID`, `MATRIX_USER_ID` and the
   cross-signing status.

The running bot only uses the access token, via `MatrixClient.restore`.

## Persistent state: the one rule

**Never delete the `bot-store` volume** (no `docker compose down -v`).

- The crypto store holds the device's private keys and the Megolm sessions
  it has received.
- If you lose it but keep the device ID, the bot can't decrypt anything and
  other devices keep encrypting for keys that no longer exist.
- Recovery: log out the old device, then rerun `scripts/login.py`.
- The same applies to `MATRIX_STORE_PASSPHRASE`: set it once, never change it.

## `bot/Dockerfile`

Two stages:

| Stage | Base | Does |
|---|---|---|
| `build` | `rust:1-slim-trixie` + uv | Installs Python 3.12 (uv-managed), runs `uv sync --frozen --no-dev --no-install-project --no-editable`, which compiles the bridge into a real wheel. Cargo registry and uv caches are BuildKit cache mounts |
| runtime | `debian:trixie-slim` | Copies only `/python` and `/app/.venv`, adds `ca-certificates`, runs as non-root `bot` (uid 1000), `VOLUME /data/store`, `CMD python -m src.main` |

Dependency layers are copied before `src/` and `scripts/`, so code changes
don't recompile Rust. Only changes under `matrix_bridge/` or the lockfile do.

## `docker-compose.yml`

A single `bot` service: builds `./bot`, `restart: unless-stopped`, reads
`.env`, mounts the named volume `bot-store` at `/data/store`.

## `.github/workflows/deploy.yml`

Triggers: push to `main` touching `bot/**`, `docker-compose.yml` or the
workflow itself, or a manual `workflow_dispatch`.

| Job | Runner | Steps |
|---|---|---|
| `test` | `ubuntu-latest` | `uv sync --frozen --no-install-package matrix-bridge`, then `pytest`. No Rust toolchain needed |
| `deploy` | `self-hosted`, environment `prod` | Write `.env` from repo variables/secrets, then `docker compose up -d --build` |

The self-hosted runner is also the host that owns the volume, which is why
the login bootstrap has to run there too.

## Tests (`bot/tests/`)

Pure-Python unit tests for `commands`, `config`, `events`, `history` and
`verification`. They never import `matrix_bridge`, so they run anywhere:

```bash
cd bot
uv sync --no-install-package matrix-bridge
uv run --no-sync pytest
```
