#!/bin/sh
# Demo traffic for the "mysql" container: a few fake workloads, so every panel of the MySQL
# dashboard moves. Each loop restarts itself, so a database restart only pauses the traffic.

until mysqladmin ping -h "$MYSQL_HOST" -uroot --silent 2>/dev/null; do sleep 2; done

q() { mysql -h "$MYSQL_HOST" -uroot shop -e "$1" >/dev/null 2>&1; }
loop() { while true; do "$@"; done; }

# shop-api: inserts and point reads, ~10/s.
writer() {
  c=$(( $(date +%s%N 2>/dev/null || date +%s) % 5000 ))
  q "INSERT INTO orders (customer, amount) VALUES ($c, RAND()*1000);
     SELECT * FROM orders WHERE id = (SELECT MAX(id) FROM orders);
     SELECT COUNT(*) FROM orders WHERE customer = $c;"
  sleep 0.1
}

# checkout: short transactions on one hot row, so row lock waits show up.
checkout() {
  q "START TRANSACTION; UPDATE counters SET value = value + 1 WHERE name = 'orders'; DO SLEEP(0.2); COMMIT;"
}

# report: a slow aggregate every 20s (counts as a slow query, long_query_time = 0.5s).
report() {
  q "SELECT customer, SUM(amount), COUNT(*), SLEEP(0.6) FROM orders GROUP BY customer ORDER BY 2 DESC LIMIT 1;"
  sleep 20
}

# cleanup: keeps the table from growing forever.
cleanup() {
  q "DELETE FROM orders WHERE created_at < NOW() - INTERVAL 1 HOUR LIMIT 5000;"
  sleep 60
}

loop writer &
loop checkout &
loop checkout &
loop report &
loop cleanup &
wait
