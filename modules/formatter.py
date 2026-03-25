"""
Telegram message formatter — creates beautiful, readable messages
with picks, analysis, and Superbet links.
"""
from datetime import datetime


# =========================================================================
# Pick Formatting
# =========================================================================

def format_value_bets(
    home_team: str,
    away_team: str,
    league: str,
    league_flag: str,
    match_date: str,
    value_bets: list[dict],
    reasoning: list[str],
    patterns: list[str],
    superbet_link: str = None,
) -> str:
    """Format value bets for a single match into a Telegram message."""
    if not value_bets:
        return ""

    # Header
    try:
        dt = datetime.fromisoformat(match_date.replace("Z", "+00:00"))
        time_str = dt.strftime("%H:%M")
        date_str = dt.strftime("%d/%m")
    except (ValueError, AttributeError):
        time_str = "--:--"
        date_str = match_date or ""

    stars_map = {1: "⭐", 2: "⭐⭐", 3: "⭐⭐⭐"}

    lines = [
        f"{league_flag} <b>{league}</b>",
        f"⚽ <b>{home_team}</b> vs <b>{away_team}</b>",
        f"🕐 {date_str} às {time_str}",
        "",
    ]

    # Picks
    for i, bet in enumerate(value_bets):
        confidence = stars_map.get(bet["confidence"], "⭐")
        lines.extend([
            f"{'─' * 30}",
            f"📊 <b>{bet['market_label']}</b>",
            f"🎯 Pick: <b>{bet['pick']}</b>",
            f"💰 Odd: <b>{bet['odd']:.2f}</b> ({bet['bookmaker']})",
            f"📈 Odd justa: {bet['fair_odd']:.2f}",
            f"🔥 Edge: <b>{bet['edge']:.1%}</b>",
            f"🏆 Confiança: {confidence}",
        ])

        # Deep link
        link = bet.get("link")
        if link:
            lines.append(f"🔗 <a href=\"{link}\">Apostar agora</a>")

    # Reasoning
    if reasoning:
        lines.extend(["", "📋 <b>Análise:</b>"])
        for r in reasoning[:5]:  # Limit to 5 most important
            lines.append(f"• {r}")

    # Patterns
    if patterns:
        lines.extend(["", "🔄 <b>Padrões detectados:</b>"])
        from modules.analyzer import PATTERNS
        for p in patterns:
            desc = PATTERNS.get(p, {}).get("description", p)
            lines.append(f"• {desc}")

    # Superbet fallback link
    if superbet_link and not any(b.get("link") for b in value_bets):
        lines.extend(["", f"🎰 <a href=\"{superbet_link}\">Abrir na Superbet</a>"])

    lines.append("")
    return "\n".join(lines)


def format_stats_only_analysis(
    home_team: str,
    away_team: str,
    league: str,
    league_flag: str,
    match_date: str,
    probabilities: dict,
) -> str:
    """Format analysis for leagues without odds (stats-only mode)."""
    try:
        dt = datetime.fromisoformat(match_date.replace("Z", "+00:00"))
        time_str = dt.strftime("%H:%M")
        date_str = dt.strftime("%d/%m")
    except (ValueError, AttributeError):
        time_str = "--:--"
        date_str = match_date or ""

    lines = [
        f"{league_flag} <b>{league}</b>",
        f"⚽ <b>{home_team}</b> vs <b>{away_team}</b>",
        f"🕐 {date_str} às {time_str}",
        "",
        "📊 <b>Análise Estatística</b> (odds não disponíveis)",
        "",
    ]

    # Show probabilities
    probs = probabilities.get("h2h", {})
    if probs:
        lines.append(f"🏠 Vitória {home_team}: <b>{probs.get('home', 0):.0%}</b>")
        lines.append(f"🤝 Empate: <b>{probs.get('draw', 0):.0%}</b>")
        lines.append(f"✈️ Vitória {away_team}: <b>{probs.get('away', 0):.0%}</b>")
        lines.append("")

    totals = probabilities.get("totals", {})
    if totals:
        lines.append(f"⬆️ Over 2.5: <b>{totals.get('over_25', 0):.0%}</b>")
        lines.append(f"⬇️ Under 2.5: <b>{totals.get('under_25', 0):.0%}</b>")
        lines.append("")

    btts = probabilities.get("btts", {})
    if btts:
        lines.append(f"✅ Ambas marcam: <b>{btts.get('yes', 0):.0%}</b>")
        lines.append(f"❌ Não marcam ambas: <b>{btts.get('no', 0):.0%}</b>")
        lines.append("")

    # Reasoning
    reasoning = probabilities.get("reasoning", [])
    if reasoning:
        lines.append("📋 <b>Análise:</b>")
        for r in reasoning[:5]:
            lines.append(f"• {r}")

    # Patterns
    patterns = probabilities.get("patterns_triggered", [])
    if patterns:
        lines.append("")
        lines.append("🔄 <b>Padrões detectados:</b>")
        from modules.analyzer import PATTERNS
        for p in patterns:
            desc = PATTERNS.get(p, {}).get("description", p)
            lines.append(f"• {desc}")

    lines.extend(["", "⚠️ Sem odds disponíveis — use como referência para apostar manualmente."])
    return "\n".join(lines)


