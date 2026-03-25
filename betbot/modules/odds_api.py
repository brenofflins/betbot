"""
The Odds API integration — real-time odds from 80+ bookmakers.
Optimized for free tier (500 requests/month).
"""
import httpx
from datetime import datetime
from typing import Optional

import config
from modules.database import get_connection, log_api_call, get_api_usage_month


class OddsAPIError(Exception):
    pass


class RateLimitExceeded(OddsAPIError):
    pass


async def _request(endpoint: str, params: dict = None) -> dict:
    """Make a request to The Odds API with rate limit checking."""
    conn = get_connection()
    usage = get_api_usage_month(conn, "odds_api")
    if usage >= config.ODDS_API_MONTHLY_LIMIT - 20:  # Keep 20 as buffer
        conn.close()
        raise RateLimitExceeded(
            f"The Odds API: {usage}/{config.ODDS_API_MONTHLY_LIMIT} requests used this month. "
            "Saving remaining calls."
        )

    url = f"{config.ODDS_API_BASE}/{endpoint}"
    all_params = {"apiKey": config.ODDS_API_KEY}
    all_params.update(params or {})

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, params=all_params)

    log_api_call(conn, "odds_api", endpoint, resp.status_code)
    conn.close()

    if resp.status_code == 429:
        raise RateLimitExceeded("The Odds API rate limit exceeded.")
    if resp.status_code != 200:
        raise OddsAPIError(f"Odds API error {resp.status_code}: {resp.text[:200]}")

    # Log remaining requests from headers
    remaining = resp.headers.get("x-requests-remaining", "?")
    used = resp.headers.get("x-requests-used", "?")

    return resp.json()


# =========================================================================
# Available Sports
# =========================================================================

async def get_available_sports() -> list[dict]:
    """Get list of available sports/leagues with upcoming games."""
    data = await _request("sports")
    return [
        {
            "key": s["key"],
            "title": s["title"],
            "active": s["active"],
            "has_outrights": s.get("has_outrights", False),
        }
        for s in data
        if s.get("group") == "Soccer" and s.get("active")
    ]


# =========================================================================
# Odds
# =========================================================================

async def get_odds(
    sport_key: str,
    markets: str = "h2h",
    regions: str = "eu,uk",
    odds_format: str = "decimal",
    include_links: bool = True,
) -> list[dict]:
    """
    Get odds for a sport/league.

    Args:
        sport_key: e.g., "soccer_epl", "soccer_brazil_campeonato"
        markets: comma-separated, e.g., "h2h,totals,btts"
        regions: comma-separated, e.g., "eu,uk,us"
        odds_format: "decimal" or "american"
        include_links: whether to include deep links to bookmakers
    """
    params = {
        "regions": regions,
        "markets": markets,
        "oddsFormat": odds_format,
    }
    if include_links:
        params["includeLinks"] = "true"
        params["includeSids"] = "true"

    data = await _request(f"sports/{sport_key}/odds", params)

    events = []
    for event in data:
        parsed_event = {
            "event_id": event["id"],
            "sport_key": event["sport_key"],
            "commence_time": event["commence_time"],
            "home_team": event["home_team"],
            "away_team": event["away_team"],
            "bookmakers": [],
        }

        for bm in event.get("bookmakers", []):
            bookmaker_data = {
                "key": bm["key"],
                "title": bm["title"],
                "link": bm.get("link"),  # Deep link if available
                "markets": {},
            }

            for market in bm.get("markets", []):
                market_key = market["key"]
                outcomes = []
                for outcome in market.get("outcomes", []):
                    outcome_data = {
                        "name": outcome["name"],
                        "price": outcome["price"],
                        "point": outcome.get("point"),  # For totals (e.g., 2.5)
                        "link": outcome.get("link"),  # Deep link to specific bet
                    }
                    outcomes.append(outcome_data)
                bookmaker_data["markets"][market_key] = outcomes

            parsed_event["bookmakers"].append(bookmaker_data)

        events.append(parsed_event)

    return events


async def get_best_odds(sport_key: str) -> list[dict]:
    """
    Get odds for all markets and find the best odds across bookmakers.
    Returns events with best_odds per outcome.
    """
    events = await get_odds(sport_key, markets="h2h,totals", include_links=True)

    for event in events:
        event["best_odds"] = {}

        for bm in event["bookmakers"]:
            for market_key, outcomes in bm["markets"].items():
                if market_key not in event["best_odds"]:
                    event["best_odds"][market_key] = {}

                for outcome in outcomes:
                    name = outcome["name"]
                    if outcome.get("point") is not None:
                        name = f"{name} {outcome['point']}"

                    current_best = event["best_odds"][market_key].get(name)
                    if not current_best or outcome["price"] > current_best["price"]:
                        event["best_odds"][market_key][name] = {
                            "name": outcome["name"],
                            "price": outcome["price"],
                            "point": outcome.get("point"),
                            "bookmaker": bm["title"],
                            "bookmaker_key": bm["key"],
                            "link": outcome.get("link") or bm.get("link"),
                        }

    return events


# =========================================================================
# Deep Link Helpers
# =========================================================================

def find_superbet_odds(event: dict) -> Optional[dict]:
    """
    Find Superbet-specific odds and links in an event.
    Falls back to constructing a URL if no deep link is available.
    """
    for bm in event.get("bookmakers", []):
        if "superbet" in bm["key"].lower():
            return {
                "bookmaker": bm["title"],
                "link": bm.get("link"),
                "markets": bm["markets"],
            }
    return None


def build_superbet_event_url(home_team: str, away_team: str) -> str:
    """
    Build a best-guess Superbet URL for an event.
    Since Superbet doesn't have public deep link docs, this links to their
    football section. User can find the match from there.
    """
    return f"{config.SUPERBET_BASE_URL}/apostas/futebol"


# =========================================================================
# Utility: Implied Probability
# =========================================================================

def odds_to_implied_prob(decimal_odds: float) -> float:
    """Convert decimal odds to implied probability."""
    if decimal_odds <= 0:
        return 0
    return round(1 / decimal_odds, 4)


def implied_prob_to_odds(prob: float) -> float:
    """Convert probability to fair decimal odds."""
    if prob <= 0:
        return float("inf")
    return round(1 / prob, 2)
