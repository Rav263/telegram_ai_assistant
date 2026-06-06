# Startup Catch-Up And Chat Policy

**Goal:** Capture messages missed while `app-listener` was offline and let the owner manage listener chat policy from the bot.

## Design

- `app-listener` remains the single Telegram session owner.
- On startup, after registering the live update handler, the listener scans known readable chats with non-zero cursors and saves messages newer than each cursor.
- Startup catch-up uses the same read-only `iter_new_messages` path as one-shot ingestion and never marks messages read intentionally.
- Chat policy has two layers:
  - environment policy from `TELEGRAM_LISTENER_ALLOWED_CHANNEL_IDS` and `TELEGRAM_LISTENER_DENIED_CHAT_IDS`;
  - database overrides managed by the bot.
- Deny overrides allow. Broadcast channels still require explicit allow.
- The bot uses known chats from the local `chats` table; it does not query Telegram directly.

## TDD Steps

1. Add failing listener tests for startup catch-up:
   - lists known chats through a repository;
   - skips cursor `0` chats;
   - saves new messages and advances each cursor;
   - applies latest effective policy before catch-up.
2. Add failing repository/schema tests for `chat_policy_overrides`:
   - schema creates and indexes the table;
   - repository lists effective policy ids;
   - repository can deny, allow, and reset a chat;
   - chat query repository lists policy chat choices with status.
3. Add failing bot tests for `/blacklist` UI:
   - renders six chats per page;
   - has previous/next buttons;
   - callback can deny, allow, reset, and refresh.
4. Implement repositories, listener startup catch-up, dynamic policy provider, bot service callbacks, app wiring.
5. Update runbook and changelog.
6. Run full unittest suite and `git diff --check`.

## Pass Criteria

- Listener restart saves messages missed during downtime for known allowed chats.
- Denied chats are skipped during startup catch-up and live updates.
- Broadcast channels are read only when env or DB policy allows them.
- Bot `/blacklist` can manage DB policy overrides without exposing secrets.
- No raw Telegram message text appears in logs or bot policy responses.
