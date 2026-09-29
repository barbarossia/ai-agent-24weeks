CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA week11_obsidian_agent;
COMMENT ON SCHEMA week11_obsidian_agent IS 'week11-obsidian-knowledge-agent:001';
CREATE TABLE week11_obsidian_agent.settings (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    version integer NOT NULL CHECK (version = 1),
    dimension integer NOT NULL,
    provider_id text NOT NULL
);
CREATE TABLE week11_obsidian_agent.documents (
    doc_id text PRIMARY KEY,
    source_path text NOT NULL UNIQUE CHECK (btrim(source_path) <> ''),
    title text NOT NULL,
    tags text[] NOT NULL,
    modified_at timestamptz NOT NULL,
    content_hash text NOT NULL,
    indexed_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE week11_obsidian_agent.chunks (
    chunk_id text PRIMARY KEY,
    doc_id text NOT NULL REFERENCES week11_obsidian_agent.documents(doc_id) ON DELETE CASCADE,
    chunk_index integer NOT NULL CHECK (chunk_index >= 0),
    heading_path text NOT NULL,
    content text NOT NULL,
    embedding vector(__DIMENSION__) NOT NULL,
    UNIQUE (doc_id, chunk_index)
);
