#!/bin/sh
# Demo traffic for the "redis" container: cache reads with misses, writes with TTL, lists and hashes.
# Memory stays around 50-80 MB of the 256 MB limit, so the demo does not trigger Redis alerts.

until redis-cli -h "$REDIS_HOST" ping >/dev/null 2>&1; do sleep 1; done

loop() { while true; do "$@"; sleep 1; done; }

# Reads over a key space twice the size of what is written: about half are misses.
loop redis-benchmark -h "$REDIS_HOST" -q -n 20000 -c 4 -r 200000 -t get >/dev/null 2>&1 &
# Writes with a short TTL: expired_keys grows.
loop redis-benchmark -h "$REDIS_HOST" -q -n 5000 -c 2 -r 100000 -d 512 setex key:__rand_int__ 60 v >/dev/null 2>&1 &
# Lists and hashes, so the command mix panel has more than GET/SET. LPUSH and LPOP balance out.
loop redis-benchmark -h "$REDIS_HOST" -q -n 3000 -c 2 -r 10000 -t lpush,lpop,hset >/dev/null 2>&1 &
wait
