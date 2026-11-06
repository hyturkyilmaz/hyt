#!/bin/sh
# Postgres konteyneri ilk açılışında (boş veri dizini) bir kez çalışır.
# Rolleri kurar: netkar_owner (migrasyon), netkar_app (uygulama), netkar_auth (auth_gate işlev sahibi).
# Şifreler ortamdan gelir; betikte veya imajda sır yoktur.
set -eu

: "${NETKAR_OWNER_PASSWORD:?NETKAR_OWNER_PASSWORD tanımlı olmalı}"
: "${NETKAR_APP_PASSWORD:?NETKAR_APP_PASSWORD tanımlı olmalı}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v owner_pw="$NETKAR_OWNER_PASSWORD" -v app_pw="$NETKAR_APP_PASSWORD" -v dbname="$POSTGRES_DB" <<'SQL'
CREATE ROLE netkar_owner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD :'owner_pw';
CREATE ROLE netkar_app   LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD :'app_pw';
CREATE ROLE netkar_auth  NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
-- INHERIT FALSE: owner yalnız SET ROLE ile (migrasyonda) netkar_auth olur; RLS politikalarını devralmaz.
GRANT netkar_auth TO netkar_owner WITH INHERIT FALSE, SET TRUE;
ALTER DATABASE :"dbname" OWNER TO netkar_owner;
REVOKE ALL ON DATABASE :"dbname" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"dbname" TO netkar_app;
SQL