def format_daily_summary(picks_by_match: list[dict]) -> str:
    """Format a summary of all daily picks."""
    if not picks_by_match:
        return "🔍 Nenhuma value bet encontrada nos jogos analisados hoje."

    total_picks = sum(len(m["value_bets"]) for m in picks_by_match)
    high_confidence = sum(
        1 for m in picks_by_match
        for b in m["value_bets"]
        if b["confidence"] >= 3
    )

    lines = [
        "📊 <b>RESUMO DO DIA</b>",
        f"{'═' * 30}",
        f"🎯 Total de picks: <b>{total_picks}</b>",
        f"⭐⭐⭐ Alta confiança: <b>{high_confidence}</b>",
        "",
    ]

    for match in picks_by_match:
        best_bet = max(match["value_bets"], key=lambda x: x["edge"])
        stars = "⭐" * best_bet["confidence"]
        lines.append(
            f"• {match['league_flag']} {match['home_team']} vs {match['away_team']} "
            f"→ {best_bet['pick']} @{best_bet['odd']:.2f} {stars}"
        )

    lines.extend([
        "",
        "Use /detalhe [número] para ver a análise completa de cada jogo.",
    ])
    return "\n".join(lines)


# =========================================================================
# Stats & Feedback Formatting
# =========================================================================

def format_performance_stats(stats: dict, period: str = "Geral") -> str:
    """Format performance statistics."""
    if stats["total"] == 0:
        return "📊 Ainda não há dados suficientes para estatísticas."

    roi_emoji = "📈" if stats["roi"] > 0 else "📉"

    lines = [
        f"📊 <b>PERFORMANCE — {period}</b>",
        f"{'═' * 30}",
        f"Total de picks: <b>{stats['total']}</b>",
        f"✅ Acertos: <b>{stats['wins']}</b>",
        f"❌ Erros: <b>{stats['losses']}</b>",
        f"🎯 Taxa de acerto: <b>{stats['hit_rate']}%</b>",
        f"💰 Odd média: <b>{stats['avg_odd']}</b>",
        f"{roi_emoji} ROI: <b>{stats['roi']:+.1f}%</b>",
    ]

    return "\n".join(lines)


def format_leagues_list() -> str:
    """Format available leagues."""
    import config
    lines = ["🏟️ <b>LIGAS DISPONÍVEIS</b>", ""]

    by_region = {}
    for name, data in config.LEAGUES.items():
        country = data["country"]
        if country not in by_region:
            by_region[country] = []
        by_region[country].append(f"{data['flag']} {name}")

    for region, leagues in by_region.items():
        lines.append(f"<b>{region}:</b>")
        for league in leagues:
            lines.append(f"  • {league}")
        lines.append("")

    lines.append("Use /analise [liga] para analisar os jogos de uma liga.")
    return "\n".join(lines)


def format_pending_feedback(picks: list[dict]) -> str:
    """Format picks awaiting feedback."""
    if not picks:
        return "✅ Nenhuma pick pendente de feedback."

    lines = ["📝 <b>PICKS PARA AVALIAR</b>", ""]
    for p in picks[:10]:  # Limit to 10
        result_emoji = {"win": "✅", "loss": "❌", "void": "⚪", "pending": "⏳"}.get(p["result"], "❓")
        lines.append(
            f"{result_emoji} #{p['id']} | {p['home_team']} vs {p['away_team']} | "
            f"{p['pick']} @{p['odd']:.2f}"
        )

    lines.extend([
        "",
        "Responda com:",
        "/fb [id] bom — Pick foi boa",
        "/fb [id] ruim — Pick foi ruim",
        "/fb [id] [comentário] — Feedback detalhado",
    ])
    return "\n".join(lines)


# =========================================================================
# Help & Welcome
# =========================================================================

def format_welcome() -> str:
    return "\n".join([
        "🤖⚽ <b>BetBot — Seu Analista de Value Bets</b>",
        "",
        "Eu analiso jogos de futebol das principais ligas do mundo, "
        "comparo odds de 80+ casas de apostas e encontro as melhores "
        "oportunidades de valor pra você.",
        "",
        "🧠 Quanto mais você usa e dá feedback, mais eu aprendo!",
        "",
        "Comandos:",
        "/jogos — Jogos do dia (todas as ligas)",
        "/ligas — Ver ligas disponíveis",
        "/analise [liga] — Analisar jogos de uma liga",
        "/value — Melhores value bets do momento",
        "/stats — Sua performance geral",
        "/pendentes — Picks esperando resultado",
        "/fb [id] [bom/ruim/nota] — Dar feedback",
        "/uso — Uso de API (controle de requests)",
        "/ajuda — Este menu",
    ])


def format_api_usage(football_today: int, odds_month: int) -> str:
    """Format API usage stats."""
    import config
    fb_pct = football_today / config.API_FOOTBALL_DAILY_LIMIT * 100
    odds_pct = odds_month / config.ODDS_API_MONTHLY_LIMIT * 100

    fb_bar = _progress_bar(fb_pct)
    odds_bar = _progress_bar(odds_pct)

    return "\n".join([
        "📡 <b>USO DE API</b>",
        "",
        f"<b>API-Football</b> (diário):",
        f"{fb_bar} {football_today}/{config.API_FOOTBALL_DAILY_LIMIT}",
        "",
        f"<b>The Odds API</b> (mensal):",
        f"{odds_bar} {odds_month}/{config.ODDS_API_MONTHLY_LIMIT}",
    ])


def _progress_bar(pct: float, length: int = 10) -> str:
    """Create a simple text progress bar."""
    filled = int(pct / 100 * length)
    filled = min(filled, length)
    bar = "█" * filled + "░" * (length - filled)
    color = "🟢" if pct < 60 else "🟡" if pct < 85 else "🔴"
    return f"{color} [{bar}] {pct:.0f}%"
