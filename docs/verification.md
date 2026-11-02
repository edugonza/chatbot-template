# Verification

Lets a user verify the bot from Element X (or any client with SAS emoji
verification), so the bot shows as verified and its messages don't carry
"unverified device" warnings.

## Prerequisites

The bot's device must be **signed by the bot's own cross-signing identity**.
`scripts/login.py` sets this up once (see [deployment.md](deployment.md)).
On startup, `main.py` checks `cross_signing_status()` and logs a warning if
this device doesn't hold all three private keys (master, self-signing,
user-signing).

Without it, a user can still verify, but clients show the bot's device as not
trusted by its owner.

## Two kinds of request

| Kind | Who sends it | `room_id` in callbacks |
|---|---|---|
| **In-room** | Element X, when you verify another user from their profile in a DM | The DM's room ID |
| **To-device** | Some clients, and device-to-device verification | `None` |

Both are handled by the same Rust state machine (see
[matrix-bridge.md](matrix-bridge.md#verification-state-machine)).

## The flow

```
Element X                         Rust bridge                     VerificationPolicy
    │ m.key.verification.request ──►│                                     │
    │                               │── on_verification_request ────────► │ allowlisted user?
    │                               │◄──────────────── True / False ───── │
    │◄── ready (or cancel) ─────────│                                     │
    │ start SAS ───────────────────►│ accept                              │
    │◄──── key exchange ───────────►│                                     │
    │  (shows 7 emojis)             │── on_verification_emojis ─────────► │ post emojis as m.notice
    │                               │◄──────────────────────── True ───── │
    │                               │ confirm                             │
    │ user compares, "They match" ─►│                                     │
    │◄───────────── done ──────────►│── on_verification_done ───────────► │ post "✅ Verification complete."
```

## `src/verification.py`: `VerificationPolicy`

| Callback | Behaviour |
|---|---|
| `on_verification_request` | Accept only if `user_id` is in `MATRIX_ALLOWED_USERS`. An allowlisted **room** does not grant this. |
| `on_verification_emojis` | Log the emojis. For in-room requests, also post them as an `m.notice` in the DM. Always returns `True` (confirm). |
| `on_verification_done` | Log it, and post a completion notice for in-room requests |
| `on_verification_cancelled` | Log the reason |

## Security model

- A bot has no human to compare emojis, so **it confirms automatically**.
- The real check is **the user's**: they compare the emojis their client
  shows with the ones the bot posted, and tap "They match" only if they're identical.
- A man-in-the-middle would produce different emojis on each side. Posting
  the bot's emojis through the (already encrypted) room lets the user see the
  mismatch.
- The allowlist stops strangers from marking the bot's side as verified
  against their devices.
- If the crypto store is lost and the identity reset, everyone has to verify
  again.

## Limitations

- Only SAS emoji verification. QR-code verification isn't compiled in, and
  SAS without emoji support (decimal only) is cancelled.
- The bot never *starts* a verification. It only responds.

## Customising

- Different trust rules (e.g. a separate `MATRIX_VERIFIERS` list): change
  `on_verification_request`.
- Don't post emojis in the room: remove the `_notice` call. The user can
  still read them from the logs.
