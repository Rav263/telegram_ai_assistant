CREATE TABLE IF NOT EXISTS accounts (
    account_id TEXT PRIMARY KEY,
    telegram_user_id BIGINT UNIQUE,
    display_name TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chats (
    account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    chat_id BIGINT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    chat_type TEXT NOT NULL DEFAULT '',
    last_ingested_message_id BIGINT NOT NULL DEFAULT 0,
    last_ingested_at TIMESTAMPTZ,
    ingestion_error TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (account_id, chat_id)
);

ALTER TABLE chats
    ADD COLUMN IF NOT EXISTS last_ingested_message_id BIGINT NOT NULL DEFAULT 0;

ALTER TABLE chats
    ADD COLUMN IF NOT EXISTS last_ingested_at TIMESTAMPTZ;

ALTER TABLE chats
    ADD COLUMN IF NOT EXISTS ingestion_error TEXT NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS messages (
    message_id BIGSERIAL PRIMARY KEY,
    account_id TEXT NOT NULL,
    chat_id BIGINT NOT NULL,
    telegram_message_id BIGINT NOT NULL,
    sender_id BIGINT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('incoming', 'outgoing')),
    sent_at TIMESTAMPTZ NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    caption TEXT NOT NULL DEFAULT '',
    reply_to_message_id BIGINT,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    FOREIGN KEY (account_id, chat_id) REFERENCES chats(account_id, chat_id) ON DELETE CASCADE,
    UNIQUE (account_id, chat_id, telegram_message_id)
);

CREATE TABLE IF NOT EXISTS message_processing_state (
    account_id TEXT NOT NULL,
    chat_id BIGINT NOT NULL,
    telegram_message_id BIGINT NOT NULL,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    error TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (account_id, chat_id, telegram_message_id, stage),
    FOREIGN KEY (account_id, chat_id, telegram_message_id)
        REFERENCES messages(account_id, chat_id, telegram_message_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS raw_updates (
    raw_update_id BIGSERIAL PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    chat_id BIGINT,
    telegram_message_id BIGINT,
    payload JSONB NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS message_candidates (
    candidate_id BIGSERIAL PRIMARY KEY,
    account_id TEXT NOT NULL,
    chat_id BIGINT NOT NULL,
    telegram_message_id BIGINT NOT NULL,
    score NUMERIC(5, 4) NOT NULL,
    reasons JSONB NOT NULL DEFAULT '[]'::JSONB,
    status TEXT NOT NULL DEFAULT 'queued',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    FOREIGN KEY (account_id, chat_id, telegram_message_id)
        REFERENCES messages(account_id, chat_id, telegram_message_id)
        ON DELETE CASCADE,
    UNIQUE (account_id, chat_id, telegram_message_id)
);

CREATE TABLE IF NOT EXISTS extracted_items (
    item_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    item_type TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    confidence NUMERIC(5, 4) NOT NULL,
    status TEXT NOT NULL,
    rationale TEXT NOT NULL DEFAULT '',
    due_at TIMESTAMPTZ,
    source_refs JSONB NOT NULL DEFAULT '[]'::JSONB,
    metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS item_status_events (
    status_event_id BIGSERIAL PRIMARY KEY,
    item_id TEXT NOT NULL REFERENCES extracted_items(item_id) ON DELETE CASCADE,
    old_status TEXT,
    new_status TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS review_queue (
    review_id BIGSERIAL PRIMARY KEY,
    item_id TEXT REFERENCES extracted_items(item_id) ON DELETE CASCADE,
    review_type TEXT NOT NULL DEFAULT 'item',
    state TEXT NOT NULL DEFAULT 'pending',
    reason TEXT NOT NULL DEFAULT '',
    payload JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);

ALTER TABLE review_queue
    ADD COLUMN IF NOT EXISTS review_type TEXT NOT NULL DEFAULT 'item';

ALTER TABLE review_queue
    ADD COLUMN IF NOT EXISTS payload JSONB NOT NULL DEFAULT '{}'::JSONB;

ALTER TABLE review_queue
    ALTER COLUMN item_id DROP NOT NULL;

CREATE TABLE IF NOT EXISTS llm_runs (
    llm_run_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    request_payload JSONB NOT NULL DEFAULT '{}'::JSONB,
    response_payload JSONB,
    status TEXT NOT NULL,
    error TEXT NOT NULL DEFAULT '',
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS runtime_events (
    runtime_event_id BIGSERIAL PRIMARY KEY,
    component TEXT NOT NULL,
    severity TEXT NOT NULL,
    event_type TEXT NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS backfill_jobs (
    backfill_job_id BIGSERIAL PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    from_date TIMESTAMPTZ NOT NULL,
    to_date TIMESTAMPTZ NOT NULL,
    cursor_payload JSONB NOT NULL DEFAULT '{}'::JSONB,
    error TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS bot_actions (
    bot_action_id BIGSERIAL PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    telegram_user_id BIGINT NOT NULL,
    action_type TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS bot_runtime_state (
    bot_name TEXT PRIMARY KEY,
    last_update_id BIGINT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS settings (
    setting_key TEXT PRIMARY KEY,
    setting_value JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_messages_account_chat_sent_at
    ON messages(account_id, chat_id, sent_at);

CREATE INDEX IF NOT EXISTS idx_message_candidates_status
    ON message_candidates(status, created_at);

CREATE INDEX IF NOT EXISTS idx_extracted_items_status
    ON extracted_items(status, updated_at);

CREATE INDEX IF NOT EXISTS idx_runtime_events_severity_created_at
    ON runtime_events(severity, created_at DESC, runtime_event_id DESC);
