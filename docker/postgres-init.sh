#!/bin/sh
# Executed only for a NEW PostgreSQL volume by the official image entrypoint.
set -eu
case "$ERP_DATABASE" in
    ''|[!a-z]*|*[!a-z0-9_]*) echo 'Invalid ERP_DATABASE' >&2; exit 1 ;;
esac
if [ "${#ERP_DATABASE}" -gt 63 ]; then
    echo 'ERP_DATABASE is too long' >&2
    exit 1
fi
psql --username postgres --dbname postgres --set ON_ERROR_STOP=1 --set database="$ERP_DATABASE" <<'SQL'
DO $$
DECLARE secret text := btrim(pg_read_file('/run/secrets/db_password'), E' \t\r\n');
BEGIN
    IF length(secret) < 16 THEN
        RAISE EXCEPTION 'Use a database secret with at least 16 characters';
    END IF;
    EXECUTE format('CREATE ROLE odoo LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD %L', secret);
END $$;
SELECT format('CREATE DATABASE %I OWNER odoo', :'database') \gexec
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', :'database') \gexec
REVOKE ALL ON DATABASE postgres FROM PUBLIC;
GRANT CONNECT ON DATABASE postgres TO odoo;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SQL
