"""Quality and safety gate for posts. Runs before every deploy; a failing post stops the whole publish.

The rules exist because posts may be written by an AI that reads untrusted web pages: they block raw HTML,
script-like content, risky claims and thin/misfiled posts.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from . import mr
from .content import ContentError, Post, Site, load_post

SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
RAW_HTML = re.compile(r"<\s*/?\s*[A-Za-z][^>]*>")
BAD_LINK = re.compile(r"\]\(\s*(?:javascript|data|vbscript):", re.I)
NEEDS_SOURCES = {"news", "finance", "health"}
LIMITS = {"title": (20, 80), "description": (90, 175), "words": 350, "tags": (3, 7), "min_ratio": 0.6}

# Claims that must never appear in health / finance content (Marathi phrases, matched as substrings).
RISKY = {
    "finance": ["हमखास फायदा", "गॅरंटीड रिटर्न", "निश्चित परतावा", "१००% खात्री", "100% खात्री", "दुप्पट पैसे",
                "रातोरात श्रीमंत", "हा शेअर खरेदी करा", "हा शेअर विका", "जोखीम नाही"],
    "health": ["कायमचा इलाज", "चमत्कारिक", "१००% खात्रीशीर", "100% खात्रीशीर", "डॉक्टरांची गरज नाही",
               "औषध बंद करा", "कर्करोग बरा होतो", "मधुमेह पूर्ण बरा"],
}


def check_post(post: Post, site: Site) -> list[str]:
    e: list[str] = []
    lo, hi = LIMITS["title"]
    if not lo <= len(post.title) <= hi:
        e.append(f"title length {len(post.title)} not in {lo}-{hi}")
    lo, hi = LIMITS["description"]
    if not lo <= len(post.description) <= hi:
        e.append(f"description length {len(post.description)} not in {lo}-{hi} (SEO snippet)")
    if not SLUG.match(post.slug):
        e.append(f"slug {post.slug!r} must be lowercase English letters/digits/hyphens")
    if post.category not in site.categories:
        e.append(f"category {post.category!r} not one of {sorted(site.categories)}")
    lo, hi = LIMITS["tags"]
    if not lo <= len(post.tags) <= hi:
        e.append(f"needs {lo}-{hi} tags, has {len(post.tags)}")
    if post.words < LIMITS["words"]:
        e.append(f"body has {post.words} words; minimum {LIMITS['words']}")
    if mr.devanagari_ratio(post.title + " " + post.body) < LIMITS["min_ratio"]:
        e.append("text is not predominantly Marathi (Devanagari)")
    if len(re.findall(r"^##\s+\S", post.body, re.M)) < 2:
        e.append("needs at least 2 '##' section headings")
    if RAW_HTML.search(post.body) or "<!--" in post.body:
        e.append("raw HTML is not allowed in the body (use Markdown only)")
    if BAD_LINK.search(post.body):
        e.append("javascript:/data: links are not allowed")
    for i, s in enumerate(post.sources):
        url = s.get("url", "") if isinstance(s, dict) else ""
        if not (isinstance(s, dict) and s.get("name") and urlparse(url).scheme in ("http", "https")
                and urlparse(url).netloc):
            e.append(f"source #{i + 1} needs 'name' and an http(s) 'url'")
        elif "news.google.com/rss/articles" in url:
            e.append(f"source #{i + 1}: cite the publisher's own article URL, not a Google News redirect")
    if post.category in NEEDS_SOURCES and not post.sources:
        e.append(f"category {post.category!r} requires at least one source")
    for phrase in RISKY.get(post.category, []):
        if phrase in post.body or phrase in post.title:
            e.append(f"risky claim not allowed in {post.category}: {phrase!r}")
    prompt = post.raw.get("image_prompt")
    if prompt is not None and not re.match(r"^[A-Za-z0-9 ,.'\-()]{15,300}$", " ".join(str(prompt).split())):
        e.append("image_prompt must be 15-300 characters of plain English (letters, digits, , . ' - ( ))")
    alt = post.raw.get("image_alt")
    if alt is not None and not 5 <= len(str(alt)) <= 160:
        e.append("image_alt must be 5-160 characters (Marathi description of the picture)")
    if post.image and not (post.image.startswith("/") or urlparse(post.image).scheme in ("http", "https")):
        e.append("image must be a site path or http(s) URL")
    return e


def check_all(root: Path, site: Site, now: datetime | None = None) -> dict[str, list[str]]:
    """Validate every post file (including drafts and scheduled ones). Returns {file: [errors]}."""
    problems: dict[str, list[str]] = {}
    posts: list[Post] = []
    for path in sorted((root / "content" / "posts").rglob("*.md")):
        rel = str(path.relative_to(root))
        try:
            post = load_post(path, site)
        except ContentError as exc:
            problems[rel] = [str(exc)]
            continue
        posts.append(post)
        errs = check_post(post, site)
        if not path.stem.startswith(post.date.strftime("%Y-%m-%d")):
            errs.append(f"file name should start with the post date {post.date:%Y-%m-%d}")
        if errs:
            problems[rel] = errs
    slugs = Counter(p.slug for p in posts)
    for p in posts:
        if slugs[p.slug] > 1:
            problems.setdefault(str(p.path.relative_to(root)), []).append(f"duplicate slug {p.slug!r}")
    titles = Counter(p.title for p in posts)
    for p in posts:
        if titles[p.title] > 1:
            problems.setdefault(str(p.path.relative_to(root)), []).append("duplicate title")
    return problems


def check_daily_set(root: Path, site: Site, day: str) -> list[str]:
    """For the daily run: exactly one post per category dated `day` (YYYY-MM-DD)."""
    from .content import load_posts
    posts = [p for p in load_posts(root, site, include_hidden=True) if p.date.strftime("%Y-%m-%d") == day]
    by_cat = Counter(p.category for p in posts)
    missing = [c for c in site.categories if by_cat[c] == 0]
    extra = [c for c, n in by_cat.items() if n > 1]
    out = []
    if missing:
        out.append(f"missing posts for {day}: {', '.join(missing)}")
    if extra:
        out.append(f"more than one post for {day} in: {', '.join(extra)}")
    return out
