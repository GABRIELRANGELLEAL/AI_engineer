-- Initialize pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Grant permissions to the app user
GRANT USAGE ON SCHEMA public TO legaluser;
GRANT CREATE ON SCHEMA public TO legaluser;
