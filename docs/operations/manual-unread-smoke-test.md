# Manual Unread Smoke Test

This checklist verifies that Telegram ingestion does not mark messages as read in the owner's main Telegram interface.

## Preconditions

- Use a controlled chat with a second Telegram account or a trusted tester.
- Use a chat that is not secret chat.
- Start with the owner account logged out of other experimental clients if possible.
- Confirm the ingestor code path does not call `mark_read`, `send_read_acknowledge`, reactions, edits, deletes, or sends.

## Steps

1. Stop the assistant processes.
2. Open the owner's normal Telegram app and select the controlled chat.
3. Ask the second account to send a unique text message.
4. Confirm the normal Telegram app shows an unread badge for that controlled chat.
5. Start only the assistant ingestor.
6. Wait until the message is persisted by the assistant.
7. Do not click the controlled chat in the normal Telegram app.
8. Confirm the unread badge is still visible in the normal Telegram app.
9. Stop the ingestor.

## Pass Criteria

- The assistant stores the message.
- The normal Telegram app keeps the unread badge.
- No read receipt is sent from the owner account.

## Failure And Rollback

If the unread badge disappears, treat the Telegram adapter as unsafe. Run rollback to a version that does not run the real ingestion adapter, disable the account session, and inspect whether a code path called `mark_read`, `send_read_acknowledge`, or another mutating Telegram method.
