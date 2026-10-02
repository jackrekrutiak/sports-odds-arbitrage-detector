"""
Live web dashboard for the arbitrage demo.

Runs a background polling loop (same detection logic as main.py) and
serves a browser page that shows current best odds and flashes
opportunities in/out as they appear and disappear, without needing the
terminal to stay in the foreground.

Run:
    python live_dashboard.py --source sim
    ODDS_API_KEY=... python live_dashboard.py --source live --sport nfl nba nhl mlb ncaaf --poll-seconds 20

Then open http://localhost:8765 in your browser.
"""

from __future__ import annotations

import argparse
import os
import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from arbitrage import detect_arbitrage, group_by_event, stake_distribution
from llm_analyst import summarize_opportunity
from simulator import SimulatedOddsFeed

STATE_LOCK = threading.Lock()
STATE = {
    "updated_at": None,
    "table": [],
    "opportunities": {},
}

# Rough sportsbook deep-link targets — bettor still places the bet themselves,
# this just gets them to the right site fast. Extend/adjust as needed.
BOOK_LINKS = {
    "DraftKings": "https://sportsbook.draftkings.com/",
    "FanDuel": "https://sportsbook.fanduel.com/",
    "BetMGM": "https://sports.betmgm.com/",
    "Caesars": "https://www.caesars.com/sportsbook-and-casino",
    "Pinnacle": "https://www.pinnacle.com/",
}


def build_table_rows(grouped):
    rows = []
    for event_id, snaps in grouped.items():
        best = {}
        for snap in snaps:
            for outcome in snap.outcomes:
                if outcome.name not in best or outcome.decimal_odds > best[outcome.name][0]:
                    best[outcome.name] = (outcome.decimal_odds, snap.bookmaker)
        event_name = snaps[0].event_name
        for outcome_name, (odds, book) in best.items():
            rows.append(
                {
                    "event": event_name,
                    "outcome": outcome_name,
                    "odds": round(odds, 3),
                    "book": book,
                    "implied_pct": round((1 / odds) * 100, 1),
                }
            )
    return rows


def polling_loop(feed, stake: float):
    summary_cache = {}
    for batch in feed.stream(max_ticks=None):
        grouped = group_by_event(batch)
        rows = build_table_rows(grouped)

        current_opps = {}
        for event_id, snaps in grouped.items():
            opp = detect_arbitrage(snaps)
            if opp is None:
                continue
            key = event_id
            stakes = stake_distribution(stake, opp)
            # The template summary is free, so it is rebuilt every tick and always matches the
            # prices shown. LLM summaries are cached and only rewritten when the books change,
            # to avoid an API call on every price tick.
            books = tuple(sorted((o, q.bookmaker) for o, q in opp.best_odds.items()))
            if not os.environ.get("ANTHROPIC_API_KEY") or summary_cache.get(key, (None,))[0] != books:
                summary_cache[key] = (books, summarize_opportunity(opp, stakes))
            current_opps[key] = {
                "event_name": opp.event_name,
                "margin_pct": round(opp.profit_margin_pct, 2),
                "legs": [
                    {
                        "outcome": outcome,
                        "odds": quote.decimal_odds,
                        "book": quote.bookmaker,
                        "stake": stakes.get(outcome, 0),
                        "link": BOOK_LINKS.get(quote.bookmaker, "#"),
                    }
                    for outcome, quote in opp.best_odds.items()
                ],
                "summary": summary_cache[key][1],
            }

        with STATE_LOCK:
            prev_opps = STATE["opportunities"]
            for key, data in current_opps.items():
                data["first_seen"] = prev_opps.get(key, {}).get(
                    "first_seen", datetime.now(timezone.utc).isoformat()
                )
            STATE["table"] = rows
            STATE["opportunities"] = current_opps
            STATE["updated_at"] = datetime.now(timezone.utc).isoformat()

        # stale summaries for opportunities no longer active get dropped
        # so a re-appearing opportunity gets a fresh summary later
        for key in list(summary_cache.keys()):
            if key not in current_opps:
                summary_cache.pop(key, None)


