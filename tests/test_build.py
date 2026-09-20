import json
import re
import xml.etree.ElementTree as ET

import pytest

from blogtool.build import BuildError, Builder
from tests.conftest import NOW


def built(blog, base="https://user.github.io", n=3):
    cats = ["technology", "finance", "health", "news"]
    for i in range(n):
        blog.add(slug=f"post-{i}", category=cats[i % 4], date=f"2026-09-{15 + i:02d}T07:30:00+05:30")
    b = Builder(blog.root, base, now=NOW)
    b.build()
    return b, blog.root / "public"


def ld_nodes(html):
    """Every JSON-LD node on the page, flattened out of the @graph wrapper."""
    out = []
    for m in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
        data = json.loads(m)
        out.extend(data.get("@graph", [data]))
    return out


def test_files_created(blog):
    blog.set_site(contact_email="")
    b, out = built(blog, n=4)
    for rel in ["index.html", "404.html", "sitemap.xml", "rss.xml", "robots.txt", "search.json", "style.css",
                "favicon.svg", "search.js", ".nojekyll", "archive/index.html", "search/index.html",
                "trending/index.html", "about/index.html", "disclaimer/index.html", "privacy/index.html",
                "posts/post-0/index.html", "technology/index.html", "news/index.html", "technology/rss.xml"]:
        assert (out / rel).exists(), rel
    assert not (out / "contact" / "index.html").exists()             # no contact email configured


def test_categories_without_posts_are_not_built(blog):
    """An empty category page is thin content and an empty nav link is a dead end."""
    b, out = built(blog)
    assert "ai" in b.site.categories and not (out / "ai").exists()
    assert not (out / "how-to").exists() and not (out / "stock-market").exists()
    home = (out / "index.html").read_text(encoding="utf-8")
    assert 'href="/technology/"' in home and 'href="/ai/"' not in home


def test_old_category_urls_redirect(blog):
    b, out = built(blog)
    stub = (out / "category/technology/index.html").read_text(encoding="utf-8")
    assert 'rel="canonical" href="https://user.github.io/technology/"' in stub
    assert 'http-equiv="refresh"' in stub and "noindex" in stub
    assert 'rel="canonical" href="https://user.github.io/technology/"' in \
           (out / "category/tech/index.html").read_text(encoding="utf-8")       # the category was renamed
    assert not (out / "category/ai").exists()                                   # never redirect to a missing page
    assert "/category/" not in (out / "sitemap.xml").read_text(encoding="utf-8")


def test_category_slug_may_not_collide_with_a_page(blog):
    blog.set_site(categories={"about": {"name": "About", "description": "d", "color": "#111"}})
    blog.add(slug="x", category="about")
    with pytest.raises(BuildError, match="collides"):
        Builder(blog.root, "https://user.github.io", now=NOW)


def test_post_seo(blog):
    b, out = built(blog)
    html = (out / "posts/post-0/index.html").read_text(encoding="utf-8")
    assert '<html lang="mr">' in html
    assert '<link rel="canonical" href="https://user.github.io/posts/post-0/">' in html
    assert 'property="og:locale" content="mr_IN"' in html and 'property="og:type" content="article"' in html
    assert 'name="description"' in html and "<title>चाचणी लेखाचे शीर्षक post-0 | मराठी नजर</title>" in html
    nodes = ld_nodes(html)
    post = next(x for x in nodes if x["@type"] == "Article")
    assert post["inLanguage"] == "mr" and post["datePublished"].startswith("2026-09-15")
    assert post["mainEntityOfPage"]["@id"] == "https://user.github.io/posts/post-0/"
    assert post["author"]["@id"] == post["publisher"]["@id"]              # organisation byline, no invented person
    org = next(x for x in nodes if x["@type"] == "Organization")
    assert org["@id"] == post["author"]["@id"] and org["name"] == "मराठी नजर"
    assert any(x["@type"] == "BreadcrumbList" for x in nodes)
    assert "संदर्भ / स्रोत" in html and "https://example.com/a" in html and "AI च्या मदतीने" in html


