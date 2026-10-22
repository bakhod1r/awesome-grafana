-- Demo MySQL schema and the exporter user. Runs once, on the first start of an empty mysql-data volume.

-- Read-only monitoring user for mysqld-exporter (same grants a real server needs).
CREATE USER IF NOT EXISTS 'exporter'@'%' IDENTIFIED BY 'exporter' WITH MAX_USER_CONNECTIONS 3;
GRANT PROCESS, REPLICATION CLIENT, SELECT ON *.* TO 'exporter'@'%';

-- Demo application user and schema.
CREATE DATABASE IF NOT EXISTS shop;
CREATE USER IF NOT EXISTS 'shop'@'%' IDENTIFIED BY 'shop';
GRANT ALL ON shop.* TO 'shop'@'%';

USE shop;
CREATE TABLE IF NOT EXISTS orders (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  customer INT NOT NULL,
  amount DECIMAL(12,2) NOT NULL,
  status VARCHAR(16) NOT NULL DEFAULT 'new',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
-- Hot row for lock waits: every checkout updates the same counter.
CREATE TABLE IF NOT EXISTS counters (name VARCHAR(32) PRIMARY KEY, value BIGINT NOT NULL);
INSERT IGNORE INTO counters VALUES ('orders', 0);
