"""
Live odds feed using The Odds API (https://the-odds-api.com/).

Same stream() generator interface as SimulatedOddsFeed, so main.py can
swap between simulated and live data by changing which class it builds.
Supports pulling multiple sports/leagues in the same feed so arbitrage
can be scanned across all of them at once.

Requires an ODDS_API_KEY environment variable — set it in your shell,
never hardcode it here:

    export ODDS_API_KEY=your-key-here
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Iterator, List, Optional, Sequence

from models import Outcome, OddsSnapshot

API_BASE = "https://api.the-odds-api.com/v4"

# Friendly short names -> The Odds API's sport keys
SPORT_ALIASES = {
    "nfl": "americanfootball_nfl",
    "ncaaf": "americanfootball_ncaaf",
    "nba": "basketball_nba",
    "ncaab": "basketball_ncaab",
    "mlb": "baseball_mlb",
    "nhl": "icehockey_nhl",
}

DEFAULT_SPORTS = ["nfl"]


def resolve_sport_key(name: str) -> str:
    """Accept either a friendly alias ('nfl') or a raw API sport key
    ('americanfootball_nfl') and return the API sport key."""
    key = name.strip().lower()
    return SPORT_ALIASES.get(key, name.strip())


class LiveOddsFeed:
    def __init__(
        self,
        sports: Sequence[str] = tuple(DEFAULT_SPORTS),
        poll_seconds: float = 30.0,
        api_key: Optional[str] = None,
    ):
        self.sports = [resolve_sport_key(s) for s in sports]
        self.poll_seconds = poll_seconds
        self.api_key = api_key or os.environ.get("ODDS_API_KEY")
        if not self.api_key:
            raise RuntimeError(
                "No API key found. Set ODDS_API_KEY in your environment first:\n"
                "    export ODDS_API_KEY=your-key-here"
            )

    def _fetch_sport(self, sport_key: str) -> list[dict]:
        url = (
            f"{API_BASE}/sports/{sport_key}/odds/"
            f"?apiKey={self.api_key}&regions=us&markets=h2h&oddsFormat=decimal"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "odds-arb-demo/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                remaining = resp.headers.get("x-requests-remaining")
                if remaining is not None:
                    print(f"[live_feed] {sport_key}: API requests remaining this period: {remaining}")
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            # Don't let one bad/out-of-season sport key kill the whole run
            print(f"[live_feed] {sport_key}: API error {exc.code}: {body}")
            return []

    def _parse(self, raw_events: list[dict]) -> List[OddsSnapshot]:
        snapshots: List[OddsSnapshot] = []
        for event in raw_events:
            event_id = event["id"]
            event_name = f"{event['away_team']} @ {event['home_team']}"
            for book in event.get("bookmakers", []):
                for market in book.get("markets", []):
                    if market["key"] != "h2h":
                        continue
                    outcomes = [
                        Outcome(name=o["name"], decimal_odds=float(o["price"]))
                        for o in market["outcomes"]
                    ]
                    if not outcomes:
                        continue
                    snapshots.append(
                        OddsSnapshot(
                            bookmaker=book["title"],
                            event_id=event_id,
                            event_name=event_name,
                            market="moneyline",
                            outcomes=outcomes,
                        )
                    )
        return snapshots

    def _fetch_all(self) -> List[OddsSnapshot]:
        all_snapshots: List[OddsSnapshot] = []
        for sport_key in self.sports:
            raw = self._fetch_sport(sport_key)
            all_snapshots.extend(self._parse(raw))
        return all_snapshots

    def stream(self, max_ticks: Optional[int] = None) -> Iterator[List[OddsSnapshot]]:
        """Poll every configured sport every poll_seconds, yielding one
        combined batch of snapshots per poll — same shape
        SimulatedOddsFeed.stream() yields."""
        tick = 0
        while max_ticks is None or tick < max_ticks:
            yield self._fetch_all()
            tick += 1
            if max_ticks is None or tick < max_ticks:
                time.sleep(self.poll_seconds)
