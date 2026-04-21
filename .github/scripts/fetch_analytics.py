"""Fetch Cloudflare Web Analytics (RUM) for the last 7 days.

Writes report.md (GitHub issue body) and report.html (artifact).
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

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

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


def fmt_day(date_str: str) -> str:
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{d.strftime('%b')} {d.day}"
    except ValueError:
        return date_str


# ---------------------------------------------------------------------------
# Country code → full name
# ---------------------------------------------------------------------------

_COUNTRY_NAMES: dict[str, str] = {
    "AF": "Afghanistan", "AL": "Albania", "DZ": "Algeria",
    "AR": "Argentina", "AU": "Australia", "AT": "Austria",
    "AZ": "Azerbaijan", "BE": "Belgium", "BR": "Brazil",
    "BG": "Bulgaria", "CA": "Canada", "CL": "Chile",
    "CN": "China", "CO": "Colombia", "HR": "Croatia",
    "CZ": "Czech Republic", "DK": "Denmark", "EG": "Egypt",
    "EE": "Estonia", "FI": "Finland", "FR": "France",
    "DE": "Germany", "GH": "Ghana", "GR": "Greece",
    "HK": "Hong Kong", "HU": "Hungary", "IN": "India",
    "ID": "Indonesia", "IE": "Ireland", "IL": "Israel",
    "IT": "Italy", "JP": "Japan", "KZ": "Kazakhstan",
    "KE": "Kenya", "KR": "South Korea", "LV": "Latvia",
    "LT": "Lithuania", "MY": "Malaysia", "MX": "Mexico",
    "MA": "Morocco", "NL": "Netherlands", "NZ": "New Zealand",
    "NG": "Nigeria", "NO": "Norway", "PK": "Pakistan",
    "PE": "Peru", "PH": "Philippines", "PL": "Poland",
    "PT": "Portugal", "RO": "Romania", "RU": "Russia",
    "SA": "Saudi Arabia", "RS": "Serbia", "SG": "Singapore",
    "SK": "Slovakia", "ZA": "South Africa", "ES": "Spain",
    "SE": "Sweden", "CH": "Switzerland", "TW": "Taiwan",
    "TH": "Thailand", "TN": "Tunisia", "TR": "Turkey",
    "UA": "Ukraine", "AE": "United Arab Emirates",
    "GB": "United Kingdom", "US": "United States",
    "UZ": "Uzbekistan", "VN": "Vietnam",
}


def country_name(code: str) -> str:
    if not code:
        return "Unknown"
    return _COUNTRY_NAMES.get(code.upper(), code)


# ---------------------------------------------------------------------------
# Browser name cleanup
# ---------------------------------------------------------------------------

_BROWSER_CLEAN = {
    "MobileSafari": "Mobile Safari",
    "ChromeMobile": "Chrome Mobile",
    "ChromeHeadless": "Chrome Headless",
    "SamsungBrowser": "Samsung Browser",
    "AndroidBrowser": "Android Browser",
    "YaBrowser": "Yandex Browser",
}


def clean_browser(name: str) -> str:
    return _BROWSER_CLEAN.get(name, name) if name else "Unknown"


# ---------------------------------------------------------------------------
# GraphQL query
# ---------------------------------------------------------------------------

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

payload = json.dumps({
    "query": QUERY,
    "variables": {
        "accountTag": CF_ACCOUNT_TAG,
        "siteTag": CF_SITE_TAG,
        "start": iso(start),
        "end": iso(now),
    },
}).encode()

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

total_pv = totals["count"]
total_visits = totals["sum"]["visits"]
days_with_data = len(acct["byDay"])
avg_per_day = round(total_pv / days_with_data) if days_with_data else 0
best_day_row = max(acct["byDay"], key=lambda r: r["count"], default=None)
best_day = fmt_day(best_day_row["dimensions"]["date"]) if best_day_row else "—"
best_day_pv = best_day_row["count"] if best_day_row else 0

# ---------------------------------------------------------------------------
# Markdown helpers
# ---------------------------------------------------------------------------


def extract_name(row: dict, key: str, name_fn=None, fallback: str = "Unknown") -> str:
    raw = row["dimensions"].get(key) or ""
    return (name_fn(raw) if name_fn else raw) or fallback


def pct(n: int, total: int) -> str:
    if not total:
        return "—"
    return f"{round(n / total * 100)}%"


def bar(n: int, total: int, width: int = 20) -> str:
    if not total:
        return ""
    filled = round(n / total * width)
    return "█" * filled + "░" * (width - filled)


def md_table_with_bar(rows: list[dict], label: str, key: str, name_fn=None) -> str:
    if not rows:
        return "_No data_\n"
    header = f"| {label} | | Pageviews | Share |\n| --- | --- | ---: | ---: |\n"
    lines = []
    for r in rows:
        name = extract_name(r, key, name_fn)
        pv = r["count"]
        lines.append(
            f"| {name} | `{bar(pv, total_pv)}` | {pv:,} | {pct(pv, total_pv)} |"
        )
    return header + "\n".join(lines) + "\n"


def md_table_simple(rows: list[dict], label: str, key: str, name_fn=None) -> str:
    if not rows:
        return "_No data_\n"
    header = f"| {label} | Pageviews | Visits |\n| --- | ---: | ---: |\n"
    lines = []
    for r in rows:
        name = extract_name(r, key, name_fn, fallback="Direct / unknown")
        lines.append(f"| {name} | {r['count']:,} | {r['sum']['visits']:,} |")
    return header + "\n".join(lines) + "\n"


def mermaid_xychart(rows: list[dict]) -> str:
    if not rows:
        return ""
    labels = []
    values = []
    max_val = 0
    for r in rows:
        labels.append(fmt_day(r["dimensions"]["date"]))
        count = r["count"]
        values.append(str(count))
        if count > max_val:
            max_val = count
    x_axis = ", ".join(f'"{l}"' for l in labels)
    return (
        "```mermaid\n"
        "xychart-beta\n"
        '    title "Daily pageviews"\n'
        f"    x-axis [{x_axis}]\n"
        f'    y-axis "Pageviews" 0 --> {max_val + 5}\n'
        f"    bar [{', '.join(values)}]\n"
        "```"
    )


def mermaid_pie(rows: list[dict], title: str, key: str, name_fn=None, top: int = 6) -> str:
    if not rows:
        return ""
    slices = []
    other = 0
    for i, r in enumerate(rows):
        name = extract_name(r, key, name_fn)
        if i < top:
            slices.append(f'    "{name}" : {r["count"]}')
        else:
            other += r["count"]
    if other:
        slices.append(f'    "Other" : {other}')
    entries = "\n".join(slices)
    return (
        "```mermaid\n"
        "pie showData\n"
        f'    title "{title}"\n'
        f"{entries}\n"
        "```"
    )


# ---------------------------------------------------------------------------
# Build markdown report
# ---------------------------------------------------------------------------

daily_chart = mermaid_xychart(acct["byDay"])
country_chart = mermaid_pie(acct["topCountries"], "Visitors by country", "countryName", country_name)
device_chart = mermaid_pie(acct["byDevice"], "Visitors by device", "deviceType", str.title)
browser_chart = mermaid_pie(acct["byBrowser"], "Visitors by browser", "userAgentBrowser", clean_browser)

md = f"""# Weekly analytics — {day(start)} → {day(now)}

