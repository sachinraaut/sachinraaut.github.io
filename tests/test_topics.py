import json
from datetime import datetime, timedelta, timezone

from blogtool import topics

NOW = datetime.now(timezone.utc)


def rfc(dt):
    return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")


def gnews(items):
    body = "".join(f'<item><title>{t} - {s}</title><link>https://news.google.com/rss/articles/CBM{i}</link>'
                   f'<pubDate>{rfc(d)}</pubDate><source url="https://x.com">{s}</source></item>'
                   for i, (t, s, d) in enumerate(items))
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>{body}</channel></rss>'


TRENDS = """<?xml version="1.0"?><rss xmlns:ht="https://trends.google.com/trending/rss" version="2.0"><channel>
<item><title>iran war</title><ht:approx_traffic>200+</ht:approx_traffic><pubDate>Sat, 19 Sep 2026 21:00:00 -0700</pubDate>
<ht:news_item><ht:news_item_title>Headline A</ht:news_item_title><ht:news_item_url>https://aljazeera.com/a</ht:news_item_url>
<ht:news_item_source>Al Jazeera</ht:news_item_source></ht:news_item></item></channel></rss>"""


def test_parse_rss_strips_publisher_suffix():
    items = topics.parse_rss(gnews([("मोठी बातमी येथे आहे", "लोकमत", NOW)]), "feed", "mr")
    assert items[0]["headline"] == "मोठी बातमी येथे आहे" and items[0]["source"] == "लोकमत"
    assert items[0]["published"].tzinfo is not None


def test_parse_rss_handles_bom_bytes():
    xml = ("﻿" + gnews([("Some headline text here", "Src", NOW)])).encode("utf-8")
    assert topics.parse_rss(xml, "f")[0]["headline"] == "Some headline text here"


def test_parse_trends():
    t = topics.parse_trends(TRENDS)
    assert t[0]["query"] == "iran war" and t[0]["traffic"] == "200+"
    assert t[0]["articles"] == [{"title": "Headline A", "url": "https://aljazeera.com/a", "source": "Al Jazeera"}]


def test_cluster_groups_same_story_across_outlets():
    items = topics.parse_rss(gnews([
        ("UPI शुल्कावर सरकारची भूमिका बदलली राज ठाकरे यांची टीका", "ABP", NOW),
        ("UPI शुल्कावर सरकारची भूमिका बदलली ठाकरे यांची जोरदार टीका", "Lokmat", NOW),
        ("पावसाचा येलो अलर्ट राज्यात कायम", "Sakal", NOW)]), "f")
    c = topics.cluster(items)
    assert len(c) == 2 and c[0]["coverage"] == 2 and set(c[0]["sources"]) == {"ABP", "Lokmat"}


def test_fetch_all_filters_old_and_excluded(tmp_path, monkeypatch):
    (tmp_path / "content" / "posts").mkdir(parents=True)
    (tmp_path / "site.json").write_text(json.dumps({"title": "t", "tagline": "t", "description": "d", "author": "a",
                                                     "base_url": "https://x.io", "categories": {}}))
    feeds = {"categories": {"tech": [{"name": "F1", "url": "u1", "lang": "en"}, {"name": "F2", "url": "bad"}]},
             "trends": {"name": "T", "url": "tr"}, "max_age_hours": 48, "per_category": 5,
             "exclude_sources": ["Cureus"]}
    (tmp_path / "feeds.json").write_text(json.dumps(feeds))
    pages = {"u1": gnews([("Fresh gadget launch news today", "Verge", NOW - timedelta(hours=3)),
                          ("Old stale story from last week", "Verge", NOW - timedelta(days=7)),
                          ("Journal paper about something", "Cureus", NOW)]), "tr": TRENDS}

    def fake(url):
        if url == "bad":
            raise RuntimeError("boom")
        return pages[url]
    out = topics.fetch_all(tmp_path, tmp_path / "topics" / "t.json", fetch=fake, log=lambda *_: 0)
    d = json.loads(out.read_text(encoding="utf-8"))
    assert [c["headline"] for c in d["categories"]["tech"]] == ["Fresh gadget launch news today"]
    assert d["failed_feeds"][0]["feed"] == "F2" and d["trends"][0]["query"] == "iran war"
