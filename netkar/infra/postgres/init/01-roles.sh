#!/bin/sh
# Postgres konteyneri ilk açılışında (boş veri dizini) bir kez çalışır.
# Rolleri kurar: netkar_owner (migrasyon), netkar_app (API), netkar_worker (senkron işçisi; şifreli sütunları
# okuyabilen tek rol), netkar_auth (auth_gate işlev sahibi), netkar_sync_gate (sync_gate işlev sahibi).
# Var olan bir veri dizininde (bu betik çalışmaz) rolleri kurmak için: docs/adr/0005 §6 ve services/api/README.md.
# Şifreler ortamdan gelir; betikte veya imajda sır yoktur.
set -eu

: "${NETKAR_OWNER_PASSWORD:?NETKAR_OWNER_PASSWORD tanımlı olmalı}"
: "${NETKAR_APP_PASSWORD:?NETKAR_APP_PASSWORD tanımlı olmalı}"
: "${NETKAR_WORKER_PASSWORD:?NETKAR_WORKER_PASSWORD tanımlı olmalı}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v owner_pw="$NETKAR_OWNER_PASSWORD" -v app_pw="$NETKAR_APP_PASSWORD" \
  -v worker_pw="$NETKAR_WORKER_PASSWORD" -v dbname="$POSTGRES_DB" <<'SQL'
CREATE ROLE netkar_owner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD :'owner_pw';
CREATE ROLE netkar_app   LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD :'app_pw';
CREATE ROLE netkar_worker LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD :'worker_pw';
CREATE ROLE netkar_auth  NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
CREATE ROLE netkar_sync_gate NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
-- INHERIT FALSE: owner yalnız SET ROLE ile (migrasyonda) netkar_auth olur; RLS politikalarını devralmaz.
GRANT netkar_auth TO netkar_owner WITH INHERIT FALSE, SET TRUE;
GRANT netkar_sync_gate TO netkar_owner WITH INHERIT FALSE, SET TRUE;
ALTER DATABASE :"dbname" OWNER TO netkar_owner;
REVOKE ALL ON DATABASE :"dbname" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"dbname" TO netkar_app;
GRANT CONNECT ON DATABASE :"dbname" TO netkar_worker;
SQL
