#!/bin/bash
set -e
echo "Restoring database from /dump.sql..."
grep -v '\\restrict' /dump.sql | psql -v ON_ERROR_STOP=1 \
    --username "$POSTGRES_USER" \
    --dbname "$POSTGRES_DB"
echo "Restore complete."
