"""Fetch Cloudflare Web Analytics (RUM) for the last 7 days.

Writes report.md (email attachment) and report.html (email body).
No third-party deps — uses stdlib urllib. Needs Python 3.9+.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from urllib import request, error

# --- Config -----------------------------------------------------------------

CF_API_TOKEN = os.environ.get("CF_API_TOKEN")
CF_ACCOUNT_TAG = os.environ.get("CF_ACCOUNT_TAG")
CF_SITE_TAG = os.environ.get("CF_SITE_TAG")

if not (CF_API_TOKEN and CF_ACCOUNT_TAG and CF_SITE_TAG):
    sys.exit("Missing CF_API_TOKEN, CF_ACCOUNT_TAG, or CF_SITE_TAG")

ENDPOINT = "https://api.cloudflare.com/client/v4/graphql"

now = datetime.now(timezone.utc).replace(microsecond=0)
start = now - timedelta(days=7)


def iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def day(d: datetime) -> str:
    return d.strftime("%Y-%m-%d")

# --- Query ------------------------------------------------------------------

QUERY = """
query Weekly($accountTag: String!, $siteTag: String!, $start: Time!, $end: Time!) {
  viewer {
    accounts(filter: { accountTag: $accountTag }) {
      totals: rumPageloadEventsAdaptiveGroups(
        filter: { siteTag: $siteTag, datetime_geq: $start, datetime_leq: $end }
        limit: 1
      ) { count sum { visits } }

      byDay: rumPageloadEventsAdaptiveGroups(
        filter: { siteTag: $siteTag, datetime_geq: $start, datetime_leq: $end }
        limit: 10
        orderBy: [date_ASC]
      ) { count sum { visits } dimensions { date } }

      topPaths: rumPageloadEventsAdaptiveGroups(
        filter: { siteTag: $siteTag, datetime_geq: $start, datetime_leq: $end }
        limit: 10
        orderBy: [count_DESC]
      ) { count sum { visits } dimensions { requestPath } }

      topReferers: rumPageloadEventsAdaptiveGroups(
        filter: { siteTag: $siteTag, datetime_geq: $start, datetime_leq: $end }
        limit: 10
        orderBy: [count_DESC]
      ) { count sum { visits } dimensions { refererHost } }

      topCountries: rumPageloadEventsAdaptiveGroups(
        filter: { siteTag: $siteTag, datetime_geq: $start, datetime_leq: $end }
        limit: 10
        orderBy: [count_DESC]
      ) { count sum { visits } dimensions { countryName } }

      byDevice: rumPageloadEventsAdaptiveGroups(
        filter: { siteTag: $siteTag, datetime_geq: $start, datetime_leq: $end }
        limit: 10
        orderBy: [count_DESC]
      ) { count sum { visits } dimensions { deviceType } }

      byBrowser: rumPageloadEventsAdaptiveGroups(
        filter: { siteTag: $siteTag, datetime_geq: $start, datetime_leq: $end }
        limit: 10
        orderBy: [count_DESC]
      ) { count sum { visits } dimensions { userAgentBrowser } }
    }
  }
}
"""

payload = json.dumps(
    {
        "query": QUERY,
        "variables": {
            "accountTag": CF_ACCOUNT_TAG,
            "siteTag": CF_SITE_TAG,
            "start": iso(start),
            "end": iso(now),
        },
    }
).encode()

req = request.Request(
    ENDPOINT,
    data=payload,
    headers={
        "Authorization": f"Bearer {CF_API_TOKEN}",
        "Content-Type": "application/json",
    },
    method="POST",
)

try:
    with request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read())
except error.HTTPError as e:
    sys.exit(f"HTTP {e.code}: {e.read().decode(errors='replace')}")
except error.URLError as e:
    sys.exit(f"Network error: {e}")

if body.get("errors"):
    sys.exit("GraphQL errors:\n" + json.dumps(body["errors"], indent=2))

acct = body["data"]["viewer"]["accounts"][0]
totals = (acct["totals"] or [{"count": 0, "sum": {"visits": 0}}])[0]

# --- Markdown (attachment) --------------------------------------------------


def md_table(rows: list[dict], label: str, key: str) -> str:
    if not rows:
        return "_no data_\n"
    header = f"| {label} | Pageviews | Visits |\n| --- | ---: | ---: |\n"
    lines = [
        f"| {r['dimensions'].get(key) or '(unknown)'} | {r['count']} | {r['sum']['visits']} |"
        for r in rows
    ]
    return header + "\n".join(lines) + "\n"


md = f"""# Weekly analytics — {day(start)} → {day(now)}

