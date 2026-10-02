"""
Main demo runner: streams simulated multi-book odds, detects cross-book
arbitrage opportunities, and prints an LLM-generated plain-English
summary for each one found — with a live terminal dashboard showing
current best odds per event.

Run:
    python main.py                # simulated feed, template summaries
    ANTHROPIC_API_KEY=sk-... python main.py   # simulated feed, real LLM summaries

Flags:
    --ticks N        run for N ticks then exit (default: run until Ctrl+C)
    --stake AMOUNT   total stake to size each detected opportunity with (default: 1000)
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime

from rich.console import Console
from rich.live import Live
from rich.table import Table

from arbitrage import detect_arbitrage, group_by_event, stake_distribution
from llm_analyst import summarize_opportunity
from simulator import SimulatedOddsFeed

console = Console()


def render_dashboard(grouped_snapshots, opportunities_found: int) -> Table:
    table = Table(title=f"Live Odds — arbitrage opportunities found: {opportunities_found}")
    table.add_column("Event")
    table.add_column("Outcome")
    table.add_column("Best Odds")
    table.add_column("Book")
    table.add_column("Implied %")

    for event_id, snaps in grouped_snapshots.items():
        best = {}
        for snap in snaps:
            for outcome in snap.outcomes:
                if outcome.name not in best or outcome.decimal_odds > best[outcome.name][0]:
                    best[outcome.name] = (outcome.decimal_odds, snap.bookmaker)
        event_name = snaps[0].event_name
        first = True
        for outcome_name, (odds, book) in best.items():
            table.add_row(
                event_name if first else "",
                outcome_name,
                f"{odds:.3f}",
                book,
                f"{(1 / odds) * 100:.1f}%",
            )
            first = False
    return table


def main() -> None:
    parser = argparse.ArgumentParser(description="Odds arbitrage detection demo")
    parser.add_argument("--ticks", type=int, default=30, help="number of ticks to run")
    parser.add_argument("--stake", type=float, default=1000.0, help="total stake to size opportunities with")
    parser.add_argument("--tick-seconds", type=float, default=0.5, help="seconds between ticks")
    parser.add_argument("--source", choices=["sim", "live"], default="sim",
                         help="'sim' = fake data (default), 'live' = real odds via The Odds API")
    parser.add_argument("--sport", nargs="+", default=["nfl"],
                         help="one or more sports for --source live, e.g. --sport nfl nba nhl mlb ncaaf "
                              "(friendly aliases or raw API sport keys both work)")
    args = parser.parse_args()

    if args.source == "live":
        from live_feed import LiveOddsFeed
        feed = LiveOddsFeed(sports=args.sport, poll_seconds=args.tick_seconds)
    else:
        feed = SimulatedOddsFeed(seed=42, tick_seconds=args.tick_seconds)
    opportunities_found = 0
    seen_this_run = set()  # avoid spamming the same live opportunity every tick

    console.print(
        "[bold cyan]Odds Arbitrage Demo[/bold cyan] — simulated multi-book feed, "
        f"running {args.ticks} ticks. Press Ctrl+C to stop early.\n"
    )

    with Live(console=console, refresh_per_second=4) as live:
        try:
            for batch in feed.stream(max_ticks=args.ticks):
                grouped = group_by_event(batch)
                live.update(render_dashboard(grouped, opportunities_found))

                for event_id, snaps in grouped.items():
                    opp = detect_arbitrage(snaps)
                    if opp is None:
                        continue

                    # de-dupe: only announce a *new* opportunity, not the same
                    # one re-detected every tick while it's still open
                    key = (event_id, round(opp.profit_margin_pct, 2))
                    if key in seen_this_run:
                        continue
                    seen_this_run.add(key)
                    opportunities_found += 1

                    stakes = stake_distribution(args.stake, opp)
                    summary = summarize_opportunity(opp, stakes)

                    console.print(
                        f"\n[bold green]ARBITRAGE FOUND[/bold green] "
                        f"[{datetime.utcnow().strftime('%H:%M:%S')}] "
                        f"{opp.event_name} — margin {opp.profit_margin_pct:.2f}%"
                    )
                    console.print(f"[dim]{summary}[/dim]\n")

        except KeyboardInterrupt:
            pass

    console.print(
        f"\n[bold]Done.[/bold] Total distinct arbitrage opportunities detected: "
        f"{opportunities_found}"
    )


if __name__ == "__main__":
    sys.exit(main() or 0)
