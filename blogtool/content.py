"""Loading posts and pages from content/ (Markdown with YAML front matter)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path

import markdown
import unicodedata
import yaml

from . import mr

FRONT = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.S)


@dataclass
class Site:
    title: str
    tagline: str
    description: str
    author: str
    base_url: str
    language: str = "mr"
    locale: str = "mr_IN"
    timezone_offset: str = "+05:30"
    contact_email: str = ""
    google_site_verification: str = ""
    custom_domain: str = ""
    posts_per_page: int = 12
    ga4_id: str = ""
    ads: dict = field(default_factory=dict)
    organization: dict = field(default_factory=dict)
    daily_categories: list = field(default_factory=list)
    categories: dict = field(default_factory=dict)

    @property
    def base_path(self) -> str:
        """URL path prefix, e.g. '/repo' for project pages, '' for user pages or a custom domain."""
        from urllib.parse import urlparse
        return urlparse(self.base_url).path.rstrip("/")

    @property
    def origin(self) -> str:
        from urllib.parse import urlparse
        u = urlparse(self.base_url)
        return f"{u.scheme}://{u.netloc}"

    @property
    def ads_enabled(self) -> bool:
        return bool((self.ads or {}).get("client"))

    def tz(self) -> timezone:
        sign = -1 if self.timezone_offset.startswith("-") else 1
        h, m = self.timezone_offset.lstrip("+-").split(":")
        return timezone(sign * timedelta(hours=int(h), minutes=int(m)))


def load_site(root: Path, base_url: str | None = None) -> Site:
    raw = json.loads((root / "site.json").read_text(encoding="utf-8"))
    if base_url:
        raw["base_url"] = base_url
    if raw.get("custom_domain") and not base_url:
        raw["base_url"] = f"https://{raw['custom_domain']}"
    raw["base_url"] = raw["base_url"].rstrip("/")
    return Site(**raw)


@dataclass
class Post:
    slug: str
    title: str
    description: str
    date: datetime
    category: str
    tags: list
    sources: list
    body: str
    path: Path
    updated: datetime | None = None
    draft: bool = False
    ai_assisted: bool = True
    image: str = ""
    html: str = ""
    seo_title: str = ""
    seo_description: str = ""
    faq: list = field(default_factory=list)
    pros: list = field(default_factory=list)
    cons: list = field(default_factory=list)
    related_slugs: list = field(default_factory=list)
    featured: bool = False
    trending: bool = False
    toc: list = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    @property
    def words(self) -> int:
        return mr.word_count(self.body)

    @property
    def minutes(self) -> int:
        return mr.reading_minutes(self.body)

    @property
    def url_path(self) -> str:
        return f"/posts/{self.slug}/"

    @property
    def image_alt(self) -> str:
        return str(self.raw.get("image_alt") or self.title)

    @property
    def lastmod(self) -> datetime:
        return self.updated or self.date

    @property
    def meta_title(self) -> str:
        """Shorter headline for <title>/OG when the display headline is long."""
        return self.seo_title or self.title

    @property
    def meta_description(self) -> str:
        return self.seo_description or self.description

    @property
    def was_updated(self) -> bool:
        return bool(self.updated and self.updated.date() != self.date.date())


class ContentError(ValueError):
    pass


PLAIN_SCALARS = re.compile(
    r"^(title|description|seo_title|seo_description|image|image_alt|image_prompt|slug|category)"
    r":[ \t]*(?![\"'|>\[{])(.+?)[ \t]*$", re.M)


def _autoquote(block: str) -> str:
    """Quote plain top-level text fields. A ': ' inside an unquoted Marathi title/description is the most common
    reason AI-written front matter fails to parse (e.g.  title: UPI: फसवणूक टाळा)."""
    def q(m):
        return f'{m.group(1)}: "{m.group(2).replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34))}"'
    return PLAIN_SCALARS.sub(q, block)


def parse_front(text: str, path: Path | str = "") -> tuple[dict, str]:
    m = FRONT.match(text)
    if not m:
        raise ContentError(f"{path}: missing YAML front matter (--- ... ---)")
    try:
        try:
            meta = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            meta = yaml.safe_load(_autoquote(m.group(1))) or {}
    except yaml.YAMLError as exc:
        raise ContentError(f"{path}: invalid YAML front matter: {exc}") from exc
    if not isinstance(meta, dict):
        raise ContentError(f"{path}: front matter must be a mapping")
    return meta, m.group(2).strip()


def _dt(value, site: Site, path) -> datetime:
    if isinstance(value, datetime):
        d = value
    else:
        try:
            d = datetime.fromisoformat(str(value))
        except ValueError as exc:
            raise ContentError(f"{path}: invalid date {value!r} (use e.g. 2026-09-20T07:30:00+05:30)") from exc
    return d if d.tzinfo else d.replace(tzinfo=site.tz())


DEVANAGARI_BLOCK = r"\u0900-\u097F"


def slug_mr(value: str, separator: str = "-") -> str:
    r"""Heading id that keeps Marathi readable. Python's \w drops the matras (Mn marks), which turns
    'म्हणजे' into 'महणज', so the Devanagari block is allowed explicitly."""
    v = unicodedata.normalize("NFC", str(value)).strip().lower()
    v = re.sub(rf"[^\w\s{DEVANAGARI_BLOCK}-]", "", v, flags=re.U)
    return re.sub(r"[-\s]+", separator, v).strip(separator)


def _flatten_toc(tokens, out) -> list:
    """markdown's toc_tokens tree -> a flat [{level, id, name}] list for the on-page contents box."""
    for t in tokens:
        out.append({"level": t["level"], "id": t["id"], "name": re.sub(r"<[^>]+>", "", t["name"]).strip()})
        _flatten_toc(t.get("children") or [], out)
    return out


