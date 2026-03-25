"""
Database module — SQLite storage for picks, results, feedback, and learning.
"""
import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path

import config


def get_connection() -> sqlite3.Connection:
    """Get a database connection, creating tables if needed."""
    Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    _create_tables(conn)
    return conn


def _create_tables(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS picks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT DEFAULT (datetime('now')),
            fixture_id INTEGER,
            league TEXT,
            home_team TEXT,
            away_team TEXT,
            match_date TEXT,
            market TEXT,
            pick TEXT,
            odd REAL,
            bookmaker TEXT,
            implied_prob REAL,
            estimated_prob REAL,
            edge REAL,
            confidence INTEGER,
            reasoning TEXT,
            deep_link TEXT,
            -- Result tracking
            result TEXT,           -- 'win', 'loss', 'void', 'pending'
            settled_at TEXT,
            -- User feedback
            user_feedback TEXT,    -- 'good', 'bad', or free text
            feedback_note TEXT,
            feedback_at TEXT
        );

        CREATE TABLE IF NOT EXISTS league_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            league TEXT,
            market TEXT,
            total_picks INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            avg_odd REAL DEFAULT 0,
            roi REAL DEFAULT 0,
            last_updated TEXT
        );

        CREATE TABLE IF NOT EXISTS pattern_performance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern_name TEXT UNIQUE,
            description TEXT,
            times_triggered INTEGER DEFAULT 0,
            times_correct INTEGER DEFAULT 0,
            hit_rate REAL DEFAULT 0,
            last_updated TEXT
        );

        CREATE TABLE IF NOT EXISTS api_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            api_name TEXT,
            endpoint TEXT,
            called_at TEXT DEFAULT (datetime('now')),
            response_status INTEGER
        );

        CREATE TABLE IF NOT EXISTS user_preferences (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT DEFAULT (datetime('now'))
        );
    """)
    conn.commit()


# =========================================================================
# Picks CRUD
# =========================================================================

def save_pick(conn: sqlite3.Connection, pick: dict) -> int:
    """Save a new pick recommendation. Returns the pick ID."""
    cursor = conn.execute("""
        INSERT INTO picks (
            fixture_id, league, home_team, away_team, match_date,
            market, pick, odd, bookmaker, implied_prob, estimated_prob,
            edge, confidence, reasoning, deep_link, result
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
    """, (
        pick.get("fixture_id"), pick.get("league"),
        pick.get("home_team"), pick.get("away_team"),
        pick.get("match_date"), pick.get("market"),
        pick.get("pick"), pick.get("odd"),
        pick.get("bookmaker"), pick.get("implied_prob"),
        pick.get("estimated_prob"), pick.get("edge"),
        pick.get("confidence"), pick.get("reasoning"),
        pick.get("deep_link"),
    ))
    conn.commit()
    return cursor.lastrowid


def update_pick_result(conn: sqlite3.Connection, pick_id: int, result: str):
    """Update a pick with its actual result."""
    conn.execute("""
        UPDATE picks SET result = ?, settled_at = datetime('now')
        WHERE id = ?
    """, (result, pick_id))
    conn.commit()


def save_feedback(conn: sqlite3.Connection, pick_id: int, feedback: str, note: str = ""):
    """Save user feedback for a pick."""
    conn.execute("""
        UPDATE picks SET user_feedback = ?, feedback_note = ?, feedback_at = datetime('now')
        WHERE id = ?
    """, (feedback, note, pick_id))
    conn.commit()


def get_pending_picks(conn: sqlite3.Connection) -> list[dict]:
    """Get all picks that haven't been settled yet."""
    rows = conn.execute(
        "SELECT * FROM picks WHERE result = 'pending' ORDER BY match_date"
    ).fetchall()
    return [dict(r) for r in rows]


def get_recent_picks(conn: sqlite3.Connection, days: int = 7) -> list[dict]:
    """Get picks from the last N days."""
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT * FROM picks WHERE created_at >= ? ORDER BY created_at DESC", (cutoff,)
    ).fetchall()
    return [dict(r) for r in rows]


