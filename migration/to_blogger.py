"""Convert the Markdown posts in content/posts/ into Blogger-ready HTML.

The site renders a post from Markdown *plus* front matter (image, disclaimer, pros/cons, FAQ, sources,
tags, AI note) using Jinja templates and a stylesheet. Blogger has neither: a post body is one blob of
HTML and the theme supplies no classes we control. So this module:

  1. reuses blogtool's own render_markdown() so the prose HTML is byte-identical to the live site,
  2. re-expresses the class-based constructs (admonitions, tables) as BOTH a `mn-` class and an inline
     style, because there is a filed report of Blogger stripping style= attributes on publish; if that
     happens the classes still match migration/theme.css pasted into Theme > Customize > Add CSS,
  3. appends the parts the templates add (disclaimer, pros/cons, FAQ, sources, tags, AI note),
  4. rewrites relative internal links and the hero image to absolute URLs.

Nothing here touches content/posts/. Output goes to migration/out/.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blogtool.content import load_site, load_post  # noqa: E402

# Kept deliberately plain so they read correctly on both a light and a dark Blogger theme.
# Every entry is (css_class, inline_style) — emitted together, see the module docstring.
S = {
    "note": ("mn-note", "border:1px solid #d7dbe0;border-left:4px solid #1d4ed8;border-radius:8px;"
                        "padding:12px 16px;margin:20px 0;background:rgba(29,78,216,.04)"),
    "note_title": ("mn-note-title", "margin:0 0 6px;font-weight:700"),
    "disclaimer": ("mn-disclaimer", "border:1px solid #e6d9a8;border-radius:8px;padding:12px 16px;"
                                    "margin:20px 0;background:rgba(234,179,8,.08);font-size:.95em"),
    "table": ("mn-table", "border-collapse:collapse;width:100%;margin:20px 0;font-size:.97em"),
    "th": ("", "border:1px solid #d7dbe0;padding:8px 10px;text-align:left;"
               "background:rgba(0,0,0,.04);font-weight:700"),
    "td": ("", "border:1px solid #d7dbe0;padding:8px 10px;text-align:left"),
    "pros": ("mn-pros", "border:1px solid #bbf7d0;border-radius:8px;padding:12px 16px;margin:0 0 12px;"
                        "background:rgba(21,128,61,.05)"),
    "cons": ("mn-cons", "border:1px solid #fecaca;border-radius:8px;padding:12px 16px;margin:0;"
                        "background:rgba(220,38,38,.05)"),
    "small": ("mn-small", "font-size:.9em;color:#555"),
    "caption": ("mn-caption", "font-size:.88em;color:#666;margin:6px 0 0"),
    "hero": ("mn-hero", "margin:0 0 20px"),
    "img": ("mn-img", "max-width:100%;height:auto;border-radius:10px"),
    "faq": ("mn-faq", "margin:8px 0"),
    "faq_q": ("mn-faq-q", "cursor:pointer;font-weight:700"),
}


def attrs(key: str) -> str:
    """class + style for one of the constructs above."""
    cls, style = S[key]
    return (f' class="{cls}"' if cls else "") + (f' style="{style}"' if style else "")


def style_prose(h: str) -> str:
    """Swap the stylesheet-dependent constructs for class+inline-styled equivalents."""
    def note(m):
        inner = re.sub(r'<p class="admonition-title">(.*?)</p>',
                       lambda t: f"<p{attrs('note_title')}>{t.group(1)}</p>", m.group(1), flags=re.S)
        return f"<div{attrs('note')}>{inner}</div>"

    # The admonition extension never nests divs in these posts (verified across all 41).
    h = re.sub(r'<div class="admonition note">(.*?)</div>', note, h, flags=re.S)
    h = h.replace("<table>", f"<table{attrs('table')}>")
    h = h.replace("<th>", f"<th{attrs('th')}>").replace("<td>", f"<td{attrs('td')}>")
    # Heading ids exist for the on-site contents box; Blogger builds no such box.
    h = re.sub(r'<h([23]) id="[^"]*">', r"<h\1>", h)
    return h


def rewrite_links(h: str, resolve) -> str:
    """`<a href="../other-slug/">` is relative to the old site's /posts/<slug>/ layout."""
    return re.sub(r'<a href="\.\./([a-z0-9-]+)/"', lambda m: f'<a href="{resolve(m.group(1))}"', h)


def hero(post, image_host: str, manifest: dict) -> str:
    jpg = ROOT / "static" / "images" / "posts" / f"{post.slug}.jpg"
    if post.image:
        src = post.image if post.image.startswith("http") else f"{image_host}{post.image}"
    elif jpg.exists():
        src = f"{image_host}/images/posts/{post.slug}.jpg"
    else:
        return ""
    # Blogger flags mixed content, so the image host must be https.
    if not src.startswith("https://"):
        raise ValueError(f"{post.slug}: image URL must be https, got {src!r}")
    cap = (f"<p{attrs('caption')}>चित्र: AI ने तयार केलेले प्रातिनिधिक चित्र (खरे छायाचित्र नाही)</p>"
           if manifest.get(post.slug, {}).get("kind") == "ai" else "")
    return (f"<div{attrs('hero')}><img src=\"{html.escape(src)}\" "
            f"alt=\"{html.escape(post.image_alt)}\"{attrs('img')}/>{cap}</div>")


