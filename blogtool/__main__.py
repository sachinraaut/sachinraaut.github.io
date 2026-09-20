"""python -m blogtool <build|validate|topics|serve>"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="blogtool")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build the site into public/")
    b.add_argument("--base-url", default=os.environ.get("BASE_URL"))
    v = sub.add_parser("validate", help="check every post against the quality/safety rules")
    v.add_argument("--daily", metavar="YYYY-MM-DD", help="also require one post per category for that date")
    im = sub.add_parser("images", help="create missing post images (AI if a free key is set, else designed cards)")
    im.add_argument("--upgrade", action="store_true", help="replace designed cards with AI images where possible")
    im.add_argument("--site-card", action="store_true", help="also (re)create the default social preview image")
    t = sub.add_parser("topics", help="fetch today's trending topics per category into topics/")
    t.add_argument("--out", default=str(ROOT / "topics" / "today.json"))
    s = sub.add_parser("serve", help="build and preview locally on http://127.0.0.1:8000")
    s.add_argument("--port", type=int, default=8000)
    a = ap.parse_args(argv)

    if a.cmd == "build":
        from .build import Builder
        r = Builder(ROOT, a.base_url).build()
        print(f"built {r['posts']} posts, {r['files']} files -> {r['out']}")
    elif a.cmd == "validate":
        from .content import load_site
        from .validate import check_all, check_daily_set
        site = load_site(ROOT)
        problems = check_all(ROOT, site)
        if a.daily:
            extra = check_daily_set(ROOT, site, a.daily)
            if extra:
                problems["daily set"] = extra
        for f, errs in problems.items():
            print(f"FAIL {f}")
            for e in errs:
                print(f"   - {e}")
        n = len(list((ROOT / "content" / "posts").rglob("*.md")))
        print(f"{n} posts checked, {len(problems)} with problems")
        return 1 if problems else 0
    elif a.cmd == "images":
        from .content import load_posts, load_site
        from .images import CloudflareFlux, ensure_images, make_site_card
        site = load_site(ROOT)
        provider = CloudflareFlux.from_env()
        print("AI provider:", provider.name if provider else "none (CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN not set): designed cards only")
        stats = ensure_images(ROOT, site, load_posts(ROOT, site, include_hidden=True), provider, upgrade=a.upgrade)
        if a.site_card or not (ROOT / "static" / "og-default.jpg").exists():
            print("site card:", make_site_card(ROOT, site))
        print("images:", stats)
    elif a.cmd == "topics":
        from .topics import fetch_all
        path = fetch_all(ROOT, Path(a.out))
        print(f"topics written to {path}")
    elif a.cmd == "serve":
        import functools
        import http.server
        from .build import Builder
        Builder(ROOT, f"http://127.0.0.1:{a.port}").build()
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT / "public"))
        print(f"Preview: http://127.0.0.1:{a.port}  (Ctrl+C to stop)")
        http.server.HTTPServer(("127.0.0.1", a.port), handler).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
