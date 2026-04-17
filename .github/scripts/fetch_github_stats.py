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

TOP_REPO_LIMIT = 3
TOP_LANG_LIMIT = 6

QUERY = """
query($login: String!) {
  user(login: $login) {
    login
    name
    avatarUrl
    url
    bio
    followers { totalCount }
    following { totalCount }
    publicRepos: repositories(ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC) { totalCount }
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

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "login": user["login"],
        "name": user.get("name"),
        "url": user["url"],
        "avatar_url": user.get("avatarUrl"),
        "bio": user.get("bio"),
        "followers": user["followers"]["totalCount"],
        "following": user["following"]["totalCount"],
        "public_repos": user["publicRepos"]["totalCount"],
        "total_stars": total_stars(repos),
        "contributions_past_year": {
            "commits": contrib.get("totalCommitContributions", 0),
            "pull_requests": contrib.get("totalPullRequestContributions", 0),
            "issues": contrib.get("totalIssueContributions", 0),
            "reviews": contrib.get("totalPullRequestReviewContributions", 0),
        },
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
