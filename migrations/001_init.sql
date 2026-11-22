-- 001_init.sql
-- First schema of the Learning Resource Sharing app.
-- Plain SQL, applied once by our own small migration runner (no ORM, no Alembic).

BEGIN;

-- Which migration files have already been applied.
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT        PRIMARY KEY,               -- file name, e.g. '001_init'
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- People who can log in and share resources.
CREATE TABLE users (
    id            BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email         TEXT        NOT NULL,
    name          TEXT        NOT NULL CHECK (length(name) BETWEEN 1 AND 100),
    password_hash TEXT        NOT NULL,                -- bcrypt hash, never the password
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- one account per email, case-insensitive (Foo@x.com == foo@x.com)
CREATE UNIQUE INDEX users_email_lower_uq ON users (lower(email));

-- A shared resource (title + owner). Links live in resource_details.
CREATE TABLE resources (
    id          BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    title       TEXT        NOT NULL CHECK (length(title) BETWEEN 1 AND 200),
    user_id     BIGINT      NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ                            -- NULL until first edit
);
-- PostgreSQL does not index foreign keys by itself:
CREATE INDEX resources_user_id_idx    ON resources (user_id);          -- "my resources", ON DELETE CASCADE
CREATE INDEX resources_created_at_idx ON resources (created_at DESC);  -- newest-first list

-- One or more links that belong to a resource.
CREATE TABLE resource_details (
    id           BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    resource_id  BIGINT      NOT NULL REFERENCES resources (id) ON DELETE CASCADE,
    link         TEXT        NOT NULL CHECK (link ~* '^https?://'),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX resource_details_resource_id_idx ON resource_details (resource_id);

INSERT INTO schema_migrations (version) VALUES ('001_init');

COMMIT;
