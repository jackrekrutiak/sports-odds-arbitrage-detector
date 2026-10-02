"""
Arbitrage math engine.

Standard sports-arbitrage detection: for a given event/market, find the
best (highest) available decimal odds for each outcome across all books,
sum the implied probabilities, and if that sum is < 1.0 there's a
risk-free arbitrage (the "overround" has gone negative across books).

This is textbook arbitrage-betting math — the same calculation any odds
comparison / arb-finding tool performs. See e.g.:
https://en.wikipedia.org/wiki/Arbitrage_betting
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional

import numpy as np

from models import ArbitrageOpportunity, BestOutcomeQuote, OddsSnapshot


def best_odds_per_outcome(snapshots: List[OddsSnapshot]) -> Dict[str, BestOutcomeQuote]:
    """
    Given all current snapshots for ONE event+market, find the best
    (highest) decimal odds available for each outcome, and which book
    offers it.
    """
    best: Dict[str, BestOutcomeQuote] = {}
    for snap in snapshots:
        for outcome in snap.outcomes:
            current_best = best.get(outcome.name)
            if current_best is None or outcome.decimal_odds > current_best.decimal_odds:
                best[outcome.name] = BestOutcomeQuote(
                    outcome=outcome.name,
                    decimal_odds=outcome.decimal_odds,
                    bookmaker=snap.bookmaker,
                )
    return best


def detect_arbitrage(snapshots: List[OddsSnapshot]) -> Optional[ArbitrageOpportunity]:
    """
    Check one event+market's snapshots for a cross-book arbitrage.
    Returns None if there's no arbitrage (total implied probability >= 1.0).
    """
    if not snapshots:
        return None

    event_id = snapshots[0].event_id
    event_name = snapshots[0].event_name
    market = snapshots[0].market

    best = best_odds_per_outcome(snapshots)
    if not best:
        return None

    # Vectorized implied-probability sum with NumPy
    odds_array = np.array([q.decimal_odds for q in best.values()], dtype=float)
    implied_probs = 1.0 / odds_array
    total_implied = float(implied_probs.sum())

    if total_implied >= 1.0:
        return None  # no arbitrage — books' combined margin still favors the house

    profit_margin_pct = (1.0 - total_implied) * 100.0

    return ArbitrageOpportunity(
        event_id=event_id,
        event_name=event_name,
        market=market,
        best_odds=best,
        total_implied_probability=total_implied,
        profit_margin_pct=profit_margin_pct,
    )


def stake_distribution(total_stake: float, opportunity: ArbitrageOpportunity) -> Dict[str, float]:
    """
    Given a total stake to allocate, compute how much to bet on each
    outcome so the payout is equal regardless of which outcome wins
    (the standard arbitrage stake formula):

        stake_i = total_stake * (1 / odds_i) / total_implied_probability
    """
    stakes: Dict[str, float] = {}
    for outcome_name, quote in opportunity.best_odds.items():
        implied = 1.0 / quote.decimal_odds
        stakes[outcome_name] = round(
            total_stake * implied / opportunity.total_implied_probability, 2
        )
    return stakes


def group_by_event(snapshots: List[OddsSnapshot]) -> Dict[str, List[OddsSnapshot]]:
    """Group a flat list of snapshots (multiple events/books) by event_id."""
    grouped: Dict[str, List[OddsSnapshot]] = defaultdict(list)
    for snap in snapshots:
        grouped[snap.event_id].append(snap)
    return grouped
