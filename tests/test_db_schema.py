from pathlib import Path
import re
import unittest


SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "telegram_ai_assistant"
    / "db"
    / "schema.sql"
)


class DBSchemaTests(unittest.TestCase):
    def test_schema_defines_all_mvp_tables(self):
        self.assertTrue(SCHEMA_PATH.exists(), "schema.sql must exist")
        schema = SCHEMA_PATH.read_text(encoding="utf-8").lower()

        required_tables = (
            "accounts",
            "chats",
            "messages",
            "message_processing_state",
            "raw_updates",
            "message_candidates",
            "extracted_items",
            "item_status_events",
            "review_queue",
            "llm_runs",
            "llm_actions",
            "runtime_events",
            "backfill_jobs",
            "bot_actions",
            "bot_runtime_state",
            "bot_sessions",
            "chat_policy_overrides",
            "settings",
        )

        for table_name in required_tables:
            with self.subTest(table_name=table_name):
                self.assertRegex(
                    schema,
                    rf"create\s+table\s+if\s+not\s+exists\s+{table_name}\b",
                )

    def test_messages_are_unique_per_account_chat_and_telegram_message(self):
        self.assertTrue(SCHEMA_PATH.exists(), "schema.sql must exist")
        schema = re.sub(
            r"\s+",
            " ",
            SCHEMA_PATH.read_text(encoding="utf-8").lower(),
        )

        self.assertIn(
            "unique (account_id, chat_id, telegram_message_id)",
            schema,
        )

    def test_chats_include_ingestion_cursor_columns(self):
        self.assertTrue(SCHEMA_PATH.exists(), "schema.sql must exist")
        schema = re.sub(
            r"\s+",
            " ",
            SCHEMA_PATH.read_text(encoding="utf-8").lower(),
        )

        self.assertRegex(
            schema,
            r"last_ingested_message_id\s+bigint\s+not\s+null\s+default\s+0",
        )
        self.assertRegex(schema, r"last_ingested_at\s+timestamptz")
        self.assertRegex(
            schema,
            r"ingestion_error\s+text\s+not\s+null\s+default\s+''",
        )

    def test_schema_adds_ingestion_cursor_columns_to_existing_chats_table(self):
        self.assertTrue(SCHEMA_PATH.exists(), "schema.sql must exist")
        schema = re.sub(
            r"\s+",
            " ",
            SCHEMA_PATH.read_text(encoding="utf-8").lower(),
        )

        self.assertIn(
            "alter table chats add column if not exists last_ingested_message_id bigint not null default 0",
            schema,
        )
        self.assertIn(
            "alter table chats add column if not exists last_ingested_at timestamptz",
            schema,
        )
        self.assertIn(
            "alter table chats add column if not exists ingestion_error text not null default ''",
            schema,
        )

    def test_message_processing_state_tracks_candidate_filter_stage(self):
        self.assertTrue(SCHEMA_PATH.exists(), "schema.sql must exist")
        schema = re.sub(
            r"\s+",
            " ",
            SCHEMA_PATH.read_text(encoding="utf-8").lower(),
        )

        self.assertIn("create table if not exists message_processing_state", schema)
        self.assertIn(
            "primary key (account_id, chat_id, telegram_message_id, stage)",
            schema,
        )
        self.assertIn(
            "references messages(account_id, chat_id, telegram_message_id)",
            schema,
        )
        self.assertRegex(schema, r"stage\s+text\s+not\s+null")
        self.assertRegex(schema, r"status\s+text\s+not\s+null")
        self.assertRegex(schema, r"error\s+text\s+not\s+null\s+default\s+''")

    def test_review_queue_supports_item_and_status_change_reviews(self):
        self.assertTrue(SCHEMA_PATH.exists(), "schema.sql must exist")
        schema = re.sub(
            r"\s+",
            " ",
            SCHEMA_PATH.read_text(encoding="utf-8").lower(),
        )

        self.assertRegex(
            schema,
            r"item_id\s+text\s+references\s+extracted_items\(item_id\)",
        )
        self.assertIn(
            "review_type text not null default 'item'",
            schema,
        )
        self.assertIn(
            "payload jsonb not null default '{}'::jsonb",
            schema,
        )
        self.assertIn(
            "state text not null default 'pending'",
            schema,
        )
        self.assertIn(
            "resolved_at timestamptz",
            schema,
        )
        self.assertIn(
            "alter table review_queue add column if not exists review_type text not null default 'item'",
            schema,
        )
        self.assertIn(
            "alter table review_queue add column if not exists payload jsonb not null default '{}'::jsonb",
            schema,
        )
        self.assertIn(
            "alter table review_queue alter column item_id drop not null",
            schema,
        )

    def test_llm_actions_store_audited_action_proposals(self):
        self.assertTrue(SCHEMA_PATH.exists(), "schema.sql must exist")
        schema = re.sub(
            r"\s+",
            " ",
            SCHEMA_PATH.read_text(encoding="utf-8").lower(),
        )

        self.assertIn("create table if not exists llm_actions", schema)
        self.assertRegex(schema, r"llm_action_id\s+bigserial\s+primary\s+key")
        self.assertRegex(schema, r"account_id\s+text\s+not\s+null\s+references\s+accounts\(account_id\)")
        self.assertRegex(schema, r"action_key\s+text\s+not\s+null\s+unique")
        self.assertRegex(schema, r"action_type\s+text\s+not\s+null")
        self.assertRegex(schema, r"state\s+text\s+not\s+null")
        self.assertRegex(schema, r"confidence\s+numeric\(5,\s*4\)\s+not\s+null")
        self.assertRegex(schema, r"target_item_id\s+text")
        self.assertIn("payload jsonb not null default '{}'::jsonb", schema)
        self.assertIn("source_refs jsonb not null default '[]'::jsonb", schema)
        self.assertIn("rationale text not null default ''", schema)
        self.assertRegex(schema, r"applied_at\s+timestamptz")
        self.assertRegex(schema, r"rejected_at\s+timestamptz")
        self.assertIn(
            "create index if not exists idx_llm_actions_state_created_at on llm_actions(state, created_at, llm_action_id)",
            schema,
        )
        self.assertIn(
            "create index if not exists idx_llm_actions_target_item_id on llm_actions(target_item_id)",
            schema,
        )

    def test_review_queue_can_reference_llm_actions(self):
        self.assertTrue(SCHEMA_PATH.exists(), "schema.sql must exist")
        schema = re.sub(
            r"\s+",
            " ",
            SCHEMA_PATH.read_text(encoding="utf-8").lower(),
        )

        self.assertRegex(
            schema,
            r"llm_action_id\s+bigint\s+references\s+llm_actions\(llm_action_id\)",
        )
        self.assertIn(
            "alter table review_queue add column if not exists llm_action_id bigint",
            schema,
        )
        self.assertIn(
            "create index if not exists idx_review_queue_llm_action_id on review_queue(llm_action_id)",
            schema,
        )

    def test_runtime_events_support_bot_log_lookup(self):
        self.assertTrue(SCHEMA_PATH.exists(), "schema.sql must exist")
        schema = re.sub(
            r"\s+",
            " ",
            SCHEMA_PATH.read_text(encoding="utf-8").lower(),
        )

        self.assertIn("create table if not exists runtime_events", schema)
        self.assertRegex(schema, r"component\s+text\s+not\s+null")
        self.assertRegex(schema, r"severity\s+text\s+not\s+null")
        self.assertRegex(schema, r"event_type\s+text\s+not\s+null")
        self.assertIn("metadata jsonb not null default '{}'::jsonb", schema)
        self.assertIn(
            "create index if not exists idx_runtime_events_severity_created_at on runtime_events(severity, created_at desc, runtime_event_id desc)",
            schema,
        )

    def test_bot_runtime_state_persists_update_offsets(self):
        self.assertTrue(SCHEMA_PATH.exists(), "schema.sql must exist")
        schema = re.sub(
            r"\s+",
            " ",
            SCHEMA_PATH.read_text(encoding="utf-8").lower(),
        )

        self.assertIn("create table if not exists bot_runtime_state", schema)
        self.assertRegex(schema, r"bot_name\s+text\s+primary\s+key")
        self.assertRegex(schema, r"last_update_id\s+bigint\s+not\s+null")

    def test_bot_sessions_store_short_lived_flow_state(self):
        self.assertTrue(SCHEMA_PATH.exists(), "schema.sql must exist")
        schema = re.sub(
            r"\s+",
            " ",
            SCHEMA_PATH.read_text(encoding="utf-8").lower(),
        )

        self.assertIn("create table if not exists bot_sessions", schema)
        self.assertRegex(schema, r"telegram_user_id\s+bigint\s+not\s+null")
        self.assertRegex(schema, r"bot_chat_id\s+bigint\s+not\s+null")
        self.assertRegex(schema, r"flow_id\s+text\s+not\s+null")
        self.assertIn("payload jsonb not null default '{}'::jsonb", schema)
        self.assertRegex(schema, r"expires_at\s+timestamptz\s+not\s+null")
        self.assertIn(
            "primary key (telegram_user_id, bot_chat_id, flow_id)",
            schema,
        )
        self.assertIn(
            "create index if not exists idx_bot_sessions_expires_at on bot_sessions(expires_at)",
            schema,
        )

    def test_chat_policy_overrides_store_bot_managed_listener_policy(self):
        self.assertTrue(SCHEMA_PATH.exists(), "schema.sql must exist")
        schema = re.sub(
            r"\s+",
            " ",
            SCHEMA_PATH.read_text(encoding="utf-8").lower(),
        )

        self.assertIn("create table if not exists chat_policy_overrides", schema)
        self.assertRegex(schema, r"chat_id\s+bigint\s+not\s+null")
        self.assertIn("policy_state text not null", schema)
        self.assertIn("check (policy_state in ('allow', 'deny'))", schema)
        self.assertIn("primary key (account_id, chat_id)", schema)
        self.assertIn(
            "create index if not exists idx_chat_policy_overrides_account_state on chat_policy_overrides(account_id, policy_state)",
            schema,
        )

    def test_backfill_jobs_support_persisted_bot_managed_execution(self):
        self.assertTrue(SCHEMA_PATH.exists(), "schema.sql must exist")
        schema = re.sub(
            r"\s+",
            " ",
            SCHEMA_PATH.read_text(encoding="utf-8").lower(),
        )

        self.assertIn("create table if not exists backfill_jobs", schema)
        self.assertRegex(schema, r"chat_id\s+bigint\s+not\s+null\s+default\s+0")
        self.assertRegex(schema, r"chat_title\s+text\s+not\s+null\s+default\s+''")
        self.assertRegex(schema, r"next_before_message_id\s+bigint")
        self.assertRegex(schema, r"saved_count\s+integer\s+not\s+null\s+default\s+0")
        self.assertRegex(schema, r"last_error_type\s+text\s+not\s+null\s+default\s+''")
        self.assertIn("last_error_metadata jsonb not null default '{}'::jsonb", schema)
        self.assertRegex(schema, r"updated_at\s+timestamptz\s+not\s+null\s+default\s+now\(\)")
        self.assertIn(
            "create index if not exists idx_backfill_jobs_account_status_created_at on backfill_jobs(account_id, status, created_at)",
            schema,
        )
        self.assertIn(
            "create index if not exists idx_backfill_jobs_account_chat_created_at on backfill_jobs(account_id, chat_id, created_at desc)",
            schema,
        )

    def test_schema_adds_backfill_job_columns_to_existing_tables(self):
        self.assertTrue(SCHEMA_PATH.exists(), "schema.sql must exist")
        schema = re.sub(
            r"\s+",
            " ",
            SCHEMA_PATH.read_text(encoding="utf-8").lower(),
        )

        self.assertIn(
            "alter table backfill_jobs add column if not exists chat_id bigint not null default 0",
            schema,
        )
        self.assertIn(
            "alter table backfill_jobs add column if not exists chat_title text not null default ''",
            schema,
        )
        self.assertIn(
            "alter table backfill_jobs add column if not exists next_before_message_id bigint",
            schema,
        )
        self.assertIn(
            "alter table backfill_jobs add column if not exists saved_count integer not null default 0",
            schema,
        )
        self.assertIn(
            "alter table backfill_jobs add column if not exists last_error_type text not null default ''",
            schema,
        )
        self.assertIn(
            "alter table backfill_jobs add column if not exists last_error_metadata jsonb not null default '{}'::jsonb",
            schema,
        )
        self.assertIn(
            "alter table backfill_jobs add column if not exists updated_at timestamptz not null default now()",
            schema,
        )


if __name__ == "__main__":
    unittest.main()
