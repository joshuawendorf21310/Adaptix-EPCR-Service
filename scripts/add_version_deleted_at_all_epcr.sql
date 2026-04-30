DO $$
DECLARE
    t RECORD;
BEGIN
    FOR t IN
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name LIKE 'epcr_%'
    LOOP
        EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1', t.table_name);
        EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ', t.table_name);
    END LOOP;
END $$;
