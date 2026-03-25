"""
Value Bet Analysis Engine
Combines statistics, patterns, and context to estimate probabilities
and find value in bookmaker odds.
"""
import math
from typing import Optional

import config
from modules.odds_api import odds_to_implied_prob, implied_prob_to_odds
from modules.database import get_connection, get_confidence_adjustments


# =========================================================================
# Recurring Patterns Database
# These are well-documented football betting patterns that tend to repeat.
# The system learns which ones are effective via the feedback loop.
# =========================================================================

PATTERNS = {
    "home_fortress": {
        "description": "Time com >75% vitórias em casa nos últimos 10 jogos",
        "check": lambda stats, ctx: (
            stats.get("home_win_pct", 0) > 75
            and ctx.get("is_home", False)
        ),
        "adjustment": 0.05,  # +5% to home win probability
        "markets": ["h2h"],
    },
    "away_nightmare": {
        "description": "Time com <20% vitórias fora nos últimos 10 jogos",
        "check": lambda stats, ctx: (
            stats.get("away_win_pct", 0) < 20
            and not ctx.get("is_home", True)
        ),
        "adjustment": -0.05,
        "markets": ["h2h"],
    },
    "goals_machine": {
        "description": "Média de gols do time >2.0 por jogo + adversário sofre >1.5/jogo",
        "check": lambda stats, ctx: (
            float(stats.get("goals_for_avg", 0)) > 2.0
            and float(ctx.get("opp_goals_against_avg", 0)) > 1.5
        ),
        "adjustment": 0.08,
        "markets": ["totals"],
    },
    "btts_lovers": {
        "description": "Ambos marcaram em >65% dos jogos de ambos os times",
        "check": lambda stats, ctx: (
            stats.get("btts_pct", 0) > 65
            and ctx.get("opp_btts_pct", 0) > 65
        ),
        "adjustment": 0.10,
        "markets": ["btts"],
    },
    "derby_goals": {
        "description": "H2H com média >2.5 gols e >60% over 2.5",
        "check": lambda stats, ctx: (
            ctx.get("h2h_avg_goals", 0) > 2.5
            and ctx.get("h2h_over25_pct", 0) > 60
        ),
        "adjustment": 0.07,
        "markets": ["totals"],
    },
    "form_streak": {
        "description": "Time em sequência de 4+ vitórias consecutivas",
        "check": lambda stats, ctx: (
            len(stats.get("form", "")) >= 4
            and stats.get("form", "")[-4:] == "WWWW"
        ),
        "adjustment": 0.04,
        "markets": ["h2h"],
    },
    "losing_streak": {
        "description": "Time em sequência de 4+ derrotas consecutivas",
        "check": lambda stats, ctx: (
            len(stats.get("form", "")) >= 4
            and stats.get("form", "")[-4:] == "LLLL"
        ),
        "adjustment": -0.04,
        "markets": ["h2h"],
    },
    "top_vs_bottom": {
        "description": "Time no top 4 enfrentando time na zona de rebaixamento",
        "check": lambda stats, ctx: (
            ctx.get("rank_diff", 0) >= 12
            and ctx.get("is_favorite", False)
        ),
        "adjustment": 0.06,
        "markets": ["h2h"],
    },
    "low_scoring_league": {
        "description": "Liga com média <2.2 gols/jogo — favorece Under",
        "check": lambda stats, ctx: ctx.get("league_avg_goals", 3.0) < 2.2,
        "adjustment": -0.06,
        "markets": ["totals"],
    },
    "clean_sheet_specialist": {
        "description": "Time com >40% clean sheets — desfavorece BTTS",
        "check": lambda stats, ctx: stats.get("clean_sheet_pct", 0) > 40,
        "adjustment": -0.08,
        "markets": ["btts"],
    },
}


# =========================================================================
# Probability Estimation
# =========================================================================