**Site tag:** `{CF_SITE_TAG}`

## Totals
- **Pageviews:** {totals['count']}
- **Visits:** {totals['sum']['visits']}

## By day
{md_table(acct['byDay'], 'Date', 'date')}
## Top paths
{md_table(acct['topPaths'], 'Path', 'requestPath')}
## Top referers
{md_table(acct['topReferers'], 'Referer', 'refererHost')}
## Top countries
{md_table(acct['topCountries'], 'Country', 'countryName')}
## By device
{md_table(acct['byDevice'], 'Device', 'deviceType')}
## By browser
{md_table(acct['byBrowser'], 'Browser', 'userAgentBrowser')}
"""

Path("report.md").write_text(md)

# --- HTML (email body) ------------------------------------------------------


def html_table(rows: list[dict], label: str, key: str) -> str:
    if not rows:
        return "<p><em>no data</em></p>"
    header = (
        f'<tr><th align="left">{label}</th>'
        '<th align="right">Pageviews</th>'
        '<th align="right">Visits</th></tr>'
    )
    body_rows = "".join(
        f"<tr><td>{escape(str(r['dimensions'].get(key) or '')) or '<em>(unknown)</em>'}</td>"
        f"<td align=\"right\">{r['count']}</td>"
        f"<td align=\"right\">{r['sum']['visits']}</td></tr>"
        for r in rows
    )
    return (
        '<table cellpadding="6" cellspacing="0" '
        'style="border-collapse:collapse;border:1px solid #ddd;font-size:14px">'
        f'<thead style="background:#f4f4f4">{header}</thead>'
        f"<tbody>{body_rows}</tbody></table>"
    )


html = f"""<!doctype html>
<html><body style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#222;max-width:720px;margin:0 auto;padding:16px">
  <h1 style="margin:0 0 8px">Weekly analytics</h1>
  <p style="color:#666;margin:0 0 16px">{day(start)} → {day(now)} · site <code>{escape(CF_SITE_TAG)}</code></p>

  <h2 style="margin-top:24px">Totals</h2>
  <p><strong>{totals['count']}</strong> pageviews · <strong>{totals['sum']['visits']}</strong> visits</p>

  <h2 style="margin-top:24px">By day</h2>
  {html_table(acct['byDay'], 'Date', 'date')}

  <h2 style="margin-top:24px">Top paths</h2>
  {html_table(acct['topPaths'], 'Path', 'requestPath')}

  <h2 style="margin-top:24px">Top referers</h2>
  {html_table(acct['topReferers'], 'Referer', 'refererHost')}

  <h2 style="margin-top:24px">Top countries</h2>
  {html_table(acct['topCountries'], 'Country', 'countryName')}

  <h2 style="margin-top:24px">By device</h2>
  {html_table(acct['byDevice'], 'Device', 'deviceType')}

  <h2 style="margin-top:24px">By browser</h2>
  {html_table(acct['byBrowser'], 'Browser', 'userAgentBrowser')}

  <p style="color:#999;font-size:12px;margin-top:32px">Generated by .github/workflows/weekly-analytics.yml</p>
</body></html>"""

Path("report.html").write_text(html)

# --- Workflow outputs -------------------------------------------------------

gh_output = os.environ.get("GITHUB_OUTPUT")
if gh_output:
    with open(gh_output, "a") as f:
        f.write(f"week_ending={day(now)}\n")
        f.write(f"pageviews={totals['count']}\n")
        f.write(f"visits={totals['sum']['visits']}\n")

print(
    f"Wrote report.md & report.html — {totals['count']} pageviews, "
    f"{totals['sum']['visits']} visits."
)
