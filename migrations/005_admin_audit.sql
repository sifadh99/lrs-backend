-- 005_admin_audit.sql
-- Every admin action is written down: who did what to whom, and when.
-- Answers "who blocked this user?" / "who deleted my resource?" later, and makes a
-- stolen admin account visible. Rows are only ever inserted, never changed.

CREATE TABLE admin_audit (
    id         BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    -- SET NULL: deleting an admin account must not erase what that admin did
    admin_id   BIGINT      REFERENCES users (id) ON DELETE SET NULL,
    admin_email TEXT       NOT NULL,      -- copied, so the log still reads well after a delete
    action     TEXT        NOT NULL,      -- e.g. user.block, user.delete, resource.delete
    target     TEXT        NOT NULL,      -- e.g. "user:7 spam@x.com", "resource:42"
    details    JSONB       NOT NULL DEFAULT '{}',
    at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX admin_audit_at_idx ON admin_audit (at DESC);   -- newest first
