"""
LLM analyst layer.

Takes a detected ArbitrageOpportunity (plain numeric data) and produces a
short, plain-English explanation of what the opportunity is, why it
exists, and what the risks/caveats are — the kind of "explain this to a
trader" summary layer that makes a numbers-only detector more usable in
a demo.

The LLM is a *narrator/explainer* here, not a decision-maker: it never
decides whether to place a bet or executes anything. All the actual
math (odds comparison, margin, stake sizing) is already done by
arbitrage.py before this module is ever called.

Requires an ANTHROPIC_API_KEY environment variable to call the real API.
Without one, falls back to a template-based summary so the demo still
runs end-to-end.
"""

from __future__ import annotations

import os
from typing import Dict, Optional

from models import ArbitrageOpportunity

SYSTEM_PROMPT = """You are a sports-trading analyst assistant. You will be given a \
detected cross-bookmaker arbitrage opportunity (odds that already exist publicly \
across different sportsbooks). Write a concise (3-5 sentence) plain-English summary \
for a trader: what the opportunity is, the guaranteed profit margin, and one or two \
practical caveats (e.g. odds can move before all legs are placed, books may limit \
accounts that arbitrage frequently, stake limits may apply). Do not recommend any \
action beyond what the data shows. Be factual and concise."""


def _template_summary(opportunity: ArbitrageOpportunity, stakes: Dict[str, float]) -> str:
    """Fallback summary with no LLM call, used when no API key is configured."""
    legs = "; ".join(
        f"{outcome} @ {quote.decimal_odds} on {quote.bookmaker} (stake ${stakes.get(outcome, 0):.2f})"
        for outcome, quote in opportunity.best_odds.items()
    )
    return (
        f"Arbitrage detected on {opportunity.event_name} ({opportunity.market}): "
        f"{legs}. Combined implied probability is "
        f"{opportunity.total_implied_probability * 100:.2f}%, leaving a guaranteed "
        f"{opportunity.profit_margin_pct:.2f}% margin if all legs are placed at these "
        f"prices. Caveats: odds can move before every leg is filled, and some books "
        f"restrict or limit accounts that place frequent arbitrage bets."
    )


def summarize_opportunity(
    opportunity: ArbitrageOpportunity,
    stakes: Dict[str, float],
    model: str = "claude-sonnet-5",
) -> str:
    """
    Returns a natural-language explanation of the arbitrage opportunity.
    Uses the Anthropic API if ANTHROPIC_API_KEY is set; otherwise falls
    back to a deterministic template so the demo still works out of the box.
    """
    api_key: Optional[str] = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return _template_summary(opportunity, stakes)

    try:
        import anthropic  # imported lazily so it's only required if a key is set

        client = anthropic.Anthropic(api_key=api_key)

        legs_desc = "\n".join(
            f"- {outcome}: {quote.decimal_odds} decimal odds on {quote.bookmaker}, "
            f"suggested stake ${stakes.get(outcome, 0):.2f}"
            for outcome, quote in opportunity.best_odds.items()
        )
        user_message = (
            f"Event: {opportunity.event_name}\n"
            f"Market: {opportunity.market}\n"
            f"Legs:\n{legs_desc}\n"
            f"Total implied probability: {opportunity.total_implied_probability * 100:.2f}%\n"
            f"Guaranteed profit margin: {opportunity.profit_margin_pct:.2f}%\n"
        )

        response = client.messages.create(
            model=model,
            max_tokens=300,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        return response.content[0].text.strip()
    except Exception as exc:  # noqa: BLE001 - demo-grade fallback on any API issue
        fallback = _template_summary(opportunity, stakes)
        return f"[LLM call failed ({exc}); showing template summary]\n{fallback}"
