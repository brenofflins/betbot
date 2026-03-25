"""
BetBot Configuration
All API keys and settings in one place.
"""
import os

# =============================================================================
# API Keys
# =============================================================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", "")

# =============================================================================
# API Endpoints
# =============================================================================
ODDS_API_BASE = "https://api.the-odds-api.com/v4"
API_FOOTBALL_BASE = "https://v3.football.api-sports.io"

# =============================================================================
# Leagues Configuration
# Key: readable name → Value: dict with IDs for each API
# =============================================================================
LEAGUES = {
    # Top 5 Europe
    "Premier League": {"api_football_id": 39, "odds_api_key": "soccer_epl", "country": "England", "flag": "🏴󠁧󠁢󠁥󠁮󠁧󠁿"},
    "La Liga": {"api_football_id": 140, "odds_api_key": "soccer_spain_la_liga", "country": "Spain", "flag": "🇪🇸"},
    "Serie A": {"api_football_id": 135, "odds_api_key": "soccer_italy_serie_a", "country": "Italy", "flag": "🇮🇹"},
    "Bundesliga": {"api_football_id": 78, "odds_api_key": "soccer_germany_bundesliga", "country": "Germany", "flag": "🇩🇪"},
    "Ligue 1": {"api_football_id": 61, "odds_api_key": "soccer_france_ligue_one", "country": "France", "flag": "🇫🇷"},
    # South America
    "Brasileirão": {"api_football_id": 71, "odds_api_key": "soccer_brazil_campeonato", "country": "Brazil", "flag": "🇧🇷"},
    "Copa do Brasil": {"api_football_id": 73, "odds_api_key": "soccer_brazil_copa_do_brasil", "country": "Brazil", "flag": "🇧🇷"},
    "Liga Argentina": {"api_football_id": 128, "odds_api_key": "soccer_argentina_primera_division", "country": "Argentina", "flag": "🇦🇷"},
    # Continental
    "Champions League": {"api_football_id": 2, "odds_api_key": "soccer_uefa_champs_league", "country": "Europe", "flag": "🇪🇺"},
    "Europa League": {"api_football_id": 3, "odds_api_key": "soccer_uefa_europa_league", "country": "Europe", "flag": "🇪🇺"},
    "Libertadores": {"api_football_id": 13, "odds_api_key": "soccer_conmebol_copa_libertadores", "country": "South America", "flag": "🌎"},
    "Sul-Americana": {"api_football_id": 11, "odds_api_key": "soccer_conmebol_copa_sudamericana", "country": "South America", "flag": "🌎"},
}

# =============================================================================
# Analysis Settings
# =============================================================================

# Minimum edge (%) for a bet to be considered "value"
# e.g., 0.05 = the estimated probability is at least 5% higher than implied
MIN_VALUE_EDGE = 0.05

# Confidence thresholds
CONFIDENCE_THRESHOLDS = {
    1: 0.05,   # ⭐ — edge 5-10%
    2: 0.10,   # ⭐⭐ — edge 10-15%
    3: 0.15,   # ⭐⭐⭐ — edge 15%+
}

# Markets to analyze
MARKETS = {
    "h2h": "1X2 (Resultado)",
    "totals": "Over/Under Gols",
    "btts": "Ambas Marcam (BTTS)",
}

# Weights for probability estimation (sum = 1.0)
ANALYSIS_WEIGHTS = {
    "recent_form": 0.25,        # Last 5 games
    "h2h_history": 0.15,        # Head-to-head record
    "home_away_record": 0.20,   # Home/away performance
    "goals_stats": 0.15,        # Goals scored/conceded averages
    "league_position": 0.10,    # Current standings gap
    "injuries": 0.10,           # Key players missing
    "motivation": 0.05,         # Derby, relegation battle, title race
}

# =============================================================================
# Rate Limiting — Free Tier Budgets
# =============================================================================
ODDS_API_MONTHLY_LIMIT = 500
API_FOOTBALL_DAILY_LIMIT = 100

# =============================================================================
# Database
# =============================================================================
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Default: data/betbot.db relative to project root
# Falls back to /tmp if the project dir doesn't support SQLite (e.g., mounted FS)
_DEFAULT_DB = os.path.join(_BASE_DIR, "data", "betbot.db")
DB_PATH = os.getenv("DB_PATH", _DEFAULT_DB)

# =============================================================================
# Superbet
# =============================================================================
SUPERBET_BASE_URL = "https://superbet.bet.br"
