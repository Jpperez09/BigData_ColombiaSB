-- =============================================================================
-- Migration 001 — Initial schema
-- Target: Supabase (PostgreSQL 15+)
-- Matches: docs/schema.md · utils/models.py
-- Run once; idempotent via IF NOT EXISTS / OR REPLACE guards.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- Extensions
-- ---------------------------------------------------------------------------

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";   -- uuid_generate_v4()
CREATE EXTENSION IF NOT EXISTS pg_trgm;        -- GIN trigram indexes for fuzzy match

-- ---------------------------------------------------------------------------
-- sources  (lookup table)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS sources (
    id          SERIAL      PRIMARY KEY,
    name        TEXT        NOT NULL UNIQUE,
    description TEXT        NOT NULL
);

INSERT INTO sources (name, description) VALUES
    ('gmaps',            'Google Maps Places API / scraper'),
    ('instagram',        'Instagram business profiles'),
    ('paginas_amarillas','Páginas Amarillas Colombia directory'),
    ('mercado_libre',    'Mercado Libre Colombia store listings')
ON CONFLICT (name) DO NOTHING;

-- ---------------------------------------------------------------------------
-- businesses_raw  (staging, one row per source × business)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS businesses_raw (

    -- Identity
    id                      UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    master_id               UUID,                           -- FK filled by Step 2
    source                  TEXT            NOT NULL
                                REFERENCES sources (name),
    source_id               TEXT            NOT NULL,

    -- Name
    name                    TEXT            NOT NULL,
    name_normalized         TEXT,

    -- Location
    address_raw             TEXT,
    address_street          TEXT,
    city                    TEXT            NOT NULL
                                CHECK (city IN ('Medellín', 'Bogotá')),
    neighborhood            TEXT,
    lat                     DOUBLE PRECISION,
    lng                     DOUBLE PRECISION,

    -- Contact
    phone_raw               TEXT,
    phone_e164              TEXT
                                CHECK (phone_e164 ~ '^\+57[0-9]{10}$'),
    whatsapp_flag           BOOLEAN         NOT NULL DEFAULT FALSE,

    -- Instagram
    instagram_handle        TEXT,
    instagram_followers     INTEGER         CHECK (instagram_followers >= 0),
    instagram_posts_count   INTEGER         CHECK (instagram_posts_count >= 0),
    instagram_last_post_at  TIMESTAMPTZ,
    instagram_has_catalog   BOOLEAN,

    -- Classification
    category_raw            TEXT,
    ciiu_code               TEXT,

    -- Metrics
    rating                  NUMERIC(2,1)    CHECK (rating >= 0 AND rating <= 5),
    reviews_count           INTEGER         CHECK (reviews_count >= 0),

    -- Online presence
    website                 TEXT,
    bio_text                TEXT,

    -- Metadata
    quality_flags           JSONB           NOT NULL DEFAULT '[]'::JSONB,
    scraped_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- Uniqueness: one row per (source, business) to allow safe upserts
    CONSTRAINT uq_businesses_raw_source_id UNIQUE (source, source_id)
);

COMMENT ON COLUMN businesses_raw.master_id IS
    'Assigned by Step 2 entity-resolution. NULL until deduplication runs.';

COMMENT ON COLUMN businesses_raw.whatsapp_flag IS
    'TRUE if the source explicitly marks the phone as WhatsApp OR if a wa.me link was found on the page.';

COMMENT ON COLUMN businesses_raw.ciiu_code IS
    'CIIU sector code (Colombia). NOT scraped — assigned programmatically in Step 2 based on category_raw.';

COMMENT ON COLUMN businesses_raw.quality_flags IS
    'JSONB array of issue tags, e.g. ["missing_phone","low_confidence_address"]. '
    'Valid values: missing_phone, missing_address, low_confidence_address, '
    'unverified_coordinates, inactive_instagram, duplicate_candidate.';

