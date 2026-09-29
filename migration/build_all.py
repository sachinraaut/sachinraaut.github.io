"""Regenerate every migration artefact, deterministically.

There are two variants, and which one you want depends on whether the post permalinks can be pinned:

  pinned   internal links point at https://marathinazar.blogspot.com/YYYY/MM/<slug>.html
           Correct ONLY if each post's permalink really is <slug> -- i.e. the API route
           (publish_blogger.py), or a manual Custom Permalink set on each draft before publishing.

  safe     internal links point at the existing https://sachinraaut.github.io/posts/<slug>/
           Always correct, because that site stays live to serve the redirect stubs anyway.
           This is the variant to use for a plain no-code XML import, where Blogger assigns the
           slugs and we cannot know them in advance.

Running one command for both is deliberate: generating them separately let posts.json and the XML
drift out of sync, which is the kind of thing that ships a broken link graph.
"""
from __future__ import annotations

import html
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "migration" / "out"
PY = sys.executable

VARIANTS = {
    # name:   (link_mode, posts.json,                 import xml)
    "pinned": ("blogger", "posts-pinned-links.json", "blogger-import-pinned.xml"),
    "safe": ("old-site", "posts-safe-links.json", "blogger-import-safe.xml"),
}


def run(*args: str) -> None:
    subprocess.run([PY, *args], check=True, cwd=ROOT)


def preview(posts_file: Path, dest: Path) -> None:
    """Three representative posts -- a table + callout, pros/cons + FAQ, and a health disclaimer."""
    recs = {r["slug"]: r for r in json.loads(posts_file.read_text(encoding="utf-8"))}
    pick = ["sbi-cash-withdrawal-charges-october-2026", "gemini-find-hub-remembered-items",
            "seasonal-flu-symptoms-risk-groups-india"]
    css = (ROOT / "migration" / "theme.css").read_text(encoding="utf-8")
    parts = []
    for s in pick:
        r = recs[s]
        labels = " · ".join(html.escape(x) for x in r["labels"])
        parts.append(
            f'<article class="post-body"><p class="lbl">{labels}</p>'
            f'<h1>{html.escape(r["title"])}</h1>'
            f'<p class="meta">{r["published"]}{" · SCHEDULED" if r["scheduled"] else ""}</p>'
            f'{r["content"]}</article><hr/>')
    dest.write_text(f"""<!doctype html><html lang="mr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Blogger preview</title>
<style>
:root{{color-scheme:light dark}}
body{{font-family:'Noto Sans Devanagari',system-ui,sans-serif;line-height:1.75;max-width:760px;
margin:0 auto;padding:24px 16px;background:#fff;color:#16181d}}
@media (prefers-color-scheme:dark){{body{{background:#14161a;color:#e8eaed}}}}
h1{{font-size:1.6rem;line-height:1.35;margin:.2em 0}}
.lbl{{font-size:.8rem;letter-spacing:.04em;color:#6b7280;margin:0}}
.meta{{font-size:.85rem;color:#6b7280;margin:.2em 0 1.4em}}
hr{{margin:56px 0;border:0;border-top:2px dashed #cbd5e1}}
{css}
</style></head><body>
<p class="meta"><strong>Preview only.</strong> The exact HTML that becomes each Blogger post body,
with theme.css applied. Blogger supplies the surrounding theme.</p><hr/>{''.join(parts)}</body></html>
""", encoding="utf-8")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (mode, posts_name, xml_name) in VARIANTS.items():
        print(f"== {name} ==")
        run("migration/to_blogger.py", "--link-mode", mode, "--out", str(OUT))
        (OUT / "posts.json").rename(OUT / posts_name)
        run("migration/build_atom.py", "--posts", str(OUT / posts_name), "--out", str(OUT / xml_name))

    # a 2-post trial file, from the safe variant -- nothing in it can break
    run("migration/build_atom.py", "--posts", str(OUT / VARIANTS["safe"][1]),
        "--out", str(OUT / "blogger-import-trial.xml"), "--limit", "2")

    preview(OUT / VARIANTS["safe"][1], OUT / "preview.html")
    print(f"\npreview.html regenerated")
    for f in sorted(OUT.iterdir()):
        print(f"  {f.name:34} {f.stat().st_size / 1024:7.0f} KB")
