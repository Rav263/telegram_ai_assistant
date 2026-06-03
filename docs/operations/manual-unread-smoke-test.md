# Manual Unread Smoke Test

This checklist verifies that Telegram ingestion does not mark messages as read in the owner's main Telegram interface.

## Preconditions

- Use a controlled chat with a second Telegram account or a trusted tester.
- Use a chat that is not secret chat.
- Start with the owner account logged out of other experimental clients if possible.
- Configure `TELEGRAM_INGEST_CHAT_ID` to the controlled chat id.
- Confirm the ingestor code path does not call `mark_read`, `send_read_acknowledge`, reactions, edits, deletes, or sends.

## Steps

1. Stop the assistant processes.
2. Open the owner's normal Telegram app and select the controlled chat.
3. Ask the second account to send a unique text message.
4. Confirm the normal Telegram app shows an unread badge for that controlled chat.
5. Start only the assistant ingestor:

   ```bash
   PYTHONPATH=src .venv/bin/python -m telegram_ai_assistant.cli run ingestor
   ```

   If the package is installed, the equivalent command is `telegram-ai-assistant run ingestor`.

6. Wait until the message is persisted by the assistant.
7. Confirm the message was saved:

   ```sql
   SELECT chat_id, telegram_message_id, text, caption
   FROM messages
   WHERE account_id = 'owner' AND chat_id = 123456789
   ORDER BY telegram_message_id DESC
   LIMIT 5;
   ```

8. Confirm the chat cursor advanced:

   ```sql
   SELECT last_ingested_message_id
   FROM chats
   WHERE account_id = 'owner' AND chat_id = 123456789;
   ```

9. Do not click the controlled chat in the normal Telegram app.
10. Confirm the unread badge is still visible in the normal Telegram app.
11. Stop the ingestor if it is still running.

## Pass Criteria

- The assistant stores the message.
- `last_ingested_message_id` advances to the latest saved Telegram message id.
- The normal Telegram app keeps the unread badge.
- No read receipt is sent from the owner account.

## Failure And Rollback

If the unread badge disappears, treat the Telegram adapter as unsafe. Run rollback to a version that does not run the real ingestion adapter, disable the account session, and inspect whether a code path called `mark_read`, `send_read_acknowledge`, or another mutating Telegram method.
