-- EarthVision Enterprise database bootstrap (PostgreSQL + PostGIS)
-- Applied automatically by docker-compose via /docker-entrypoint-initdb.d

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Application role helpers (optional; primary schema is managed by Alembic / SQLAlchemy)
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'earthvision_app') THEN
    CREATE ROLE earthvision_app LOGIN PASSWORD 'earthvision';
  END IF;
END
$$;

-- Useful spatial indexes can be added after Alembic migrations create tables.
-- Grant usage so the app role can operate on public schema objects created later.
GRANT USAGE ON SCHEMA public TO earthvision_app;
GRANT CREATE ON SCHEMA public TO earthvision_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO earthvision_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO earthvision_app;

-- Health-check friendly marker
CREATE TABLE IF NOT EXISTS schema_bootstrap (
  id SERIAL PRIMARY KEY,
  applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  note TEXT NOT NULL DEFAULT 'EarthVision PostGIS ready'
);

INSERT INTO schema_bootstrap (note)
SELECT 'init.sql applied'
WHERE NOT EXISTS (SELECT 1 FROM schema_bootstrap WHERE note = 'init.sql applied');
