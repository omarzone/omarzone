#!/usr/bin/env python3
"""Generate self-hosted GitHub stats cards (stats.svg, langs.svg) for the profile README.

Runs inside GitHub Actions with GITHUB_TOKEN. Only public data is used, so the
cards never depend on third-party hosted services.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import urllib.request
from collections import defaultdict
from html import escape

USER = os.environ.get("GH_USER", "omarzone")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
OUT_DIR = os.environ.get("OUT_DIR", "metrics")
IGNORED_LANGS = {"Papyrus", "CMake", "Blade", "SCSS", "CSS", "HTML", "Smarty", "Makefile", "Shell", "Objective-C", "Roff", "Batchfile", "PowerShell"}

BG = "#0D1117"
TITLE = "#36BCF7"
TEXT = "#c9d1d9"
MUTED = "#8b949e"
BORDER = "#30363d"


def api(url: str, data: dict | None = None) -> dict | list:
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "profile-stats",
    })
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, body, timeout=60) as r:
        return json.load(r)


def paginate(url: str) -> list:
    items: list = []
    page = 1
    while True:
        chunk = api(f"{url}{'&' if '?' in url else '?'}per_page=100&page={page}")
        if not chunk:
            return items
        items.extend(chunk)
        page += 1


def graphql(query: str, variables: dict) -> dict:
    res = api("https://api.github.com/graphql", {"query": query, "variables": variables})
    if "errors" in res:
        raise RuntimeError(res["errors"])
    return res["data"]


def fetch() -> dict:
    user = api(f"https://api.github.com/users/{USER}")
    # With a personal token (METRICS_TOKEN secret) owned by USER, private repos are included in the
    # aggregated language percentages. Repo names are never written to the cards.
    repos_url = f"https://api.github.com/users/{USER}/repos?type=owner"
    try:
        if api("https://api.github.com/user").get("login", "").lower() == USER.lower():
            repos_url = "https://api.github.com/user/repos?affiliation=owner,organization_member&visibility=all"
    except Exception:  # noqa: BLE001  (GITHUB_TOKEN has no /user endpoint)
        pass
    repos = [r for r in paginate(repos_url) if not r["fork"]]
    stars = sum(r["stargazers_count"] for r in repos)

    lang_bytes: dict[str, int] = defaultdict(int)
    for r in repos:
        try:
            for lang, n in api(r["languages_url"]).items():
                if lang not in IGNORED_LANGS:
                    lang_bytes[lang] += n
        except Exception as e:  # noqa: BLE001
            print(f"skip languages for {r['name']}: {e}", file=sys.stderr)

    now = dt.datetime.now(dt.timezone.utc)
    q = """
    query($login:String!, $from:DateTime!, $to:DateTime!) {
      user(login:$login) {
        contributionsCollection(from:$from, to:$to) {
          totalCommitContributions
          restrictedContributionsCount
          totalPullRequestContributions
          totalIssueContributions
          totalPullRequestReviewContributions
          contributionCalendar { totalContributions weeks { contributionDays { date contributionCount } } }
        }
      }
    }"""
    cc = graphql(q, {"login": USER, "from": (now - dt.timedelta(days=365)).isoformat(), "to": now.isoformat()})["user"]["contributionsCollection"]

    days = [d for w in cc["contributionCalendar"]["weeks"] for d in w["contributionDays"]]
    days.sort(key=lambda d: d["date"])
    best = cur = 0
    for d in days:
        cur = cur + 1 if d["contributionCount"] > 0 else 0
        best = max(best, cur)
    # current streak: count back from today (allow today to be empty)
    current = 0
    for d in reversed(days):
        if d["contributionCount"] > 0:
            current += 1
        elif d["date"] == now.date().isoformat():
            continue
        else:
            break

    return {
        "name": user.get("name") or USER,
        "followers": user["followers"],
        "public_repos": user["public_repos"],
        "repos": len(repos),
        "stars": stars,
        "commits": cc["totalCommitContributions"] + cc["restrictedContributionsCount"],
        "prs": cc["totalPullRequestContributions"],
        "issues": cc["totalIssueContributions"],
        "reviews": cc["totalPullRequestReviewContributions"],
        "contributions": cc["contributionCalendar"]["totalContributions"],
        "best_streak": best,
        "current_streak": current,
        "langs": dict(sorted(lang_bytes.items(), key=lambda kv: -kv[1])),
    }


def fmt(n: int) -> str:
    return f"{n/1000:.1f}k" if n >= 1000 else str(n)


def stats_card(s: dict) -> str:
    rows = [
        ("★", "Total stars earned", s["stars"]),
        ("▣", "Repositories (public + private)", s["repos"]),
        ("⎇", "Contributions (last year)", s["contributions"]),
        ("✎", "Commits (last year)", s["commits"]),
        ("⇄", "Pull requests", s["prs"]),
        ("!", "Issues", s["issues"]),
        ("🔥", "Best streak (days)", s["best_streak"]),
    ]
    w, h = 495, 60 + 28 * len(rows)
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="GitHub stats">',
        "<style>",
        f".t{{font:600 18px 'Segoe UI',Ubuntu,Sans-Serif;fill:{TITLE}}}",
        f".l{{font:400 14px 'Segoe UI',Ubuntu,Sans-Serif;fill:{TEXT}}}",
        f".v{{font:700 14px 'Segoe UI',Ubuntu,Sans-Serif;fill:{TEXT}}}",
        f".i{{font:700 14px 'Segoe UI',Ubuntu,Sans-Serif;fill:{TITLE}}}",
        ".r{opacity:0;animation:f .5s ease-in-out forwards}@keyframes f{to{opacity:1}}",
        "</style>",
        f'<rect x="0.5" y="0.5" width="{w-1}" height="{h-1}" rx="6" fill="{BG}" stroke="{BORDER}"/>',
        f'<text class="t" x="25" y="35">{escape(s["name"])}\'s GitHub Stats</text>',
    ]
    y = 68
    for k, (icon, label, val) in enumerate(rows):
        lines.append(f'<g class="r" style="animation-delay:{150 + k*120}ms">')
        lines.append(f'<text class="i" x="25" y="{y}">{escape(icon)}</text>')
        lines.append(f'<text class="l" x="55" y="{y}">{escape(label)}:</text>')
        lines.append(f'<text class="v" x="{w-25}" y="{y}" text-anchor="end">{fmt(val)}</text>')
        lines.append("</g>")
        y += 28
    lines.append("</svg>")
    return "\n".join(lines)


LANG_COLORS = {
    "PHP": "#4F5D95", "Java": "#b07219", "Dart": "#00B4AB", "TypeScript": "#3178c6", "JavaScript": "#f1e05a",
    "Python": "#3572A5", "C": "#555555", "C++": "#f34b7d", "Swift": "#F05138", "Kotlin": "#A97BFF", "Ruby": "#701516",
    "Go": "#00ADD8", "Rust": "#dea584", "Luau": "#00A2FF", "Astro": "#ff5a03", "Vue": "#41b883", "Objective-C": "#438eff",
}


def langs_card(s: dict, limit: int = 8) -> str:
    langs = list(s["langs"].items())[:limit]
    total = sum(n for _, n in langs) or 1
    w = 495
    bar_w = w - 50
    rows = (len(langs) + 1) // 2
    h = 95 + rows * 26
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="Most used languages">',
        "<style>",
        f".t{{font:600 18px 'Segoe UI',Ubuntu,Sans-Serif;fill:{TITLE}}}",
        f".l{{font:400 12px 'Segoe UI',Ubuntu,Sans-Serif;fill:{TEXT}}}",
        f".p{{font:400 12px 'Segoe UI',Ubuntu,Sans-Serif;fill:{MUTED}}}",
        ".b{transform-origin:25px 0;animation:g .8s ease-out forwards;transform:scaleX(0)}@keyframes g{to{transform:scaleX(1)}}",
        "</style>",
        f'<rect x="0.5" y="0.5" width="{w-1}" height="{h-1}" rx="6" fill="{BG}" stroke="{BORDER}"/>',
        '<text class="t" x="25" y="35">Most Used Languages</text>',
        f'<mask id="m"><rect x="25" y="55" width="{bar_w}" height="8" rx="4" fill="#fff"/></mask>',
        '<g mask="url(#m)" class="b">',
    ]
    x = 25.0
    for lang, n in langs:
        seg = bar_w * n / total
        lines.append(f'<rect x="{x:.1f}" y="55" width="{seg:.1f}" height="8" fill="{LANG_COLORS.get(lang, "#8b949e")}"/>')
        x += seg
    lines.append("</g>")
    for k, (lang, n) in enumerate(langs):
        col, row = k % 2, k // 2
        cx, cy = 25 + col * 235, 90 + row * 26
        pct = 100 * n / total
        lines.append(f'<circle cx="{cx+5}" cy="{cy-4}" r="5" fill="{LANG_COLORS.get(lang, "#8b949e")}"/>')
        lines.append(f'<text class="l" x="{cx+18}" y="{cy}">{escape(lang)}</text>')
        lines.append(f'<text class="p" x="{cx+18+8*len(lang)+8}" y="{cy}">{pct:.1f}%</text>')
    lines.append("</svg>")
    return "\n".join(lines)


def main() -> None:
    s = fetch()
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "stats.svg"), "w", encoding="utf-8") as f:
        f.write(stats_card(s))
    with open(os.path.join(OUT_DIR, "langs.svg"), "w", encoding="utf-8") as f:
        f.write(langs_card(s))
    print(json.dumps({k: v for k, v in s.items() if k != "langs"}, indent=2))
    print("langs:", list(s["langs"])[:8])


if __name__ == "__main__":
    main()
