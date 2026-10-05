-- Runs once on first Postgres start: app role (non-superuser, subject to RLS) and test database.
CREATE ROLE companyos_app LOGIN PASSWORD 'companyos_app_dev';
CREATE DATABASE companyos_test OWNER companyos;
\connect companyos
CREATE EXTENSION IF NOT EXISTS vector;
GRANT CONNECT ON DATABASE companyos TO companyos_app;
GRANT USAGE ON SCHEMA public TO companyos_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO companyos_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO companyos_app;
\connect companyos_test
CREATE EXTENSION IF NOT EXISTS vector;
GRANT CONNECT ON DATABASE companyos_test TO companyos_app;
GRANT USAGE ON SCHEMA public TO companyos_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO companyos_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO companyos_app;
