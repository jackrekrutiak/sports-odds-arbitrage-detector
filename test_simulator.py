"""Simulated and live feed tests (no network). Run with `pytest`, or `python test_simulator.py` for a printed demo."""
import pytest

from live_feed import LiveOddsFeed, resolve_sport_key
from simulator import BOOKMAKERS, EVENTS, MIN_BOOK_OVERROUND, SimulatedOddsFeed


def test_simulator_is_reproducible_with_a_seed():
    a = [[o.decimal_odds for s in b for o in s.outcomes] for b in SimulatedOddsFeed(seed=1, tick_seconds=0).stream(max_ticks=3)]
    b = [[o.decimal_odds for s in b for o in s.outcomes] for b in SimulatedOddsFeed(seed=1, tick_seconds=0).stream(max_ticks=3)]
    assert a == b


def test_simulator_batch_shape_and_valid_odds():
    batches = list(SimulatedOddsFeed(seed=42, tick_seconds=0).stream(max_ticks=5))
    assert len(batches) == 5
    for batch in batches:
        assert len(batch) == len(EVENTS) * len(BOOKMAKERS)
        assert all(o.decimal_odds > 1.0 for s in batch for o in s.outcomes)


def test_every_book_keeps_a_margin():
    for batch in SimulatedOddsFeed(seed=3, tick_seconds=0).stream(max_ticks=200):
        for s in batch:
            assert sum(1 / o.decimal_odds for o in s.outcomes) >= MIN_BOOK_OVERROUND - 0.002


def test_sport_aliases():
    assert resolve_sport_key("NFL") == "americanfootball_nfl"
    assert resolve_sport_key("icehockey_nhl") == "icehockey_nhl"


def test_live_feed_requires_key(monkeypatch):
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        LiveOddsFeed()


def test_live_feed_parses_the_odds_api_payload():
    feed = LiveOddsFeed(api_key="test")
    raw = [{"id": "g1", "home_team": "Bills", "away_team": "Chiefs", "bookmakers": [
        {"title": "FanDuel", "markets": [
            {"key": "h2h", "outcomes": [{"name": "Chiefs", "price": 2.2}, {"name": "Bills", "price": 1.7}]},
            {"key": "spreads", "outcomes": [{"name": "Chiefs", "price": 1.9}]}]},
        {"title": "BetMGM", "markets": []}]}]
    snaps = feed._parse(raw)
    assert len(snaps) == 1
    s = snaps[0]
    assert (s.bookmaker, s.event_name, s.market) == ("FanDuel", "Chiefs @ Bills", "moneyline")
    assert [(o.name, o.decimal_odds) for o in s.outcomes] == [("Chiefs", 2.2), ("Bills", 1.7)]


if __name__ == "__main__":
    for batch in SimulatedOddsFeed(seed=42, tick_seconds=0).stream(max_ticks=2):
        for snap in batch:
            print(snap.bookmaker, snap.event_name, [(o.name, o.decimal_odds) for o in snap.outcomes])