def estimate_match_probabilities(
    home_stats: dict,
    away_stats: dict,
    h2h: dict,
    standings: list[dict],
    injuries: list[dict],
    league_name: str,
) -> dict:
    """
    Estimate probabilities for all markets based on available data.

    Returns: {
        "h2h": {"home": prob, "draw": prob, "away": prob},
        "totals": {"over_25": prob, "under_25": prob},
        "btts": {"yes": prob, "no": prob},
        "patterns_triggered": [list of pattern names],
        "reasoning": [list of reasoning strings],
    }
    """
    w = config.ANALYSIS_WEIGHTS
    reasoning = []
    patterns_triggered = []

    # --- 1. Recent Form ---
    home_form = home_stats.get("form", "")[-5:]
    away_form = away_stats.get("form", "")[-5:]

    home_form_score = _form_to_score(home_form)
    away_form_score = _form_to_score(away_form)
    reasoning.append(
        f"Forma recente: {home_stats.get('team', 'Casa')} [{home_form}] "
        f"({home_form_score:.0%}) vs {away_stats.get('team', 'Fora')} [{away_form}] ({away_form_score:.0%})"
    )

    # --- 2. Home/Away Record ---
    home_home_wr = _safe_ratio(
        home_stats.get("fixtures", {}).get("wins", {}).get("home", 0),
        home_stats.get("fixtures", {}).get("played", {}).get("home", 1),
    )
    away_away_wr = _safe_ratio(
        away_stats.get("fixtures", {}).get("wins", {}).get("away", 0),
        away_stats.get("fixtures", {}).get("played", {}).get("away", 1),
    )
    reasoning.append(
        f"Casa em casa: {home_home_wr:.0%} vitórias | Fora como visitante: {away_away_wr:.0%} vitórias"
    )

    # --- 3. H2H History ---
    h2h_summary = h2h.get("summary", {})
    h2h_total = h2h_summary.get("total_matches", 0)
    if h2h_total > 0:
        h2h_home_advantage = h2h_summary.get("team1_wins", 0) / h2h_total
        reasoning.append(
            f"H2H ({h2h_total} jogos): {h2h_summary.get('team1_wins', 0)}V "
            f"{h2h_summary.get('draws', 0)}E {h2h_summary.get('team2_wins', 0)}D | "
            f"Média gols: {h2h_summary.get('avg_goals', 0)} | "
            f"Over 2.5: {h2h_summary.get('over25_pct', 0)}% | "
            f"BTTS: {h2h_summary.get('btts_pct', 0)}%"
        )
    else:
        h2h_home_advantage = 0.5

    # --- 4. Goals Stats ---
    home_gf_avg = float(home_stats.get("goals_for_avg", {}).get("home", "1.2"))
    home_ga_avg = float(home_stats.get("goals_against_avg", {}).get("home", "1.0"))
    away_gf_avg = float(away_stats.get("goals_for_avg", {}).get("away", "1.0"))
    away_ga_avg = float(away_stats.get("goals_against_avg", {}).get("away", "1.3"))

    expected_home_goals = (home_gf_avg + away_ga_avg) / 2
    expected_away_goals = (away_gf_avg + home_ga_avg) / 2
    expected_total = expected_home_goals + expected_away_goals
    reasoning.append(
        f"Gols esperados: Casa {expected_home_goals:.1f} - Fora {expected_away_goals:.1f} "
        f"(Total: {expected_total:.1f})"
    )

    # --- 5. Standings Position ---
    home_rank, away_rank = _get_ranks(
        standings,
        home_stats.get("team_id"),
        away_stats.get("team_id"),
    )
    rank_diff = away_rank - home_rank  # Positive = home is higher ranked

    # --- 6. Injuries ---
    home_injuries = [i for i in injuries if i.get("team_id") == home_stats.get("team_id")]
    away_injuries = [i for i in injuries if i.get("team_id") == away_stats.get("team_id")]
    injury_factor = (len(away_injuries) - len(home_injuries)) * 0.01  # Slight adjustment
    if injuries:
        reasoning.append(
            f"Desfalques: Casa {len(home_injuries)} jogadores | Fora {len(away_injuries)} jogadores"
        )

    # --- Combine into H2H probabilities ---
    # Base: weighted combination
    raw_home_prob = (
        w["recent_form"] * home_form_score
        + w["home_away_record"] * home_home_wr
        + w["h2h_history"] * h2h_home_advantage
        + w["goals_stats"] * min(1, expected_home_goals / (expected_total or 1))
        + w["league_position"] * _rank_to_prob(rank_diff)
        + w["injuries"] * (0.5 + injury_factor)
        + w["motivation"] * 0.52  # Slight home advantage default
    )
    raw_away_prob = (
        w["recent_form"] * away_form_score
        + w["home_away_record"] * away_away_wr
        + w["h2h_history"] * (1 - h2h_home_advantage)
        + w["goals_stats"] * min(1, expected_away_goals / (expected_total or 1))
        + w["league_position"] * _rank_to_prob(-rank_diff)
        + w["injuries"] * (0.5 - injury_factor)
        + w["motivation"] * 0.48
    )

    # Draw probability from historical baseline (~25-28% in most leagues)
    draw_base = 0.26
    raw_draw_prob = draw_base + (1 - abs(raw_home_prob - raw_away_prob)) * 0.05

    # Normalize to sum to 1
    total = raw_home_prob + raw_draw_prob + raw_away_prob
    home_prob = raw_home_prob / total
    draw_prob = raw_draw_prob / total
    away_prob = raw_away_prob / total

    # --- Over/Under using Poisson approximation ---
    over25_prob = 1 - _poisson_under(expected_total, 2.5)
    under25_prob = 1 - over25_prob

    # --- BTTS ---
    prob_home_scores = 1 - math.exp(-expected_home_goals)
    prob_away_scores = 1 - math.exp(-expected_away_goals)
    btts_yes = prob_home_scores * prob_away_scores
    btts_no = 1 - btts_yes

    # --- Apply Patterns ---
    context = {
        "is_home": True,
        "h2h_avg_goals": h2h_summary.get("avg_goals", 0),
        "h2h_over25_pct": h2h_summary.get("over25_pct", 0),
        "opp_goals_against_avg": away_stats.get("goals_against_avg", {}).get("total", "1.2"),
        "opp_btts_pct": 50,  # Default, would need more data
        "rank_diff": rank_diff,
        "is_favorite": home_prob > away_prob,
        "league_avg_goals": expected_total,
    }

    home_context = {**context, "home_win_pct": home_home_wr * 100}
    for name, pattern in PATTERNS.items():
        if pattern["check"](home_stats, home_context):
            patterns_triggered.append(name)
            adj = pattern["adjustment"]
            if "h2h" in pattern["markets"]:
                home_prob += adj
                away_prob -= adj / 2
                draw_prob -= adj / 2
            if "totals" in pattern["markets"]:
                over25_prob += adj
                under25_prob -= adj
            if "btts" in pattern["markets"]:
                btts_yes += adj
                btts_no -= adj
            reasoning.append(f"Padrão: {pattern['description']}")

    # --- Apply Learning Adjustments ---
    conn = get_connection()
    adjustments = get_confidence_adjustments(conn)
    conn.close()

    h2h_adj = adjustments.get(f"{league_name}|h2h", 1.0)
    totals_adj = adjustments.get(f"{league_name}|totals", 1.0)
    btts_adj = adjustments.get(f"{league_name}|btts", 1.0)

    # Clamp all probabilities
    home_prob = _clamp(home_prob)
    draw_prob = _clamp(draw_prob)
    away_prob = _clamp(away_prob)
    over25_prob = _clamp(over25_prob)
    under25_prob = _clamp(under25_prob)
    btts_yes = _clamp(btts_yes)
    btts_no = _clamp(btts_no)

    # Re-normalize h2h
    h2h_total = home_prob + draw_prob + away_prob
    home_prob /= h2h_total
    draw_prob /= h2h_total
    away_prob /= h2h_total

    return {
        "h2h": {"home": round(home_prob, 4), "draw": round(draw_prob, 4), "away": round(away_prob, 4)},
        "totals": {"over_25": round(over25_prob, 4), "under_25": round(under25_prob, 4)},
        "btts": {"yes": round(btts_yes, 4), "no": round(btts_no, 4)},
        "expected_goals": {"home": round(expected_home_goals, 2), "away": round(expected_away_goals, 2)},
        "patterns_triggered": patterns_triggered,
        "reasoning": reasoning,
        "learning_adjustments": {"h2h": h2h_adj, "totals": totals_adj, "btts": btts_adj},
    }


