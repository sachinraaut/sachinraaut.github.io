"""Fetch trending topics from free public RSS feeds and write a per-category brief for the daily writer.

The brief lists candidate stories (clustered across outlets; more outlets = more prominent) and today's Google
Trends searches with their publisher article URLs. It is only a starting point: the writer must open and read the
real sources before writing, and never state facts that are not in them.
"""
from __future__ import annotations

import json
import re
import string
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
HT = "{https://trends.google.com/trending/rss}"
STRIP = string.punctuation + "‘’“”…|:–—"


def http_get(url: str, timeout: int = 25) -> bytes:
    """Bytes, so the XML parser can honour the document's own encoding declaration / BOM."""
    r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    return r.content


def parse_date(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        d = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def split_source(title: str, source: str | None) -> tuple[str, str]:
    """Google News titles end with ' - Publisher'. Returns (headline, publisher)."""
    title = title.strip()
    if source and title.endswith(f" - {source}"):
        return title[: -len(source) - 3].strip(), source
    if " - " in title and not source:
        head, _, tail = title.rpartition(" - ")
        return head.strip(), tail.strip()
    return title, source or ""


def parse_rss(xml_text: str | bytes, feed_name: str, lang: str = "") -> list[dict]:
    root = ET.fromstring(xml_text)
    out = []
    for item in root.iter("item"):
        src_el = item.find("source")
        headline, source = split_source(item.findtext("title") or "", src_el.text if src_el is not None else None)
        if not headline:
            continue
        out.append({"headline": headline, "source": source or feed_name, "url": (item.findtext("link") or "").strip(),
                    "published": parse_date(item.findtext("pubDate")), "feed": feed_name, "lang": lang})
    return out


def parse_trends(xml_text: str | bytes) -> list[dict]:
    root = ET.fromstring(xml_text)
    out = []
    for item in root.iter("item"):
        articles = [{"title": (n.findtext(f"{HT}news_item_title") or "").strip(),
                     "url": (n.findtext(f"{HT}news_item_url") or "").strip(),
                     "source": (n.findtext(f"{HT}news_item_source") or "").strip()}
                    for n in item.findall(f"{HT}news_item")]
        out.append({"query": (item.findtext("title") or "").strip(),
                    "traffic": (item.findtext(f"{HT}approx_traffic") or "").strip(),
                    "published": parse_date(item.findtext("pubDate")), "articles": [a for a in articles if a["url"]]})
    return out


def tokens(headline: str) -> set[str]:
    return {t for t in (w.strip(STRIP).lower() for w in headline.split()) if len(t) > 2}


def cluster(items: list[dict], threshold: float = 0.5) -> list[dict]:
    """Group near-duplicate headlines (Jaccard similarity of words). Cluster size = distinct outlets covering it."""
    clusters: list[dict] = []
    for it in sorted(items, key=lambda i: i["published"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True):
        tk = tokens(it["headline"])
        for c in clusters:
            inter, union = len(tk & c["tokens"]), len(tk | c["tokens"])
            if union and inter / union >= threshold:
                c["items"].append(it)
                c["tokens"] |= tk
                break
        else:
            clusters.append({"tokens": set(tk), "items": [it]})
    out = []
    for c in clusters:
        first = c["items"][0]
        sources = sorted({i["source"] for i in c["items"] if i["source"]})
        out.append({"headline": first["headline"], "lang": first["lang"], "coverage": len(sources), "sources": sources,
                    "published": first["published"].isoformat() if first["published"] else None,
                    "links": [{"source": i["source"], "url": i["url"]} for i in c["items"] if i["url"]][:5]})
    return sorted(out, key=lambda c: (c["coverage"], c["published"] or ""), reverse=True)


def recent_post_titles(root: Path, days: int = 10) -> list[dict]:
    from .content import load_posts, load_site
    site = load_site(root)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return [{"date": p.date.strftime("%Y-%m-%d"), "category": p.category, "title": p.title, "slug": p.slug}
            for p in load_posts(root, site, include_hidden=True) if p.date >= cutoff]


def fetch_all(root: Path, out_path: Path, fetch=http_get, log=print) -> Path:
    cfg = json.loads((root / "feeds.json").read_text(encoding="utf-8"))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=cfg.get("max_age_hours", 48))
    brief = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "categories": {},
             "trends": [], "recent_posts": recent_post_titles(root), "failed_feeds": []}
    for cat, feeds in cfg["categories"].items():
        items = []
        for f in feeds:
            try:
                items += parse_rss(fetch(f["url"]), f["name"], f.get("lang", ""))
            except Exception as exc:                         # one broken feed must not stop the daily run
                brief["failed_feeds"].append({"feed": f["name"], "error": str(exc)[:160]})
                log(f"feed failed: {f['name']}: {exc}")
        banned = {b.lower() for b in cfg.get("exclude_sources", [])}
        fresh = [i for i in items if (i["published"] is None or i["published"] >= cutoff)
                 and i["source"].lower() not in banned]
        brief["categories"][cat] = cluster(fresh)[: cfg.get("per_category", 15)]
    try:
        tr = parse_trends(fetch(cfg["trends"]["url"]))
        brief["trends"] = [{**t, "published": t["published"].isoformat() if t["published"] else None} for t in tr]
    except Exception as exc:
        brief["failed_feeds"].append({"feed": cfg["trends"]["name"], "error": str(exc)[:160]})
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(brief, ensure_ascii=False, indent=1), encoding="utf-8")
    return out_path
