#!/usr/bin/env python3
"""Refreshes README.md and assets/id-dashboard.svg from your public GitHub data.

Runs inside GitHub Actions (see .github/workflows/update-profile.yml). Standard library only.
It rewrites:
  * the projects table between <!--PROJECTS:START--> and <!--PROJECTS:END-->
  * the stats line between <!--STATS:START--> and <!--STATS:END-->
  * the four live tiles (repos, stars, followers, top language) in assets/id-dashboard.svg
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
        # markers missing (README was edited by hand): add the section at the end instead of failing
        head = "\n\n## Projects\n\n" if tag == "PROJECTS" else "\n\n"
        return text.rstrip() + head + "<!--%s:START-->\n%s\n<!--%s:END-->\n" % (tag, new, tag)
    return pat.sub(lambda m: m.group(1) + "\n" + new + "\n" + m.group(3), text)


def find_files(name):
    """Every copy of `name` in the repo (it may sit in assets/, asset/, or the top level)."""
    found = []
    for folder, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d != ".git"]
        if name in files:
            found.append(os.path.join(folder, name))
    return found


def patch_svg(svg, elem_id, value, max_size=62):
    """Replace a tile's text and shrink the font so long values (e.g. 'JavaScript') still fit the 128px tile."""
    size = max(14, min(max_size, int(128 / (0.62 * max(len(value), 1)))))
    pat = re.compile(r'(<text[^>]*\bid="%s"[^>]*?)(\s*font-size="[^"]*")?([^>]*>)(.*?)(</text>)' % re.escape(elem_id), re.S)
    safe = value.replace("&", "&amp;").replace("<", "&lt;")

    def sub(m):
        head = re.sub(r'\sfont-size="[^"]*"', "", m.group(1) + (m.group(3) or "").rsplit(">", 1)[0])
        return '%s font-size="%d">%s</text>' % (head, size, safe)
    return pat.sub(sub, svg)


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
    readme = open(readme_p, encoding="utf-8").read() if os.path.exists(readme_p) else "# Hi, I'm %s\n" % USER
    old_readme = readme

    table = build_table(mine) if mine else "_No public projects yet. New repositories appear here automatically._"
    readme = replace_between(readme, "PROJECTS", table)
    readme = replace_between(readme, "STATS", build_stats(user, mine))

    top = Counter(r["language"] for r in mine if r.get("language")).most_common(1)
    stars = sum(r.get("stargazers_count", 0) for r in mine)
    values = [("i-stat-repos", str(len(mine))), ("i-stat-stars", str(stars)),
              ("i-stat-followers", str(user.get("followers", 0))), ("i-stat-lang", top[0][0] if top else "n/a")]

    svg_paths = find_files("id-dashboard.svg")
    if not svg_paths:
        print("WARNING: id-dashboard.svg was not found anywhere in the repo; only the README was updated.")
    changed_svgs = []
    for path in svg_paths:
        svg = old_svg = open(path, encoding="utf-8").read()
        for elem_id, val in values:
            svg = patch_svg(svg, elem_id, val)
        if svg != old_svg:
            open(path, "w", encoding="utf-8").write(svg)
            changed_svgs.append(os.path.relpath(path, ROOT))

    if not changed_svgs and readme == old_readme:
        print("No changes.")
        return 0
    if changed_svgs:  # new ?v= so GitHub fetches the fresh image instead of its cached copy
        stamp = dt.datetime.utcnow().strftime("%Y%m%d%H%M")
        readme = re.sub(r"id-dashboard\.svg\?v=\w+", "id-dashboard.svg?v=" + stamp, readme)
    open(readme_p, "w", encoding="utf-8").write(readme)
    print("Updated %s: %d projects, %s" % (", ".join(changed_svgs) or "README only", len(mine), build_stats(user, mine)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
