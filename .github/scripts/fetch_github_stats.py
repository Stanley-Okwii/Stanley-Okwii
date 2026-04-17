#!/usr/bin/env python3
"""Fetch public GitHub stats via GraphQL and write JSON for docs/index.html.

Rank/grade (S / A+ / A / A- / B+ / B / B- / C+ / C) is a Python port of the
github-readme-stats scoring curve (MIT, Anurag Hazra): weighted contributions
scored against an exponential CDF with median thresholds, then bucketed by
percentile.
"""

import json
import math
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

USER_LOGIN = os.environ.get("GITHUB_USER", "Stanley-Okwii")
GRAPHQL_URL = "https://api.github.com/graphql"
OUTPUT = Path(__file__).resolve().parents[2] / "docs" / "data" / "github.json"

TOP_REPO_LIMIT = 3
TOP_LANG_LIMIT = 6

# github-readme-stats medians/weights.
RANK_MEDIANS = {
    "commits": 1000,
    "prs": 50,
    "issues": 25,
    "reviews": 2,
    "stars": 50,
    "followers": 10,
}
RANK_WEIGHTS = {
    "commits": 2,
    "prs": 3,
    "issues": 1,
    "reviews": 1,
    "stars": 4,
    "followers": 1,
}
RANK_THRESHOLDS = [
    ("S", 1),
    ("A+", 12.5),
    ("A", 25),
    ("A-", 37.5),
    ("B+", 50),
    ("B", 62.5),
    ("B-", 75),
    ("C+", 87.5),
    ("C", 100),
]

QUERY = """
query($login: String!) {
  user(login: $login) {
    login
    name
    avatarUrl
    url
    bio
    createdAt
    followers { totalCount }
    following { totalCount }
    publicRepos: repositories(ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC) { totalCount }
    pullRequests(states: [OPEN, MERGED, CLOSED]) { totalCount }
    issues(states: [OPEN, CLOSED]) { totalCount }
    repositoriesContributedTo(
      contributionTypes: [COMMIT, PULL_REQUEST, ISSUE, PULL_REQUEST_REVIEW],
      first: 1
    ) { totalCount }
    contributionsCollection {
      totalCommitContributions
      totalPullRequestContributions
      totalIssueContributions
      totalPullRequestReviewContributions
    }
    repositories(
      first: 100,
      ownerAffiliations: OWNER,
      isFork: false,
      privacy: PUBLIC,
      orderBy: {field: STARGAZERS, direction: DESC}
    ) {
      nodes {
        name
        description
        url
        stargazerCount
        pushedAt
        primaryLanguage { name color }
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


def graphql(token: str, login: str) -> dict:
    body = json.dumps({"query": QUERY, "variables": {"login": login}}).encode("utf-8")
    req = urllib.request.Request(
        GRAPHQL_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": f"{login}-stats-fetcher",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        if resp.status != 200:
            raise RuntimeError(f"GraphQL returned HTTP {resp.status}")
        payload = json.loads(resp.read().decode("utf-8"))
    if payload.get("errors"):
        raise RuntimeError(f"GraphQL errors: {payload['errors']}")
    user = payload.get("data", {}).get("user")
    if not user:
        raise RuntimeError(f"No user data returned for login={login!r}")
    return user


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


def top_repos(repos: list) -> list:
    result = []
    for repo in repos[:TOP_REPO_LIMIT]:
        result.append({
            "name": repo["name"],
            "description": repo.get("description") or "",
            "url": repo["url"],
            "stargazer_count": repo.get("stargazerCount", 0),
            "primary_language": (repo.get("primaryLanguage") or {}).get("name"),
        })
    return result


def total_stars(repos: list) -> int:
    return sum(r.get("stargazerCount", 0) for r in repos)


def compute_rank(totals: dict) -> dict:
    def cdf(value: float, median: float) -> float:
        if median <= 0:
            return 0.0
        return 1 - math.exp(-math.log(2) * value / median)

    total_weight = sum(RANK_WEIGHTS.values())
    score = sum(
        cdf(totals[key], RANK_MEDIANS[key]) * weight
        for key, weight in RANK_WEIGHTS.items()
    ) / total_weight
    percentile = round((1 - score) * 100, 1)
    level = RANK_THRESHOLDS[-1][0]
    for name, cutoff in RANK_THRESHOLDS:
        if percentile <= cutoff:
            level = name
            break
    return {"level": level, "percentile": percentile, "score": round(score, 4)}


def main() -> int:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        print("GITHUB_TOKEN is not set", file=sys.stderr)
        return 2

    try:
        user = graphql(token, USER_LOGIN)
    except (urllib.error.URLError, urllib.error.HTTPError, RuntimeError) as exc:
        print(f"GitHub API error: {exc}", file=sys.stderr)
        return 1

    repos = user["repositories"]["nodes"]
    contrib = user.get("contributionsCollection") or {}
    stars = total_stars(repos)

    totals = {
        "commits": contrib.get("totalCommitContributions", 0),
        "prs": (user.get("pullRequests") or {}).get("totalCount", 0),
        "prs_year": contrib.get("totalPullRequestContributions", 0),
        "issues": (user.get("issues") or {}).get("totalCount", 0),
        "issues_year": contrib.get("totalIssueContributions", 0),
        "reviews": contrib.get("totalPullRequestReviewContributions", 0),
        "stars": stars,
        "contributed_to": (user.get("repositoriesContributedTo") or {}).get("totalCount", 0),
        "followers": user["followers"]["totalCount"],
    }

    # Score against the commits median using rank-input keys only.
    rank_totals = {
        "commits": totals["commits"],
        "prs": totals["prs"],
        "issues": totals["issues"],
        "reviews": totals["reviews"],
        "stars": totals["stars"],
        "followers": totals["followers"],
    }
    rank = compute_rank(rank_totals)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "login": user["login"],
        "name": user.get("name"),
        "url": user["url"],
        "avatar_url": user.get("avatarUrl"),
        "bio": user.get("bio"),
        "created_at": user.get("createdAt") or "",
        "followers": user["followers"]["totalCount"],
        "following": user["following"]["totalCount"],
        "public_repos": user["publicRepos"]["totalCount"],
        "total_stars": stars,
        "contributions_past_year": {
            "commits": contrib.get("totalCommitContributions", 0),
            "pull_requests": contrib.get("totalPullRequestContributions", 0),
            "issues": contrib.get("totalIssueContributions", 0),
            "reviews": contrib.get("totalPullRequestReviewContributions", 0),
        },
        "totals": totals,
        "rank": rank,
        "top_languages": aggregate_languages(repos),
        "top_repos": top_repos(repos),
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"Wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
