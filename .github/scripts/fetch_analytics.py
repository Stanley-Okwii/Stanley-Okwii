"""Fetch Cloudflare Web Analytics (RUM) for the last 7 days.

Writes report.md (GitHub issue body) and report.html (artifact).
No third-party deps — uses stdlib urllib. Needs Python 3.9+.
"""

from __future__ import annotations

import json
import os
import re
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

_COUNTRY_FILE = Path(__file__).parent / "country_codes.json"
try:
    _COUNTRY_NAMES: dict[str, str] = json.loads(_COUNTRY_FILE.read_text())
except FileNotFoundError:
    _COUNTRY_NAMES = {}


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

      byCountryDay: rumPageloadEventsAdaptiveGroups(
        filter: { siteTag: $siteTag, datetime_geq: $start, datetime_leq: $end }
        limit: 1000
        orderBy: [count_DESC]
      ) { count dimensions { date countryName } }

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

_HEADERS = {
    "Authorization": f"Bearer {CF_API_TOKEN}",
    "Content-Type": "application/json",
}


def graphql(query: str, variables: dict | None = None, *, raise_on_errors: bool = True) -> dict:
    payload = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = request.Request(ENDPOINT, data=payload, headers=_HEADERS, method="POST")
    try:
        with request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read())
    except error.HTTPError as e:
        sys.exit(f"HTTP {e.code}: {e.read().decode(errors='replace')}")
    except error.URLError as e:
        sys.exit(f"Network error: {e}")
    if body.get("errors") and raise_on_errors:
        sys.exit("GraphQL errors:\n" + json.dumps(body["errors"], indent=2))
    return body


body = graphql(QUERY, {
    "accountTag": CF_ACCOUNT_TAG,
    "siteTag": CF_SITE_TAG,
    "start": iso(start),
    "end": iso(now),
})

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
# Sections by Core Web Vitals element events
# ---------------------------------------------------------------------------

_SECTIONS = ["hero", "stats", "skills", "experience", "projects", "education", "contact"]


def classify_section(selector: str) -> str:
    if not selector:
        return "Other"
    for token in re.findall(r"#([\w-]+)", selector):
        tok = token.lower()
        for s in _SECTIONS:
            if tok == s or tok.startswith(s + "-"):
                return s.title()
    if selector.lower().startswith(("html>body>nav", "nav>", "nav ")):
        return "Navigation"
    return "Other"


def _log(msg: str) -> None:
    print(f"[vitals] {msg}", file=sys.stderr)


_VITALS_KEYWORDS = ("element", "selector", "target")
_VITALS_FALLBACK_CANDIDATES = [
    "largestContentfulPaintElement",
    "cumulativeLayoutShiftElement",
    "interactionNextPaintElement",
    "cumulativeLayoutShiftTargetElement",
    "interactionNextPaintTargetElement",
    "element",
    "targetElement",
    "selector",
]


def _introspect_dimension_fields() -> list[str]:
    for type_name in (
        "RumWebVitalsEventsAdaptiveGroupsDimensions",
        "RumWebVitalsEventsAdaptiveDimensions",
    ):
        res = graphql(
            "query($n: String!){ __type(name:$n){ fields { name } } }",
            {"n": type_name},
            raise_on_errors=False,
        )
        t = ((res.get("data") or {}).get("__type")) or {}
        fields = [f["name"] for f in (t.get("fields") or [])]
        if fields:
            _log(f"introspection {type_name}: {len(fields)} dimensions")
            return fields
    _log("introspection returned no dimension fields (schema may disallow it)")
    return []


def _probe_field(fname: str) -> bool:
    probe = (
        "query Probe($accountTag: String!, $siteTag: String!, $start: Time!, $end: Time!) {"
        " viewer { accounts(filter: { accountTag: $accountTag }) {"
        f" rumWebVitalsEventsAdaptiveGroups("
        f"   filter: {{ siteTag: $siteTag, datetime_geq: $start, datetime_leq: $end }} limit: 1"
        f" ) {{ count dimensions {{ {fname} }} }}"
        " } } }"
    )
    res = graphql(
        probe,
        {
            "accountTag": CF_ACCOUNT_TAG,
            "siteTag": CF_SITE_TAG,
            "start": iso(start),
            "end": iso(now),
        },
        raise_on_errors=False,
    )
    return not res.get("errors")


