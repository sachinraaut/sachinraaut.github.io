import json
import re
import xml.etree.ElementTree as ET

from blogtool.build import Builder
from tests.conftest import NOW


def built(blog, base="https://user.github.io", n=3):
    cats = ["tech", "finance", "health", "news"]
    for i in range(n):
        blog.add(slug=f"post-{i}", category=cats[i % 4], date=f"2026-09-{18 + i:02d}T07:30:00+05:30")
    b = Builder(blog.root, base, now=NOW)
    b.build()
    return b, blog.root / "public"


def test_files_created(blog):
    blog.set_site(contact_email="")
    b, out = built(blog)
    for rel in ["index.html", "404.html", "sitemap.xml", "rss.xml", "robots.txt", "search.json", "style.css",
                "favicon.svg", "search.js", ".nojekyll", "archive/index.html", "search/index.html",
                "about/index.html", "disclaimer/index.html", "privacy/index.html", "posts/post-0/index.html",
                "category/tech/index.html", "category/news/index.html"]:
        assert (out / rel).exists(), rel
    assert not (out / "contact" / "index.html").exists()             # no contact email configured


def test_post_seo(blog):
    b, out = built(blog)
    html = (out / "posts/post-0/index.html").read_text(encoding="utf-8")
    assert '<html lang="mr">' in html
    assert '<link rel="canonical" href="https://user.github.io/posts/post-0/">' in html
    assert 'property="og:locale" content="mr_IN"' in html and 'property="og:type" content="article"' in html
    assert 'name="description"' in html and "<title>चाचणी लेखाचे शीर्षक post-0 | मराठी नजर</title>" in html
    ld = [json.loads(m) for m in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)]
    post = next(x for x in ld if x["@type"] == "BlogPosting")
    assert post["inLanguage"] == "mr" and post["datePublished"].startswith("2026-09-18")
    assert post["mainEntityOfPage"]["@id"] == "https://user.github.io/posts/post-0/"
    assert any(x["@type"] == "BreadcrumbList" for x in ld)
    assert "संदर्भ / स्रोत" in html and "https://example.com/a" in html and "AI च्या मदतीने" in html


def test_category_disclaimers(blog):
    b, out = built(blog, n=4)
    assert "वैद्यकीय सल्ला" in (out / "posts/post-2/index.html").read_text(encoding="utf-8")     # health
    assert "SEBI" in (out / "posts/post-1/index.html").read_text(encoding="utf-8")                # finance
    assert "महत्त्वाची सूचना" not in (out / "posts/post-0/index.html").read_text(encoding="utf-8")  # tech


def test_sitemap_rss_robots(blog):
    b, out = built(blog)
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locs = [e.text for e in ET.parse(out / "sitemap.xml").getroot().findall("s:url/s:loc", ns)]
    assert "https://user.github.io/" in locs and "https://user.github.io/posts/post-2/" in locs
    assert not any("/search/" in l for l in locs)                    # noindex page kept out of the sitemap
    items = ET.parse(out / "rss.xml").getroot().findall("channel/item")
    assert len(items) == 3 and items[0].find("title").text.endswith("post-2")      # newest first
    assert "Sitemap: https://user.github.io/sitemap.xml" in (out / "robots.txt").read_text()
    assert 'noindex' in (out / "search/index.html").read_text(encoding="utf-8")


def test_future_and_draft_not_published(blog):
    blog.add(slug="visible")
    blog.add(slug="later", date="2026-09-20T23:00:00+05:30")
    blog.add(slug="wip", extra={"draft": True})
    b = Builder(blog.root, "https://user.github.io", now=NOW)
    b.build()
    out = blog.root / "public"
    assert (out / "posts/visible/index.html").exists()
    assert not (out / "posts/later").exists() and not (out / "posts/wip").exists()
    assert "later" not in (out / "sitemap.xml").read_text() and "wip" not in (out / "search.json").read_text()


def test_project_page_base_path(blog):
    b, out = built(blog, base="https://user.github.io/my-blog")
    html = (out / "index.html").read_text(encoding="utf-8")
    assert 'href="/my-blog/style.css"' in html and 'href="/my-blog/posts/post-0/"' in html
    assert 'rel="canonical" href="https://user.github.io/my-blog/"' in html
    assert json.loads((out / "search.json").read_text())[0]["u"].startswith("/my-blog/posts/")


def test_pagination_and_archive(blog):
    blog.set_site(posts_per_page=2)
    for i in range(5):
        blog.add(slug=f"t{i}", category="tech", date=f"2026-09-{10 + i:02d}T07:30:00+05:30")
    Builder(blog.root, "https://user.github.io", now=NOW).build()
    out = blog.root / "public"
    assert (out / "category/tech/page/3/index.html").exists() and not (out / "category/tech/page/4").exists()
    p2 = (out / "category/tech/page/2/index.html").read_text(encoding="utf-8")
    assert 'rel="prev" href="https://user.github.io/category/tech/"' in p2 and 'rel="next"' in p2
    assert (out / "archive/index.html").read_text(encoding="utf-8").count("<li>") == 5
    assert len(list((out).glob("index.html"))) == 1
    assert (out / "index.html").read_text(encoding="utf-8").count('class="card"') >= 2


def test_empty_site_builds(blog):
    Builder(blog.root, "https://user.github.io", now=NOW).build()
    assert "लवकरच नवीन लेख" in (blog.root / "public/index.html").read_text(encoding="utf-8")


def test_contact_page_and_custom_domain(blog):
    blog.set_site(contact_email="me@example.com", custom_domain="blog.example.com", google_site_verification="tok123")
    blog.add(slug="x")
    Builder(blog.root, None, now=NOW).build()
    out = blog.root / "public"
    assert 'mailto:me@example.com' in (out / "contact/index.html").read_text(encoding="utf-8")
    assert (out / "CNAME").read_text().strip() == "blog.example.com"
    home = (out / "index.html").read_text(encoding="utf-8")
    assert 'rel="canonical" href="https://blog.example.com/"' in home and 'google-site-verification" content="tok123"' in home


def test_html_is_escaped_in_titles(blog):
    blog.add(slug="esc", title='शीर्षक "A" & <b>B</b> चाचणी करणारे मोठे शीर्षक')
    Builder(blog.root, "https://user.github.io", now=NOW).build()
    html = (blog.root / "public/posts/esc/index.html").read_text(encoding="utf-8")
    assert "<b>B</b>" not in html.split("<main")[0] and "&lt;b&gt;B&lt;/b&gt;" in html
