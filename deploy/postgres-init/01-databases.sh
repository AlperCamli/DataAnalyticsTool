#!/bin/bash
# Compose-local init: the ops database the core migrates into, plus a
# demo source database seeded with the customer-shaped fixture DDL so
# the postgres connector has something real to introspect in live mode.
set -euo pipefail

psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" <<'SQL'
CREATE DATABASE cl_ops;
CREATE DATABASE cl_demo;
SQL

if [ -f /seed/supabase-customer.sql ]; then
  psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d cl_demo -f /seed/supabase-customer.sql
fi