def test_news_posts_use_newsarticle(blog):
    b, out = built(blog, n=4)
    news = ld_nodes((out / "posts/post-3/index.html").read_text(encoding="utf-8"))
    assert any(x["@type"] == "NewsArticle" for x in news)
    tech = ld_nodes((out / "posts/post-0/index.html").read_text(encoding="utf-8"))
    assert any(x["@type"] == "Article" for x in tech) and not any(x["@type"] == "NewsArticle" for x in tech)


def test_home_has_website_and_searchaction(blog):
    b, out = built(blog)
    nodes = ld_nodes((out / "index.html").read_text(encoding="utf-8"))
    site = next(x for x in nodes if x["@type"] == "WebSite")
    assert site["potentialAction"]["@type"] == "SearchAction"
    assert "search_term_string" in site["potentialAction"]["target"]["urlTemplate"]
    assert any(x["@type"] == "ItemList" for x in nodes)


def test_faq_block_and_schema(blog):
    faq = [{"q": "हा प्रश्न आहे का?", "a": "हे उत्तर आहे."}, {"q": "दुसरा प्रश्न आहे का?", "a": "दुसरे उत्तर."}]
    blog.add(slug="withfaq", extra={"faq": faq})
    blog.add(slug="nofaq")
    Builder(blog.root, "https://user.github.io", now=NOW).build()
    out = blog.root / "public"
    html = (out / "posts/withfaq/index.html").read_text(encoding="utf-8")
    assert "वारंवार विचारले जाणारे प्रश्न" in html and "<summary>हा प्रश्न आहे का?</summary>" in html
    page = next(x for x in ld_nodes(html) if x["@type"] == "FAQPage")
    assert [q["name"] for q in page["mainEntity"]] == ["हा प्रश्न आहे का?", "दुसरा प्रश्न आहे का?"]
    # No FAQ on the page means no FAQ markup: the schema must match what a reader can see.
    assert not any(x["@type"] == "FAQPage" for x in ld_nodes((out / "posts/nofaq/index.html").read_text(encoding="utf-8")))


def test_toc_only_for_long_posts(blog):
    long_body = "".join(f"## शीर्षक {i}\n\nहा एक मराठी परिच्छेद आहे जो पुरेसा मोठा आहे. " * 12 + "\n\n" for i in range(4))
    blog.add(slug="long", body=long_body)
    blog.add(slug="short")
    Builder(blog.root, "https://user.github.io", now=NOW).build()
    out = blog.root / "public"
    long_html = (out / "posts/long/index.html").read_text(encoding="utf-8")
    assert "या लेखात काय आहे?" in long_html and 'href="#शीर्षक-0"' in long_html
    assert 'id="शीर्षक-0"' in long_html                       # the anchor the contents box points at
    assert "या लेखात काय आहे?" not in (out / "posts/short/index.html").read_text(encoding="utf-8")


def test_prev_next_links(blog):
    b, out = built(blog)
    mid = (out / "posts/post-1/index.html").read_text(encoding="utf-8")
    assert 'href="/posts/post-2/"' in mid and 'href="/posts/post-0/"' in mid
    newest = (out / "posts/post-2/index.html").read_text(encoding="utf-8")
    assert "नवीन लेख" not in newest.split('class="prevnext"')[1].split("</nav>")[0]


def test_related_can_be_curated(blog):
    blog.add(slug="a")
    blog.add(slug="b", category="health", date="2026-09-19T07:30:00+05:30")
    blog.add(slug="c", category="finance", date="2026-09-18T07:30:00+05:30", extra={"related": ["a"]})
    Builder(blog.root, "https://user.github.io", now=NOW).build()
    block = (blog.root / "public/posts/c/index.html").read_text(encoding="utf-8").split("हेही वाचा")[1]
    assert 'href="/posts/a/"' in block and 'href="/posts/b/"' not in block


def test_category_page_has_breadcrumbs_itemlist_and_feed(blog):
    b, out = built(blog)
    html = (out / "technology/index.html").read_text(encoding="utf-8")
    nodes = ld_nodes(html)
    assert any(x["@type"] == "BreadcrumbList" for x in nodes) and any(x["@type"] == "ItemList" for x in nodes)
    assert 'href="/technology/rss.xml"' in html
    feed = ET.parse(out / "technology/rss.xml").getroot()
    assert all("post-0" in i.find("link").text for i in feed.findall("channel/item"))


