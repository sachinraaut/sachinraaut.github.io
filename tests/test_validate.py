import pytest

from blogtool.content import load_post, load_site
from blogtool.validate import check_all, check_daily_set, check_post
from tests.conftest import BODY, ROOT, make_post

SITE = load_site(ROOT)


def errors(tmp_path, **kw):
    f = tmp_path / "p.md"
    f.write_text(make_post(**kw), encoding="utf-8")
    return check_post(load_post(f, SITE), SITE)


def test_good_post_passes(tmp_path):
    assert errors(tmp_path) == []


@pytest.mark.parametrize("kw,fragment", [
    ({"title": "लहान"}, "title length"),
    ({"slug": "Bad_Slug"}, "slug"),
    ({"category": "sports"}, "category"),
    ({"tags": ("एक",)}, "tags"),
    ({"body": "## अ\n\nलहान मजकूर\n\n## ब\n\nआणखी"}, "words"),
    ({"body": BODY.replace("## दुसरा विभाग", "दुसरा")}, "headings"),
    ({"body": BODY + "\n<script>alert(1)</script>\n"}, "raw HTML"),
    ({"body": BODY + "\n[क्लिक](javascript:alert(1))\n"}, "javascript"),
    ({"body": BODY + "\n<!-- hidden -->\n"}, "raw HTML"),
    ({"body": ("## a\n\n" + "this is entirely english text " * 120 + "\n\n## b\n\n" + "more english " * 30)}, "Marathi"),
    ({"category": "news", "sources": False}, "requires at least one source"),
    ({"extra": {"sources": [{"name": "x", "url": "ftp://bad"}]}}, "http(s)"),
    ({"extra": {"sources": [{"name": "x", "url": "https://news.google.com/rss/articles/CBMabc"}]}}, "Google News redirect"),
    ({"category": "finance", "body": BODY + "\nहा शेअर खरेदी करा.\n"}, "risky claim"),
    ({"category": "health", "body": BODY + "\nहा चमत्कारिक उपाय आहे.\n"}, "risky claim"),
    ({"extra": {"image": "javascript:x"}}, "image"),
])
def test_rules_reject(tmp_path, kw, fragment):
    assert any(fragment in e for e in errors(tmp_path, **kw)), errors(tmp_path, **kw)


def test_tech_without_sources_is_allowed(tmp_path):
    assert errors(tmp_path, category="tech", sources=False) == []


def test_check_all_duplicates_and_filename(blog):
    blog.add(slug="one")
    blog.add(slug="one", date="2026-09-19T07:30:00+05:30", title="वेगळे शीर्षक क्रमांक दोन आहे")
    blog.add(filename="wrong-name.md", slug="two")
    problems = check_all(blog.root, load_site(blog.root))
    flat = " ".join(" ".join(v) for v in problems.values())
    assert "duplicate slug" in flat and "file name should start" in flat


def test_broken_front_matter_reported(blog):
    (blog.root / "content" / "posts" / "2026-09-20-x.md").write_text("junk", encoding="utf-8")
    assert "front matter" in " ".join(check_all(blog.root, load_site(blog.root))["content/posts/2026-09-20-x.md"])


def test_daily_set(blog):
    for cat in ("tech", "finance", "health"):
        blog.add(slug=f"d-{cat}", category=cat)
    site = load_site(blog.root)
    assert "missing posts for 2026-09-20: news" in check_daily_set(blog.root, site, "2026-09-20")[0]
    blog.add(slug="d-news", category="news")
    assert check_daily_set(blog.root, site, "2026-09-20") == []
    blog.add(slug="d-news2", category="news", title="दुसरे बातमी शीर्षक जे वेगळे आहे")
    assert "more than one" in check_daily_set(blog.root, site, "2026-09-20")[0]
