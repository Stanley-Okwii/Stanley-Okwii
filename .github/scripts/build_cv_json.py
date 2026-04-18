#!/usr/bin/env python3
"""Read the rendercv source YAML and emit docs/data/cv.json for the portfolio site."""

import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src" / "templates" / "achievement.yaml"
OUTPUT = ROOT / "docs" / "data" / "cv.json"

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
         "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

MD_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
SAFE_SCHEMES = ("http:", "https:", "mailto:", "tel:")


def md_to_html(text):
    if text is None:
        return ""
    escaped = html.escape(str(text), quote=False)

    def replace(m):
        url = m.group(2)
        if not any(url.lower().lstrip().startswith(s) for s in SAFE_SCHEMES):
            url = "#"
        return f'<a href="{html.escape(url, quote=True)}" rel="noopener">{html.escape(m.group(1), quote=False)}</a>'

    return MD_LINK.sub(replace, escaped)


def fmt_date(value):
    if not value:
        return ""
    s = str(value).strip()
    if s.lower() == "present":
        return "Present"
    m = re.match(r"^(\d{4})-(\d{1,2})(?:-\d{1,2})?$", s)
    if not m:
        return s
    year, month = int(m.group(1)), int(m.group(2))
    if 1 <= month <= 12:
        return f"{MONTHS[month - 1]} {year}"
    return str(year)


def period(start, end):
    a, b = fmt_date(start), fmt_date(end)
    if a and b:
        return f"{a} — {b}"
    return a or b


def main() -> int:
    if not SOURCE.exists():
        print(f"CV source not found at {SOURCE}", file=sys.stderr)
        return 1
    with SOURCE.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    cv = data.get("cv") or {}
    sections = cv.get("sections") or {}

    summary_items = sections.get("Summary") or sections.get("summary") or []
    summary = " ".join(md_to_html(s) for s in summary_items) if isinstance(summary_items, list) else md_to_html(summary_items)

    socials = {s.get("network", "").lower(): s.get("username", "") for s in (cv.get("social_networks") or [])}
    linkedin = socials.get("linkedin")
    github = socials.get("github")

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "name": cv.get("name") or "",
        "location": cv.get("location") or "",
        "summary": summary,
        "contact": {
            "email": cv.get("email") or "",
            "phone": cv.get("phone") or "",
            "location": cv.get("location") or "",
            "linkedin_url": f"https://www.linkedin.com/in/{linkedin}/" if linkedin else "",
            "linkedin_handle": linkedin or "",
            "github_url": f"https://github.com/{github}" if github else "",
            "github_handle": github or "",
        },
        "skills": [
            {"label": s.get("label", ""), "details": s.get("details", "")}
            for s in (sections.get("skills") or [])
        ],
        "experience": [
            {
                "position": md_to_html(item.get("position") or ""),
                "company": md_to_html(item.get("company") or ""),
                "period": period(item.get("start_date"), item.get("end_date")),
                "location": str(item.get("location") or ""),
                "summary": md_to_html(item.get("summary") or ""),
                "highlights": [md_to_html(h) for h in (item.get("highlights") or [])],
            }
            for item in (sections.get("experience") or [])
        ],
        "projects": [
            {
                "name": md_to_html(item.get("name") or ""),
                "role": md_to_html(item.get("summary") or ""),
                "period": period(item.get("start_date"), item.get("end_date")),
                "location": str(item.get("location") or ""),
                "highlights": [md_to_html(h) for h in (item.get("highlights") or [])],
            }
            for item in (sections.get("projects") or [])
        ],
        "education": [
            {
                "institution": md_to_html(item.get("institution") or ""),
                "area": md_to_html(item.get("area") or ""),
                "degree": md_to_html(item.get("degree") or ""),
                "period": period(item.get("start_date"), item.get("end_date")),
                "location": str(item.get("location") or ""),
                "highlights": [md_to_html(h) for h in (item.get("highlights") or [])],
            }
            for item in (sections.get("education") or [])
        ],
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"Wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
