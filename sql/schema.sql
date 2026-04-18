-- Activer l'extension pour générer des UUID
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. USERS & ROLES
CREATE TABLE IF NOT EXISTS users  (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    full_name VARCHAR(150) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role VARCHAR(20) CHECK (role IN ('ADMIN', 'FIELD_AGENT', 'VALIDATOR')),
    created_by UUID REFERENCES users(id), -- L'admin qui a créé ce compte
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. REFERENTIAL TABLES
CREATE TABLE IF NOT EXISTS elections (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL,
    type VARCHAR(50),
    status VARCHAR(20) DEFAULT 'DRAFT' CHECK (status IN ('OPEN', 'ARCHIVED', 'DRAFT'))
);


CREATE UNIQUE INDEX IF NOT EXISTS only_one_active_election
ON elections (status)
WHERE status = 'OPEN' OR status='DRAFT';


CREATE TABLE IF NOT EXISTS source_documents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    election_id UUID REFERENCES elections(id) NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    file_type VARCHAR(50) NOT NULL, -- 'PDF_ARCHIVE' or 'SCAN_PV'
    storage_url TEXT NOT NULL,
    integrity_hash VARCHAR(64) NOT NULL,
    uploaded_by UUID REFERENCES users(id) NOT NULL, -- Qui a chargé le fichier
    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    -- verification des integrite des fichiers aux etapes cles
    last_integrity_check TIMESTAMP,
    integrity_status boolean DEFAULT TRUE
);



CREATE TABLE IF NOT EXISTS candidates (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    full_name VARCHAR(150),
    party_ticker VARCHAR(20),
    color_code VARCHAR(7)
);



CREATE TABLE IF NOT EXISTS locality_results_staging(
    id SERIAL PRIMARY KEY,

    region VARCHAR(100),
    locality TEXT,
    election_id UUID REFERENCES elections(id) NOT NULL,

    source_id UUID REFERENCES source_documents(id),

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

    winner str,

    bbox_json TEXT, -- [x0, x1, width, height, page]

    processed_by UUID REFERENCES users(id) NOT NULL, -- Agent qui a fait le scan/saisie
    validated_by UUID REFERENCES users(id), -- Validateur qui a approuvé
    validation_status VARCHAR(20) DEFAULT 'PENDING',

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    validated_at TIMESTAMP,

    UNIQUE (election_id, region, locality)

);


CREATE TABLE IF NOT EXISTS candidate_results_staging (
    id SERIAL PRIMARY KEY,
    locality_id INTEGER REFERENCES locality_results_staging(id) NOT NULL,

    full_name VARCHAR(150),
    party_ticker VARCHAR(20),
    raw_value INTEGER,

    bbox_json TEXT,

    processed_by UUID REFERENCES users(id) NOT NULL, -- Agent qui a fait le scan/saisie
    validated_by UUID REFERENCES users(id), -- Validateur qui a approuvé
    validation_status VARCHAR(20) DEFAULT 'PENDING',

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    validated_at TIMESTAMP
);

-- 6. TRANSACTIONAL (VOTE EN DIRECT)
CREATE TABLE IF NOT EXISTS voter_registry (
    voter_id_hash VARCHAR(64) PRIMARY KEY,
    election_id UUID REFERENCES elections(id),
    voted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
