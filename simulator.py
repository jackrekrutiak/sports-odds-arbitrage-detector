"""
Simulated multi-bookmaker odds feed.

This generates realistic, independently-varying odds across several
bookmakers for a handful of events, using a simple random walk per
book. Each bookmaker moves its own line independently (their own risk
models, their own customer flow) — which is *why* natural pricing gaps
open up between books. This is standard "market noise", not a staged
lag or an engineered exploit of any single book's latency.

Swap `SimulatedOddsFeed` for a real feed (e.g. The Odds API,
https://the-odds-api.com/) by implementing the same `stream()` generator
interface and yielding `OddsSnapshot` objects.
"""

from __future__ import annotations

import random
import time
from datetime import datetime
from typing import Iterator, List

from models import Outcome, OddsSnapshot

# A real book never prices its own market below 100% implied probability: it keeps a margin
# (the "vig"). Each simulated book keeps at least this much, so any arbitrage the detector
# finds comes from two different books disagreeing, never from one book mispricing itself.
MIN_BOOK_OVERROUND = 1.02

BOOKMAKERS = ["Pinnacle", "DraftKings", "FanDuel", "BetMGM", "Caesars"]

EVENTS = [
    {
        "event_id": "cfb-001",
        "event_name": "Ohio State vs Michigan",
        "outcomes": ["Ohio State", "Michigan"],
    },
    {
        "event_id": "cfb-002",
        "event_name": "Georgia vs Alabama",
        "outcomes": ["Georgia", "Alabama"],
    },
    {
        "event_id": "nfl-001",
        "event_name": "Chiefs vs Bills",
        "outcomes": ["Chiefs", "Bills"],
    },
]


class SimulatedOddsFeed:
    """Generates a stream of OddsSnapshot objects with independent per-book drift."""

    def __init__(self, seed: int | None = None, tick_seconds: float = 1.0):
        self._rng = random.Random(seed)
        self.tick_seconds = tick_seconds
        # Each book starts each event's each outcome at a base decimal odds,
        # then does an independent random walk over time.
        self._state: dict[tuple[str, str, str], float] = {}
        for event in EVENTS:
            for outcome in event["outcomes"]:
                base = self._rng.uniform(1.7, 2.3)
                for book in BOOKMAKERS:
                    # small per-book offset so books aren't identical from the start
                    offset = self._rng.uniform(-0.05, 0.05)
                    self._state[(event["event_id"], outcome, book)] = max(1.05, base + offset)

    def _step_odds(self, key: tuple[str, str, str]) -> float:
        current = self._state[key]
        # independent small random walk per (event, outcome, book)
        drift = self._rng.uniform(-0.04, 0.04)
        new_value = max(1.05, current + drift)
        self._state[key] = new_value
        return new_value

    def stream(self, max_ticks: int | None = None) -> Iterator[List[OddsSnapshot]]:
        """
        Yields a list of OddsSnapshots (one per bookmaker per event) for each tick.
        Set max_ticks for a finite demo run; leave None to run until interrupted.
        """
        tick = 0
        while max_ticks is None or tick < max_ticks:
            batch: List[OddsSnapshot] = []
            now = datetime.utcnow()
            for event in EVENTS:
                for book in BOOKMAKERS:
                    raw = [self._step_odds((event["event_id"], name, book)) for name in event["outcomes"]]
                    overround = sum(1.0 / o for o in raw)
                    if overround < MIN_BOOK_OVERROUND:
                        raw = [o * overround / MIN_BOOK_OVERROUND for o in raw]
                    outcomes = [
                        Outcome(name=name, decimal_odds=round(o, 3))
                        for name, o in zip(event["outcomes"], raw)
                    ]
                    batch.append(
                        OddsSnapshot(
                            bookmaker=book,
                            event_id=event["event_id"],
                            event_name=event["event_name"],
                            market="moneyline",
                            outcomes=outcomes,
                            timestamp=now,
                        )
                    )
            yield batch
            tick += 1
            if self.tick_seconds:
                time.sleep(self.tick_seconds)