def discover_vitals_element_fields() -> list[str]:
    override = os.environ.get("CF_VITALS_ELEMENT_FIELDS", "").strip()
    if override:
        fields = [f.strip() for f in override.split(",") if f.strip()]
        _log(f"override fields: {fields}")
        return fields

    all_dims = _introspect_dimension_fields()
    if all_dims:
        matches = [f for f in all_dims if any(k in f.lower() for k in _VITALS_KEYWORDS)]
        if matches:
            _log(f"keyword matches: {matches}")
            return matches
        _log(f"no keyword matches; available dims: {', '.join(all_dims[:30])}")

    _log("falling back to candidate probes")
    valid = [c for c in _VITALS_FALLBACK_CANDIDATES if _probe_field(c)]
    _log(f"probed candidates → valid: {valid}")
    return valid


vitals_fields = discover_vitals_element_fields()
section_counts: dict[str, int] = {}

if vitals_fields:
    sub_queries = "\n".join(
        f"""v{i}: rumWebVitalsEventsAdaptiveGroups(
            filter: {{ siteTag: $siteTag, datetime_geq: $start, datetime_leq: $end }}
            limit: 100
            orderBy: [count_DESC]
          ) {{ count dimensions {{ {fname} }} }}"""
        for i, fname in enumerate(vitals_fields)
    )
    vitals_query = (
        "query Vitals($accountTag: String!, $siteTag: String!, $start: Time!, $end: Time!) {"
        " viewer { accounts(filter: { accountTag: $accountTag }) { "
        + sub_queries
        + " } } }"
    )
    v_body = graphql(
        vitals_query,
        {
            "accountTag": CF_ACCOUNT_TAG,
            "siteTag": CF_SITE_TAG,
            "start": iso(start),
            "end": iso(now),
        },
        raise_on_errors=False,
    )
    if v_body.get("errors"):
        _log(f"vitals query errors: {json.dumps(v_body['errors'])[:500]}")
    v_accounts = (((v_body.get("data") or {}).get("viewer") or {}).get("accounts")) or []
    if v_accounts:
        v_acct = v_accounts[0]
        for i, fname in enumerate(vitals_fields):
            rows = v_acct.get(f"v{i}") or []
            _log(f"v{i} ({fname}): {len(rows)} rows")
            for row in rows:
                selector = (row.get("dimensions") or {}).get(fname) or ""
                section = classify_section(selector)
                section_counts[section] = section_counts.get(section, 0) + row["count"]

sections_ranked = sorted(section_counts.items(), key=lambda kv: kv[1], reverse=True)
sections_total = sum(section_counts.values())
_log(f"section totals: {dict(sections_ranked)} (sum={sections_total})")

# ---------------------------------------------------------------------------
# All-time history (persisted weekly snapshots)
# ---------------------------------------------------------------------------

_HISTORY_FILE = Path(__file__).parent / "analytics-history.json"

try:
    _history = json.loads(_HISTORY_FILE.read_text())
except (FileNotFoundError, json.JSONDecodeError):
    _history = {"weeks": []}

_weeks = [w for w in _history.get("weeks", []) if w.get("week_ending") != day(now)]
_weeks.append({
    "week_ending": day(now),
    "pageviews": total_pv,
    "visits": total_visits,
})
_weeks.sort(key=lambda w: w["week_ending"])
_history["weeks"] = _weeks
_HISTORY_FILE.write_text(json.dumps(_history, indent=2) + "\n")

alltime_pv = sum(w["pageviews"] for w in _weeks)
alltime_visits = sum(w["visits"] for w in _weeks)
alltime_weeks = len(_weeks)
alltime_first = _weeks[0]["week_ending"] if _weeks else "—"

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


def md_table_day(rows: list[dict]) -> str:
    if not rows:
        return "_No data_\n"
    max_pv = max(r["count"] for r in rows) or 1
    header = "| Date | | Pageviews |\n| --- | --- | ---: |\n"
    lines = [
        f"| {fmt_day(r['dimensions']['date'])} | `{bar(r['count'], max_pv)}` | {r['count']:,} |"
        for r in rows
    ]
    return header + "\n".join(lines) + "\n"


def _pivot_country_day(rows: list[dict], top_n: int = 8) -> tuple[list[str], list[tuple[str, dict[str, int], int]]]:
    """Returns (sorted_dates, [(country_label, {date: count}, total), ...])."""
    dates: set[str] = set()
    by_country: dict[str, dict[str, int]] = {}
    for r in rows:
        d = r["dimensions"]["date"]
        c = r["dimensions"].get("countryName") or ""
        dates.add(d)
        per_day = by_country.setdefault(c, {})
        per_day[d] = per_day.get(d, 0) + r["count"]
    ranked = sorted(
        ((country_name(c), per_day, sum(per_day.values())) for c, per_day in by_country.items()),
        key=lambda t: t[2],
        reverse=True,
    )[:top_n]
    return sorted(dates), ranked


