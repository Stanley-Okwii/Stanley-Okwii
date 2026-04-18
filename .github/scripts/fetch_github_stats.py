#!/usr/bin/env python3
"""Fetch public GitHub stats via GraphQL and write JSON for docs/index.html."""

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

USER_LOGIN = os.environ.get("GITHUB_USER", "Stanley-Okwii")
GRAPHQL_URL = "https://api.github.com/graphql"
OUTPUT = Path(__file__).resolve().parents[2] / "docs" / "data" / "github.json"

TOP_LANG_LIMIT = 6

QUERY = """
query($login: String!) {
  user(login: $login) {
    login
    url
    createdAt
    publicRepos: repositories(ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC) { totalCount }
    privateRepos: repositories(ownerAffiliations: OWNER, isFork: false, privacy: PRIVATE) { totalCount }
    pullRequests(states: [OPEN, MERGED, CLOSED]) { totalCount }
    issues(states: [OPEN, CLOSED]) { totalCount }
    contributionsCollection {
      totalCommitContributions
      contributionYears
      contributionCalendar {
        totalContributions
        weeks {
          firstDay
          contributionDays { contributionCount }
        }
      }
    }
    repositories(
      first: 100,
      ownerAffiliations: OWNER,
      isFork: false,
      orderBy: {field: STARGAZERS, direction: DESC}
    ) {
      nodes {
        isPrivate
        stargazerCount
        languages(first: 20, orderBy: {field: SIZE, direction: DESC}) {
          edges {
            size
            node { name color }
          }
        }
      }
    }
  }
}
"""


def graphql(token: str, query: str, variables: dict) -> dict:
    body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    req = urllib.request.Request(
        GRAPHQL_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": f"{variables.get('login', 'stats')}-stats-fetcher",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        if resp.status != 200:
            raise RuntimeError(f"GraphQL returned HTTP {resp.status}")
        payload = json.loads(resp.read().decode("utf-8"))
    if payload.get("errors"):
        raise RuntimeError(f"GraphQL errors: {payload['errors']}")
    return payload.get("data") or {}


def fetch_user(token: str, login: str) -> dict:
    data = graphql(token, QUERY, {"login": login})
    user = data.get("user")
    if not user:
        raise RuntimeError(f"No user data returned for login={login!r}")
    return user


def fetch_all_time_contributions(token: str, login: str, years: list) -> int:
    if not years:
        return 0
    aliases = [
        f'y{y}: contributionsCollection(from: "{y}-01-01T00:00:00Z", to: "{y}-12-31T23:59:59Z") {{ contributionCalendar {{ totalContributions }} }}'
        for y in sorted(years)
    ]
    query = "query($login: String!) { user(login: $login) { " + " ".join(aliases) + " } }"
    data = graphql(token, query, {"login": login})
    user = data.get("user") or {}
    total = 0
    for year in years:
        block = user.get(f"y{year}") or {}
        cal = block.get("contributionCalendar") or {}
        total += cal.get("totalContributions", 0) or 0
    return total


def weekly_contributions(calendar: dict) -> list:
    result = []
    for week in (calendar.get("weeks") or []):
        count = sum((d.get("contributionCount") or 0) for d in (week.get("contributionDays") or []))
        result.append({"week_start": week.get("firstDay"), "count": count})
    return result


def active_days(calendar: dict) -> int:
    count = 0
    for week in (calendar.get("weeks") or []):
        for day in (week.get("contributionDays") or []):
            if (day.get("contributionCount") or 0) > 0:
                count += 1
    return count


def longest_streak(calendar: dict) -> int:
    best = current = 0
    for week in (calendar.get("weeks") or []):
        for day in (week.get("contributionDays") or []):
            if (day.get("contributionCount") or 0) > 0:
                current += 1
                if current > best:
                    best = current
            else:
                current = 0
    return best


def aggregate_languages(repos: list) -> list:
    sizes: dict = {}
    for repo in repos:
        for edge in (repo.get("languages", {}).get("edges") or []):
            node = edge.get("node") or {}
            name = node.get("name")
            if not name:
                continue
            entry = sizes.setdefault(name, {"size": 0, "color": node.get("color")})
            entry["size"] += edge.get("size", 0) or 0
    total = sum(e["size"] for e in sizes.values()) or 1
    items = [
        {
            "name": name,
            "size": value["size"],
            "color": value["color"],
            "percent": round(value["size"] / total * 100, 2),
        }
        for name, value in sizes.items()
    ]
    items.sort(key=lambda x: x["size"], reverse=True)
    return items[:TOP_LANG_LIMIT]


def total_stars(repos: list) -> int:
    return sum(r.get("stargazerCount", 0) for r in repos if not r.get("isPrivate"))


def main() -> int:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        print("GITHUB_TOKEN is not set", file=sys.stderr)
        return 2

    try:
        user = fetch_user(token, USER_LOGIN)
    except (urllib.error.URLError, urllib.error.HTTPError, RuntimeError) as exc:
        print(f"GitHub API error: {exc}", file=sys.stderr)
        return 1

    repos = (user.get("repositories") or {}).get("nodes") or []
    contrib = user.get("contributionsCollection") or {}
    calendar = contrib.get("contributionCalendar") or {}
    years = contrib.get("contributionYears") or []

    try:
        all_time = fetch_all_time_contributions(token, USER_LOGIN, years)
    except (urllib.error.URLError, urllib.error.HTTPError, RuntimeError) as exc:
        print(f"All-time contributions fetch failed: {exc}", file=sys.stderr)
        all_time = calendar.get("totalContributions", 0) or 0

    stars = total_stars(repos)
    commits = contrib.get("totalCommitContributions", 0)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "login": user["login"],
        "url": user["url"],
        "created_at": user.get("createdAt") or "",
        "public_repos": (user.get("publicRepos") or {}).get("totalCount", 0),
        "private_repos": (user.get("privateRepos") or {}).get("totalCount", 0),
        "total_stars": stars,
        "contributions_past_year": {
            "commits": commits,
            "total": calendar.get("totalContributions", 0) or 0,
        },
        "contributions_all_time": all_time,
        "contributions_weekly": weekly_contributions(calendar),
        "active_days_past_year": active_days(calendar),
        "longest_streak_past_year": longest_streak(calendar),
        "totals": {
            "commits": commits,
            "prs": (user.get("pullRequests") or {}).get("totalCount", 0),
            "issues": (user.get("issues") or {}).get("totalCount", 0),
            "stars": stars,
        },
        "top_languages": aggregate_languages(repos),
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"Wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
