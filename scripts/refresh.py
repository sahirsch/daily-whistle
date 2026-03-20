#!/usr/bin/env python3
"""Daily Whistle refresh — fetches real scores from ESPN, writes narrative data.json via Claude."""

import anthropic
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from urllib.request import urlopen
from urllib.error import URLError

# ── Date setup ────────────────────────────────────────────────────────────────
# Run at 6 AM Pacific. Morning edition covers last night's scores.
PDT = timezone(timedelta(hours=-7))          # PDT (UTC-7); covers Mar–Nov
now_pt        = datetime.now(PDT)
yesterday_pt  = now_pt - timedelta(days=1)
date_str      = yesterday_pt.strftime('%Y-%m-%d')   # scores date  (display)
date_api      = yesterday_pt.strftime('%Y%m%d')     # scores date  (ESPN API)
edition_date  = now_pt.strftime('%Y-%m-%d')         # today's date (masthead)
day_of_week   = now_pt.strftime('%A')

print(f"Edition: {edition_date} ({day_of_week}) | Covering scores from: {date_str}")

# ── Current issue number ──────────────────────────────────────────────────────
try:
    with open('data.json') as f:
        current = json.load(f)
    issue = current['meta']['issue'] + 1
except Exception:
    issue = 855
print(f"Issue #{issue}")

# ── ESPN score fetchers ───────────────────────────────────────────────────────
ESPN = "https://site.api.espn.com/apis/site/v2/sports"

def fetch_scores(sport_path: str, date: str) -> str:
    url = f"{ESPN}/{sport_path}/scoreboard?dates={date}"
    try:
        with urlopen(url, timeout=10) as r:
            data = json.loads(r.read())
        lines = []
        for ev in data.get('events', []):
            comp   = ev['competitions'][0]
            away_c = next(c for c in comp['competitors'] if c['homeAway'] == 'away')
            home_c = next(c for c in comp['competitors'] if c['homeAway'] == 'home')
            status = ev['status']['type']
            a = away_c['team']['abbreviation']
            h = home_c['team']['abbreviation']
            if status.get('completed'):
                winner = a if away_c.get('winner') else h
                lines.append(f"{a} {away_c['score']} @ {h} {home_c['score']} [FINAL, winner:{winner}]")
            elif status.get('name') == 'STATUS_IN_PROGRESS':
                clock  = ev['status'].get('displayClock', '')
                period = ev['status'].get('period', '')
                lines.append(f"{a} {away_c['score']} @ {h} {home_c['score']} [LIVE {clock} P{period}]")
            else:
                lines.append(f"{a} vs {h} [UPCOMING {ev.get('date','')}]")
        return '\n'.join(lines) if lines else "No games scheduled."
    except URLError as e:
        return f"Network error: {e}"
    except Exception as e:
        return f"Parse error: {e}"

nba = fetch_scores("basketball/nba", date_api)
nhl = fetch_scores("hockey/nhl",     date_api)
mlb = fetch_scores("baseball/mlb",   date_api)

print(f"\nNBA scores ({date_str}):\n{nba}")
print(f"\nNHL scores ({date_str}):\n{nhl}")
print(f"\nMLB scores ({date_str}):\n{mlb}")

# ── Claude prompt ─────────────────────────────────────────────────────────────
prompt = f"""You are the editor of The Daily Whistle, Issue #{issue} — {day_of_week}, {edition_date}, Morning Edition.

Here are the real scores from last night ({date_str}):

=== NBA ===
{nba}

=== NHL ===
{nhl}

=== MLB ===
{mlb}

Write a complete, compelling data.json. Editorial rules:
- Pick the 3–4 most narratively interesting games per league (star performances, playoff stakes, streaks, rivalries). Skip blowouts with no storyline.
- Top stories (2–3 items): the biggest cross-league narratives — records, injuries, playoff drama.
- League sections: 2 prose stories each. Bold key names/stats with <strong>Name</strong>. Short paragraphs.
- Ticker: same games as scoreboard, muted for finals, blue for upcoming.
- MLB in mid-March: treat as spring training context. If WBC games appear, they are primary.

Output ONLY raw JSON — no markdown fences, no explanation. Start with {{ and end with }}.

Required schema (fill with real data, maintain all field names exactly):
{{
  "meta": {{"date": "{edition_date}", "dayOfWeek": "{day_of_week}", "edition": "Morning", "issue": {issue}}},
  "ticker": [
    {{"text": "TEAM1 X · TEAM2 Y", "type": "final", "badge": "Final"}},
    {{"text": "TEAM1 vs TEAM2",    "type": "next",  "badge": "7 ET · ESPN"}}
  ],
  "scoreboard": {{
    "nba": {{
      "games": [
        {{"away": "OKC", "awayScore": 119, "home": "MEM", "homeScore": 104,
          "winner": "away", "status": "final", "tag": "Narrative note", "tagType": "context"}}
      ],
      "note": "One italic sentence of context or tonight's games"
    }},
    "nhl": {{"games": [], "note": "..."}},
    "wbc": {{"label": "MLB", "games": [], "note": "..."}}
  }},
  "topStories": [
    {{"kicker": "SHORT LABEL", "headline": "Compelling headline", "body": ["Para with <strong>Name</strong> and stats."]}}
  ],
  "sections": {{
    "nba": {{"stories": [
      {{"divider": "Scores & Standings", "headline": "...", "body": ["..."]}},
      {{"divider": "Injuries & News",    "headline": "...", "body": ["..."]}}
    ]}},
    "nhl": {{"stories": [{{"divider": "Playoff Race",   "headline": "...", "body": ["..."]}}]}},
    "mlb": {{"stories": [{{"headline": "...", "body": ["..."]}}]}}
  }}
}}

tagType values: "final" (gray) | "upcoming" (blue) | "live" (red) | "context" (gold) | "wbc" (green)
ticker type:   "final" (muted) | "next" (blue)  | "live" (green)
"""

# ── Call Claude ───────────────────────────────────────────────────────────────
client = anthropic.Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'])

print("\nCalling Claude for narrative writing...")
response = client.messages.create(
    model="claude-opus-4-5",
    max_tokens=8000,
    messages=[{"role": "user", "content": prompt}]
)

raw = response.content[0].text.strip()

# Strip accidental markdown fences
if raw.startswith("```"):
    parts = raw.split("```")
    raw = parts[1].lstrip("json").strip() if len(parts) > 1 else raw

# ── Parse & write ─────────────────────────────────────────────────────────────
try:
    data = json.loads(raw)
except json.JSONDecodeError as e:
    print(f"JSON parse error: {e}")
    print(f"Response preview:\n{raw[:500]}")
    sys.exit(1)

with open('data.json', 'w') as f:
    json.dump(data, f, indent=2)

print(f"\n✓ data.json updated — Issue #{data['meta']['issue']}, {data['meta']['date']}")
