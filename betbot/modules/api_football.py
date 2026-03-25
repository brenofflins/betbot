"""
API-Football integration — fixtures, stats, H2H, injuries, standings.
Optimized for free tier (100 requests/day).
"""
import httpx
from datetime import datetime, timedelta
from typing import Optional

import config
from modules.database import get_connection, log_api_call, get_api_usage_today


HEADERS = {
    "x-apisports-key": config.API_FOOTBALL_KEY,
}


class APIFootballError(Exception):
    pass


class RateLimitExceeded(APIFootballError):
    pass


async def _request(endpoint: str, params: dict = None) -> dict:
    """Make a request to API-Football with rate limit checking."""
    conn = get_connection()
    usage = get_api_usage_today(conn, "api_football")
    if usage >= config.API_FOOTBALL_DAILY_LIMIT - 5:  # Keep 5 as buffer
        conn.close()
        raise RateLimitExceeded(
            f"API-Football: {usage}/{config.API_FOOTBALL_DAILY_LIMIT} requests used today. "
            "Saving remaining calls for critical data."
        )

    url = f"{config.API_FOOTBALL_BASE}/{endpoint}"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, headers=HEADERS, params=params or {})

    log_api_call(conn, "api_football", endpoint, resp.status_code)
    conn.close()

    if resp.status_code != 200:
        raise APIFootballError(f"API-Football error {resp.status_code}: {resp.text[:200]}")

    data = resp.json()
    if data.get("errors"):
        raise APIFootballError(f"API-Football errors: {data['errors']}")

    return data


# =========================================================================
# Fixtures
# =========================================================================

async def get_fixtures_today(league_id: int = None, date: str = None) -> list[dict]:
    """
    Get today's fixtures, optionally filtered by league.
    Returns a list of fixture dicts with teams, status, scores.
    """
    target_date = date or datetime.now().strftime("%Y-%m-%d")
    params = {"date": target_date}
    if league_id:
        params["league"] = league_id
        params["season"] = datetime.now().year

    data = await _request("fixtures", params)
    fixtures = []
    for f in data.get("response", []):
        fixtures.append({
            "fixture_id": f["fixture"]["id"],
            "date": f["fixture"]["date"],
            "status": f["fixture"]["status"]["short"],
            "league": f["league"]["name"],
            "league_id": f["league"]["id"],
            "country": f["league"]["country"],
            "home_team": f["teams"]["home"]["name"],
            "home_id": f["teams"]["home"]["id"],
            "away_team": f["teams"]["away"]["name"],
            "away_id": f["teams"]["away"]["id"],
            "home_goals": f["goals"]["home"],
            "away_goals": f["goals"]["away"],
        })
    return fixtures


async def get_fixtures_by_league(league_id: int, next_n: int = 10) -> list[dict]:
    """Get next N fixtures for a specific league."""
    params = {
        "league": league_id,
        "season": datetime.now().year,
        "next": next_n,
    }
    data = await _request("fixtures", params)
    return [
        {
            "fixture_id": f["fixture"]["id"],
            "date": f["fixture"]["date"],
            "status": f["fixture"]["status"]["short"],
            "home_team": f["teams"]["home"]["name"],
            "home_id": f["teams"]["home"]["id"],
            "away_team": f["teams"]["away"]["name"],
            "away_id": f["teams"]["away"]["id"],
        }
        for f in data.get("response", [])
    ]


# =========================================================================
# Team Statistics
# =========================================================================

async def get_team_stats(team_id: int, league_id: int, season: int = None) -> dict:
    """
    Get comprehensive team statistics for a season.
    Includes form, goals, wins/draws/losses home/away, etc.
    """
    season = season or datetime.now().year
    data = await _request("teams/statistics", {
        "team": team_id,
        "league": league_id,
        "season": season,
    })
    resp = data.get("response", {})
    if not resp:
        return {}

    fixtures = resp.get("fixtures", {})
    goals_for = resp.get("goals", {}).get("for", {})
    goals_against = resp.get("goals", {}).get("against", {})

    return {
        "form": resp.get("form", ""),
        "fixtures": {
            "played": {
                "home": fixtures.get("played", {}).get("home", 0),
                "away": fixtures.get("played", {}).get("away", 0),
                "total": fixtures.get("played", {}).get("total", 0),
            },
            "wins": {
                "home": fixtures.get("wins", {}).get("home", 0),
                "away": fixtures.get("wins", {}).get("away", 0),
                "total": fixtures.get("wins", {}).get("total", 0),
            },
            "draws": {
                "home": fixtures.get("draws", {}).get("home", 0),
                "away": fixtures.get("draws", {}).get("away", 0),
                "total": fixtures.get("draws", {}).get("total", 0),
            },
            "losses": {
                "home": fixtures.get("losses", {}).get("home", 0),
                "away": fixtures.get("losses", {}).get("away", 0),
                "total": fixtures.get("losses", {}).get("total", 0),
            },
        },
        "goals_for_avg": {
            "home": goals_for.get("average", {}).get("home", "0"),
            "away": goals_for.get("average", {}).get("away", "0"),
            "total": goals_for.get("average", {}).get("total", "0"),
        },
        "goals_against_avg": {
            "home": goals_against.get("average", {}).get("home", "0"),
            "away": goals_against.get("average", {}).get("away", "0"),
            "total": goals_against.get("average", {}).get("total", "0"),
        },
        "clean_sheets": resp.get("clean_sheet", {}),
        "failed_to_score": resp.get("failed_to_score", {}),
    }