# =========================================================================
# Value Bet Detection
# =========================================================================

def find_value_bets(
    probabilities: dict,
    bookmaker_odds: dict,
    min_edge: float = None,
) -> list[dict]:
    """
    Compare estimated probabilities with bookmaker odds to find value.

    Args:
        probabilities: output from estimate_match_probabilities
        bookmaker_odds: {"h2h": {"Home": 2.10, ...}, "totals": {...}, ...}
        min_edge: minimum edge to qualify (default from config)

    Returns list of value bets found, sorted by edge (highest first).
    """
    min_edge = min_edge or config.MIN_VALUE_EDGE
    value_bets = []

    # Map market outcomes to probability keys
    market_mapping = {
        "h2h": [
            ("Home", "home"),
            ("Draw", "draw"),
            ("Away", "away"),
        ],
        "totals": [
            ("Over", "over_25"),
            ("Under", "under_25"),
        ],
        "btts": [
            ("Yes", "yes"),
            ("No", "no"),
        ],
    }

    for market, outcomes in market_mapping.items():
        if market not in probabilities or market not in bookmaker_odds:
            continue

        for outcome_name, prob_key in outcomes:
            estimated_prob = probabilities[market].get(prob_key, 0)
            odds_data = bookmaker_odds[market].get(outcome_name)

            if not odds_data:
                continue

            best_odd = odds_data["price"]
            implied_prob = odds_to_implied_prob(best_odd)
            edge = estimated_prob - implied_prob

            if edge >= min_edge:
                confidence = _edge_to_confidence(edge)
                fair_odd = implied_prob_to_odds(estimated_prob)

                value_bets.append({
                    "market": market,
                    "market_label": config.MARKETS.get(market, market),
                    "pick": outcome_name,
                    "odd": best_odd,
                    "fair_odd": fair_odd,
                    "bookmaker": odds_data.get("bookmaker", "Unknown"),
                    "link": odds_data.get("link"),
                    "implied_prob": round(implied_prob, 4),
                    "estimated_prob": round(estimated_prob, 4),
                    "edge": round(edge, 4),
                    "confidence": confidence,
                })

    # Sort by edge descending
    value_bets.sort(key=lambda x: x["edge"], reverse=True)
    return value_bets


