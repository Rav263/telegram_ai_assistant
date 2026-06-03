import unittest

from telegram_ai_assistant.ingestion.chat_policy import ChatIngestionPolicy, ChatMetadata


class ChatIngestionPolicyTests(unittest.TestCase):
    def test_allows_private_basic_group_and_supergroup_by_default(self):
        policy = ChatIngestionPolicy()

        self.assertTrue(policy.can_read(ChatMetadata(chat_id=10, chat_type="private")))
        self.assertTrue(policy.can_read(ChatMetadata(chat_id=11, chat_type="group")))
        self.assertTrue(
            policy.can_read(
                ChatMetadata(
                    chat_id=-10012,
                    chat_type="channel",
                    is_megagroup=True,
                    is_broadcast=False,
                )
            )
        )

    def test_rejects_broadcast_channel_without_allowlist(self):
        policy = ChatIngestionPolicy()

        self.assertFalse(
            policy.can_read(
                ChatMetadata(
                    chat_id=-100111,
                    chat_type="channel",
                    is_megagroup=False,
                    is_broadcast=True,
                )
            )
        )

    def test_allows_broadcast_channel_when_allowlisted(self):
        policy = ChatIngestionPolicy(allowed_channel_ids=frozenset({-100111}))

        self.assertTrue(
            policy.can_read(
                ChatMetadata(
                    chat_id=-100111,
                    chat_type="channel",
                    is_megagroup=False,
                    is_broadcast=True,
                )
            )
        )

    def test_denylist_overrides_default_and_channel_allowlist(self):
        policy = ChatIngestionPolicy(
            allowed_channel_ids=frozenset({-100111}),
            denied_chat_ids=frozenset({10, -100111}),
        )

        self.assertFalse(policy.can_read(ChatMetadata(chat_id=10, chat_type="private")))
        self.assertFalse(
            policy.can_read(
                ChatMetadata(
                    chat_id=-100111,
                    chat_type="channel",
                    is_megagroup=False,
                    is_broadcast=True,
                )
            )
        )

    def test_rejects_unknown_and_secret_chat_types(self):
        policy = ChatIngestionPolicy()

        self.assertFalse(policy.can_read(ChatMetadata(chat_id=20, chat_type="secret")))
        self.assertFalse(policy.can_read(ChatMetadata(chat_id=21, chat_type="unknown")))


if __name__ == "__main__":
    unittest.main()
