-- 002_login_attempts.sql
-- Every login try is recorded, so too many failures can be blocked (brute-force protection).
-- Kept in PostgreSQL (not in app memory) so the limit holds across all app replicas.

CREATE TABLE login_attempts (
    id         BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email      TEXT        NOT NULL,              -- as typed, compared with lower()
    ip         INET,                              -- client address; NULL if unknown
    succeeded  BOOLEAN     NOT NULL,
    at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- "failures for this e-mail / this IP in the last 15 minutes"
CREATE INDEX login_attempts_email_at_idx ON login_attempts (lower(email), at DESC);
CREATE INDEX login_attempts_ip_at_idx    ON login_attempts (ip, at DESC);