# =========================================================================
# Helper Functions
# =========================================================================

def _form_to_score(form: str) -> float:
    """Convert form string (WWDLW) to a score between 0 and 1."""
    if not form:
        return 0.5
    points = {"W": 3, "D": 1, "L": 0}
    total = sum(points.get(c, 0) for c in form.upper())
    max_possible = len(form) * 3
    return total / max_possible if max_possible > 0 else 0.5


def _safe_ratio(wins: int, total: int) -> float:
    """Safe division for win ratio."""
    return wins / total if total > 0 else 0.5


def _rank_to_prob(rank_diff: int) -> float:
    """Convert rank difference to a probability-like score."""
    # Sigmoid-like mapping: big diff → closer to 0 or 1
    return 1 / (1 + math.exp(-rank_diff / 5))


def _poisson_under(expected_goals: float, threshold: float) -> float:
    """Probability of total goals being under threshold using Poisson."""
    prob = 0
    for k in range(int(threshold) + 1):
        prob += (expected_goals ** k * math.exp(-expected_goals)) / math.factorial(k)
    return min(1, max(0, prob))


def _edge_to_confidence(edge: float) -> int:
    """Map edge to confidence stars (1-3)."""
    for stars in sorted(config.CONFIDENCE_THRESHOLDS.keys(), reverse=True):
        if edge >= config.CONFIDENCE_THRESHOLDS[stars]:
            return stars
    return 1


def _clamp(value: float, low: float = 0.02, high: float = 0.98) -> float:
    """Clamp a probability between low and high."""
    return max(low, min(high, value))
