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
