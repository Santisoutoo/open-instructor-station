"""The SQLite schema of the navdata index — DDL, version and connection pragmas.

**This file has exactly one owner.** ``CLAUDE.md`` forbids parallelising navdata
schema changes, so the DDL lives in one module rather than being spread across
the parsers that fill it.

Four rules shape what is below, and each of them has already paid for itself:

1. **No optional SQLite modules.** No FTS5, no R\\*Tree, no JSON1, no
   extensions. CI runs four Python x OS combinations and the modules compiled
   into CPython's bundled SQLite vary between them; a Windows-only
   ``no such module: rtree`` is a broken build for a query that measures in
   microseconds either way. Plain tables and B-tree indexes work everywhere.
2. **The database is derived and disposable.** It is never migrated, never
   repaired and never hand-edited. **Bumping** :data:`SCHEMA_VERSION` *is* the
   migration: on a mismatch the cache is discarded and rebuilt from the user's
   own install, which is a path that already runs every AIRAC cycle.
3. **Every index exists because a query needs it.** This file is written once
   per cycle and that write is the user's first impression of the product.
4. **Denormalised where it removes a join from a hot path.** Runway rows carry
   their airport's ICAO rather than a surrogate key.

Airways (``earth_awy.dat``) and minimum sector altitudes (``earth_msa.dat``) are
deliberately **absent**. Nothing in Phase 1 queries them — airways belong to the
flight-plan helper and MSAs to the map — and indexing them now would add
~125 000 rows to a build the user waits for, for no Phase 1 value. Adding them
later is a :data:`SCHEMA_VERSION` bump and one rebuild, which rule 2 makes cheap
by construction.
"""

from __future__ import annotations

import sqlite3

__all__ = [
    "FINALISE_PRAGMAS",
    "INSERT_AIRPORT",
    "INSERT_FIX",
    "INSERT_HOLD",
    "INSERT_META",
    "INSERT_NAVAID",
    "INSERT_PARKING",
    "INSERT_RUNWAY",
    "INSERT_SOURCE_FILE",
    "SCHEMA_SQL",
    "SCHEMA_VERSION",
    "apply_schema",
    "prepare_for_build",
    "read_user_version",
]

#: Bumping this **is** the migration: a cache whose ``PRAGMA user_version``
#: differs is deleted and rebuilt. There are no ``ALTER TABLE`` scripts, because
#: the source of truth is on the user's disk and regeneration is already a
#: routine, instrumented path.
SCHEMA_VERSION = 1

#: Rows are inserted with ``executemany`` in batches of this size. It is also
#: the granularity at which the build checks its cancellation event: large
#: enough that the check costs nothing per row, small enough that cancelling
#: reacts within a fraction of a second.
INSERT_BATCH_SIZE = 10_000