# =========================================================================
# Performance & Learning Stats
# =========================================================================

def get_performance_stats(conn: sqlite3.Connection, league: str = None, market: str = None) -> dict:
    """Calculate performance statistics with optional league/market filters."""
    query = "SELECT * FROM picks WHERE result IN ('win', 'loss')"
    params = []

    if league:
        query += " AND league = ?"
        params.append(league)
    if market:
        query += " AND market = ?"
        params.append(market)

    rows = conn.execute(query, params).fetchall()
    picks = [dict(r) for r in rows]

    if not picks:
        return {"total": 0, "wins": 0, "losses": 0, "hit_rate": 0, "roi": 0, "avg_odd": 0}

    wins = sum(1 for p in picks if p["result"] == "win")
    losses = sum(1 for p in picks if p["result"] == "loss")
    total = wins + losses
    avg_odd = sum(p["odd"] for p in picks) / total

    # ROI calculation: (total_returns - total_staked) / total_staked * 100
    # Assuming flat 1 unit per bet
    total_returns = sum(p["odd"] for p in picks if p["result"] == "win")
    roi = ((total_returns - total) / total) * 100 if total > 0 else 0

    return {
        "total": total,
        "wins": wins,
        "losses": losses,
        "hit_rate": round(wins / total * 100, 1) if total > 0 else 0,
        "roi": round(roi, 1),
        "avg_odd": round(avg_odd, 2),
    }


def get_confidence_adjustments(conn: sqlite3.Connection) -> dict:
    """
    Calculate adjustments based on historical performance.
    Returns a dict of {league+market: adjustment_factor} that the analysis
    engine uses to fine-tune confidence scores.
    """
    adjustments = {}
    rows = conn.execute("""
        SELECT league, market,
               COUNT(*) as total,
               SUM(CASE WHEN result = 'win' THEN 1 ELSE 0 END) as wins,
               AVG(CASE WHEN user_feedback = 'good' THEN 1
                        WHEN user_feedback = 'bad' THEN -1
                        ELSE 0 END) as feedback_score
        FROM picks
        WHERE result IN ('win', 'loss')
        GROUP BY league, market
        HAVING total >= 5
    """).fetchall()

    for row in rows:
        key = f"{row['league']}|{row['market']}"
        hit_rate = row["wins"] / row["total"]
        feedback_mod = row["feedback_score"] * 0.05  # ±5% based on user feedback

        # Base adjustment: if hit rate > 55%, boost; if < 40%, penalize
        if hit_rate > 0.55:
            adj = 1 + (hit_rate - 0.55) * 0.5 + feedback_mod
        elif hit_rate < 0.40:
            adj = 1 - (0.40 - hit_rate) * 0.5 + feedback_mod
        else:
            adj = 1.0 + feedback_mod

        adjustments[key] = round(max(0.5, min(1.5, adj)), 3)

    return adjustments


# =========================================================================
# API Usage Tracking
# =========================================================================

def log_api_call(conn: sqlite3.Connection, api_name: str, endpoint: str, status: int = 200):
    conn.execute(
        "INSERT INTO api_usage (api_name, endpoint, response_status) VALUES (?, ?, ?)",
        (api_name, endpoint, status),
    )
    conn.commit()


def get_api_usage_today(conn: sqlite3.Connection, api_name: str) -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM api_usage WHERE api_name = ? AND called_at >= ?",
        (api_name, today),
    ).fetchone()
    return row["cnt"]


def get_api_usage_month(conn: sqlite3.Connection, api_name: str) -> int:
    month_start = datetime.now().replace(day=1).strftime("%Y-%m-%d")
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM api_usage WHERE api_name = ? AND called_at >= ?",
        (api_name, month_start),
    ).fetchone()
    return row["cnt"]
