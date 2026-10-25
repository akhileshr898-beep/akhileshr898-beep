#!/usr/bin/env python3
"""Refreshes README.md and assets/id-dashboard.svg from your public GitHub data.

Runs inside GitHub Actions (see .github/workflows/update-profile.yml). Standard library only.
It rewrites:
  * the projects table between <!--PROJECTS:START--> and <!--PROJECTS:END-->
  * the stats line between <!--STATS:START--> and <!--STATS:END-->
  * the "Public repos" tile in assets/id-dashboard.svg
  * the ?v= cache-buster on id-dashboard.svg in the README, when anything changed
"""
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections import Counter

USER = os.environ.get("PROFILE_USER") or os.environ.get("GITHUB_REPOSITORY_OWNER") or "akhileshr898-beep"
TOKEN = os.environ.get("GITHUB_TOKEN", "")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_ROWS = 12


def fetch_json(url):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "profile-readme-updater"})
    if TOKEN:
        req.add_header("Authorization", "Bearer " + TOKEN)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def load_data():
    user = fetch_json("https://api.github.com/users/%s" % USER)
    repos, page = [], 1
    while True:
        chunk = fetch_json("https://api.github.com/users/%s/repos?per_page=100&type=owner&sort=pushed&page=%d" % (USER, page))
        repos += chunk
        if len(chunk) < 100:
            break
        page += 1
    return user, repos


def cell(text):
    return (text or "").replace("|", "\\|").replace("\n", " ").strip()


def build_table(repos):
    rows = ["| Project | Description | Language | Stars | Forks | Updated |", "| --- | --- | --- | --- | --- | --- |"]
    for r in repos[:MAX_ROWS]:
        name = "[**%s**](%s)" % (cell(r["name"]), r["html_url"])
        if r.get("homepage"):
            name += " · [Live](%s)" % r["homepage"].strip()
        desc = cell(r.get("description")) or "No description yet."
        topics = r.get("topics") or []
        if topics:
            desc += "<br>" + " ".join("`%s`" % t for t in topics[:5])
        updated = (r.get("pushed_at") or r.get("updated_at") or "")[:10]
        rows.append("| %s | %s | %s | %d | %d | %s |" % (name, desc, cell(r.get("language")) or "-", r.get("stargazers_count", 0), r.get("forks_count", 0), updated))
    if len(repos) > MAX_ROWS:
        rows.append("")
        rows.append("[See all %d repositories](https://github.com/%s?tab=repositories)" % (len(repos), USER))
    return "\n".join(rows)


def build_stats(user, repos):
    stars = sum(r.get("stargazers_count", 0) for r in repos)
    langs = [l for l, _ in Counter(r["language"] for r in repos if r.get("language")).most_common(4)]
    parts = ["**%d** public repos" % len(repos), "**%d** stars" % stars, "**%d** followers" % user.get("followers", 0)]
    if langs:
        parts.append("top languages: " + ", ".join(langs))
    return " · ".join(parts)


def replace_between(text, tag, new):
    pat = re.compile(r"(<!--%s:START-->)(.*?)(<!--%s:END-->)" % (tag, tag), re.S)
    if not pat.search(text):
        raise SystemExit("README.md is missing the <!--%s:START--> / <!--%s:END--> markers" % (tag, tag))
    return pat.sub(lambda m: m.group(1) + "\n" + new + "\n" + m.group(3), text)


def patch_svg(svg, elem_id, value):
    pat = re.compile(r'(<text[^>]*\bid="%s"[^>]*>)(.*?)(</text>)' % re.escape(elem_id), re.S)
    value = value.replace("&", "&amp;").replace("<", "&lt;")
    return pat.sub(lambda m: m.group(1) + value + m.group(3), svg)


def main(user=None, repos=None):
    if user is None:
        try:
            user, repos = load_data()
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            print("GitHub API unavailable, leaving files unchanged: %s" % e)
            return 0
    mine = [r for r in repos if not r.get("fork") and not r.get("archived") and r["name"].lower() != USER.lower()]
    mine.sort(key=lambda r: r.get("pushed_at") or "", reverse=True)

    readme_p = os.path.join(ROOT, "README.md")
    svg_p = os.path.join(ROOT, "assets", "id-dashboard.svg")
    readme = open(readme_p, encoding="utf-8").read()
    svg = open(svg_p, encoding="utf-8").read()
    old = (readme, svg)

    table = build_table(mine) if mine else "_No public projects yet. New repositories appear here automatically._"
    readme = replace_between(readme, "PROJECTS", table)
    readme = replace_between(readme, "STATS", build_stats(user, mine))

    top = Counter(r["language"] for r in mine if r.get("language")).most_common(1)
    svg = patch_svg(svg, "i-stat-repos", "%02d" % len(mine))
    svg = patch_svg(svg, "i-stat-sub", ("Top language: " + top[0][0]) if top else "Updated from GitHub")

    if (readme, svg) == old:
        print("No changes.")
        return 0
    stamp = dt.date.today().strftime("%Y%m%d")
    readme = re.sub(r"id-dashboard\.svg\?v=\w+", "id-dashboard.svg?v=" + stamp, readme)
    open(readme_p, "w", encoding="utf-8").write(readme)
    open(svg_p, "w", encoding="utf-8").write(svg)
    print("Updated: %d projects, %s" % (len(mine), build_stats(user, mine)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