HTML_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Odds Arbitrage — Live</title>
<style>
  :root {
    --bg: #0b0e14; --panel: #131720; --border: #232938;
    --text: #e6e8ee; --muted: #8a92a6;
    --green: #2ecc71; --green-glow: rgba(46, 204, 113, 0.25);
    --red: #ff5c5c; --amber: #f0a84e;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: var(--bg); color: var(--text); padding: 24px;
  }
  h1 { font-size: 20px; margin: 0 0 4px; }
  .topbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; flex-wrap: wrap; gap: 8px; }
  .sub { color: var(--muted); font-size: 13px; margin-bottom: 20px; }
  .settings { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--muted); }
  .settings label { display: flex; align-items: center; gap: 6px; cursor: pointer; user-select: none; }
  .settings input[type=checkbox] { width: 16px; height: 16px; accent-color: var(--green); cursor: pointer; }
  .grid { display: grid; grid-template-columns: 1.1fr 1fr; gap: 20px; align-items: start; }
  @media (max-width: 900px) { .grid { grid-template-columns: 1fr; } }
  .panel { background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 16px; }
  .panel h2 { font-size: 14px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); margin: 0 0 12px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--border); }
  th { color: var(--muted); font-weight: 500; }
  .opp-card {
    border: 1px solid var(--border); border-radius: 10px; padding: 14px; margin-bottom: 12px;
    background: var(--panel); transition: box-shadow 0.3s, border-color 0.3s, opacity 0.3s;
  }
  .opp-card.flash {
    animation: flashIn 1.2s ease-out 2;
    border-color: var(--green);
  }
  .opp-card.leaving { animation: fadeOut 0.6s ease-in forwards; }
  .opp-card.closed { opacity: 0.55; border-color: var(--border); }
  @keyframes flashIn {
    0% { box-shadow: 0 0 0 0 var(--green-glow); }
    50% { box-shadow: 0 0 24px 4px var(--green-glow); }
    100% { box-shadow: 0 0 0 0 transparent; }
  }
  @keyframes fadeOut { to { opacity: 0; transform: scale(0.97); } }
  .opp-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; gap: 8px; }
  .opp-header-left { display: flex; align-items: center; gap: 8px; }
  .opp-event { font-weight: 600; font-size: 14px; }
  .opp-margin { color: var(--green); font-weight: 700; font-size: 15px; }
  .status-badge { font-size: 10.5px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; padding: 2px 7px; border-radius: 999px; }
  .status-badge.open { background: rgba(46,204,113,0.18); color: var(--green); }
  .status-badge.closed { background: rgba(255,92,92,0.15); color: var(--red); }
  .pin-btn { background: none; border: 1px solid var(--border); color: var(--muted); border-radius: 6px; padding: 3px 7px; font-size: 13px; cursor: pointer; line-height: 1; }
  .pin-btn.pinned { color: var(--amber); border-color: var(--amber); }
  .dismiss-btn { background: none; border: none; color: var(--muted); font-size: 16px; cursor: pointer; line-height: 1; padding: 2px 4px; }
  .dismiss-btn:hover { color: var(--text); }
  .opp-summary { color: var(--muted); font-size: 12.5px; margin: 6px 0 10px; line-height: 1.4; }
  .legs { display: flex; gap: 10px; flex-wrap: wrap; }
  .leg { background: #1a1f2c; border: 1px solid var(--border); border-radius: 8px; padding: 10px; font-size: 13px; flex: 1; min-width: 170px; display: flex; flex-direction: column; gap: 6px; }
  .leg-book { font-weight: 700; font-size: 13.5px; }
  .leg-odds { color: var(--text); }
  .leg-stake-row { display: flex; align-items: center; justify-content: space-between; gap: 6px; }
  .leg-stake { font-weight: 700; font-size: 15px; }
  .copy-btn {
    background: #232938; border: 1px solid var(--border); color: var(--text);
    border-radius: 6px; padding: 4px 8px; font-size: 11.5px; cursor: pointer; white-space: nowrap;
  }
  .copy-btn:hover { background: #2b3347; }
  .copy-btn.copied { background: var(--green); color: #06180d; border-color: var(--green); }
  .place-bet-btn {
    display: block; text-align: center; text-decoration: none;
    background: var(--green); color: #06180d; font-weight: 800; font-size: 15px;
    padding: 12px 10px; border-radius: 8px; margin-top: 2px;
    transition: transform 0.08s, background 0.15s;
  }
  .place-bet-btn:hover { background: #3ee585; transform: translateY(-1px); }
  .place-bet-btn:active { transform: translateY(0); }
  .empty { color: var(--muted); font-size: 13px; padding: 20px 0; text-align: center; }
  .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: var(--green); margin-right: 6px; animation: pulse 1.6s infinite; }
  @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.3; } }
</style>
</head>
<body>
  <div class="topbar">
    <h1><span class="dot"></span>Odds Arbitrage — Live</h1>
    <div class="settings">
      <label><input type="checkbox" id="secondMonitorToggle"> Open bets on 2nd monitor</label>
    </div>
  </div>
  <div class="sub" id="updated">connecting…</div>
  <div class="grid">
    <div class="panel">
      <h2>Live Best Odds</h2>
      <table id="odds-table"><thead>
        <tr><th>Event</th><th>Outcome</th><th>Odds</th><th>Book</th><th>Implied %</th></tr>
      </thead><tbody></tbody></table>
    </div>
    <div class="panel">
      <h2>Opportunities</h2>
      <div id="opps"></div>
    </div>
  </div>

<script>
let knownOpps = new Set();
let pinned = new Set();       // keys the user pinned to keep visible after they close
let lastSeenData = {};        // key -> last known opp data, so a closed-but-pinned card still shows numbers

const monitorToggle = document.getElementById('secondMonitorToggle');
monitorToggle.checked = localStorage.getItem('secondMonitor') === 'true';
monitorToggle.addEventListener('change', () => {
  localStorage.setItem('secondMonitor', monitorToggle.checked);
});

function openBetWindow(url) {
  const useSecondMonitor = localStorage.getItem('secondMonitor') === 'true';
  const width = 900, height = 900;
  let left = Math.round((window.screen.availWidth - width) / 2);
  let top = 40;
  if (useSecondMonitor) {
    // Push the window past the primary display's width so it lands on a
    // second monitor to the right, when one exists. Some browsers/OS combos
    // may still clamp this back onto the primary screen for security reasons
    // — if that happens, just drag the window over once and it'll remember.
    left = window.screen.availWidth + 40;
  }
  window.open(url, '_blank', `width=${width},height=${height},left=${left},top=${top},noopener`);
}

function copyToClipboard(text, btn) {
  navigator.clipboard.writeText(text).then(() => {
    const old = btn.textContent;
    btn.textContent = 'Copied!';
    btn.classList.add('copied');
    setTimeout(() => { btn.textContent = old; btn.classList.remove('copied'); }, 1100);
  });
}

function togglePin(key, btn) {
  if (pinned.has(key)) {
    pinned.delete(key);
    btn.classList.remove('pinned');
  } else {
    pinned.add(key);
    btn.classList.add('pinned');
  }
}

function dismissCard(key, card) {
  pinned.delete(key);
  delete lastSeenData[key];
  card.classList.add('leaving');
  setTimeout(() => card.remove(), 600);
}

async function poll() {
  try {
    const res = await fetch('/api/state', { cache: 'no-store' });
    const state = await res.json();
    render(state);
  } catch (e) {
    document.getElementById('updated').textContent = 'connection lost — retrying…';
  }
  setTimeout(poll, 1500);
}

function legHtml(key, l) {
  const stakeText = (l.stake.toFixed ? l.stake.toFixed(2) : l.stake);
  const copyPayload = `${l.book}: ${l.outcome} @ ${l.odds}, stake $${stakeText}`;
  return `
    <div class="leg">
      <div class="leg-book">${l.book}</div>
      <div class="leg-odds">${l.outcome} @ ${l.odds}</div>
      <div class="leg-stake-row">
        <span class="leg-stake">$${stakeText}</span>
        <button class="copy-btn" onclick="copyToClipboard('${copyPayload.replace(/'/g, "\\'")}', this)">Copy</button>
      </div>
      <a class="place-bet-btn" href="javascript:void(0)" onclick="openBetWindow('${l.link}')">Place Bet →</a>
    </div>`;
}

function cardHtml(key, opp, isOpen) {
  const pinClass = pinned.has(key) ? 'pinned' : '';
  const statusHtml = isOpen
    ? '<span class="status-badge open">Open</span>'
    : '<span class="status-badge closed">Closed</span>';
  return `
    <div class="opp-header">
      <div class="opp-header-left">
        <span class="opp-event">${opp.event_name}</span>
        ${statusHtml}
      </div>
      <div class="opp-header-left">
        <span class="opp-margin">+${opp.margin_pct}%</span>
        <button class="pin-btn ${pinClass}" onclick="togglePin('${key}', this)" title="Pin to keep visible after it closes">📌</button>
        <button class="dismiss-btn" onclick="dismissCard('${key}', this.closest('.opp-card'))" title="Dismiss">✕</button>
      </div>
    </div>
    <div class="opp-summary">${opp.summary}</div>
    <div class="legs">${opp.legs.map(l => legHtml(key, l)).join('')}</div>`;
}

function render(state) {
  document.getElementById('updated').textContent =
    state.updated_at ? ('last update: ' + new Date(state.updated_at).toLocaleTimeString()) : 'waiting for first update…';

  const tbody = document.querySelector('#odds-table tbody');
  tbody.innerHTML = '';
  (state.table || []).forEach(r => {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${r.event}</td><td>${r.outcome}</td><td>${r.odds}</td><td>${r.book}</td><td>${r.implied_pct}%</td>`;
    tbody.appendChild(tr);
  });

  const oppsEl = document.getElementById('opps');
  const currentKeys = new Set(Object.keys(state.opportunities || {}));

  for (const [key, opp] of Object.entries(state.opportunities || {})) {
    lastSeenData[key] = opp;
  }

  // cards that disappeared from the live feed: remove unless pinned,
  // in which case keep showing the last known numbers, marked Closed
  [...oppsEl.children].forEach(card => {
    const key = card.dataset.key;
    if (!currentKeys.has(key)) {
      if (pinned.has(key)) {
        card.classList.add('closed');
        card.innerHTML = cardHtml(key, lastSeenData[key], false);
      } else {
        card.classList.add('leaving');
        setTimeout(() => card.remove(), 600);
      }
    }
  });

  const willBeEmpty = currentKeys.size === 0 && [...oppsEl.children].every(c => pinned.has(c.dataset.key) === false && c.classList.contains('leaving'));
  if (oppsEl.children.length === 0) {
    oppsEl.innerHTML = '<div class="empty">No arbitrage opportunities right now.</div>';
  } else if (oppsEl.querySelector('.empty') && currentKeys.size > 0) {
    oppsEl.innerHTML = '';
  }

  for (const [key, opp] of Object.entries(state.opportunities || {})) {
    let card = oppsEl.querySelector(`[data-key="${key}"]`);
    const isNew = !knownOpps.has(key);
    if (!card) {
      card = document.createElement('div');
      card.className = 'opp-card';
      card.dataset.key = key;
      oppsEl.appendChild(card);
    }
    card.classList.remove('closed');
    card.innerHTML = cardHtml(key, opp, true);
    if (isNew) {
      card.classList.add('flash');
      setTimeout(() => card.classList.remove('flash'), 2500);
    }
  }
  knownOpps = currentKeys;
}

poll();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # quiet

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            body = HTML_PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/state":
            with STATE_LOCK:
                body = json.dumps(STATE).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


def main():
    parser = argparse.ArgumentParser(description="Live web dashboard for the arbitrage demo")
    parser.add_argument("--source", choices=["sim", "live"], default="sim")
    parser.add_argument("--sport", nargs="+", default=["nfl"],
                         help="leagues for --source live, e.g. --sport nfl nba nhl mlb ncaaf")
    parser.add_argument("--stake", type=float, default=1000.0)
    parser.add_argument("--poll-seconds", type=float, default=15.0,
                         help="how often to refresh odds (tick interval)")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    if args.source == "live":
        from live_feed import LiveOddsFeed
        feed = LiveOddsFeed(sports=args.sport, poll_seconds=args.poll_seconds)
    else:
        feed = SimulatedOddsFeed(seed=42, tick_seconds=args.poll_seconds)

    thread = threading.Thread(target=polling_loop, args=(feed, args.stake), daemon=True)
    thread.start()

    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    print(f"Dashboard running — open http://localhost:{args.port} in your browser")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
