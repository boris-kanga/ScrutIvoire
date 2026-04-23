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


CREATE TABLE IF NOT EXISTS regions (
    id SERIAL PRIMARY KEY,
    election_id UUID NOT NULL REFERENCES elections(id) ON DELETE CASCADE,
    original_raw_name VARCHAR(100)
);


CREATE TABLE IF NOT EXISTS circonscriptions(
    id SERIAL PRIMARY KEY,
    election_id UUID NOT NULL REFERENCES elections(id) ON DELETE CASCADE,
    region_id INTEGER NOT NULL REFERENCES regions(id) ON DELETE CASCADE,
    original_raw_name TEXT,
    source_id UUID REFERENCES source_documents(id) ON DELETE CASCADE,
    crop_url TEXT DEFAULT NULL,
    bbox_json TEXT -- [x0, top, x1, bottom, page]

);

CREATE TABLE IF NOT EXISTS political_parties(
    id SERIAL PRIMARY KEY,
    election_id UUID NOT NULL REFERENCES elections(id) ON DELETE CASCADE,
    original_raw_name TEXT
);


CREATE TABLE IF NOT EXISTS candidates (
    id SERIAL PRIMARY KEY,
    election_id UUID NOT NULL REFERENCES elections(id) ON DELETE CASCADE,
    source_id UUID REFERENCES source_documents(id) ON DELETE CASCADE,
    circonscription_id INTEGER DEFAULT NULL -- for presidential election
                REFERENCES circonscriptions(id) ON DELETE CASCADE,
    party_id INTEGER REFERENCES political_parties(id) ON DELETE CASCADE,
    is_independent BOOLEAN DEFAULT NULL,

    original_raw_name TEXT,
    crop_url TEXT DEFAULT NULL,

    bbox_json TEXT DEFAULT NULL -- for presidential election: [x0, top, x1, bottom, page]
);


CREATE TABLE IF NOT EXISTS ref_entities(
    id SERIAL PRIMARY KEY,
    election_id UUID NOT NULL REFERENCES elections(id) ON DELETE CASCADE,

    -- Les cibles possibles du match
    circonscription_id INTEGER DEFAULT NULL REFERENCES circonscriptions(id),
    region_id          INTEGER DEFAULT NULL REFERENCES regions(id),
    party_id           INTEGER DEFAULT NULL REFERENCES political_parties(id),
    candidate_id       INTEGER DEFAULT NULL REFERENCES candidates(id),

    canonic_name TEXT NOT NULL, -- La version "propre" (ex: "SUD-COMOÉ")
    raw_name TEXT,              -- La version "PDF" (ex: "Sud-Comoe")

    type VARCHAR(255) CHECK (
        type IN (
            'COMMUNE', 'SOUS_PREFECTURE', 'ZONE', -- Pour circonscription_id
            'REGION',                             -- Pour region_id
            'CANDIDATE',                          -- Pour candidate_id
            'PARTY'                               -- Pour party_id
        )
    )
);


CREATE TABLE IF NOT EXISTS locality_results_staging(
    id SERIAL PRIMARY KEY,
    election_id UUID NOT NULL REFERENCES elections(id) ON DELETE CASCADE,

    circonscription_id INTEGER NOT NULL REFERENCES circonscriptions(id) ON DELETE CASCADE,

    --region VARCHAR(100),
    --locality TEXT,

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

    validated_by UUID REFERENCES users(id) ON DELETE SET NULL, -- Validateur qui a approuvé
    validation_status VARCHAR(20) DEFAULT 'PENDING',

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    validated_at TIMESTAMP,

    UNIQUE (election_id, circonscription_id)

);


CREATE TABLE IF NOT EXISTS candidate_results_staging (
    id SERIAL PRIMARY KEY,
    election_id UUID NOT NULL REFERENCES elections(id) ON DELETE CASCADE,

    circonscription_id INTEGER NOT NULL REFERENCES circonscriptions(id) ON DELETE CASCADE,

    candidate_id       INTEGER NOT NULL REFERENCES candidates(id),

    raw_value INTEGER,

    winner    BOOLEAN DEFAULT NULL,

    validated_by UUID REFERENCES users(id) ON DELETE SET NULL, -- Validateur qui a approuvé
    validation_status VARCHAR(20) DEFAULT 'PENDING',

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    validated_at TIMESTAMP
);


CREATE TABLE IF NOT EXISTS chat_session(
    id SERIAL PRIMARY KEY,
    election_id UUID,
    session_id UUID NOT NULL,
    question text,

    answer text,

    ask_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    answer_time TIMESTAMP,

    status VARCHAR(20) DEFAULT 'PENDING',
    answer_meta JSONB

);

-- 6. TRANSACTIONAL (VOTE EN DIRECT)
CREATE TABLE IF NOT EXISTS voter_registry (
    voter_id_hash VARCHAR(64) PRIMARY KEY,
    election_id UUID REFERENCES elections(id) ON DELETE CASCADE,
    voted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
