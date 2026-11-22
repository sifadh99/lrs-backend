-- 003_categories.sql
-- Two-level catalog: groups (Network, DevOps, ...) and topics inside them (CCNA, CKA, ...).
-- Resources get a category, a kind (video/docs/tool/lab/course/article) and a short description.
-- Links get an optional label (e.g. the real YouTube title) and a thumbnail URL.

CREATE TABLE categories (
    id          BIGINT  GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    slug        TEXT    NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9-]{1,40}$'),   -- used in URLs: #/c/network/ccna
    name        TEXT    NOT NULL CHECK (length(name) BETWEEN 1 AND 60),
    description TEXT    CHECK (length(description) <= 300),
    icon        TEXT    CHECK (length(icon) <= 8),                            -- an emoji
    parent_id   BIGINT  REFERENCES categories (id) ON DELETE CASCADE,         -- NULL = top-level group
    sort_order  INT     NOT NULL DEFAULT 0
);
CREATE INDEX categories_parent_id_idx ON categories (parent_id);

ALTER TABLE resources
    ADD COLUMN category_id BIGINT REFERENCES categories (id) ON DELETE SET NULL,
    ADD COLUMN kind        TEXT NOT NULL DEFAULT 'article'
                           CHECK (kind IN ('video', 'docs', 'tool', 'lab', 'course', 'article')),
    ADD COLUMN description TEXT CHECK (length(description) <= 500);
-- topic page: "resources of this category, newest first"
CREATE INDEX resources_category_created_idx ON resources (category_id, created_at DESC);

ALTER TABLE resource_details
    ADD COLUMN label         TEXT CHECK (length(label) <= 300),
    ADD COLUMN thumbnail_url TEXT CHECK (thumbnail_url ~* '^https://');
