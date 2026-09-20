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


class Builder:
    def __init__(self, root: Path, base_url: str | None = None, now: datetime | None = None, out: Path | None = None):
        self.root = root
        self.site = load_site(root, base_url)
        self.now = now or datetime.now(timezone.utc)
        self.out = out or root / "public"
        self.posts = load_posts(root, self.site, self.now)
        self._resolve_images()
        self.pages = load_pages(root)
        self.env = Environment(loader=FileSystemLoader(str(root / "templates")),
                               autoescape=select_autoescape(["html", "xml"]), trim_blocks=True, lstrip_blocks=True)
        self.env.globals.update(site=self.site, url=self.url, abs_url=self.abs_url, categories=self.site.categories,
                                pages=self.pages, now=self.now)
        self.env.globals["image_kind"] = lambda slug: self.image_kind.get(slug, {}).get("kind", "")
        self.env.globals["default_image"] = self.default_image
        self.env.filters.update(mr_date=mr.date, mr_num=mr.num, month_year=mr.month_year)
        self.written: list[str] = []

    def _resolve_images(self) -> None:
        """Use an explicit front-matter `image`, else the generated static/images/posts/<slug>.jpg if it exists."""
        manifest_file = self.root / "data" / "images.json"
        self.image_kind = json.loads(manifest_file.read_text(encoding="utf-8")) if manifest_file.exists() else {}
        for p in self.posts:
            if not p.image and (self.root / "static" / "images" / "posts" / f"{p.slug}.jpg").exists():
                p.image = f"/images/posts/{p.slug}.jpg"
        self.default_image = "/og-default.jpg" if (self.root / "static" / "og-default.jpg").exists() else ""

    # -- urls
    def url(self, path: str) -> str:
        return f"{self.site.base_path}{path}"

    def abs_url(self, path: str) -> str:
        return f"{self.site.origin}{self.url(path)}"

    # -- io
    def write(self, rel: str, content: str) -> None:
        p = self.out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        self.written.append(rel)

    def render(self, template: str, rel: str, **ctx) -> None:
        self.write(rel, self.env.get_template(template).render(**ctx))

    # -- build
    def build(self) -> dict:
        if self.out.exists():
            shutil.rmtree(self.out)
        self.out.mkdir(parents=True)
        static = self.root / "static"
        if static.exists():
            shutil.copytree(static, self.out, dirs_exist_ok=True)
        s, posts = self.site, self.posts
        by_cat: dict[str, list[Post]] = defaultdict(list)
        for p in posts:
            by_cat[p.category].append(p)

        latest = posts[: s.posts_per_page]
        self.render("index.html", "index.html", posts=latest, by_cat=by_cat, canonical=self.abs_url("/"),
                    page_title=s.title, meta_description=s.description, is_home=True, total=len(posts))
        for p in posts:
            related = self.related(p, posts)
            self.render("post.html", f"posts/{p.slug}/index.html", post=p, related=related,
                        canonical=self.abs_url(p.url_path), page_title=f"{p.title} | {s.title}",
                        meta_description=p.description, cat=s.categories[p.category])
        per = s.posts_per_page
        for slug, cat in s.categories.items():
            items = by_cat.get(slug, [])
            pages = max(1, -(-len(items) // per))
            for n in range(1, pages + 1):
                base = f"/category/{slug}/"
                path = base if n == 1 else f"{base}page/{n}/"
                self.render("list.html", path.strip("/") + "/index.html", posts=items[(n - 1) * per: n * per],
                            heading=cat["name"], intro=cat["description"], page=n, pages=pages, base=base,
                            canonical=self.abs_url(path), page_title=f"{cat['name']} | {s.title}",
                            meta_description=cat["description"], cat_slug=slug)
        months: dict[str, list[Post]] = defaultdict(list)
        for p in posts:
            months[p.date.strftime("%Y-%m")].append(p)
        self.render("archive.html", "archive/index.html", months=sorted(months.items(), reverse=True),
                    canonical=self.abs_url("/archive/"), page_title=f"सर्व लेख | {s.title}",
                    meta_description=f"{s.title} वरील सर्व लेख: महिन्यानुसार.")
        self.render("search.html", "search/index.html", canonical=self.abs_url("/search/"),
                    page_title=f"शोधा | {s.title}", meta_description=f"{s.title} वर लेख शोधा.", noindex=True)
        for slug, page in self.pages.items():
            if slug == "contact" and not s.contact_email:
                continue
            if slug == "contact":
                mail = escape(s.contact_email)
                page = type(page)(page.slug, page.title, page.description,
                                  page.html + f'<p><a href="mailto:{mail}">{mail}</a></p>', page.body)
            self.render("page.html", f"{slug}/index.html", page=page, canonical=self.abs_url(f"/{slug}/"),
                        page_title=f"{page.title} | {s.title}", meta_description=page.description or s.description)
        self.render("404.html", "404.html", canonical=self.abs_url("/"), page_title=f"पान सापडले नाही | {s.title}",
                    meta_description=s.description, noindex=True)
        self.write("search.json", json.dumps([
            {"t": p.title, "d": p.description, "u": self.url(p.url_path), "c": s.categories[p.category]["name"],
             "g": " ".join(p.tags), "y": p.date.strftime("%Y-%m-%d")} for p in posts], ensure_ascii=False))
        self.write("sitemap.xml", self.sitemap(posts))
        self.write("rss.xml", self.rss(posts[:30]))
        self.write("robots.txt", f"User-agent: *\nAllow: /\n\nSitemap: {self.abs_url('/sitemap.xml')}\n")
        self.write(".nojekyll", "")
        if s.custom_domain:
            self.write("CNAME", s.custom_domain + "\n")
        return {"posts": len(posts), "files": len(self.written), "out": str(self.out)}

    @staticmethod
    def related(post: Post, posts: list[Post], n: int = 3) -> list[Post]:
        tags = set(post.tags)
        scored = sorted((p for p in posts if p.slug != post.slug),
                        key=lambda p: (len(tags & set(p.tags)) + (2 if p.category == post.category else 0), p.date),
                        reverse=True)
        return scored[:n]

    def sitemap(self, posts: list[Post]) -> str:
        s = self.site
        urls = [(self.abs_url("/"), max((p.lastmod for p in posts), default=self.now)), (self.abs_url("/archive/"),
                max((p.lastmod for p in posts), default=self.now))]
        urls += [(self.abs_url(f"/category/{c}/"), max((p.lastmod for p in posts if p.category == c),
                                                       default=self.now)) for c in s.categories]
        urls += [(self.abs_url(f"/{slug}/"), self.now) for slug in self.pages
                 if not (slug == "contact" and not s.contact_email)]
        urls += [(self.abs_url(p.url_path), p.lastmod) for p in posts]
        body = "".join(f"<url><loc>{escape(u)}</loc><lastmod>{d.isoformat(timespec='seconds')}</lastmod></url>\n"
                       for u, d in urls)
        return ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                f"{body}</urlset>\n")

    def rss(self, posts: list[Post]) -> str:
        s = self.site
        items = "".join(
            f"<item><title>{escape(p.title)}</title><link>{escape(self.abs_url(p.url_path))}</link>"
            f"<guid isPermaLink=\"true\">{escape(self.abs_url(p.url_path))}</guid>"
            f"<pubDate>{format_datetime(p.date)}</pubDate>"
            f"<category>{escape(s.categories[p.category]['name'])}</category>"
            f"<description>{escape(p.description)}</description></item>\n" for p in posts)
        last = format_datetime(posts[0].date) if posts else format_datetime(self.now)
        return ('<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">'
                f"<channel><title>{escape(s.title)}</title><link>{escape(self.abs_url('/'))}</link>"
                f"<description>{escape(s.description)}</description><language>{s.language}</language>"
                f"<lastBuildDate>{last}</lastBuildDate>"
                f'<atom:link href="{escape(self.abs_url("/rss.xml"))}" rel="self" type="application/rss+xml"/>\n'
                f"{items}</channel></rss>\n")
