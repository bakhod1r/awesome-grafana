#!/bin/sh
# Demo traffic for the "postgres" container. Each block below is one fake service with its own
# application_name (PGAPPNAME), so the PostgreSQL dashboard can show per-service numbers.
# Every loop restarts itself, so a database restart only pauses the traffic.

until pg_isready -q; do sleep 1; done
sleep 3  # init.sql runs on a temporary server first; wait for the real one

# Schema (idempotent): pgbench tables in shop, invoices in billing.
PGUSER=shop PGPASSWORD=shop pgbench -i -s 5 -q shop 2>/dev/null || true
PGUSER=billing PGPASSWORD=billing psql -q -d billing <<'SQL'
CREATE TABLE IF NOT EXISTS invoices (
  id bigserial PRIMARY KEY, customer int NOT NULL, amount numeric(12,2) NOT NULL,
  status text NOT NULL DEFAULT 'new', created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS payments (
  id bigserial PRIMARY KEY, invoice_id bigint NOT NULL, amount numeric(12,2) NOT NULL,
  paid_at timestamptz NOT NULL DEFAULT now());
-- Never used by any query: shows up under "Unused indexes" on the dashboard.
CREATE INDEX IF NOT EXISTS payments_paid_at_idx ON payments (paid_at);
SQL

cat > /tmp/billing.sql <<'SQL'
\set c random(1, 5000)
\set a random(1, 100000)
INSERT INTO invoices (customer, amount) VALUES (:c, :a / 100.0);
UPDATE invoices SET status = 'paid' WHERE id = (SELECT max(id) FROM invoices WHERE customer = :c);
INSERT INTO payments (invoice_id, amount) SELECT max(id), :a / 100.0 FROM invoices;
SQL

loop() { while true; do "$@"; sleep 2; done; }

# shop-api: steady OLTP traffic, ~20 transactions/s over 6 connections.
PGAPPNAME=shop-api PGUSER=shop PGPASSWORD=shop loop pgbench -n -c 6 -j 2 -R 20 -T 3600 shop >/dev/null 2>&1 &

# shop-catalog: read-only selects, ~40/s.
PGAPPNAME=shop-catalog PGUSER=shop PGPASSWORD=shop loop pgbench -n -S -c 4 -j 2 -R 40 -T 3600 shop >/dev/null 2>&1 &

# billing-worker: inserts and updates in billing, ~8/s. The un-indexed customer lookup gets slower as the table grows.
PGAPPNAME=billing-worker PGUSER=billing PGPASSWORD=billing loop pgbench -n -f /tmp/billing.sql -c 2 -R 8 -T 3600 billing >/dev/null 2>&1 &

# reports: heavy analytical queries every 20s (seq scans, sorts, temp files, 0.3-2.5s each).
(while true; do
  PGAPPNAME=reports PGUSER=shop PGPASSWORD=shop psql -q -d shop -c "SET work_mem='64kB'" \
    -c "SELECT bid, count(*), sum(abalance), avg(abalance) FROM pgbench_accounts GROUP BY bid ORDER BY 2 DESC" \
    -c "SELECT aid FROM pgbench_accounts ORDER BY abalance DESC, filler LIMIT 50" \
    -c "SELECT pg_sleep(random() * 2)" >/dev/null 2>&1
  sleep 20
done) &

# legacy-cron: opens a transaction, takes a row lock and sits idle for 90s every 5 minutes
# (idle in transaction + lock waits for shop-api).
(while true; do
  sleep 300
  PGAPPNAME=legacy-cron PGUSER=shop PGPASSWORD=shop psql -q -d shop \
    -c "BEGIN; UPDATE pgbench_branches SET bbalance = bbalance WHERE bid = 1; SELECT pg_sleep(90); COMMIT;" >/dev/null 2>&1
done) &

# Deadlock every 10 minutes: two sessions update the same two rows in opposite order.
(while true; do
  sleep 600
  PGAPPNAME=billing-worker PGUSER=shop PGPASSWORD=shop psql -q -d shop \
    -c "BEGIN; UPDATE pgbench_tellers SET tbalance = tbalance WHERE tid = 1; SELECT pg_sleep(2); UPDATE pgbench_tellers SET tbalance = tbalance WHERE tid = 2; COMMIT;" >/dev/null 2>&1 &
  PGAPPNAME=shop-api PGUSER=shop PGPASSWORD=shop psql -q -d shop \
    -c "BEGIN; UPDATE pgbench_tellers SET tbalance = tbalance WHERE tid = 2; SELECT pg_sleep(2); UPDATE pgbench_tellers SET tbalance = tbalance WHERE tid = 1; COMMIT;" >/dev/null 2>&1
  wait
done) &

# Errors: a buggy service querying a missing table every 30s (ERROR lines in the log).
(while true; do
  PGAPPNAME=shop-api PGUSER=shop PGPASSWORD=shop psql -q -d shop -c "SELECT * FROM orders_v2 LIMIT 1" >/dev/null 2>&1
  sleep 30
done) &

wait