# =========================================================================
# Head to Head
# =========================================================================

async def get_h2h(team1_id: int, team2_id: int, last_n: int = 10) -> dict:
    """Get head-to-head record between two teams."""
    data = await _request("fixtures/headtohead", {
        "h2h": f"{team1_id}-{team2_id}",
        "last": last_n,
    })
    matches = data.get("response", [])
    if not matches:
        return {"matches": [], "summary": {}}

    team1_wins = 0
    team2_wins = 0
    draws = 0
    total_goals = 0
    btts_count = 0
    over25_count = 0

    parsed_matches = []
    for m in matches:
        home_goals = m["goals"]["home"] or 0
        away_goals = m["goals"]["away"] or 0
        total = home_goals + away_goals
        total_goals += total

        if total > 2.5:
            over25_count += 1
        if home_goals > 0 and away_goals > 0:
            btts_count += 1

        home_id = m["teams"]["home"]["id"]
        if home_goals > away_goals:
            winner_id = home_id
        elif away_goals > home_goals:
            winner_id = m["teams"]["away"]["id"]
        else:
            winner_id = None

        if winner_id == team1_id:
            team1_wins += 1
        elif winner_id == team2_id:
            team2_wins += 1
        else:
            draws += 1

        parsed_matches.append({
            "date": m["fixture"]["date"],
            "home": m["teams"]["home"]["name"],
            "away": m["teams"]["away"]["name"],
            "score": f"{home_goals}-{away_goals}",
        })

    n = len(matches)
    return {
        "matches": parsed_matches,
        "summary": {
            "total_matches": n,
            "team1_wins": team1_wins,
            "team2_wins": team2_wins,
            "draws": draws,
            "avg_goals": round(total_goals / n, 2) if n else 0,
            "over25_pct": round(over25_count / n * 100, 1) if n else 0,
            "btts_pct": round(btts_count / n * 100, 1) if n else 0,
        },
    }


# =========================================================================
# Injuries & Suspensions
# =========================================================================

async def get_injuries(fixture_id: int) -> list[dict]:
    """Get injuries/suspensions for a specific fixture."""
    data = await _request("injuries", {"fixture": fixture_id})
    injuries = []
    for item in data.get("response", []):
        injuries.append({
            "team": item["team"]["name"],
            "team_id": item["team"]["id"],
            "player": item["player"]["name"],
            "type": item["player"].get("type", "unknown"),
            "reason": item["player"].get("reason", ""),
        })
    return injuries


# =========================================================================
# Standings
# =========================================================================

async def get_standings(league_id: int, season: int = None) -> list[dict]:
    """Get current league standings."""
    season = season or datetime.now().year
    data = await _request("standings", {
        "league": league_id,
        "season": season,
    })
    resp = data.get("response", [])
    if not resp:
        return []

    standings = []
    for league_data in resp:
        for group in league_data.get("league", {}).get("standings", []):
            for team in group:
                standings.append({
                    "rank": team["rank"],
                    "team": team["team"]["name"],
                    "team_id": team["team"]["id"],
                    "points": team["points"],
                    "played": team["all"]["played"],
                    "wins": team["all"]["win"],
                    "draws": team["all"]["draw"],
                    "losses": team["all"]["lose"],
                    "goals_for": team["all"]["goals"]["for"],
                    "goals_against": team["all"]["goals"]["against"],
                    "goal_diff": team["goalsDiff"],
                    "form": team.get("form", ""),
                })
    return standings


# =========================================================================
# Fixture Results (for settling bets)
# =========================================================================

async def get_fixture_result(fixture_id: int) -> Optional[dict]:
    """Get the final result of a fixture."""
    data = await _request("fixtures", {"id": fixture_id})
    resp = data.get("response", [])
    if not resp:
        return None

    f = resp[0]
    status = f["fixture"]["status"]["short"]
    if status not in ("FT", "AET", "PEN"):
        return None  # Match not finished yet

    home_goals = f["goals"]["home"] or 0
    away_goals = f["goals"]["away"] or 0

    return {
        "fixture_id": fixture_id,
        "status": status,
        "home_goals": home_goals,
        "away_goals": away_goals,
        "total_goals": home_goals + away_goals,
        "btts": home_goals > 0 and away_goals > 0,
        "winner": (
            "home" if home_goals > away_goals
            else "away" if away_goals > home_goals
            else "draw"
        ),
    }
