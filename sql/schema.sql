-- Activer l'extension pour générer des UUID
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. USERS & ROLES
CREATE TABLE IF NOT EXISTS users  (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    full_name VARCHAR(150) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role VARCHAR(20) CHECK (role IN ('ADMIN', 'FIELD_AGENT', 'VALIDATOR')),
    created_by UUID REFERENCES users(id) ON DELETE SET NULL, -- L'admin qui a créé ce compte
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. REFERENTIAL TABLES
CREATE TABLE IF NOT EXISTS elections (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL,
    type VARCHAR(50),  -- "legislative | presidential | municipal | referendum"
    status VARCHAR(20) DEFAULT 'DRAFT' CHECK (status IN ('OPEN', 'ARCHIVED', 'DRAFT'))
);


CREATE UNIQUE INDEX IF NOT EXISTS only_one_active_election
ON elections (status)
WHERE status = 'OPEN' OR status='DRAFT';


CREATE TABLE IF NOT EXISTS source_documents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    election_id UUID NOT NULL REFERENCES elections(id) ON DELETE CASCADE,
    file_name VARCHAR(255) NOT NULL,
    file_type VARCHAR(50) NOT NULL, -- 'PDF_ARCHIVE' or 'SCAN_PV'
    storage_url TEXT NOT NULL,
    integrity_hash VARCHAR(64) NOT NULL,
    uploaded_by UUID REFERENCES users(id) ON DELETE SET NULL, -- Qui a chargé le fichier
    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    -- verification des integrite des fichiers aux etapes cles
    last_integrity_check TIMESTAMP,
    integrity_status boolean DEFAULT TRUE
);



CREATE TABLE IF NOT EXISTS candidates (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    full_name TEXT,
    party_ticker TEXT,
    color_code VARCHAR(7)
);



CREATE TABLE IF NOT EXISTS locality_results_staging(
    id SERIAL PRIMARY KEY,

    region VARCHAR(100),
    locality TEXT,
    election_id UUID NOT NULL REFERENCES elections(id) ON DELETE CASCADE,

    source_id UUID REFERENCES source_documents(id) ON DELETE CASCADE,

    polling_stations_count integer,
    on_call_staff integer,

    pop_size_male integer,
    pop_size_female integer,
    pop_size integer,

    registered_voters_male integer,
    registered_voters_female integer,
    registered_voters_total integer,

    voters_male integer,
    voters_female integer,
    voters_total integer,

    participation_rate FLOAT8,

    null_ballots integer,
    expressed_votes integer,

    blank_ballots_pct FLOAT8,
    blank_ballots_count integer,

    unregistered_voters_count integer,

    bbox_json TEXT, -- [x0, top, x1, bottom, page]

    validated_by UUID REFERENCES users(id) ON DELETE SET NULL, -- Validateur qui a approuvé
    validation_status VARCHAR(20) DEFAULT 'PENDING',

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    validated_at TIMESTAMP,

    UNIQUE (election_id, region, locality)

);


CREATE TABLE IF NOT EXISTS candidate_results_staging (
    id SERIAL PRIMARY KEY,
    locality_id INTEGER NOT NULL REFERENCES locality_results_staging(id) ON DELETE CASCADE,
    is_independent BOOLEAN,
    full_name TEXT,
    party_ticker TEXT,
    raw_value INTEGER,

    bbox_json TEXT,

    validated_by UUID REFERENCES users(id) ON DELETE SET NULL, -- Validateur qui a approuvé
    validation_status VARCHAR(20) DEFAULT 'PENDING',

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    validated_at TIMESTAMP
);




CREATE TABLE IF NOT EXISTS locality_winner(
    id SERIAL PRIMARY KEY,
    candidate_id INTEGER NOT NULL REFERENCES candidate_results_staging(id) ON DELETE CASCADE
);

-- 6. TRANSACTIONAL (VOTE EN DIRECT)
CREATE TABLE IF NOT EXISTS voter_registry (
    voter_id_hash VARCHAR(64) PRIMARY KEY,
    election_id UUID REFERENCES elections(id) ON DELETE CASCADE,
    voted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
