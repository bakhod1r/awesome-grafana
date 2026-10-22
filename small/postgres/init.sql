-- Demo setup, runs once on the first start of the "postgres" container (empty data volume).

-- Monitoring user for postgres-exporter. pg_monitor = read every statistics view, nothing else.
CREATE ROLE postgres_exporter LOGIN PASSWORD 'exporter' IN ROLE pg_monitor;

-- pg_stat_statements is cluster-wide; creating it in "postgres" (the exporter's DSN database) is enough.
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- Two application databases with their own owners, so the dashboard has several db/user/service values.
CREATE ROLE shop LOGIN PASSWORD 'shop';
CREATE ROLE billing LOGIN PASSWORD 'billing';
CREATE DATABASE shop OWNER shop;
CREATE DATABASE billing OWNER billing;
