"""Convert the Markdown posts in content/posts/ into Blogger-ready HTML.

The site renders a post from Markdown *plus* front matter (image, disclaimer, pros/cons, FAQ, sources,
tags, AI note) using Jinja templates and a stylesheet. Blogger has neither: a post body is one blob of
HTML and the theme supplies no classes we control. So this module:

  1. reuses blogtool's own render_markdown() so the prose HTML is byte-identical to the live site,
  2. replaces the class-based constructs (admonitions, tables) with inline styles that survive any theme,
  3. appends the parts the templates add (disclaimer, pros/cons, FAQ, sources, tags, AI note),
  4. rewrites relative internal links and the hero image to absolute URLs.

Nothing here touches content/posts/. Output goes to migration/out/.
"""
from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blogtool.content import load_site, load_post  # noqa: E402

# Inline styles, because Blogger themes will not have our stylesheet. Kept deliberately plain so they
# read correctly on both a light and a dark Blogger theme.
S_NOTE = ("border:1px solid #d7dbe0;border-left:4px solid #1d4ed8;border-radius:8px;"
          "padding:12px 16px;margin:20px 0;background:rgba(29,78,216,.04)")
S_NOTE_TITLE = "margin:0 0 6px;font-weight:700"
S_DISCLAIMER = ("border:1px solid #e6d9a8;border-radius:8px;padding:12px 16px;margin:20px 0;"
                "background:rgba(234,179,8,.08);font-size:.95em")
S_TABLE = "border-collapse:collapse;width:100%;margin:20px 0;font-size:.97em"
S_TH = "border:1px solid #d7dbe0;padding:8px 10px;text-align:left;background:rgba(0,0,0,.04);font-weight:700"
S_TD = "border:1px solid #d7dbe0;padding:8px 10px;text-align:left"
S_PC_WRAP = "margin:24px 0"
S_PC_PRO = "border:1px solid #bbf7d0;border-radius:8px;padding:12px 16px;margin:0 0 12px;background:rgba(21,128,61,.05)"
S_PC_CON = "border:1px solid #fecaca;border-radius:8px;padding:12px 16px;margin:0;background:rgba(220,38,38,.05)"
S_SMALL = "font-size:.9em;color:#555"
S_CAPTION = "font-size:.88em;color:#666;margin:6px 0 0"


def style_prose(h: str) -> str:
    """Swap the stylesheet-dependent constructs for inline-styled equivalents."""
    # !!! note "title"  ->  a bordered box. The admonition extension never nests divs here (verified).
    def note(m):
        inner = m.group(1)
        inner = re.sub(r'<p class="admonition-title">(.*?)</p>',
                       lambda t: f'<p style="{S_NOTE_TITLE}">{t.group(1)}</p>', inner, flags=re.S)
        return f'<div style="{S_NOTE}">{inner}</div>'

    h = re.sub(r'<div class="admonition note">(.*?)</div>', note, h, flags=re.S)
    h = h.replace("<table>", f'<table style="{S_TABLE}">')
    h = h.replace("<th>", f'<th style="{S_TH}">').replace("<td>", f'<td style="{S_TD}">')
    # Heading ids exist for the on-site contents box; harmless on Blogger, but drop them to keep the
    # body clean since Blogger builds no such box.
    h = re.sub(r'<h([23]) id="[^"]*">', r"<h\1>", h)
    return h


def rewrite_links(h: str, link_base: str, slug_to_url: dict) -> str:
    """`<a href="../other-slug/">` is relative to the old site's /posts/<slug>/ layout."""
    def fix(m):
        slug = m.group(1)
        return f'<a href="{slug_to_url.get(slug, f"{link_base}/posts/{slug}/")}"'

    return re.sub(r'<a href="\.\./([a-z0-9-]+)/"', fix, h)


def image_url(post, site_origin: str, manifest: dict) -> tuple[str, str, bool]:
    """(src, alt, is_ai_generated). Blogger posts get one plain <img>; the srcset derivatives are a
    site-build concern and mean nothing here."""
    slug = post.slug
    jpg = ROOT / "static" / "images" / "posts" / f"{slug}.jpg"
    if post.image:
        src = post.image if post.image.startswith("http") else f"{site_origin}{post.image}"
    elif jpg.exists():
        src = f"{site_origin}/images/posts/{slug}.jpg"
    else:
        return "", "", False
    return src, post.image_alt, manifest.get(slug, {}).get("kind") == "ai"


