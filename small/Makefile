# Shortcuts for the small stack. Run `make` (or `make help`) to list targets.
# Optional exporters: make up PROFILES="postgres redis"

COMPOSE  := docker compose
PROFILES ?=
PROFILE_FLAGS := $(foreach p,$(PROFILES),--profile $(p))
DC := $(COMPOSE) $(PROFILE_FLAGS)

.DEFAULT_GOAL := help
.PHONY: help up down restart ps logs pull upgrade update dashboards check targets reload-prometheus reload-alerts pg-check minio-token config

help:  ## list targets
	@grep -hE '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

up:  ## start the stack (add PROFILES="postgres redis" for optional exporters)
	$(DC) up -d

down:  ## stop and remove containers (volumes are kept)
	$(DC) down

restart:  ## restart one service: make restart s=grafana
	$(DC) restart $(s)

ps:  ## container status
	$(DC) ps -a

logs:  ## follow logs, all or one service: make logs s=vector
	$(DC) logs -f --tail=100 $(s)

pull:  ## pull the image versions pinned in docker-compose.yml
	$(DC) pull

upgrade: pull  ## pull pinned images and recreate changed containers
	$(DC) up -d --remove-orphans

update:  ## on the server: git pull, then apply image and config changes
	git pull --ff-only
	$(MAKE) upgrade

dashboards:  ## rebuild generated dashboards (Grafana reloads them within seconds)
	python3 grafana/generators/build.py

check:  ## run every dashboard panel query, list errors and "No data"
	python3 scripts/check-dashboards.py

targets:  ## Prometheus scrape targets that are down
	@curl -s http://localhost:39090/api/v1/targets | python3 -c 'import sys,json; [print(t["health"].upper(), t["labels"]["job"], t["scrapeUrl"], t["lastError"][:80]) for t in json.load(sys.stdin)["data"]["activeTargets"] if t["health"]!="up"]'

reload-prometheus:  ## apply prometheus.yml changes (restart: no --web.enable-lifecycle); rules: make reload-alerts
	$(DC) restart prometheus

reload-alerts:  ## reload both vmalerts (metric + log rules) and Alertmanager config
	curl -s -X POST http://localhost:38881/-/reload && curl -s -X POST http://localhost:38880/-/reload && curl -s -X POST http://localhost:39093/-/reload && echo reloaded

pg-check:  ## can the PostgreSQL exporters reach their databases (pg_up 1 = yes)
	@for a in 172.17.0.1:39187 172.17.0.1:39188; do printf "%s " $$a; curl -s $$a/metrics | grep '^pg_up' || echo "exporter not running"; done

minio-token:  ## build + test the MinIO metrics token from MINIO_* in .env, write it for Prometheus
	@set -a; . ./.env; set +a; python3 scripts/minio-token.py

config:  ## validate docker-compose.yml
	$(DC) config -q && echo ok
