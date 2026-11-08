"""Generate the GitHub stats cards shown in the profile README.

Writes assets/streak.svg and assets/languages.svg. Runs in GitHub Actions
with the built-in GITHUB_TOKEN, so the cards never depend on a third-party
service being up.
"""

import datetime as dt
import json
import os
import sys
import urllib.request
from html import escape

USER = os.environ.get("GH_USER", "aekankpatel")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
OUT = os.environ.get("OUT_DIR", "assets")

BG_FROM, BG_TO = "#0f2027", "#2c5364"
ACCENT, GREEN, MUTED, WHITE = "#38BDF8", "#22C55E", "#94A3B8", "#FFFFFF"
FONT = "'Segoe UI',Ubuntu,'Helvetica Neue',Arial,sans-serif"

EXCLUDED_LANGS = {"HTML", "CSS", "SCSS", "Shell", "Batchfile", "Makefile",
                  "Dockerfile", "Procfile", "PowerShell"}
LANG_COLORS = {
    "Python": "#3572A5", "Jupyter Notebook": "#DA5B0B", "JavaScript": "#F1E05A",
    "TypeScript": "#3178C6", "R": "#198CE7", "TeX": "#3D6117", "Java": "#B07219",
    "C++": "#F34B7D", "C": "#555555", "Go": "#00ADD8", "SQL": "#E38C00",
    "PLpgSQL": "#336790", "MATLAB": "#E16737", "Rust": "#DEA584",
}


def _request(url, data=None):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "profile-stats"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def rest(path):
    return _request(f"https://api.github.com{path}")


def graphql(query, variables):
    body = json.dumps({"query": query, "variables": variables}).encode()
    result = _request("https://api.github.com/graphql", data=body)
    if "errors" in result:
        raise RuntimeError(result["errors"])
    return result["data"]


def card(width, height, body, title):
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <title>{escape(title)}</title>
  <defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="{BG_FROM}"/><stop offset="1" stop-color="{BG_TO}"/>
  </linearGradient></defs>
  <style>
    text {{ font-family: {FONT}; }}
    .fade {{ opacity: 0; animation: fade .8s ease-out forwards; }}
    @keyframes fade {{ to {{ opacity: 1; }} }}
  </style>
  <rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="12" fill="url(#bg)" stroke="{BG_TO}"/>
{body}
</svg>
"""


# ---------------------------------------------------------------- languages
def language_scores():
    """Each repo counts once, split across its languages by share of bytes.

    This keeps one huge notebook or dataset dump from drowning out
    everything else.
    """
    scores = {}
    page = 1
    while True:
        repos = rest(f"/users/{USER}/repos?per_page=100&type=owner&page={page}")
        if not repos:
            break
        for repo in repos:
            if repo["fork"] or repo["name"].lower() == USER.lower():
                continue
            langs = {k: v for k, v in rest(f"/repos/{USER}/{repo['name']}/languages").items()
                     if k not in EXCLUDED_LANGS}
            total = sum(langs.values())
            for lang, size in langs.items():
                scores[lang] = scores.get(lang, 0) + size / total
        page += 1
    return scores


def languages_svg(scores, top=6):
    grand = sum(scores.values()) or 1
    ranked = [kv for kv in sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
              if kv[1] / grand >= 0.01][:top]
    total = sum(v for _, v in ranked) or 1
    W, H = 380, 170
    bar_x, bar_y, bar_w = 25, 55, W - 50
    parts = [f'  <text x="25" y="35" fill="{ACCENT}" font-size="17" font-weight="700">Most Used Languages</text>',
             f'  <clipPath id="bar"><rect x="{bar_x}" y="{bar_y}" width="{bar_w}" height="10" rx="5"/></clipPath>',
             '  <g clip-path="url(#bar)">']
    x = bar_x
    for lang, score in ranked:
        w = bar_w * score / total
        color = LANG_COLORS.get(lang, MUTED)
        parts.append(f'    <rect x="{x:.2f}" y="{bar_y}" width="{w + 0.5:.2f}" height="10" fill="{color}"/>')
        x += w
    parts.append("  </g>")
    for i, (lang, score) in enumerate(ranked):
        col, row = i % 2, i // 2
        lx = 25 + col * 175
        ly = 92 + row * 26
        color = LANG_COLORS.get(lang, MUTED)
        pct = 100 * score / total
        parts.append(
            f'  <g class="fade" style="animation-delay:{0.15 * i:.2f}s">'
            f'<circle cx="{lx + 5}" cy="{ly - 4}" r="5" fill="{color}"/>'
            f'<text x="{lx + 16}" y="{ly}" fill="{WHITE}" font-size="13">{escape(lang)} '
            f'<tspan fill="{MUTED}">{pct:.1f}%</tspan></text></g>')
    return card(W, H, "\n".join(parts), "Most used languages")


# ------------------------------------------------------------------- streak
CAL_QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar { weeks { contributionDays { date contributionCount } } }
    }
  }
}"""