def md_alltime_sparkline(weeks: list[dict]) -> str:
    if not weeks:
        return "_No history yet._\n"
    max_pv = max(w["pageviews"] for w in weeks) or 1
    header = "| Week ending | | Pageviews | Visits |\n| --- | --- | ---: | ---: |\n"
    lines = [
        f"| {w['week_ending']} | `{bar(w['pageviews'], max_pv)}` | {w['pageviews']:,} | {w['visits']:,} |"
        for w in weeks[-12:]
    ]
    return header + "\n".join(lines) + "\n"


def md_sections(ranked: list[tuple[str, int]], total: int, fields: list[str]) -> str:
    if not fields:
        return "_Could not discover Core Web Vitals element dimensions in Cloudflare's schema. Set `CF_VITALS_ELEMENT_FIELDS` to override._\n"
    if not ranked or not total:
        return f"_No Core Web Vitals element events for this window (queried: {', '.join(fields)})._\n"
    header = "| Section | | Events | Share |\n| --- | --- | ---: | ---: |\n"
    lines = [
        f"| {name} | `{bar(count, total)}` | {count:,} | {pct(count, total)} |"
        for name, count in ranked
    ]
    return header + "\n".join(lines) + "\n"


def md_country_day_matrix(rows: list[dict], top_n: int = 8) -> str:
    if not rows:
        return "_No data_\n"
    dates, ranked = _pivot_country_day(rows, top_n)
    head_days = " | ".join(fmt_day(d) for d in dates)
    header = f"| Country | {head_days} | Total |\n"
    sep = "| --- | " + " | ".join(["---:"] * len(dates)) + " | ---: |\n"
    lines = []
    for name, per_day, total in ranked:
        cells = " | ".join(f"{per_day.get(d, 0):,}" for d in dates)
        lines.append(f"| {name} | {cells} | **{total:,}** |")
    return header + sep + "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Build markdown report
# ---------------------------------------------------------------------------

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

## All time

| Metric | Value |
| --- | --- |
| Pageviews (all time) | **{alltime_pv:,}** |
| Visits (all time) | **{alltime_visits:,}** |
| Weeks tracked | **{alltime_weeks}** (since {alltime_first}) |

{md_alltime_sparkline(_weeks)}

---

## Pageviews by day

{md_table_day(acct['byDay'])}

---

## Top countries

{md_table_with_bar(acct['topCountries'], 'Country', 'countryName', country_name)}

---

## Views by country & day

{md_country_day_matrix(acct['byCountryDay'])}

---

## Devices

{md_table_with_bar(acct['byDevice'], 'Device', 'deviceType', str.title)}

---

## Browsers

{md_table_with_bar(acct['byBrowser'], 'Browser', 'userAgentBrowser', clean_browser)}

---

## Top pages

{md_table_simple(acct['topPaths'], 'Path', 'requestPath')}

---

## Sections by attention

<sub>Counts are Core Web Vitals events (LCP / CLS / INP) rolled up to each page section — a proxy for where users actually see and interact with content, not dwell seconds.</sub>

{md_sections(sections_ranked, sections_total, vitals_fields)}

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


def _html_table(header: str, body: str) -> str:
    return (
        '<table cellpadding="8" cellspacing="0" style="border-collapse:collapse;width:100%;font-size:14px">'
        f'<thead style="background:#f8f8f8;border-bottom:2px solid #e5e7eb">{header}</thead>'
        f"<tbody>{body}</tbody></table>"
    )


def html_table_bars(rows: list[dict], label: str, key: str, name_fn=None) -> str:
    if not rows:
        return "<p><em>No data</em></p>"
    header = (
        f'<tr><th align="left">{label}</th>'
        '<th align="left">Share</th>'
        '<th align="right">Pageviews</th></tr>'
    )
    body = "".join(
        f"<tr>"
        f"<td>{escape(extract_name(r, key, name_fn))}</td>"
        f"<td>{html_bar(r['count'], total_pv)}</td>"
        f"<td align='right'>{r['count']:,}</td>"
        f"</tr>"
        for r in rows
    )
    return _html_table(header, body)


