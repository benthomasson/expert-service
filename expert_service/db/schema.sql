-- Expert Service Schema (PostgreSQL 16)

CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "vector";

CREATE TABLE IF NOT EXISTS projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,
    domain TEXT NOT NULL,
    config JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    url TEXT,
    slug TEXT NOT NULL,
    content TEXT NOT NULL,
    word_count INT,
    fetched_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(project_id, slug)
);

CREATE TABLE IF NOT EXISTS entries (
    id TEXT NOT NULL,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    topic TEXT NOT NULL,
    title TEXT,
    content TEXT NOT NULL,
    source_id UUID REFERENCES sources(id),
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (id, project_id)
);

CREATE TABLE IF NOT EXISTS claims (
    id TEXT NOT NULL,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    status TEXT DEFAULT 'IN' CHECK (status IN ('IN', 'OUT', 'STALE', 'PROPOSED')),
    source TEXT,
    source_hash TEXT,
    review_status TEXT DEFAULT 'pending' CHECK (review_status IN ('pending', 'accepted', 'rejected')),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (id, project_id)
);

CREATE TABLE IF NOT EXISTS nogoods (
    id TEXT NOT NULL,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    resolution TEXT,
    claim_ids JSONB,
    discovered_at TIMESTAMPTZ DEFAULT now(),
    resolved_at TIMESTAMPTZ,
    PRIMARY KEY (id, project_id)
);

CREATE TABLE IF NOT EXISTS assessments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    assessment_type TEXT NOT NULL CHECK (assessment_type IN ('exam', 'coverage')),
    input_data JSONB,
    results JSONB NOT NULL,
    score JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    graph_name TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    status TEXT DEFAULT 'running' CHECK (status IN ('running', 'paused', 'completed', 'failed')),
    progress JSONB DEFAULT '{}',
    started_at TIMESTAMPTZ DEFAULT now(),
    completed_at TIMESTAMPTZ,
    error TEXT
);

CREATE TABLE IF NOT EXISTS embeddings (
    id SERIAL PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_table TEXT NOT NULL,
    source_id TEXT NOT NULL,
    label TEXT,
    embedding vector(384) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Full-text search indexes
CREATE INDEX IF NOT EXISTS idx_entries_fts ON entries
    USING gin(to_tsvector('english', coalesce(title, '') || ' ' || content));
CREATE INDEX IF NOT EXISTS idx_claims_fts ON claims
    USING gin(to_tsvector('english', text));

-- Common query indexes
CREATE INDEX IF NOT EXISTS idx_sources_project ON sources(project_id);
CREATE INDEX IF NOT EXISTS idx_entries_project ON entries(project_id);
CREATE INDEX IF NOT EXISTS idx_entries_topic ON entries(project_id, topic);
CREATE INDEX IF NOT EXISTS idx_claims_project ON claims(project_id);
CREATE INDEX IF NOT EXISTS idx_claims_status ON claims(project_id, status);
CREATE INDEX IF NOT EXISTS idx_pipeline_project ON pipeline_runs(project_id);
CREATE INDEX IF NOT EXISTS idx_embeddings_project ON embeddings(project_id);