def test_trending_is_not_indexable(blog):
    b, out = built(blog)
    html = (out / "trending/index.html").read_text(encoding="utf-8")
    assert 'content="noindex, follow"' in html
    assert "/trending/" not in (out / "sitemap.xml").read_text(encoding="utf-8")


def test_sitemap_rss_robots(blog):
    b, out = built(blog)
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locs = [e.text for e in ET.parse(out / "sitemap.xml").getroot().findall("s:url/s:loc", ns)]
    assert "https://user.github.io/" in locs and "https://user.github.io/posts/post-2/" in locs
    assert "https://user.github.io/technology/" in locs
    assert not any("/search/" in l for l in locs)                    # noindex page kept out of the sitemap
    items = ET.parse(out / "rss.xml").getroot().findall("channel/item")
    assert len(items) == 3 and items[0].find("title").text.endswith("post-2")      # newest first
    assert "Sitemap: https://user.github.io/sitemap.xml" in (out / "robots.txt").read_text()
    assert 'noindex' in (out / "search/index.html").read_text(encoding="utf-8")


def test_category_disclaimers(blog):
    b, out = built(blog, n=4)
    assert "वैद्यकीय सल्ला" in (out / "posts/post-2/index.html").read_text(encoding="utf-8")     # health
    assert "SEBI" in (out / "posts/post-1/index.html").read_text(encoding="utf-8")                # finance
    assert "महत्त्वाची सूचना" not in (out / "posts/post-0/index.html").read_text(encoding="utf-8")  # technology


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
    assert 'href="/my-blog/technology/"' in html
    assert 'rel="canonical" href="https://user.github.io/my-blog/"' in html
    assert json.loads((out / "search.json").read_text())[0]["u"].startswith("/my-blog/posts/")


def test_pagination_and_archive(blog):
    blog.set_site(posts_per_page=2)
    for i in range(5):
        blog.add(slug=f"t{i}", category="technology", date=f"2026-09-{10 + i:02d}T07:30:00+05:30")
    Builder(blog.root, "https://user.github.io", now=NOW).build()
    out = blog.root / "public"
    assert (out / "technology/page/3/index.html").exists() and not (out / "technology/page/4").exists()
    p2 = (out / "technology/page/2/index.html").read_text(encoding="utf-8")
    assert 'rel="prev" href="https://user.github.io/technology/"' in p2 and 'rel="next"' in p2
    locs = (out / "sitemap.xml").read_text(encoding="utf-8")
    assert "https://user.github.io/technology/page/2/" in locs        # paginated pages belong in the sitemap
    archive = (out / "archive/index.html").read_text(encoding="utf-8").split('class="archive"')[1]
    assert archive.split("</ul>")[0].count("<li>") == 5
    assert len(list((out).glob("index.html"))) == 1
    assert (out / "index.html").read_text(encoding="utf-8").count('class="card ') >= 2


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


def test_ads_and_analytics_are_off_until_configured(blog):
    b, out = built(blog)
    home = (out / "index.html").read_text(encoding="utf-8")
    assert "adsbygoogle" not in home and "googletagmanager" not in home
    blog.set_site(ads={"client": "ca-pub-123"}, ga4_id="G-ABC123")
    Builder(blog.root, "https://user.github.io", now=NOW).build()
    home = (out / "index.html").read_text(encoding="utf-8")
    assert 'data-ad-client="ca-pub-123"' in home and "G-ABC123" in home


def test_html_is_escaped_in_titles(blog):
    blog.add(slug="esc", title='शीर्षक "A" & <b>B</b> चाचणी करणारे मोठे शीर्षक')
    Builder(blog.root, "https://user.github.io", now=NOW).build()
    html = (blog.root / "public/posts/esc/index.html").read_text(encoding="utf-8")
    assert "<b>B</b>" not in html.split("<main")[0] and "&lt;b&gt;B&lt;/b&gt;" in html
    assert "</script>" not in json.dumps(ld_nodes(html))             # JSON-LD cannot break out of its tag
