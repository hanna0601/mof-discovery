"""
Unified SQLite schema for the MOF discovery database.
One `mofs` table covers both CoRE MOF (source='core_mof') and
literature-extracted records (source='literature').
"""

PAPERS_DDL = """
CREATE TABLE IF NOT EXISTS papers (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    title            TEXT,
    year             INTEGER,
    url              TEXT,
    doi              TEXT,
    pmcid            TEXT,
    source           TEXT,           -- semantic_scholar | pubmed | openalex | upload
    open_access_pdf  TEXT,
    citation_count   INTEGER,
    publication_date TEXT,
    abstract         TEXT,
    authors          TEXT,           -- JSON array of author name strings
    fulltext_chars   INTEGER,
    fulltext_method  TEXT,           -- pmc_xml | bs4 | pdf | ...
    status           TEXT DEFAULT 'pending',
    -- pending | fetching | extracting | extracted | no_mofs | failed
    failure_reason   TEXT DEFAULT '',
    created_at       TEXT DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS papers_doi ON papers(doi) WHERE doi != '';
"""

MOFS_DDL = """
CREATE TABLE IF NOT EXISTS mofs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT NOT NULL,      -- 'core_mof' | 'literature'
    source_dataset TEXT,            -- ASR | FSR | paper source detail

    -- Identity
    name        TEXT NOT NULL,
    refcode     TEXT,               -- CoRE MOF CSD refcode
    coreid      TEXT,               -- CoRE MOF internal ID

    -- Metal / structure
    metal_node       TEXT,
    functionalization TEXT,
    topology         TEXT,

    -- Geometry (CoRE MOF CSV columns)
    surface_area_m2_g        REAL,  -- ASA (m2/g)
    pore_volume_cm3_g        REAL,  -- PV (cm3/g)
    pore_limiting_diameter_A REAL,  -- PLD (Å)
    largest_cavity_diameter_A REAL, -- LCD (Å)
    void_fraction            REAL,  -- VF
    crystal_density_g_cm3    REAL,

    -- Open metal site
    has_open_metal_site INTEGER,    -- 0 | 1

    -- Stability
    water_stability         TEXT,
    water_stability_score   REAL,   -- 0-1 numeric (CoRE MOF)
    solvent_stability_score REAL,   -- 0-1 numeric (CoRE MOF)
    thermal_stability_c     REAL,   -- °C
    stability_notes         TEXT,

    -- CO2 performance (literature)
    co2_uptake_value        REAL,
    co2_uptake_unit         TEXT,
    temperature_k           REAL,
    pressure_bar            REAL,
    selectivity_value       REAL,
    selectivity_definition  TEXT,
    working_capacity_mmol_g REAL,
    application_type        TEXT,   -- DAC | post_combustion | pre_combustion

    -- CO2 affinity (CoRE simulation)
    henry_law_co2_class TEXT,       -- weak | moderate | strong | superstrong

    -- Provenance (literature records)
    evidence_quote  TEXT,
    confidence      REAL,
    paper_id        INTEGER REFERENCES papers(id),
    paper_doi       TEXT,
    paper_title     TEXT,

    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS mofs_source ON mofs(source);
CREATE INDEX IF NOT EXISTS mofs_name   ON mofs(name);
"""

MEASUREMENTS_DDL = """
CREATE TABLE IF NOT EXISTS mof_measurements (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    mof_id           INTEGER NOT NULL REFERENCES mofs(id) ON DELETE CASCADE,
    measurement_type TEXT NOT NULL,   -- co2_uptake | selectivity | working_capacity
    value            REAL,
    unit             TEXT DEFAULT '',
    temperature_k    REAL,
    pressure_bar     REAL,
    selectivity_definition TEXT DEFAULT '',
    application_type TEXT DEFAULT '',
    evidence_quote   TEXT DEFAULT '',
    confidence       REAL DEFAULT 0.0,
    paper_id         INTEGER REFERENCES papers(id),
    paper_doi        TEXT DEFAULT '',
    paper_title      TEXT DEFAULT '',
    created_at       TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS meas_mof_id ON mof_measurements(mof_id);
CREATE INDEX IF NOT EXISTS meas_type   ON mof_measurements(measurement_type);
"""

MEMORY_DDL = """
CREATE TABLE IF NOT EXISTS agent_memory (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    query           TEXT NOT NULL,
    intent          TEXT,
    summary         TEXT,           -- condensed finding saved for future context
    query_embedding TEXT,           -- JSON array of floats (text-embedding-3-small)
    created_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS mem_created ON agent_memory(created_at);
"""

MIGRATIONS = [
    "ALTER TABLE mofs ADD COLUMN source_dataset TEXT",
    "ALTER TABLE mofs ADD COLUMN largest_cavity_diameter_A REAL",
]


def init_db(con) -> None:
    con.executescript(PAPERS_DDL + MOFS_DDL + MEASUREMENTS_DDL + MEMORY_DDL)
    for stmt in MIGRATIONS:
        try:
            con.execute(stmt)
        except Exception:
            pass
    con.commit()