def contribution_days():
    created = graphql("query($login:String!){user(login:$login){createdAt}}",
                      {"login": USER})["user"]["createdAt"]
    start = dt.datetime.fromisoformat(created.replace("Z", "+00:00"))
    now = dt.datetime.now(dt.timezone.utc)
    days = {}
    cursor = start
    while cursor < now:
        end = min(cursor + dt.timedelta(days=365), now)
        data = graphql(CAL_QUERY, {"login": USER, "from": cursor.isoformat(), "to": end.isoformat()})
        for week in data["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]:
            for day in week["contributionDays"]:
                days[dt.date.fromisoformat(day["date"])] = day["contributionCount"]
        cursor = end
    return days


def streak_stats(days, today):
    dates = sorted(d for d in days if d <= today)
    total = sum(days[d] for d in dates)
    first = next((d for d in dates if days[d] > 0), today)

    longest, longest_range, run, run_start = 0, (today, today), 0, None
    for d in dates:
        if days[d] > 0:
            run_start = d if run == 0 else run_start
            run += 1
            if run > longest:
                longest, longest_range = run, (run_start, d)
        else:
            run = 0

    # Today with no contributions yet doesn't break the streak.
    cur_end = today if days.get(today, 0) > 0 else today - dt.timedelta(days=1)
    current, d = 0, cur_end
    while days.get(d, 0) > 0:
        current += 1
        d -= dt.timedelta(days=1)
    cur_range = (d + dt.timedelta(days=1), cur_end) if current else (today, today)
    return total, first, current, cur_range, longest, longest_range


def fmt(d):
    return d.strftime("%b %-d, %Y")


def fmt_range(r):
    a, b = r
    return fmt(a) if a == b else f"{a.strftime('%b %-d')} – {fmt(b)}"


def streak_svg(total, first, current, cur_range, longest, longest_range, today):
    W, H = 495, 170
    cols = [82, W // 2, W - 82]
    parts = [
        f'  <line x1="165" y1="32" x2="165" y2="138" stroke="{MUTED}" stroke-opacity="0.3"/>',
        f'  <line x1="330" y1="32" x2="330" y2="138" stroke="{MUTED}" stroke-opacity="0.3"/>',
        # total
        f'  <g class="fade"><text x="{cols[0]}" y="80" text-anchor="middle" fill="{WHITE}" font-size="30" font-weight="700">{total:,}</text>'
        f'<text x="{cols[0]}" y="112" text-anchor="middle" fill="{ACCENT}" font-size="14" font-weight="600">Total Contributions</text>'
        f'<text x="{cols[0]}" y="135" text-anchor="middle" fill="{MUTED}" font-size="11">{fmt(first)} – Present</text></g>',
        # current, with ring
        f'  <circle cx="{cols[1]}" cy="68" r="38" fill="none" stroke="{GREEN}" stroke-width="5" stroke-dasharray="239" stroke-dashoffset="239" stroke-linecap="round" transform="rotate(-90 {cols[1]} 68)">'
        f'<animate attributeName="stroke-dashoffset" from="239" to="0" dur="1.2s" fill="freeze"/></circle>',
        f'  <text x="{cols[1]}" y="35" text-anchor="middle" font-size="18">🔥</text>',
        f'  <g class="fade" style="animation-delay:.3s"><text x="{cols[1]}" y="80" text-anchor="middle" fill="{WHITE}" font-size="30" font-weight="700">{current}</text>'
        f'<text x="{cols[1]}" y="128" text-anchor="middle" fill="{GREEN}" font-size="14" font-weight="700">Current Streak</text>'
        f'<text x="{cols[1]}" y="148" text-anchor="middle" fill="{MUTED}" font-size="11">{fmt_range(cur_range) if current else "Starts today"}</text></g>',
        # longest
        f'  <g class="fade" style="animation-delay:.6s"><text x="{cols[2]}" y="80" text-anchor="middle" fill="{WHITE}" font-size="30" font-weight="700">{longest}</text>'
        f'<text x="{cols[2]}" y="112" text-anchor="middle" fill="{ACCENT}" font-size="14" font-weight="600">Longest Streak</text>'
        f'<text x="{cols[2]}" y="135" text-anchor="middle" fill="{MUTED}" font-size="11">{fmt_range(longest_range) if longest else "—"}</text></g>',
    ]
    return card(W, H, "\n".join(parts), f"{total} contributions, {current} day current streak, {longest} day longest streak")


def write(name, svg):
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"wrote {OUT}/{name}")


def main():
    failed = False
    try:
        write("languages.svg", languages_svg(language_scores()))
    except Exception as exc:  # keep the previous card if the API hiccups
        print(f"languages card failed: {exc}", file=sys.stderr)
        failed = True
    try:
        today = dt.datetime.now(dt.timezone.utc).date()
        write("streak.svg", streak_svg(*streak_stats(contribution_days(), today), today))
    except Exception as exc:
        print(f"streak card failed: {exc}", file=sys.stderr)
        failed = True
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