def build_body(post, site, link_base: str, slug_to_url: dict, manifest: dict, image_host: str) -> str:
    """The full Blogger post body, mirroring what templates/post.html puts on the page."""
    out = []
    cat = site.categories.get(post.category, {})

    src, alt, is_ai = image_url(post, image_host, manifest)
    if src:
        out.append(
            f'<div style="margin:0 0 20px"><img src="{html.escape(src)}" alt="{html.escape(alt)}" '
            f'style="max-width:100%;height:auto;border-radius:10px"/>'
            + (f'<p style="{S_CAPTION}">चित्र: AI ने तयार केलेले प्रातिनिधिक चित्र (खरे छायाचित्र नाही)</p>'
               if is_ai else "")
            + "</div>")

    if cat.get("disclaimer"):
        out.append(f'<div style="{S_DISCLAIMER}"><strong>महत्त्वाची सूचना:</strong> '
                   f'{html.escape(cat["disclaimer"])}</div>')

    out.append(rewrite_links(style_prose(post.html), link_base, slug_to_url))

    if post.pros and post.cons:
        pros = "".join(f"<li>{html.escape(x)}</li>" for x in post.pros)
        cons = "".join(f"<li>{html.escape(x)}</li>" for x in post.cons)
        out.append(f'<div style="{S_PC_WRAP}">'
                   f'<div style="{S_PC_PRO}"><h2 style="margin-top:0">फायदे</h2><ul>{pros}</ul></div>'
                   f'<div style="{S_PC_CON}"><h2 style="margin-top:0">तोटे / जोखीम</h2><ul>{cons}</ul></div>'
                   f"</div>")

    if post.faq:
        items = "".join(
            f"<details{' open' if i == 0 else ''} style=\"margin:8px 0\">"
            f'<summary style="cursor:pointer;font-weight:700">{html.escape(f["q"])}</summary>'
            f'<div style="margin:8px 0 0">{style_prose(f["a"])}</div></details>'
            for i, f in enumerate(post.faq))
        out.append(f"<h2>वारंवार विचारले जाणारे प्रश्न</h2>{items}")

    if post.sources:
        links = "".join(
            f'<li><a href="{html.escape(str(s.get("url", "")))}" rel="noopener nofollow" '
            f'target="_blank">{html.escape(str(s.get("name", "")))}</a></li>'
            for s in post.sources if isinstance(s, dict))
        out.append(f"<h2>संदर्भ / स्रोत</h2><ul>{links}</ul>")

    if post.tags:
        out.append(f'<p style="{S_SMALL}">' + " ".join(f"#{html.escape(t)}" for t in post.tags) + "</p>")

    if post.ai_assisted:
        out.append(f'<p style="{S_SMALL}">हा लेख AI च्या मदतीने तयार केला आहे आणि प्रकाशनापूर्वी तपासला जातो. '
                   f"चूक आढळल्यास कृपया कळवा.</p>")

    return "\n".join(out)


def blogger_path(post, permalink_style: str) -> str:
    """Blogger serves posts at /YYYY/MM/<permalink>.html."""
    if permalink_style == "slug":
        return f"/{post.date:%Y}/{post.date:%m}/{post.slug}.html"
    raise ValueError(f"unknown permalink style {permalink_style!r}")


def collect(blog_url: str, image_host: str, permalink_style: str = "slug") -> list[dict]:
    site = load_site(ROOT)
    manifest_file = ROOT / "data" / "images.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8")) if manifest_file.exists() else {}

    posts = [load_post(p, site) for p in sorted((ROOT / "content" / "posts").rglob("*.md"))]
    posts.sort(key=lambda p: p.date)
    slug_to_url = {p.slug: f"{blog_url.rstrip('/')}{blogger_path(p, permalink_style)}" for p in posts}

    records = []
    for p in posts:
        records.append({
            "slug": p.slug,
            "title": p.title,
            "labels": labels_for(p, site),
            "published": p.date.isoformat(),
            "updated": (p.updated or p.date).isoformat(),
            "permalink": blogger_path(p, permalink_style),
            "url": slug_to_url[p.slug],
            "description": p.meta_description,
            "draft": bool(p.draft),
            "content": build_body(p, site, blog_url.rstrip("/"), slug_to_url, manifest, image_host),
        })
    return records


def labels_for(post, site) -> list[str]:
    """Blogger labels = the Marathi category name plus the post's own tags (deduped, order kept)."""
    cat = site.categories.get(post.category, {})
    out, seen = [], set()
    for x in [cat.get("name") or post.category] + list(post.tags):
        x = str(x).strip()
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--blog-url", default="https://marathinazar.blogspot.com")
    ap.add_argument("--image-host", default="https://sachinraaut.github.io",
                    help="absolute origin the post images are served from")
    ap.add_argument("--out", default=str(ROOT / "migration" / "out"))
    args = ap.parse_args()

    recs = collect(args.blog_url, args.image_host)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "posts.json").write_text(json.dumps(recs, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(recs)} posts -> {out / 'posts.json'}")
