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

CREATE TABLE IF NOT EXISTS geography (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    region VARCHAR(100),
    constituency VARCHAR(100),
    district VARCHAR(100),
    polling_station_name VARCHAR(100)
);

CREATE TABLE IF NOT EXISTS candidates (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    full_name VARCHAR(150),
    party_ticker VARCHAR(20),
    color_code VARCHAR(7)
);

-- 3. AUDIT & PROVENANCE
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

-- 4. STAGING (PIPELINE DE TRAITEMENT)
CREATE TABLE IF NOT EXISTS staging_results (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_id UUID REFERENCES source_documents(id),
    geography_id UUID REFERENCES geography(id) NOT NULL,
    candidate_id UUID REFERENCES candidates(id) NOT NULL,
    raw_value INTEGER,
    page_number INTEGER,
    bbox_json TEXT,
    processed_by UUID REFERENCES users(id) NOT NULL, -- Agent qui a fait le scan/saisie
    validated_by UUID REFERENCES users(id), -- Validateur qui a approuvé
    validation_status VARCHAR(20) DEFAULT 'PENDING',

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    validated_at TIMESTAMP,

    CONSTRAINT check_validation_logic
        CHECK (
            (validation_status = 'VALIDATED' AND validated_by IS NOT NULL AND validated_at IS NOT NULL)
            OR
            (validation_status != 'VALIDATED')
        )
);

-- 5. CONSOLIDATED RESULTS (LA VÉRITÉ)
CREATE TABLE IF NOT EXISTS consolidated_results (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    election_id UUID REFERENCES elections(id),
    geography_id UUID REFERENCES geography(id),
    candidate_id UUID REFERENCES candidates(id),
    source_id UUID REFERENCES source_documents(id),
    vote_count INTEGER,
    entry_type VARCHAR(30), -- 'OFFICIAL_CEI' or 'DIRECT_VOTE'
    source_page INTEGER,
    proof_coordinates TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 6. TRANSACTIONAL (VOTE EN DIRECT)
CREATE TABLE IF NOT EXISTS voter_registry (
    voter_id_hash VARCHAR(64) PRIMARY KEY,
    election_id UUID REFERENCES elections(id),
    voted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
