"""LLM analyst tests (template path, no API key needed). Run with `pytest`, or `python test_llm.py` for a printed demo."""
from arbitrage import detect_arbitrage, group_by_event, stake_distribution
from llm_analyst import summarize_opportunity
from models import OddsSnapshot, Outcome


def test_template_summary_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    snaps = [OddsSnapshot("BetMGM", "e1", "Chiefs vs Bills", "moneyline", [Outcome("Chiefs", 2.314), Outcome("Bills", 1.8)]),
             OddsSnapshot("FanDuel", "e1", "Chiefs vs Bills", "moneyline", [Outcome("Chiefs", 1.9), Outcome("Bills", 2.243)])]
    opp = detect_arbitrage(snaps)
    text = summarize_opportunity(opp, stake_distribution(1000, opp))
    for part in ("Chiefs vs Bills", "BetMGM", "FanDuel", "$492.21", "$507.79", "87.80%", "12.20%"):
        assert part in text


if __name__ == "__main__":
    from simulator import SimulatedOddsFeed

    batch = next(SimulatedOddsFeed(seed=42, tick_seconds=0).stream(max_ticks=1))
    for _, snaps in group_by_event(batch).items():
        opp = detect_arbitrage(snaps)
        if opp:
            print(summarize_opportunity(opp, stake_distribution(1000, opp)), "\n")
