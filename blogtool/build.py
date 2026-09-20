"""Static site builder: content/ + templates/ + static/  ->  public/ (deployed by GitHub Pages)."""
from __future__ import annotations

import json
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from xml.sax.saxutils import escape

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import mr
from .content import Post, Site, load_pages, load_posts, load_site
from .images import MODERN, WIDTHS, derivative_name

# Category slugs live at the top level (/finance/), so they must not collide with these.
RESERVED_PATHS = {"posts", "archive", "search", "trending", "images", "fonts", "category", "page",
                  "rss.xml", "sitemap.xml", "robots.txt", "search.json"}
TRENDING_MAX = 6
RAIL_MAX = 4


class BuildError(RuntimeError):
    pass


class Builder:
    def __init__(self, root: Path, base_url: str | None = None, now: datetime | None = None, out: Path | None = None):
        self.root = root
        self.site = load_site(root, base_url)
        self.now = now or datetime.now(timezone.utc)
        self.out = out or root / "public"
        self.posts = load_posts(root, self.site, self.now)
        self.pages = load_pages(root)
        self._check_slugs()
        self._resolve_images()
        self.by_cat: dict[str, list[Post]] = defaultdict(list)
        for p in self.posts:
            self.by_cat[p.category].append(p)
        # Only categories that actually have something to show: an empty category page is thin content
        # and an empty nav link is a dead end.
        self.live_cats = {s: c for s, c in self.site.categories.items() if self.by_cat.get(s)}
        self.env = Environment(loader=FileSystemLoader(str(root / "templates")),
                               autoescape=select_autoescape(["html", "xml"]), trim_blocks=True, lstrip_blocks=True)
        self.env.globals.update(site=self.site, url=self.url, abs_url=self.abs_url,
                                categories=self.site.categories, nav_cats=self.live_cats,
                                pages=self.pages, now=self.now, picture=self.picture,
                                cat_url=self.cat_url, has_page=lambda s: s in self.pages)
        self.env.globals["image_kind"] = lambda slug: self.image_kind.get(slug, {}).get("kind", "")
        self.env.globals["default_image"] = self.default_image
        self.env.filters.update(mr_date=mr.date, mr_num=mr.num, month_year=mr.month_year)
        self.written: list[str] = []
        self.indexable: list[tuple[str, datetime]] = []

    # -- checks
    def _check_slugs(self) -> None:
        for slug in self.site.categories:
            if slug in RESERVED_PATHS:
                raise BuildError(f"category slug {slug!r} collides with a reserved site path")
            if slug in self.pages:
                raise BuildError(f"category slug {slug!r} collides with the page content/pages/{slug}.md")

    # -- images
    def _resolve_images(self) -> None:
        """Use an explicit front-matter `image`, else the generated static/images/posts/<slug>.jpg if it exists."""
        manifest_file = self.root / "data" / "images.json"
        self.image_kind = json.loads(manifest_file.read_text(encoding="utf-8")) if manifest_file.exists() else {}
        for p in self.posts:
            if not p.image and (self.root / "static" / "images" / "posts" / f"{p.slug}.jpg").exists():
                p.image = f"/images/posts/{p.slug}.jpg"
        self.default_image = "/og-default.jpg" if (self.root / "static" / "og-default.jpg").exists() else ""

    def picture(self, post: Post, sizes: str, priority: bool = False) -> dict:
        """Everything _picture.html needs: the modern formats when their files exist, else a plain <img>."""
        src = post.image
        d = {"src": self.url(src) if not src.startswith("http") else src, "alt": post.image_alt,
             "sizes": sizes, "priority": priority, "sources": [], "jpg_srcset": ""}
        if not src.startswith(f"/images/posts/{post.slug}."):
            return d                                          # an external or hand-set image: no derivatives
        img_dir = self.root / "static" / "images" / "posts"

        def srcset(fmt):
            out = [(w, f"/images/posts/{derivative_name(post.slug, w, fmt)}") for w in WIDTHS
                   if (img_dir / derivative_name(post.slug, w, fmt)).exists()]
            return ", ".join(f"{self.url(u)} {w}w" for w, u in out)

        for fmt in MODERN:
            if ss := srcset(fmt):
                d["sources"].append({"type": f"image/{fmt}", "srcset": ss})
        jpg = [(w, f"/images/posts/{derivative_name(post.slug, w, 'jpg')}") for w in WIDTHS
               if (img_dir / derivative_name(post.slug, w, "jpg")).exists()]
        jpg.append((1200, src))
        d["jpg_srcset"] = ", ".join(f"{self.url(u)} {w}w" for w, u in sorted(set(jpg)))
        return d

    # -- urls
    def url(self, path: str) -> str:
        return f"{self.site.base_path}{path}"

    def abs_url(self, path: str) -> str:
        return f"{self.site.origin}{self.url(path)}"

    def cat_url(self, slug: str) -> str:
        return f"/{slug}/"

    # -- io
    def write(self, rel: str, content: str) -> None:
        p = self.out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        self.written.append(rel)

    def render(self, template: str, rel: str, indexable: bool = True, lastmod: datetime | None = None, **ctx) -> None:
        self.write(rel, self.env.get_template(template).render(**ctx))
        if indexable and not ctx.get("noindex"):
            path = "/" + rel[: -len("index.html")] if rel.endswith("index.html") else "/" + rel
            self.indexable.append((path, lastmod or self.now))

    # -- structured data
    def ld_organization(self) -> dict:
        org = self.site.organization or {}
        d = {"@type": "Organization", "@id": self.abs_url("/#organization"), "name": self.site.title,
             "url": self.abs_url("/"), "description": self.site.description}
        if org.get("logo"):
            d["logo"] = {"@type": "ImageObject", "url": self.abs_url(org["logo"])}
        if org.get("same_as"):
            d["sameAs"] = list(org["same_as"])
        if self.site.contact_email:
            d["email"] = self.site.contact_email
        return d

    def ld_website(self) -> dict:
        return {"@type": "WebSite", "@id": self.abs_url("/#website"), "name": self.site.title,
                "url": self.abs_url("/"), "inLanguage": self.site.language,
                "description": self.site.description,
                "publisher": {"@id": self.abs_url("/#organization")},
                "potentialAction": {"@type": "SearchAction",
                                    "target": {"@type": "EntryPoint",
                                               "urlTemplate": self.abs_url("/search/") + "?q={search_term_string}"},
                                    "query-input": "required name=search_term_string"}}

    def ld_breadcrumbs(self, trail: list[tuple[str, str]]) -> dict:
        return {"@type": "BreadcrumbList",
                "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": name, "item": item}
                                    for i, (name, item) in enumerate(trail)]}

    def ld_article(self, post: Post, canonical: str) -> dict:
        cat = self.site.categories[post.category]
        d = {"@type": "NewsArticle" if post.category == "news" else "Article",
             "headline": post.title, "description": post.meta_description, "inLanguage": self.site.language,
             "datePublished": post.date.isoformat(), "dateModified": post.lastmod.isoformat(),
             "mainEntityOfPage": {"@type": "WebPage", "@id": canonical},
             "articleSection": cat["name"], "keywords": ", ".join(post.tags), "wordCount": post.words,
             "author": {"@id": self.abs_url("/#organization")},
             "publisher": {"@id": self.abs_url("/#organization")}}
        if post.image:
            d["image"] = [post.image if post.image.startswith("http") else self.abs_url(post.image)]
        return d

    @staticmethod
    def ld_faq(post: Post) -> dict:
        return {"@type": "FAQPage",
                "mainEntity": [{"@type": "Question", "name": f["q"],
                                "acceptedAnswer": {"@type": "Answer", "text": f["a"]}} for f in post.faq]}

    def ld_itemlist(self, posts: list[Post]) -> dict:
        return {"@type": "ItemList", "itemListOrder": "https://schema.org/ItemListOrderDescending",
                "itemListElement": [{"@type": "ListItem", "position": i + 1, "url": self.abs_url(p.url_path),
                                     "name": p.title} for i, p in enumerate(posts)]}

    def graph(self, *nodes: dict) -> str:
        """JSON-LD for one page. '<' is escaped so a title containing </script> cannot break out of the tag."""
        return json.dumps({"@context": "https://schema.org", "@graph": list(nodes)},
                          ensure_ascii=False).replace("<", "\\u003c")

    # -- selections
    def trending(self) -> list[Post]:
        flagged = [p for p in self.posts if p.trending]
        return (flagged or self.posts)[:TRENDING_MAX]

    def hero(self) -> tuple[Post | None, list[Post]]:
        if not self.posts:
            return None, []
        lead = next((p for p in self.posts if p.featured), self.posts[0])
        rest = [p for p in self.posts if p.slug != lead.slug][:4]
        return lead, rest

    def related(self, post: Post, n: int = 3) -> list[Post]:
        """Manual `related:` wins; otherwise score by shared tags and category, newest first on ties."""
        if post.related_slugs:
            by_slug = {p.slug: p for p in self.posts}
            picked = [by_slug[s] for s in post.related_slugs if s in by_slug and s != post.slug]
            if picked:
                return picked[:n]
        tags = set(post.tags)
        scored = sorted((p for p in self.posts if p.slug != post.slug),
                        key=lambda p: (len(tags & set(p.tags)) * 2 + (3 if p.category == post.category else 0), p.date),
                        reverse=True)
        return scored[:n]

    def neighbours(self, post: Post) -> tuple[Post | None, Post | None]:
        """(newer, older) by date — the reader's previous/next article links."""
        i = next(i for i, p in enumerate(self.posts) if p.slug == post.slug)
        return (self.posts[i - 1] if i > 0 else None, self.posts[i + 1] if i + 1 < len(self.posts) else None)

    # -- build
    def build(self) -> dict:
        if self.out.exists():
            shutil.rmtree(self.out)
        self.out.mkdir(parents=True)
        static = self.root / "static"
        if static.exists():
            shutil.copytree(static, self.out, dirs_exist_ok=True)
        s, posts = self.site, self.posts

        self.build_home()
        for p in posts:
            self.build_post(p)
        for slug in self.live_cats:
            self.build_category(slug)
        for slug in self.live_cats:                    # old /category/<slug>/ URLs keep working
            self.write_redirect(f"category/{slug}/index.html", self.cat_url(slug))
        if "technology" in self.live_cats:             # the category was renamed from 'tech'
            self.write_redirect("category/tech/index.html", self.cat_url("technology"))
        self.build_trending()
        self.build_archive()
        self.build_search()
        self.build_pages()
        self.build_feeds()

        # No canonical on 404: pointing it at the home page would declare the 404 a duplicate of it.
        self.render("404.html", "404.html", indexable=False, canonical="",
                    page_title=f"पान सापडले नाही | {s.title}", meta_description=s.description, noindex=True)
        self.write("search.json", json.dumps([
            {"t": p.title, "d": p.description, "u": self.url(p.url_path), "c": s.categories[p.category]["name"],
             "s": p.category, "g": " ".join(p.tags), "y": p.date.strftime("%Y-%m-%d")} for p in posts],
            ensure_ascii=False))
        self.write("sitemap.xml", self.sitemap())
        self.write("robots.txt", f"User-agent: *\nAllow: /\n\nSitemap: {self.abs_url('/sitemap.xml')}\n")
        self.write(".nojekyll", "")
        if s.custom_domain:
            self.write("CNAME", s.custom_domain + "\n")
        return {"posts": len(posts), "files": len(self.written), "out": str(self.out)}

    def build_home(self) -> None:
        s = self.site
        lead, secondary = self.hero()
        shown = {p.slug for p in ([lead] if lead else []) + secondary}
        latest = [p for p in self.posts if p.slug not in shown][: s.posts_per_page]
        rails = [(slug, c, self.by_cat[slug][:RAIL_MAX]) for slug, c in self.live_cats.items()]
        self.render("index.html", "index.html",
                    lead=lead, secondary=secondary, latest=latest, rails=rails, trending=self.trending(),
                    canonical=self.abs_url("/"), page_title=f"{s.title} | {s.tagline}",
                    meta_description=s.description, is_home=True, total=len(self.posts),
                    lastmod=max((p.lastmod for p in self.posts), default=self.now),
                    ld=self.graph(self.ld_organization(), self.ld_website(),
                                  self.ld_itemlist(self.posts[:10]) if self.posts else {"@type": "WebPage"}))

    def build_post(self, p: Post) -> None:
        s, cat = self.site, self.site.categories[p.category]
        canonical = self.abs_url(p.url_path)
        newer, older = self.neighbours(p)
        nodes = [self.ld_organization(), self.ld_article(p, canonical),
                 self.ld_breadcrumbs([(s.title, self.abs_url("/")), (cat["name"], self.abs_url(self.cat_url(p.category))),
                                      (p.title, canonical)])]
        if p.faq:
            nodes.append(self.ld_faq(p))
        self.render("post.html", f"posts/{p.slug}/index.html", lastmod=p.lastmod,
                    post=p, related=self.related(p), newer=newer, older=older, cat=cat, canonical=canonical,
                    page_title=f"{p.meta_title} | {s.title}", meta_description=p.meta_description,
                    ld=self.graph(*nodes))

    def build_category(self, slug: str) -> None:
        s, cat, items = self.site, self.site.categories[slug], self.by_cat[slug]
        per = s.posts_per_page
        pages = max(1, -(-len(items) // per))
        base = self.cat_url(slug)
        for n in range(1, pages + 1):
            path = base if n == 1 else f"{base}page/{n}/"
            chunk = items[(n - 1) * per: n * per]
            canonical = self.abs_url(path)
            title = cat["name"] if n == 1 else f"{cat['name']} — पान {mr.num(n)}"
            self.render("list.html", path.strip("/") + "/index.html",
                        lastmod=max(p.lastmod for p in items),
                        posts=chunk, heading=cat["name"], intro=cat.get("intro") or cat["description"],
                        page=n, pages=pages, base=base, canonical=canonical,
                        page_title=f"{title} | {s.title}", meta_description=cat["description"], cat_slug=slug,
                        cat=cat, feed=f"{base}rss.xml",
                        ld=self.graph(self.ld_organization(),
                                      self.ld_breadcrumbs([(s.title, self.abs_url("/")), (cat["name"], canonical)]),
                                      self.ld_itemlist(chunk)))

    def build_trending(self) -> None:
        """A reader's shortcut, not an indexable page: it restates posts indexed under their own URLs."""
        s = self.site
        self.render("list.html", "trending/index.html", indexable=False, noindex=True,
                    posts=self.trending(), heading="ट्रेंडिंग", page=1, pages=1, base="/trending/",
                    intro="सध्या सर्वाधिक वाचले जाणारे आणि ताजे लेख एकाच ठिकाणी.",
                    canonical=self.abs_url("/trending/"), page_title=f"ट्रेंडिंग | {s.title}",
                    meta_description=f"{s.title} वरील ताजे आणि महत्त्वाचे लेख.", cat_slug="", cat=None)

    def build_archive(self) -> None:
        s = self.site
        months: dict[str, list[Post]] = defaultdict(list)
        for p in self.posts:
            months[p.date.strftime("%Y-%m")].append(p)
        self.render("archive.html", "archive/index.html", months=sorted(months.items(), reverse=True),
                    lastmod=max((p.lastmod for p in self.posts), default=self.now),
                    canonical=self.abs_url("/archive/"), page_title=f"सर्व लेख | {s.title}",
                    meta_description=f"{s.title} वरील सर्व लेख: महिन्यानुसार.",
                    ld=self.graph(self.ld_organization(),
                                  self.ld_breadcrumbs([(s.title, self.abs_url("/")),
                                                       ("सर्व लेख", self.abs_url("/archive/"))])))

    def build_search(self) -> None:
        s = self.site
        self.render("search.html", "search/index.html", indexable=False, canonical=self.abs_url("/search/"),
                    page_title=f"शोधा | {s.title}", meta_description=f"{s.title} वर लेख शोधा.", noindex=True)

    def build_pages(self) -> None:
        s = self.site
        for slug, page in self.pages.items():
            if slug == "contact" and not s.contact_email:
                continue
            if slug == "contact":
                mail = escape(s.contact_email)
                page = type(page)(page.slug, page.title, page.description,
                                  page.html + f'<p><a href="mailto:{mail}">{mail}</a></p>', page.body)
            canonical = self.abs_url(f"/{slug}/")
            self.render("page.html", f"{slug}/index.html", page=page, canonical=canonical,
                        page_title=f"{page.title} | {s.title}", meta_description=page.description or s.description,
                        ld=self.graph(self.ld_organization(),
                                      self.ld_breadcrumbs([(s.title, self.abs_url("/")), (page.title, canonical)])))

    def build_feeds(self) -> None:
        self.write("rss.xml", self.rss(self.posts[:30], self.site.title, "/"))
        for slug, cat in self.live_cats.items():
            self.write(f"{slug}/rss.xml",
                       self.rss(self.by_cat[slug][:30], f"{cat['name']} | {self.site.title}", self.cat_url(slug)))

    def write_redirect(self, rel: str, to: str) -> None:
        """GitHub Pages has no server redirects, so an old URL gets a canonical + meta-refresh stub."""
        self.write(rel, self.env.get_template("redirect.html").render(
            target=self.url(to), canonical=self.abs_url(to), page_title=self.site.title))

    def sitemap(self) -> str:
        body = "".join(f"<url><loc>{escape(self.abs_url(u))}</loc>"
                       f"<lastmod>{d.isoformat(timespec='seconds')}</lastmod></url>\n"
                       for u, d in sorted(set(self.indexable)))
        return ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                f"{body}</urlset>\n")

    def rss(self, posts: list[Post], title: str, link: str) -> str:
        s = self.site
        items = "".join(
            f"<item><title>{escape(p.title)}</title><link>{escape(self.abs_url(p.url_path))}</link>"
            f"<guid isPermaLink=\"true\">{escape(self.abs_url(p.url_path))}</guid>"
            f"<pubDate>{format_datetime(p.date)}</pubDate>"
            f"<category>{escape(s.categories[p.category]['name'])}</category>"
            f"<description>{escape(p.description)}</description></item>\n" for p in posts)
        last = format_datetime(posts[0].date) if posts else format_datetime(self.now)
        feed_url = self.abs_url(f"{link}rss.xml" if link != "/" else "/rss.xml")
        return ('<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">'
                f"<channel><title>{escape(title)}</title><link>{escape(self.abs_url(link))}</link>"
                f"<description>{escape(s.description)}</description><language>{s.language}</language>"
                f"<lastBuildDate>{last}</lastBuildDate>"
                f'<atom:link href="{escape(feed_url)}" rel="self" type="application/rss+xml"/>\n'
                f"{items}</channel></rss>\n")
