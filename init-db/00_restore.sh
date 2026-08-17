#!/bin/bash
# Restore database from dump.sql.
# The \restrict line (pg_dump password marker) is filtered out because
# psql treats it as an unknown metacommand and may stop on error.
set -e
echo "Restoring database from /dump.sql..."
grep -v '\\restrict' /dump.sql | psql -v ON_ERROR_STOP=1 \
    --username "$POSTGRES_USER" \
    --dbname "$POSTGRES_DB"
echo "Restore complete."
