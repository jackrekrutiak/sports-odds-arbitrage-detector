"""Arbitrage math tests. Run with `pytest`, or `python test_arbitrage.py` for a printed demo."""
import pytest

from arbitrage import best_odds_per_outcome, detect_arbitrage, group_by_event, stake_distribution
from models import OddsSnapshot, Outcome


def snap(book, home, away, event="e1"):
    return OddsSnapshot(bookmaker=book, event_id=event, event_name="Chiefs vs Bills", market="moneyline",
                        outcomes=[Outcome("Chiefs", home), Outcome("Bills", away)])


def test_best_odds_picks_highest_price_and_book():
    best = best_odds_per_outcome([snap("A", 2.10, 1.80), snap("B", 1.95, 2.05)])
    assert best["Chiefs"].bookmaker == "A" and best["Chiefs"].decimal_odds == 2.10
    assert best["Bills"].bookmaker == "B" and best["Bills"].decimal_odds == 2.05


def test_detects_arbitrage_when_implied_probability_under_100():
    opp = detect_arbitrage([snap("A", 2.314, 1.80), snap("B", 1.90, 2.243)])
    assert opp is not None
    assert opp.total_implied_probability == pytest.approx(1 / 2.314 + 1 / 2.243)
    assert opp.profit_margin_pct == pytest.approx((1 - opp.total_implied_probability) * 100)
    assert round(opp.profit_margin_pct, 1) == 12.2


def test_no_arbitrage_when_books_agree():
    assert detect_arbitrage([snap("A", 1.91, 1.91), snap("B", 1.90, 1.92)]) is None
    assert detect_arbitrage([]) is None


def test_stakes_sum_to_total_and_equalise_payout():
    opp = detect_arbitrage([snap("A", 2.314, 1.80), snap("B", 1.90, 2.243)])
    stakes = stake_distribution(1000, opp)
    assert sum(stakes.values()) == pytest.approx(1000, abs=0.02)
    assert stakes == {"Chiefs": 492.21, "Bills": 507.79}
    payouts = [stakes[o] * q.decimal_odds for o, q in opp.best_odds.items()]
    assert max(payouts) - min(payouts) < 0.05
    assert min(payouts) > 1000


def test_group_by_event():
    g = group_by_event([snap("A", 2, 2, "e1"), snap("B", 2, 2, "e2"), snap("C", 2, 2, "e1")])
    assert {k: len(v) for k, v in g.items()} == {"e1": 2, "e2": 1}


def test_invalid_odds_rejected():
    with pytest.raises(ValueError):
        _ = Outcome("X", 1.0).implied_probability


if __name__ == "__main__":
    from simulator import SimulatedOddsFeed

    batch = next(SimulatedOddsFeed(seed=42, tick_seconds=0).stream(max_ticks=1))
    for _, snaps in group_by_event(batch).items():
        opp = detect_arbitrage(snaps)
        if opp:
            print(f"ARBITRAGE on {opp.event_name}: margin {opp.profit_margin_pct:.2f}%")
            for outcome, quote in opp.best_odds.items():
                print(f"  {outcome}: {quote.decimal_odds} on {quote.bookmaker}")
            print("  Stakes for $1000:", stake_distribution(1000, opp))
        else:
            print(f"No arbitrage on {snaps[0].event_name}")
