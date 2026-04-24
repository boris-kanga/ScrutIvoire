#!/bin/bash
set -e

# Bloc 1 : Création de la fonction
# On utilise 'EOSQL' pour que Bash ne touche pas aux variables internes de Postgres ($1, $2, etc.)
psql -v ON_ERROR_STOP=1 --username "$DB_USER" --dbname "$DB_NAME" <<-'EOSQL'
    -- 1. On active l'extension nécessaire
    CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

    -- 2. Nettoyage de l'ancienne fonction au cas où la signature aurait changé
    -- On ne peut pas DROP si des triggers l'utilisent, donc on utilise CASCADE
    DROP FUNCTION IF EXISTS check_immutable_column CASCADE;

    -- 3. Création de la fonction
    CREATE OR REPLACE FUNCTION check_immutable_column()
    RETURNS TRIGGER AS $$
    DECLARE
        col_name TEXT;
        old_val TEXT;
        new_val TEXT;
    BEGIN
        -- Récupère le nom de la colonne passé en argument du trigger
        col_name := TG_ARGV[0];

        EXECUTE format('SELECT ($1).%I::text, ($2).%I::text', col_name, col_name)
        USING OLD, NEW
        INTO old_val, new_val;

        IF new_val IS DISTINCT FROM old_val THEN
            RAISE EXCEPTION 'La colonne % est immuable et ne peut pas être modifiée.', col_name;
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
EOSQL

# Bloc 2 : Création de l'utilisateur (on laisse Bash injecter les variables du .env)
psql -v ON_ERROR_STOP=1 --username "$DB_USER" --dbname "$DB_NAME" <<-EOSQL
    DO \$$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '$LLM_USER') THEN
            CREATE USER $LLM_USER WITH PASSWORD '$LLM_PWD';
        END IF;
    END
    \$$;

    GRANT CONNECT ON DATABASE $DB_NAME TO $LLM_USER;
    GRANT USAGE ON SCHEMA public TO $LLM_USER;
    GRANT SELECT ON ALL TABLES IN SCHEMA public TO $LLM_USER;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO $LLM_USER;
EOSQL
