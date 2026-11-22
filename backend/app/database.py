from __future__ import annotations

import sqlite3
from pathlib import Path

from .config import DATABASE_PATH


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS instruments (
    instrument_id TEXT PRIMARY KEY,
    market TEXT NOT NULL CHECK (market IN ('HK', 'US')),
    exchange TEXT NOT NULL,
    provider_symbol TEXT NOT NULL,
    display_symbol TEXT NOT NULL,
    name TEXT NOT NULL,
    currency TEXT NOT NULL,
    instrument_type TEXT NOT NULL DEFAULT 'EQUITY',
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    is_synthetic INTEGER NOT NULL DEFAULT 1,
    UNIQUE(market, display_symbol)
);
CREATE TABLE IF NOT EXISTS bars_raw (
    instrument_id TEXT NOT NULL REFERENCES instruments(instrument_id) ON DELETE CASCADE,
    trading_date TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume INTEGER,
    turnover REAL,
    turnover_type TEXT NOT NULL DEFAULT 'synthetic_estimate',
    source TEXT NOT NULL,
    adjustment TEXT NOT NULL DEFAULT 'unadjusted',
    data_revision TEXT NOT NULL,
    valid INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY(instrument_id, trading_date, data_revision),
    CHECK (open IS NULL OR open > 0),
    CHECK (high IS NULL OR high > 0),
    CHECK (low IS NULL OR low > 0),
    CHECK (close IS NULL OR close > 0),
    CHECK (volume IS NULL OR volume >= 0)
);
CREATE INDEX IF NOT EXISTS idx_bars_market_date ON bars_raw(trading_date, instrument_id);
CREATE TABLE IF NOT EXISTS corporate_actions (
    action_id TEXT PRIMARY KEY,
    instrument_id TEXT NOT NULL REFERENCES instruments(instrument_id) ON DELETE CASCADE,
    action_type TEXT NOT NULL,
    effective_date TEXT NOT NULL,
    known_at TEXT NOT NULL,
    value_json TEXT NOT NULL,
    source TEXT NOT NULL,
    data_revision TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id TEXT PRIMARY KEY,
    market TEXT NOT NULL CHECK (market IN ('HK', 'US')),
    trading_date TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    data_revision TEXT NOT NULL,
    input_fingerprint TEXT NOT NULL DEFAULT '',
    data_mode TEXT NOT NULL,
    source TEXT NOT NULL,
    warnings_json TEXT NOT NULL DEFAULT '[]',
    coverage_total INTEGER NOT NULL DEFAULT 0,
    coverage_success INTEGER NOT NULL DEFAULT 0,
    coverage_failed INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_snapshots_market_created ON snapshots(market, created_at DESC);
CREATE TABLE IF NOT EXISTS snapshot_items (
    snapshot_id TEXT NOT NULL REFERENCES snapshots(snapshot_id) ON DELETE CASCADE,
    instrument_id TEXT NOT NULL REFERENCES instruments(instrument_id) ON DELETE CASCADE,
    close REAL,
    ma21 REAL,
    ma55 REAL,
    high20 REAL,
    low10 REAL,
    average_turnover20 REAL,
    turnover_type TEXT NOT NULL,
    signal TEXT,
    reason TEXT,
    change_pct REAL,
    PRIMARY KEY(snapshot_id, instrument_id)
);
CREATE TABLE IF NOT EXISTS signals (
    signal_id TEXT PRIMARY KEY,
    instrument_id TEXT NOT NULL REFERENCES instruments(instrument_id) ON DELETE CASCADE,
    decision_date TEXT NOT NULL,
    confirmed_at TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    reason TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    data_revision TEXT NOT NULL,
    simulated_status TEXT NOT NULL DEFAULT 'pending',
    threshold_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(instrument_id, decision_date, signal_type, rule_version, data_revision)
);
CREATE TABLE IF NOT EXISTS watches (
    instrument_id TEXT PRIMARY KEY REFERENCES instruments(instrument_id) ON DELETE CASCADE,
    note TEXT NOT NULL DEFAULT '',
    added_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    market TEXT NOT NULL,
    trading_date TEXT,
    rule_version TEXT,
    data_revision TEXT,
    requested_at TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    input_fingerprint TEXT NOT NULL,
    error TEXT,
    elapsed_ms INTEGER
);
CREATE TABLE IF NOT EXISTS simulation_runs (
    simulation_id TEXT PRIMARY KEY,
    instrument_id TEXT NOT NULL REFERENCES instruments(instrument_id),
    market TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    data_revision TEXT NOT NULL,
    fee_bps REAL NOT NULL,
    slippage_bps REAL NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL,
    result_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trades (
    trade_id TEXT PRIMARY KEY,
    simulation_id TEXT NOT NULL REFERENCES simulation_runs(simulation_id) ON DELETE CASCADE,
    instrument_id TEXT NOT NULL REFERENCES instruments(instrument_id),
    entry_signal_date TEXT NOT NULL,
    entry_date TEXT,
    entry_price REAL,
    exit_signal_date TEXT,
    exit_date TEXT,
    exit_price REAL,
    return_pct REAL,
    cost_pct REAL NOT NULL,
    status TEXT NOT NULL,
    skip_reason TEXT
);
"""


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    database = Path(path or DATABASE_PATH)
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database, timeout=8, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def initialize(path: Path | str | None = None) -> None:
    with connect(path) as connection:
        connection.executescript(SCHEMA)
        snapshot_columns = {row["name"] for row in connection.execute("PRAGMA table_info(snapshots)").fetchall()}
        if "input_fingerprint" not in snapshot_columns:
            connection.execute("ALTER TABLE snapshots ADD COLUMN input_fingerprint TEXT NOT NULL DEFAULT ''")
        run_columns = {row["name"] for row in connection.execute("PRAGMA table_info(runs)").fetchall()}
        for name in ("trading_date", "rule_version", "data_revision"):
            if name not in run_columns:
                connection.execute(f"ALTER TABLE runs ADD COLUMN {name} TEXT")
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_idempotent_success "
            "ON runs(market, trading_date, rule_version, data_revision, input_fingerprint) "
            "WHERE status='success' AND trading_date IS NOT NULL"
        )
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_snapshots_idempotent_success "
            "ON snapshots(market, trading_date, rule_version, data_revision, input_fingerprint) "
            "WHERE status='success' AND input_fingerprint<>''"
        )
