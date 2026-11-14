#!/bin/sh
# Runs once, when the Postgres volume is first created.
# Two roles: the owner runs migrations and owns the tables; the API logs in as the
# app role, which row-level security applies to.
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<SQL
CREATE ROLE freightflow_owner LOGIN PASSWORD '${FF_OWNER_PASSWORD}';
CREATE ROLE freightflow_app LOGIN PASSWORD '${FF_APP_PASSWORD}';
CREATE DATABASE freightflow OWNER freightflow_owner;
SQL