SCHEMA_SQL = f"""
PRAGMA user_version = {SCHEMA_VERSION};

-- ---------------------------------------------------------------- metadata
CREATE TABLE meta (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);

CREATE TABLE source_file (
    role       TEXT PRIMARY KEY,
    path       TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    mtime_ns   INTEGER NOT NULL
);

-- ---------------------------------------------------------------- airports
CREATE TABLE airport (
    icao                   TEXT PRIMARY KEY,
    iata                   TEXT,
    name                   TEXT NOT NULL,
    name_norm              TEXT NOT NULL,
    city                   TEXT,
    country                TEXT,
    region_code            TEXT,
    latitude               REAL NOT NULL,
    longitude              REAL NOT NULL,
    elevation_ft           REAL NOT NULL,
    transition_altitude_ft INTEGER,
    transition_level_ft    INTEGER,
    magnetic_variation_deg REAL,
    has_tower              INTEGER NOT NULL DEFAULT 0,
    runway_count           INTEGER NOT NULL DEFAULT 0,
    longest_runway_m       REAL,
    has_procedures         INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX ix_airport_iata      ON airport(iata) WHERE iata IS NOT NULL;
CREATE INDEX ix_airport_name_norm ON airport(name_norm);
CREATE INDEX ix_airport_pos       ON airport(latitude, longitude);

-- ---------------------------------------------------------------- runways
CREATE TABLE runway (
    id                     INTEGER PRIMARY KEY,
    airport_icao           TEXT NOT NULL,
    ident                  TEXT NOT NULL,
    opposite_ident         TEXT,
    threshold_lat          REAL NOT NULL,
    threshold_lon          REAL NOT NULL,
    end_lat                REAL NOT NULL,
    end_lon                REAL NOT NULL,
    true_bearing_deg       REAL NOT NULL,
    length_m               REAL NOT NULL,
    displaced_threshold_m  REAL NOT NULL DEFAULT 0,
    width_m                REAL,
    surface                TEXT,
    elevation_ft           REAL NOT NULL,
    UNIQUE (airport_icao, ident)
);
CREATE INDEX ix_runway_airport ON runway(airport_icao);

-- ---------------------------------------------------------------- parking
CREATE TABLE parking (
    id               INTEGER PRIMARY KEY,
    airport_icao     TEXT NOT NULL,
    name             TEXT NOT NULL,
    latitude         REAL NOT NULL,
    longitude        REAL NOT NULL,
    heading_true_deg REAL NOT NULL,
    kind             TEXT NOT NULL,
    aircraft_types   TEXT,
    operation        TEXT,
    airline_codes    TEXT
);
CREATE INDEX ix_parking_airport      ON parking(airport_icao);
CREATE INDEX ix_parking_airport_kind ON parking(airport_icao, kind);

-- ---------------------------------------------------------------- navaids
CREATE TABLE navaid (
    id                     INTEGER PRIMARY KEY,
    ident                  TEXT NOT NULL,
    kind                   TEXT NOT NULL,
    name                   TEXT,
    latitude               REAL NOT NULL,
    longitude              REAL NOT NULL,
    elevation_ft           REAL,
    frequency_khz          INTEGER,
    channel                TEXT,
    range_nm               REAL,
    true_deg               REAL,
    mag_deg                REAL,
    glideslope_deg         REAL,
    magnetic_variation_deg REAL,
    region_code            TEXT,
    airport_icao           TEXT,
    runway_ident           TEXT,
    ils_category           TEXT
);
CREATE INDEX ix_navaid_ident        ON navaid(ident);
CREATE INDEX ix_navaid_ident_region ON navaid(ident, region_code);
CREATE INDEX ix_navaid_pos          ON navaid(latitude, longitude);
CREATE INDEX ix_navaid_runway       ON navaid(airport_icao, runway_ident)
                                    WHERE airport_icao IS NOT NULL;

-- ---------------------------------------------------------------- fixes
CREATE TABLE fix (
    id                    INTEGER PRIMARY KEY,
    ident                 TEXT NOT NULL,
    latitude              REAL NOT NULL,
    longitude             REAL NOT NULL,
    region_code           TEXT,
    terminal_airport_icao TEXT,
    name                  TEXT
);
CREATE INDEX ix_fix_ident        ON fix(ident);
CREATE INDEX ix_fix_ident_region ON fix(ident, region_code);
CREATE INDEX ix_fix_terminal     ON fix(terminal_airport_icao, ident)
                                 WHERE terminal_airport_icao IS NOT NULL;
CREATE INDEX ix_fix_pos          ON fix(latitude, longitude);

-- ---------------------------------------------------------------- holds
CREATE TABLE hold (
    id                     INTEGER PRIMARY KEY,
    fix_ident              TEXT NOT NULL,
    region_code            TEXT,
    airport_icao           TEXT,
    fix_type               INTEGER,
    inbound_course_mag_deg REAL NOT NULL,
    leg_time_min           REAL,
    leg_length_nm          REAL,
    turn_direction         TEXT NOT NULL,
    min_altitude_ft        REAL,
    max_altitude_ft        REAL,
    speed_kt               REAL
);
CREATE INDEX ix_hold_fix     ON hold(fix_ident, region_code);
CREATE INDEX ix_hold_airport ON hold(airport_icao) WHERE airport_icao IS NOT NULL;
"""