-- ---------------------------------------------------------------------------
-- businesses_canonical  (post Step 2, one row per real-world entity)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS businesses_canonical (

    -- Identity (master_id is required and is the logical PK)
    id                      UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    master_id               UUID            NOT NULL UNIQUE,
    source                  TEXT            NOT NULL
                                REFERENCES sources (name),
    source_id               TEXT            NOT NULL,

    -- Name
    name                    TEXT            NOT NULL,
    name_normalized         TEXT,

    -- Location
    address_raw             TEXT,
    address_street          TEXT,
    city                    TEXT            NOT NULL
                                CHECK (city IN ('Medellín', 'Bogotá')),
    neighborhood            TEXT,
    lat                     DOUBLE PRECISION,
    lng                     DOUBLE PRECISION,

    -- Contact
    phone_raw               TEXT,
    phone_e164              TEXT
                                CHECK (phone_e164 ~ '^\+57[0-9]{10}$'),
    whatsapp_flag           BOOLEAN         NOT NULL DEFAULT FALSE,

    -- Instagram
    instagram_handle        TEXT,
    instagram_followers     INTEGER         CHECK (instagram_followers >= 0),
    instagram_posts_count   INTEGER         CHECK (instagram_posts_count >= 0),
    instagram_last_post_at  TIMESTAMPTZ,
    instagram_has_catalog   BOOLEAN,

    -- Classification
    category_raw            TEXT,
    ciiu_code               TEXT,

    -- Metrics
    rating                  NUMERIC(2,1)    CHECK (rating >= 0 AND rating <= 5),
    reviews_count           INTEGER         CHECK (reviews_count >= 0),

    -- Online presence
    website                 TEXT,
    bio_text                TEXT,

    -- Metadata
    quality_flags           JSONB           NOT NULL DEFAULT '[]'::JSONB,
    scraped_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

COMMENT ON COLUMN businesses_canonical.master_id IS
    'Stable identifier for a real-world business entity across all sources. '
    'All businesses_raw rows that resolve to the same entity share this UUID.';

COMMENT ON COLUMN businesses_canonical.whatsapp_flag IS
    'TRUE if any source for this master_id marked the phone as WhatsApp.';

COMMENT ON COLUMN businesses_canonical.ciiu_code IS
    'CIIU sector code assigned in Step 2. Used for sectoral scoring and dashboard filters.';

COMMENT ON COLUMN businesses_canonical.quality_flags IS
    'Union of quality_flags from all contributing businesses_raw rows for this master_id.';

-- ---------------------------------------------------------------------------
-- Indexes — businesses_raw
-- ---------------------------------------------------------------------------

-- Covered by UNIQUE constraint above, listed here for documentation clarity:
-- UNIQUE (source, source_id) → already created via constraint

CREATE INDEX IF NOT EXISTS idx_raw_master_id
    ON businesses_raw (master_id)
    WHERE master_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_raw_city
    ON businesses_raw (city);

CREATE INDEX IF NOT EXISTS idx_raw_ciiu_code
    ON businesses_raw (ciiu_code)
    WHERE ciiu_code IS NOT NULL;

-- GIN trigram: fuzzy name matching for entity resolution in Step 2
CREATE INDEX IF NOT EXISTS idx_raw_name_normalized_trgm
    ON businesses_raw USING GIN (name_normalized gin_trgm_ops)
    WHERE name_normalized IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_raw_phone_e164
    ON businesses_raw (phone_e164)
    WHERE phone_e164 IS NOT NULL;

-- ---------------------------------------------------------------------------
-- Indexes — businesses_canonical
-- ---------------------------------------------------------------------------

-- master_id UNIQUE constraint already creates a btree index

CREATE INDEX IF NOT EXISTS idx_canonical_city
    ON businesses_canonical (city);

CREATE INDEX IF NOT EXISTS idx_canonical_ciiu_code
    ON businesses_canonical (ciiu_code)
    WHERE ciiu_code IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_canonical_name_normalized_trgm
    ON businesses_canonical USING GIN (name_normalized gin_trgm_ops)
    WHERE name_normalized IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_canonical_phone_e164
    ON businesses_canonical (phone_e164)
    WHERE phone_e164 IS NOT NULL;

-- ---------------------------------------------------------------------------
-- updated_at trigger
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

-- Trigger on businesses_raw
DROP TRIGGER IF EXISTS trg_businesses_raw_updated_at ON businesses_raw;
CREATE TRIGGER trg_businesses_raw_updated_at
    BEFORE UPDATE ON businesses_raw
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();

-- Trigger on businesses_canonical
DROP TRIGGER IF EXISTS trg_businesses_canonical_updated_at ON businesses_canonical;
CREATE TRIGGER trg_businesses_canonical_updated_at
    BEFORE UPDATE ON businesses_canonical
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();