def html_table_simple(rows: list[dict], label: str, key: str, name_fn=None) -> str:
    if not rows:
        return "<p><em>No data</em></p>"
    header = (
        f'<tr><th align="left">{label}</th>'
        '<th align="right">Pageviews</th>'
        '<th align="right">Visits</th></tr>'
    )
    body = "".join(
        f"<tr>"
        f"<td>{escape(extract_name(r, key, name_fn, fallback='Direct / unknown'))}</td>"
        f"<td align='right'>{r['count']:,}</td>"
        f"<td align='right'>{r['sum']['visits']:,}</td>"
        f"</tr>"
        for r in rows
    )
    return _html_table(header, body)


def html_alltime_bars(weeks: list[dict]) -> str:
    if not weeks:
        return "<p><em>No history yet.</em></p>"
    recent = weeks[-16:]
    max_pv = max(w["pageviews"] for w in recent) or 1
    parts = []
    for w in recent:
        h = round(w["pageviews"] / max_pv * 80)
        parts.append(
            '<div style="display:flex;flex-direction:column;align-items:center;gap:4px">'
            f'<span style="font-size:10px;color:#555">{w["pageviews"]}</span>'
            f'<div style="width:18px;height:{h}px;background:#4f46e5;border-radius:3px 3px 0 0"></div>'
            f'<span style="font-size:10px;color:#888">{escape(w["week_ending"][5:])}</span>'
            '</div>'
        )
    return f'<div style="display:flex;align-items:flex-end;gap:6px;padding:16px 0;overflow-x:auto">{"".join(parts)}</div>'


def html_sections(ranked: list[tuple[str, int]], total: int, fields: list[str]) -> str:
    if not fields:
        return "<p><em>Could not discover Core Web Vitals element dimensions in Cloudflare's schema.</em></p>"
    if not ranked or not total:
        return f"<p><em>No Core Web Vitals element events for this window (queried: {escape(', '.join(fields))}).</em></p>"
    header = (
        '<tr><th align="left">Section</th>'
        '<th align="left">Share</th>'
        '<th align="right">Events</th></tr>'
    )
    body = "".join(
        "<tr>"
        f"<td>{escape(name)}</td>"
        f"<td>{html_bar(count, total)}</td>"
        f"<td align='right'>{count:,}</td>"
        "</tr>"
        for name, count in ranked
    )
    return _html_table(header, body)


def html_country_day_matrix(rows: list[dict], top_n: int = 8) -> str:
    if not rows:
        return "<p><em>No data</em></p>"
    dates, ranked = _pivot_country_day(rows, top_n)
    header_cells = "".join(f'<th align="right">{escape(fmt_day(d))}</th>' for d in dates)
    header = (
        f'<tr><th align="left">Country</th>{header_cells}'
        '<th align="right">Total</th></tr>'
    )
    body = "".join(
        f"<tr><td>{escape(name)}</td>"
        + "".join(f'<td align="right">{per_day.get(d, 0):,}</td>' for d in dates)
        + f"<td align='right'><b>{total:,}</b></td></tr>"
        for name, per_day, total in ranked
    )
    return _html_table(header, body)


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
    <h2 {h2_style}>All time</h2>
    <div style="display:flex;gap:16px;flex-wrap:wrap;margin:0 0 12px">
      <div style="{kpi_style}"><div style="font-size:28px;font-weight:700;color:#4f46e5">{alltime_pv:,}</div><div style="color:#666;font-size:13px">Pageviews (all time)</div></div>
      <div style="{kpi_style}"><div style="font-size:28px;font-weight:700;color:#4f46e5">{alltime_visits:,}</div><div style="color:#666;font-size:13px">Visits (all time)</div></div>
      <div style="{kpi_style}"><div style="font-size:28px;font-weight:700;color:#4f46e5">{alltime_weeks}</div><div style="color:#666;font-size:13px">Weeks tracked</div></div>
    </div>
    {html_alltime_bars(_weeks)}
  </div>

  <div {section_style}>
    <h2 {h2_style}>Pageviews by day</h2>
    {html_sparkbar(acct['byDay'])}
  </div>

  <div {section_style}>
    <h2 {h2_style}>Top countries</h2>
    {html_table_bars(acct['topCountries'], 'Country', 'countryName', country_name)}
  </div>

  <div {section_style}>
    <h2 {h2_style}>Views by country & day</h2>
    {html_country_day_matrix(acct['byCountryDay'])}
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
    <h2 {h2_style}>Sections by attention</h2>
    <p style="color:#666;font-size:12px;margin:0 0 8px">Core Web Vitals events (LCP / CLS / INP) rolled up by page section — a proxy for attention, not dwell seconds.</p>
    {html_sections(sections_ranked, sections_total, vitals_fields)}
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