# ---------------------------------------------------------------------------
# Insert statements — colocated with the DDL so a column change is one edit
# ---------------------------------------------------------------------------

INSERT_META = "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)"

INSERT_SOURCE_FILE = (
    "INSERT OR REPLACE INTO source_file (role, path, size_bytes, mtime_ns) VALUES (?, ?, ?, ?)"
)

INSERT_AIRPORT = """
INSERT OR REPLACE INTO airport (
    icao, iata, name, name_norm, city, country, region_code,
    latitude, longitude, elevation_ft,
    transition_altitude_ft, transition_level_ft, magnetic_variation_deg,
    has_tower, runway_count, longest_runway_m, has_procedures
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

INSERT_RUNWAY = """
INSERT OR REPLACE INTO runway (
    airport_icao, ident, opposite_ident,
    threshold_lat, threshold_lon, end_lat, end_lon,
    true_bearing_deg, length_m, displaced_threshold_m,
    width_m, surface, elevation_ft
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

INSERT_PARKING = """
INSERT INTO parking (
    airport_icao, name, latitude, longitude, heading_true_deg,
    kind, aircraft_types, operation, airline_codes
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

INSERT_NAVAID = """
INSERT INTO navaid (
    ident, kind, name, latitude, longitude, elevation_ft,
    frequency_khz, channel, range_nm, true_deg, mag_deg, glideslope_deg,
    magnetic_variation_deg, region_code, airport_icao, runway_ident, ils_category
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

INSERT_FIX = """
INSERT INTO fix (ident, latitude, longitude, region_code, terminal_airport_icao, name)
VALUES (?, ?, ?, ?, ?, ?)
"""

INSERT_HOLD = """
INSERT INTO hold (
    fix_ident, region_code, airport_icao, fix_type, inbound_course_mag_deg,
    leg_time_min, leg_length_nm, turn_direction, min_altitude_ft, max_altitude_ft, speed_kt
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


# ---------------------------------------------------------------------------
# Connection settings
# ---------------------------------------------------------------------------


def prepare_for_build(connection: sqlite3.Connection) -> None:
    """Configure a connection for the one-shot bulk write.

    The file is disposable (rule 2), so durability guarantees during the build
    buy nothing and cost most of the build time. ``page_size`` must be set
    before any table exists, which is why this runs before :func:`apply_schema`.
    """
    connection.execute("PRAGMA page_size = 8192")
    connection.execute("PRAGMA journal_mode = OFF")
    connection.execute("PRAGMA synchronous = OFF")
    connection.execute("PRAGMA temp_store = MEMORY")


def apply_schema(connection: sqlite3.Connection) -> None:
    """Create every table and index, and stamp ``PRAGMA user_version``."""
    connection.executescript(SCHEMA_SQL)


#: Run immediately before the atomic publish, in this order.
#:
#: ``ANALYZE`` gives the planner statistics for the life of the file. Then the
#: journal mode is switched back to ``DELETE``: a finished cache is **one
#: self-contained file**, which is exactly what an atomic rename can move.
#:
#: **Never WAL.** WAL exists so readers do not block a concurrent *writer*, and
#: this database is written once, by one thread, before any reader can open it.
#: What WAL would cost is real: a WAL database is three files, the atomic
#: publish moves one of them, and a build that ends in WAL publishes a main file
#: whose committed content is partly sitting in a ``-wal`` sibling left behind
#: under the temporary name. Read-only opens are worse still — SQLite wants to
#: read, and sometimes create, the ``-shm`` file, so opening the cache starts
#: depending on write permission in the cache directory.
FINALISE_PRAGMAS = (
    "ANALYZE",
    "PRAGMA journal_mode = DELETE",
    "PRAGMA optimize",
)


def read_user_version(connection: sqlite3.Connection) -> int:
    """The schema version stamped into a cache file."""
    row = connection.execute("PRAGMA user_version").fetchone()
    return int(row[0]) if row is not None else 0