---

## At a glance

| Metric | Value |
| --- | --- |
| Pageviews | **{total_pv:,}** |
| Visits | **{total_visits:,}** |
| Avg pageviews / day | **{avg_per_day:,}** |
| Best day | **{best_day}** ({best_day_pv:,} pageviews) |

---

## Pageviews by day

{daily_chart}

---

## Top countries

{country_chart}

{md_table_with_bar(acct['topCountries'], 'Country', 'countryName', country_name)}

---

## Devices

{device_chart}

{md_table_with_bar(acct['byDevice'], 'Device', 'deviceType', str.title)}

---

## Browsers

{browser_chart}

{md_table_with_bar(acct['byBrowser'], 'Browser', 'userAgentBrowser', clean_browser)}

---

## Top pages

{md_table_simple(acct['topPaths'], 'Path', 'requestPath')}

---

## Top referrers

{md_table_simple(acct['topReferers'], 'Referrer', 'refererHost')}

---

<sub>Generated by [weekly-analytics.yml](../../actions/workflows/weekly-analytics.yml) · {iso(now)}</sub>
"""

Path("report.md").write_text(md)

# ---------------------------------------------------------------------------
# HTML artifact
# ---------------------------------------------------------------------------


def html_bar(n: int, total: int) -> str:
    pct_val = round(n / total * 100) if total else 0
    return (
        '<div style="background:#eee;border-radius:4px;height:10px;width:160px;display:inline-block;vertical-align:middle">'
        f'<div style="background:#4f46e5;border-radius:4px;height:10px;width:{pct_val * 1.6:.0f}px"></div>'
        f'</div> <span style="color:#555;font-size:12px">{pct_val}%</span>'
    )


def html_table_bars(rows: list[dict], label: str, key: str, name_fn=None) -> str:
    if not rows:
        return "<p><em>No data</em></p>"
    header = (
        f'<tr><th align="left">{label}</th>'
        '<th align="left">Share</th>'
        '<th align="right">Pageviews</th></tr>'
    )
    body_rows = "".join(
        f"<tr>"
        f"<td>{escape(extract_name(r, key, name_fn))}</td>"
        f"<td>{html_bar(r['count'], total_pv)}</td>"
        f"<td align='right'>{r['count']:,}</td>"
        f"</tr>"
        for r in rows
    )
    return (
        '<table cellpadding="8" cellspacing="0" style="border-collapse:collapse;width:100%;font-size:14px">'
        f'<thead style="background:#f8f8f8;border-bottom:2px solid #e5e7eb">{header}</thead>'
        f"<tbody>{body_rows}</tbody></table>"
    )


def html_table_simple(rows: list[dict], label: str, key: str, name_fn=None) -> str:
    if not rows:
        return "<p><em>No data</em></p>"
    header = (
        f'<tr><th align="left">{label}</th>'
        '<th align="right">Pageviews</th>'
        '<th align="right">Visits</th></tr>'
    )
    body_rows = "".join(
        f"<tr>"
        f"<td>{escape(extract_name(r, key, name_fn, fallback='Direct / unknown'))}</td>"
        f"<td align='right'>{r['count']:,}</td>"
        f"<td align='right'>{r['sum']['visits']:,}</td>"
        f"</tr>"
        for r in rows
    )
    return (
        '<table cellpadding="8" cellspacing="0" style="border-collapse:collapse;width:100%;font-size:14px">'
        f'<thead style="background:#f8f8f8;border-bottom:2px solid #e5e7eb">{header}</thead>'
        f"<tbody>{body_rows}</tbody></table>"
    )


def html_sparkbar(rows: list[dict]) -> str:
    if not rows:
        return "<p><em>No data</em></p>"
    max_val = max(r["count"] for r in rows) or 1
    parts = []
    for r in rows:
        h = round(r["count"] / max_val * 80)
        label = fmt_day(r["dimensions"]["date"])
        parts.append(
            f'<div style="display:flex;flex-direction:column;align-items:center;gap:4px">'
            f'<span style="font-size:11px;color:#555">{r["count"]}</span>'
            f'<div style="width:32px;height:{h}px;background:#4f46e5;border-radius:4px 4px 0 0"></div>'
            f'<span style="font-size:11px;color:#888">{label}</span>'
            f'</div>'
        )
    return f'<div style="display:flex;align-items:flex-end;gap:8px;padding:16px 0">{"".join(parts)}</div>'


kpi_style = "background:#f0f0ff;border-radius:8px;padding:16px 24px;text-align:center;min-width:120px"
kpis = (
    f'<div style="display:flex;gap:16px;flex-wrap:wrap;margin:16px 0">'
    f'<div style="{kpi_style}"><div style="font-size:28px;font-weight:700;color:#4f46e5">{total_pv:,}</div><div style="color:#666;font-size:13px">Pageviews</div></div>'
    f'<div style="{kpi_style}"><div style="font-size:28px;font-weight:700;color:#4f46e5">{total_visits:,}</div><div style="color:#666;font-size:13px">Visits</div></div>'
    f'<div style="{kpi_style}"><div style="font-size:28px;font-weight:700;color:#4f46e5">{avg_per_day:,}</div><div style="color:#666;font-size:13px">Avg / day</div></div>'
    f'<div style="{kpi_style}"><div style="font-size:28px;font-weight:700;color:#4f46e5">{best_day}</div><div style="color:#666;font-size:13px">Best day</div></div>'
    f'</div>'
)

section_style = 'style="margin-top:32px"'
h2_style = 'style="font-size:18px;font-weight:600;border-bottom:2px solid #e5e7eb;padding-bottom:8px;margin-bottom:16px"'

html = f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Weekly Analytics {day(start)} – {day(now)}</title></head>
<body style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#111;max-width:760px;margin:0 auto;padding:24px">

  <h1 style="margin:0 0 4px;font-size:24px">Weekly analytics</h1>
  <p style="color:#666;margin:0 0 24px">{day(start)} → {day(now)}</p>

  {kpis}

  <div {section_style}>
    <h2 {h2_style}>Pageviews by day</h2>
    {html_sparkbar(acct['byDay'])}
  </div>

  <div {section_style}>
    <h2 {h2_style}>Top countries</h2>
    {html_table_bars(acct['topCountries'], 'Country', 'countryName', country_name)}
  </div>

  <div {section_style}>
    <h2 {h2_style}>Devices</h2>
    {html_table_bars(acct['byDevice'], 'Device', 'deviceType', str.title)}
  </div>

  <div {section_style}>
    <h2 {h2_style}>Browsers</h2>
    {html_table_bars(acct['byBrowser'], 'Browser', 'userAgentBrowser', clean_browser)}
  </div>

  <div {section_style}>
    <h2 {h2_style}>Top pages</h2>
    {html_table_simple(acct['topPaths'], 'Path', 'requestPath')}
  </div>

  <div {section_style}>
    <h2 {h2_style}>Top referrers</h2>
    {html_table_simple(acct['topReferers'], 'Referrer', 'refererHost')}
  </div>

  <p style="color:#aaa;font-size:12px;margin-top:40px;border-top:1px solid #eee;padding-top:16px">
    Generated {iso(now)} · weekly-analytics.yml
  </p>
</body></html>"""

Path("report.html").write_text(html)

# ---------------------------------------------------------------------------
# Workflow outputs
# ---------------------------------------------------------------------------

gh_output = os.environ.get("GITHUB_OUTPUT")
if gh_output:
    with open(gh_output, "a") as f:
        f.write(f"week_ending={day(now)}\n")
        f.write(f"pageviews={total_pv}\n")
        f.write(f"visits={total_visits}\n")

print(
    f"Wrote report.md & report.html — {total_pv:,} pageviews, "
    f"{total_visits:,} visits."
)