def build_body(post, site, resolve, manifest: dict, image_host: str) -> str:
    """The full Blogger post body, mirroring what templates/post.html puts on the page."""
    out = [hero(post, image_host, manifest)]
    cat = site.categories.get(post.category, {})

    if cat.get("disclaimer"):
        out.append(f"<div{attrs('disclaimer')}><strong>महत्त्वाची सूचना:</strong> "
                   f"{html.escape(cat['disclaimer'])}</div>")

    out.append(rewrite_links(style_prose(post.html), resolve))

    if post.pros and post.cons:
        li = lambda xs: "".join(f"<li>{html.escape(x)}</li>" for x in xs)  # noqa: E731
        out.append(f"<div class=\"mn-pc\">"
                   f"<div{attrs('pros')}><h2 style=\"margin-top:0\">फायदे</h2><ul>{li(post.pros)}</ul></div>"
                   f"<div{attrs('cons')}><h2 style=\"margin-top:0\">तोटे / जोखीम</h2>"
                   f"<ul>{li(post.cons)}</ul></div></div>")

    if post.faq:
        items = "".join(
            f"<details{' open' if i == 0 else ''}{attrs('faq')}>"
            f"<summary{attrs('faq_q')}>{html.escape(f['q'])}</summary>"
            f"<div style=\"margin:8px 0 0\">{style_prose(f['a'])}</div></details>"
            for i, f in enumerate(post.faq))
        out.append(f"<h2>वारंवार विचारले जाणारे प्रश्न</h2>{items}")

    if post.sources:
        links = "".join(
            f'<li><a href="{html.escape(str(s.get("url", "")))}" rel="noopener nofollow" '
            f'target="_blank">{html.escape(str(s.get("name", "")))}</a></li>'
            for s in post.sources if isinstance(s, dict))
        out.append(f"<h2>संदर्भ / स्रोत</h2><ul class=\"mn-sources\">{links}</ul>")

    if post.tags:
        out.append(f"<p{attrs('small')}>" + " ".join(f"#{html.escape(t)}" for t in post.tags) + "</p>")

    if post.ai_assisted:
        out.append(f"<p{attrs('small')}>हा लेख AI च्या मदतीने तयार केला आहे आणि प्रकाशनापूर्वी तपासला जातो. "
                   f"चूक आढळल्यास कृपया कळवा.</p>")

    return "\n".join(x for x in out if x)


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


def collect(blog_url: str, image_host: str, link_mode: str = "blogger", now: dt.datetime | None = None):
    """One record per post, oldest first.

    link_mode decides what an internal `../slug/` link points at:
      blogger  -- the Blogger URL this post WILL have, /YYYY/MM/<slug>.html. Correct only if the
                  permalink is actually pinned to <slug> (see migration/README.md); publish_blogger.py
                  does pin it, a plain XML import may not.
      old-site -- the existing GitHub Pages URL. Always correct, and the right choice while both
                  sites are live or if the permalink trick turns out not to work.
    """
    site = load_site(ROOT)
    manifest_file = ROOT / "data" / "images.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8")) if manifest_file.exists() else {}
    blog_url = blog_url.rstrip("/")
    image_host = image_host.rstrip("/")
    now = now or dt.datetime.now(site.tz())

    posts = sorted((load_post(p, site) for p in (ROOT / "content" / "posts").rglob("*.md")),
                   key=lambda p: p.date)
    permalink = {p.slug: f"/{p.date:%Y}/{p.date:%m}/{p.slug}.html" for p in posts}

    def resolve(slug: str) -> str:
        if slug not in permalink:  # a `related:` typo would already have failed validation
            return f"https://sachinraaut.github.io/posts/{slug}/"
        return (f"{blog_url}{permalink[slug]}" if link_mode == "blogger"
                else f"https://sachinraaut.github.io/posts/{slug}/")

    records = []
    for p in posts:
        records.append({
            "slug": p.slug,
            "title": p.title,
            "labels": labels_for(p, site),
            "published": p.date.isoformat(),
            "updated": (p.updated or p.date).isoformat(),
            # True => its publish time has not arrived; it is not on the live site yet either.
            # Blogger must SCHEDULE these, not publish them now.
            "scheduled": p.date > now,
            "permalink": permalink[p.slug],
            "url": f"{blog_url}{permalink[p.slug]}",
            "old_url": f"https://sachinraaut.github.io/posts/{p.slug}/",
            "description": p.meta_description,
            "draft": bool(p.draft),
            "content": build_body(p, site, resolve, manifest, image_host),
        })
    return records


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--blog-url", default="https://marathinazar.blogspot.com")
    ap.add_argument("--image-host", default="https://sachinraaut.github.io",
                    help="absolute https origin the post images are served from")
    ap.add_argument("--link-mode", choices=["blogger", "old-site"], default="blogger")
    ap.add_argument("--out", default=str(ROOT / "migration" / "out"))
    args = ap.parse_args()

    recs = collect(args.blog_url, args.image_host, args.link_mode)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "posts.json").write_text(json.dumps(recs, ensure_ascii=False, indent=2), encoding="utf-8")
    sched = [r["slug"] for r in recs if r["scheduled"]]
    print(f"{len(recs)} posts -> {out / 'posts.json'}  (link-mode={args.link_mode})")
    if sched:
        print(f"  {len(sched)} not yet published on the live site, must be SCHEDULED on Blogger: "
              + ", ".join(sched))
