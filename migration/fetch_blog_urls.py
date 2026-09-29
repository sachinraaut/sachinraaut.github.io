"""Read the live Blogger blog and map each post title to the URL Blogger actually gave it.

Why this exists: Blogger assigns the permalink itself on import, so the URLs on the live blog are
not the ones this repo would predict from the slug. Without a real map, every internal link in a
new post is a guess. The blog's Atom feed is public, needs no credentials, and states the true URL
for every post, so we just ask it.

Titles are the join key: blogtool's validator already rejects duplicate titles, so they are unique.

The sandbox this repo is written in cannot reach blogspot.com, but a GitHub Actions runner can, so
this runs in CI. If the feed is unreachable the map comes back empty and callers fall back to
linking at the GitHub Pages copy, which stays live.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def fetch(blog_url: str, timeout: int = 30) -> dict:
    """{post title: live Blogger URL}. Pages through the feed 150 entries at a time."""
    out, start = {}, 1
    while True:
        q = urllib.parse.urlencode({"alt": "json", "max-results": 150, "start-index": start})
        url = f"{blog_url.rstrip('/')}/feeds/posts/default?{q}"
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                feed = json.loads(r.read().decode("utf-8")).get("feed", {})
        except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
            print(f"  could not read the blog feed ({exc}); internal links will point at the "
                  f"GitHub Pages copy instead", file=sys.stderr)
            return out
        entries = feed.get("entry") or []
        for e in entries:
            title = (e.get("title") or {}).get("$t", "").strip()
            alt = [l for l in (e.get("link") or []) if l.get("rel") == "alternate"]
            if title and alt:
                out[title] = alt[0]["href"]
        if len(entries) < 150:
            return out
        start += 150


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--blog-url", default="https://marathinazar.blogspot.com")
    ap.add_argument("--out", default=str(ROOT / "migration" / "out" / "blog-urls.json"))
    args = ap.parse_args()

    urls = fetch(args.blog_url)
    dest = Path(args.out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(urls, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(urls)} live post URLs -> {dest}")
