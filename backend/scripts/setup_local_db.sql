-- One-time setup for a local FlexiDriveMy Postgres role + database.
-- Run this once as the postgres superuser (see README.md for the exact command).
--
-- CREATEDB is granted (not SUPERUSER) so pytest-django can create/drop its
-- own test_flexidrivemy database automatically without elevated privileges.
--
-- QA audit L21: pick your OWN password below and set the SAME value as
-- POSTGRES_PASSWORD in your .env file (not committed anywhere) - this
-- script previously hardcoded one real, working password in cleartext,
-- shared by every clone of this repo; settings.py also no longer falls
-- back to it (or any default) if POSTGRES_PASSWORD is left unset.

CREATE ROLE flexidrivemy WITH LOGIN PASSWORD 'REPLACE_WITH_YOUR_OWN_LOCAL_PASSWORD' CREATEDB;
CREATE DATABASE flexidrivemy OWNER flexidrivemy;