def render_markdown(body: str) -> tuple[str, list]:
    """Returns (html, toc). 'toc' gives the h2/h3 outline; headings get ids so the box can link to them."""
    md = markdown.Markdown(
        extensions=["extra", "sane_lists", "smarty", "admonition", "toc"],
        extension_configs={"smarty": {"smart_quotes": False},
                           "toc": {"toc_depth": "2-3", "anchorlink": False, "permalink": False,
                                   "slugify": slug_mr}})
    html = md.convert(body)
    return html, _flatten_toc(getattr(md, "toc_tokens", []), [])


def _faq(meta, path) -> list:
    """[{q, a}] from front matter; the answer is rendered as Markdown so it can hold links and lists."""
    out = []
    for i, item in enumerate(meta.get("faq") or []):
        if not (isinstance(item, dict) and str(item.get("q", "")).strip() and str(item.get("a", "")).strip()):
            raise ContentError(f"{path}: faq #{i + 1} needs a 'q' and an 'a'")
        out.append({"q": str(item["q"]).strip(), "a": render_markdown(str(item["a"]).strip())[0]})
    return out


def load_post(path: Path, site: Site) -> Post:
    meta, body = parse_front(path.read_text(encoding="utf-8"), path)
    for key in ("title", "description", "date", "category", "slug"):
        if not meta.get(key):
            raise ContentError(f"{path}: missing front matter field '{key}'")
    p = Post(slug=str(meta["slug"]), title=str(meta["title"]).strip(), description=str(meta["description"]).strip(),
             date=_dt(meta["date"], site, path), category=str(meta["category"]),
             tags=[str(t) for t in (meta.get("tags") or [])], sources=list(meta.get("sources") or []),
             body=body, path=path, updated=_dt(meta["updated"], site, path) if meta.get("updated") else None,
             draft=bool(meta.get("draft", False)), ai_assisted=bool(meta.get("ai_assisted", True)),
             image=str(meta.get("image", "") or ""),
             seo_title=str(meta.get("seo_title", "") or "").strip(),
             seo_description=str(meta.get("seo_description", "") or "").strip(),
             faq=_faq(meta, path),
             pros=[str(x) for x in (meta.get("pros") or [])], cons=[str(x) for x in (meta.get("cons") or [])],
             related_slugs=[str(x) for x in (meta.get("related") or [])],
             featured=bool(meta.get("featured", False)), trending=bool(meta.get("trending", False)),
             raw=meta)
    p.html, p.toc = render_markdown(body)
    return p


def load_posts(root: Path, site: Site, now: datetime | None = None, include_hidden: bool = False) -> list[Post]:
    """All posts, newest first. Drafts and posts dated in the future are hidden unless include_hidden."""
    now = now or datetime.now(timezone.utc)
    posts = [load_post(p, site) for p in sorted((root / "content" / "posts").rglob("*.md"))]
    if not include_hidden:
        posts = [p for p in posts if not p.draft and p.date <= now]
    return sorted(posts, key=lambda p: p.date, reverse=True)


@dataclass
class Page:
    slug: str
    title: str
    description: str
    html: str
    body: str


def load_pages(root: Path) -> dict[str, Page]:
    out = {}
    d = root / "content" / "pages"
    for path in sorted(d.glob("*.md")) if d.exists() else []:
        meta, body = parse_front(path.read_text(encoding="utf-8"), path)
        out[path.stem] = Page(path.stem, str(meta.get("title", path.stem)), str(meta.get("description", "")),
                              render_markdown(body)[0], body)
    return out
