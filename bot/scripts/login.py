"""One-time device bootstrap for the bot's Matrix account.

Run this ONCE, on the machine that will host the bot's Docker volume
(i.e. the self-hosted runner), so the E2EE crypto store ends up in the
right place:

    docker compose run --rm bot python -m scripts.login

It logs in with a password (never persisted) to create a new device, sets up
cross-signing so the device is signed by the bot's identity (required for
Element X to show it as verified, and for clients that exclude insecure
devices), then prints the access_token/device_id to put into your GitHub
Actions secrets. The running bot only uses the access token.
"""

from __future__ import annotations

import asyncio
import getpass
import os

from matrix_bridge import MatrixClient


async def main() -> None:
    homeserver = os.environ.get("MATRIX_HOMESERVER", "https://matrix.org")
    user_id = os.environ.get("MATRIX_USER_ID") or input("Matrix user ID (e.g. @mybot:matrix.org): ")
    password = os.environ.get("MATRIX_PASSWORD") or getpass.getpass("Matrix password: ")
    store_path = os.environ.get("MATRIX_STORE_PATH", "/data/store")
    store_passphrase = os.environ.get("MATRIX_STORE_PASSPHRASE") or None
    device_name = os.environ.get("MATRIX_DEVICE_NAME", "chatbot")

    os.makedirs(store_path, exist_ok=True)

    client = await MatrixClient.login(
        homeserver=homeserver,
        user_id=user_id,
        password=password,
        store_path=store_path,
        store_passphrase=store_passphrase,
        device_name=device_name,
    )
    # The first sync uploads this device's identity and one-time keys.
    await client.sync_once()

    status = await client.bootstrap_cross_signing(password)
    if not status.is_complete:
        print(
            "\nThis account already has a cross-signing identity, but its private keys aren't "
            "on this new device, so the bot can't sign itself.\n"
            "Resetting creates a fresh identity: anyone who verified the bot before will have "
            "to verify it again."
        )
        if input("Reset the bot's cross-signing identity? [y/N] ").strip().lower() == "y":
            status = await client.reset_cross_signing(
                password,
                on_approval_url=lambda url: print(f"\nApprove the reset in your browser: {url}\n"),
            )

    session = client.session()
    print("\nLogin succeeded. Add these as GitHub Actions secrets:\n")
    print(f"MATRIX_ACCESS_TOKEN={session.access_token}")
    print(f"MATRIX_DEVICE_ID={session.device_id}")
    print(f"MATRIX_USER_ID={session.user_id}")
    print(f"\nCross-signing: {'ready' if status.is_complete else 'NOT set up'} ({status})")
    print(f"The crypto store was written to {store_path} — keep that volume, don't recreate it.")


if __name__ == "__main__":
    asyncio.run(main())
