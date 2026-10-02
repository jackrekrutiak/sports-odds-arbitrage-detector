"""
Data models for the odds arbitrage demo.

These are plain, general-purpose sports-betting odds structures —
a bookmaker name, an event, and decimal odds per outcome. Nothing here
is specific to any particular sport, live-lag exploitation, or book-specific
targeting; it's the same shape of data any odds-comparison product
(OddsJam, RebelBetting, oddschecker, etc.) works with.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List


@dataclass
class Outcome:
    """A single bettable outcome (e.g. 'Home', 'Away', 'Draw') and its decimal odds."""

    name: str
    decimal_odds: float

    @property
    def implied_probability(self) -> float:
        """Implied probability from decimal odds: 1 / odds."""
        if self.decimal_odds <= 1.0:
            raise ValueError(f"decimal_odds must be > 1.0, got {self.decimal_odds}")
        return 1.0 / self.decimal_odds


@dataclass
class OddsSnapshot:
    """
    A single point-in-time quote from one bookmaker for one event.

    A stream of these (varying by timestamp) is what a real odds-comparison
    feed looks like — e.g. from a provider like The Odds API.
    """

    bookmaker: str
    event_id: str
    event_name: str
    market: str  # e.g. "moneyline", "spread", "total"
    outcomes: List[Outcome]
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def outcome_map(self) -> Dict[str, Outcome]:
        return {o.name: o for o in self.outcomes}


@dataclass
class ArbitrageOpportunity:
    """A detected cross-book arbitrage: the best available odds per outcome."""

    event_id: str
    event_name: str
    market: str
    best_odds: Dict[str, "BestOutcomeQuote"]  # outcome name -> best quote
    total_implied_probability: float
    profit_margin_pct: float
    detected_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class BestOutcomeQuote:
    """The best (highest) available odds for one outcome, and which book offers it."""

    outcome: str
    decimal_odds: float
    bookmaker: str
