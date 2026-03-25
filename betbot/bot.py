"""
BetBot — Telegram Bot for Football Value Bet Analysis
Main entry point. Handles all user commands and orchestrates the analysis pipeline.
"""
import asyncio
import logging
import sys
from datetime import datetime

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode

import config
from modules import database as db
from modules import api_football as football
from modules import odds_api as odds
from modules import analyzer
from modules import formatter as fmt

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("betbot")


# =========================================================================
# Command Handlers
# =========================================================================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Welcome message."""
    await update.message.reply_text(
        fmt.format_welcome(), parse_mode=ParseMode.HTML
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help menu."""
    await update.message.reply_text(
        fmt.format_welcome(), parse_mode=ParseMode.HTML
    )


async def cmd_leagues(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List available leagues."""
    await update.message.reply_text(
        fmt.format_leagues_list(), parse_mode=ParseMode.HTML
    )


async def cmd_games_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Show today's fixtures across all configured leagues.
    Uses 1 API call (date filter) to get all games, then filters by configured leagues.
    """
    await update.message.reply_text("🔍 Buscando os principais jogos do dia...")

    try:
        today = datetime.now().strftime("%Y-%m-%d")

        # Fetch all fixtures for today in one request (efficient!)
        all_fixtures = await football.get_fixtures_today(date=today)

        if not all_fixtures:
            await update.message.reply_text(
                "Nenhum jogo encontrado hoje. Pode ser que não haja rodada nas principais ligas."
            )
            return

        # Filter only fixtures from our configured leagues
        configured_ids = {v["api_football_id"]: (k, v) for k, v in config.LEAGUES.items()}
        filtered = {}
        for f in all_fixtures:
            lid = f.get("league_id")
            if lid in configured_ids:
                league_name, league_data = configured_ids[lid]
                if league_name not in filtered:
                    filtered[league_name] = {"flag": league_data["flag"], "games": []}
                filtered[league_name]["games"].append(f)

        if not filtered:
            await update.message.reply_text(
                "Há jogos hoje, mas nenhum nas ligas que monitoro.\n"
                "Use /ligas para ver quais ligas estão configuradas."
            )
            return

        # Build the message
        total_games = sum(len(d["games"]) for d in filtered.values())
        lines = [
            f"⚽ <b>JOGOS DE HOJE — {datetime.now().strftime('%d/%m/%Y')}</b>",
            f"📊 {total_games} jogos em {len(filtered)} ligas",
            "",
        ]

        for league_name, data in filtered.items():
            flag = data["flag"]
            games = sorted(data["games"], key=lambda g: g.get("date", ""))
            lines.append(f"{flag} <b>{league_name}</b> ({len(games)} jogos)")

            for g in games:
                try:
                    dt = datetime.fromisoformat(g["date"].replace("Z", "+00:00"))
                    time_str = dt.strftime("%H:%M")
                except (ValueError, AttributeError):
                    time_str = "--:--"

                status = g.get("status", "NS")
                home = g["home_team"]
                away = g["away_team"]

                if status == "NS":
                    lines.append(f"  🕐 {time_str} | {home} vs {away}")
                elif status in ("1H", "2H", "HT", "LIVE"):
                    score = f"{g.get('home_goals', 0)}-{g.get('away_goals', 0)}"
                    lines.append(f"  🔴 AO VIVO {score} | {home} vs {away}")
                elif status in ("FT", "AET", "PEN"):
                    score = f"{g.get('home_goals', 0)}-{g.get('away_goals', 0)}"
                    lines.append(f"  ✅ {score} | {home} vs {away}")
                else:
                    lines.append(f"  ⏳ {status} | {home} vs {away}")

            lines.append("")

        lines.append("💡 Use /analise [liga] para buscar value bets.")
        lines.append("🔥 Use /value para um scan rápido das melhores oportunidades.")

        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

    except football.RateLimitExceeded as e:
        await update.message.reply_text(f"⚠️ {e}")
    except Exception as e:
        logger.error(f"Error in cmd_games_today: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Erro ao buscar jogos: {e}")


async def cmd_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Analyze value bets for a specific league.
    Usage: /analise Premier League
    """
    if not context.args:
        await update.message.reply_text(
            "Use: /analise [nome da liga]\nEx: /analise Premier League\n\n"
            "Use /ligas para ver as ligas disponíveis.",
            parse_mode=ParseMode.HTML,
        )
        return

    league_query = " ".join(context.args).strip().lower()

    # Find matching league
    matched_league = None
    for name, data in config.LEAGUES.items():
        if league_query in name.lower() or league_query in data.get("country", "").lower():
            matched_league = (name, data)
            break

    if not matched_league:
        await update.message.reply_text(
            f"❌ Liga '{' '.join(context.args)}' não encontrada.\n"
            "Use /ligas para ver as disponíveis."
        )
        return

    league_name, league_data = matched_league
    league_id = league_data["api_football_id"]
    odds_key = league_data["odds_api_key"]
    flag = league_data["flag"]

    await update.message.reply_text(
        f"🔍 Analisando {flag} <b>{league_name}</b>...\n"
        "Isso pode levar alguns segundos.",
        parse_mode=ParseMode.HTML,
    )

    try:
        # Fetch data in parallel
        fixtures_task = football.get_fixtures_by_league(league_id, next_n=5)
        odds_task = odds.get_best_odds(odds_key)

        fixtures, odds_events = await asyncio.gather(fixtures_task, odds_task)

        if not fixtures:
            await update.message.reply_text(f"Nenhum jogo próximo encontrado para {league_name}.")
            return

        if not odds_events:
            await update.message.reply_text(
                f"Odds não disponíveis para {league_name} no momento. "
                "Tente mais perto do horário dos jogos."
            )
            return

        conn = db.get_connection()
        all_picks = []

        for fixture in fixtures[:3]:  # Limit to 3 matches to save API calls
            home_team = fixture["home_team"]
            away_team = fixture["away_team"]

            # Find matching odds event
            odds_event = _find_matching_event(odds_events, home_team, away_team)
            if not odds_event:
                continue

            # Fetch detailed stats (parallel)
            try:
                stats_tasks = [
                    football.get_team_stats(fixture["home_id"], league_id),
                    football.get_team_stats(fixture["away_id"], league_id),
                    football.get_h2h(fixture["home_id"], fixture["away_id"]),
                    football.get_standings(league_id),
                ]
                home_stats, away_stats, h2h, standings = await asyncio.gather(*stats_tasks)

                # Try to get injuries (non-critical)
                try:
                    injuries = await football.get_injuries(fixture["fixture_id"])
                except Exception:
                    injuries = []

            except football.RateLimitExceeded:
                logger.warning("Rate limit approaching, skipping detailed stats")
                continue

            home_stats["team_id"] = fixture["home_id"]
            away_stats["team_id"] = fixture["away_id"]

            # Run analysis
            probabilities = analyzer.estimate_match_probabilities(
                home_stats, away_stats, h2h, standings, injuries, league_name,
            )

            # Find value bets
            value_bets = analyzer.find_value_bets(
                probabilities, odds_event.get("best_odds", {}),
            )

            if value_bets:
                # Check for Superbet link
                superbet = odds.find_superbet_odds(odds_event)
                superbet_link = (
                    superbet.get("link") if superbet
                    else odds.build_superbet_event_url(home_team, away_team)
                )

                # Format and send
                msg = fmt.format_value_bets(
                    home_team=home_team,
                    away_team=away_team,
                    league=league_name,
                    league_flag=flag,
                    match_date=fixture.get("date", ""),
                    value_bets=value_bets,
                    reasoning=probabilities["reasoning"],
                    patterns=probabilities["patterns_triggered"],
                    superbet_link=superbet_link,
                )

                if msg:
                    await update.message.reply_text(msg, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

                # Save picks to database
                for vb in value_bets:
                    db.save_pick(conn, {
                        "fixture_id": fixture["fixture_id"],
                        "league": league_name,
                        "home_team": home_team,
                        "away_team": away_team,
                        "match_date": fixture.get("date"),
                        "market": vb["market"],
                        "pick": vb["pick"],
                        "odd": vb["odd"],
                        "bookmaker": vb["bookmaker"],
                        "implied_prob": vb["implied_prob"],
                        "estimated_prob": vb["estimated_prob"],
                        "edge": vb["edge"],
                        "confidence": vb["confidence"],
                        "reasoning": "; ".join(probabilities["reasoning"][:3]),
                        "deep_link": vb.get("link") or superbet_link,
                    })

                all_picks.append({
                    "home_team": home_team,
                    "away_team": away_team,
                    "league_flag": flag,
                    "value_bets": value_bets,
                })

        conn.close()

        if not all_picks:
            await update.message.reply_text(
                f"🔍 Analisei os jogos de {league_name} mas não encontrei value bets no momento.\n"
                "Isso significa que as odds estão justas ou não há edge suficiente."
            )
        else:
            summary = fmt.format_daily_summary(all_picks)
            await update.message.reply_text(summary, parse_mode=ParseMode.HTML)

    except (football.RateLimitExceeded, odds.RateLimitExceeded) as e:
        await update.message.reply_text(f"⚠️ {e}")
    except Exception as e:
        logger.error(f"Error in cmd_analyze: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Erro na análise: {e}")


async def cmd_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quick scan: find the best value bets across all leagues with games today."""
    await update.message.reply_text("🔍 Escaneando todas as ligas por value bets... Pode levar até 1 minuto.")

    try:
        # Get today's fixtures to know which leagues have games
        fixtures = await football.get_fixtures_today()

        if not fixtures:
            await update.message.reply_text("Nenhum jogo encontrado hoje.")
            return

        # Find unique leagues with games
        active_leagues = set()
        for f in fixtures:
            league_id = f.get("league_id")
            for name, data in config.LEAGUES.items():
                if data["api_football_id"] == league_id:
                    active_leagues.add(name)

        if not active_leagues:
            await update.message.reply_text(
                "Jogos encontrados mas nenhum nas ligas configuradas. "
                "Use /ligas para ver quais estão ativas."
            )
            return

        await update.message.reply_text(
            f"📡 {len(active_leagues)} ligas com jogos hoje: {', '.join(active_leagues)}\n"
            "Analisando as 3 com mais jogos...",
            parse_mode=ParseMode.HTML,
        )

        # Analyze top 3 leagues (to save API calls)
        for league_name in list(active_leagues)[:3]:
            context.args = league_name.split()
            await cmd_analyze(update, context)

    except Exception as e:
        logger.error(f"Error in cmd_value: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Erro: {e}")


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show performance statistics."""
    conn = db.get_connection()

    # Overall stats
    overall = db.get_performance_stats(conn)
    msg = fmt.format_performance_stats(overall, "Geral")

    # Per league breakdown if enough data
    if overall["total"] >= 10:
        for league_name in config.LEAGUES:
            league_stats = db.get_performance_stats(conn, league=league_name)
            if league_stats["total"] >= 3:
                msg += "\n\n" + fmt.format_performance_stats(league_stats, league_name)

    conn.close()
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def cmd_pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show picks pending results or feedback."""
    conn = db.get_connection()
    pending = db.get_pending_picks(conn)
    conn.close()

    msg = fmt.format_pending_feedback(pending)
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def cmd_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Give feedback on a pick.
    Usage: /fb 42 bom | /fb 42 ruim | /fb 42 a odd estava errada
    """
    if len(context.args) < 2:
        await update.message.reply_text(
            "Use: /fb [id] [bom/ruim/comentário]\n"
            "Ex: /fb 42 bom\n"
            "Ex: /fb 42 ruim liga sempre imprevisível\n\n"
            "Use /pendentes para ver os IDs das picks."
        )
        return

    try:
        pick_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID inválido. Use um número.")
        return

    feedback_text = " ".join(context.args[1:]).strip().lower()

    # Classify feedback
    if feedback_text in ("bom", "boa", "boa!", "bom!", "good", "👍"):
        feedback_type = "good"
    elif feedback_text in ("ruim", "mal", "bad", "👎"):
        feedback_type = "bad"
    else:
        feedback_type = "custom"

    conn = db.get_connection()
    db.save_feedback(conn, pick_id, feedback_type, feedback_text)
    conn.close()

    await update.message.reply_text(
        f"✅ Feedback salvo para pick #{pick_id}!\n"
        "Obrigado — isso me ajuda a melhorar as próximas análises. 🧠"
    )


async def cmd_settle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Manually settle pending picks by checking results.
    Usage: /settle (checks all pending)
    """
    await update.message.reply_text("🔍 Verificando resultados das picks pendentes...")

    conn = db.get_connection()
    pending = db.get_pending_picks(conn)

    if not pending:
        await update.message.reply_text("✅ Nenhuma pick pendente!")
        conn.close()
        return

    settled = 0
    for pick in pending:
        try:
            result = await football.get_fixture_result(pick["fixture_id"])
            if not result:
                continue

            # Determine if pick won
            won = _check_pick_result(pick, result)
            db.update_pick_result(conn, pick["id"], "win" if won else "loss")
            settled += 1

        except Exception as e:
            logger.warning(f"Could not settle pick #{pick['id']}: {e}")

    conn.close()

    still_pending = len(pending) - settled
    await update.message.reply_text(
        f"✅ {settled} picks resolvidas.\n"
        f"⏳ {still_pending} ainda pendentes (jogos não terminados).\n\n"
        "Use /stats para ver sua performance atualizada."
    )


async def cmd_api_usage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show API usage statistics."""
    conn = db.get_connection()
    football_today = db.get_api_usage_today(conn, "api_football")
    odds_month = db.get_api_usage_month(conn, "odds_api")
    conn.close()

    msg = fmt.format_api_usage(football_today, odds_month)
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


# =========================================================================
# Natural Language Handler
# =========================================================================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle free-text messages with basic intent detection."""
    text = (update.message.text or "").lower().strip()

    # Simple keyword matching for natural language
    if any(w in text for w in ["jogo", "partida", "hoje", "rodada"]):
        await cmd_games_today(update, context)
    elif any(w in text for w in ["value", "valor", "aposta", "bet", "dica", "tip"]):
        # Try to extract league
        for league_name in config.LEAGUES:
            if league_name.lower() in text:
                context.args = league_name.split()
                await cmd_analyze(update, context)
                return
        await cmd_value(update, context)
    elif any(w in text for w in ["liga", "campeonato", "torneio"]):
        await cmd_leagues(update, context)
    elif any(w in text for w in ["stat", "desempenho", "resultado", "performance"]):
        await cmd_stats(update, context)
    else:
        await update.message.reply_text(
            "Não entendi. Tenta um desses:\n"
            "/jogos — Ver jogos do dia\n"
            "/value — Buscar value bets\n"
            "/analise [liga] — Analisar liga específica\n"
            "/ajuda — Ver todos os comandos"
        )


# =========================================================================
# Helpers
# =========================================================================

def _find_matching_event(odds_events: list, home_team: str, away_team: str) -> dict | None:
    """Match an API-Football fixture to an Odds API event by team names."""
    home_lower = home_team.lower()
    away_lower = away_team.lower()

    for event in odds_events:
        event_home = event["home_team"].lower()
        event_away = event["away_team"].lower()

        # Exact or partial match
        if (
            (home_lower in event_home or event_home in home_lower)
            and (away_lower in event_away or event_away in away_lower)
        ):
            return event
    return None


def _check_pick_result(pick: dict, result: dict) -> bool:
    """Check if a pick was correct based on the match result."""
    market = pick["market"]
    pick_name = pick["pick"]

    if market == "h2h":
        winner = result["winner"]
        return (
            (pick_name == "Home" and winner == "home")
            or (pick_name == "Draw" and winner == "draw")
            or (pick_name == "Away" and winner == "away")
        )

    elif market == "totals":
        total = result["total_goals"]
        if "Over" in pick_name:
            return total > 2.5
        elif "Under" in pick_name:
            return total < 2.5

    elif market == "btts":
        if pick_name == "Yes":
            return result["btts"]
        elif pick_name == "No":
            return not result["btts"]

    return False


# =========================================================================
# Main
# =========================================================================

def main():
    """Start the bot."""
    if config.TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        print("❌ Configure seu TELEGRAM_BOT_TOKEN no config.py ou variável de ambiente!")
        print("   Siga o guia no README.md para criar o bot no BotFather.")
        sys.exit(1)

    print("🤖⚽ BetBot starting...")
    print(f"   Leagues: {len(config.LEAGUES)}")
    print(f"   Markets: {', '.join(config.MARKETS.values())}")
    print(f"   Min edge: {config.MIN_VALUE_EDGE:.0%}")

    # Initialize database
    conn = db.get_connection()
    conn.close()
    print("   Database: OK")

    # Build application
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    # Register handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("ajuda", cmd_help))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("ligas", cmd_leagues))
    app.add_handler(CommandHandler("jogos", cmd_games_today))
    app.add_handler(CommandHandler("analise", cmd_analyze))
    app.add_handler(CommandHandler("value", cmd_value))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("pendentes", cmd_pending))
    app.add_handler(CommandHandler("fb", cmd_feedback))
    app.add_handler(CommandHandler("feedback", cmd_feedback))
    app.add_handler(CommandHandler("settle", cmd_settle))
    app.add_handler(CommandHandler("resolver", cmd_settle))
    app.add_handler(CommandHandler("uso", cmd_api_usage))

    # Natural language fallback
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("   Bot is running! Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
