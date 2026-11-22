-- 004_roles.sql
-- Admin role and blocking.
--
-- role: 'user' for everybody who registers; 'admin' only via the server-side CLI
--       (python -m app.admin promote <email>), never through the API.
-- disabled_at: NULL = active; a time = blocked since then (who is blocked and since
--       when, in one column; the row and the user's resources stay for the record).
--
-- A constant DEFAULT does not rewrite the table (PostgreSQL 11+), and every existing
-- account simply becomes an active 'user'.

ALTER TABLE users
    ADD COLUMN role        TEXT        NOT NULL DEFAULT 'user'
                                       CHECK (role IN ('user', 'admin')),
    ADD COLUMN disabled_at TIMESTAMPTZ;
