#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
mkdir -p backup
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
docker compose exec -T db sh -c 'pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB"' > "backup/anime-$STAMP.dump"
# Shoko may have a live SQLite DB in this directory: quiesce it for a consistent archive.
docker compose stop shoko
trap 'docker compose start shoko >/dev/null' EXIT HUP INT TERM
tar -czf "backup/shoko-$STAMP.tar.gz" -C state shoko
printf 'Database: backup/anime-%s.dump\nShoko: backup/shoko-%s.tar.gz\n' "$STAMP" "$STAMP"
