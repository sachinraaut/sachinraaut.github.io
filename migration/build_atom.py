"""Build a Blogger-importable Atom XML file from migration/out/posts.json.

Structure follows a REAL Blogger archive export (root namespaces, the g/2005#kind category that marks
an entry as a post, labels under the blogger.com/atom/ns# scheme, RFC 3339 timestamps carrying a
+05:30 offset), not a reconstruction from prose documentation.

Two things this file deliberately does NOT rely on:

  * the permalink.  There is no documented way to pin a post's slug from an import file.  The
    <link rel='alternate'> carries the intended URL because a real export has one, but treat it as a
    hint, not a guarantee -- run --limit 2 first and look at what the two test posts actually get.
  * app:draft.  A real export declares xmlns:app='http://purl.org/atom/app#' while current Google
    docs use 'http://www.w3.org/2007/app'.  We emit the former, and the README also tells you to
    switch OFF "Automatically publish all imported posts and pages" in the import dialog.  Either one
    alone should keep the posts as drafts; the reason to want both is that publishing a post FREEZES
    its permalink, and un-freezing means reverting all 41 to draft by hand.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape, quoteattr

ROOT = Path(__file__).resolve().parent.parent
KIND_SCHEME = "http://schemas.google.com/g/2005#kind"
POST_TERM = "http://schemas.google.com/blogger/2008/kind#post"
LABEL_SCHEME = "http://www.blogger.com/atom/ns#"


def entry(rec: dict, blog_id: str, n: int, author: str, blog_url: str, draft: bool) -> str:
    labels = "".join(
        f"\n  <category scheme={quoteattr(LABEL_SCHEME)} term={quoteattr(l)}/>" for l in rec["labels"])
    control = ("\n  <app:control><app:draft>yes</app:draft></app:control>" if draft else "")
    return f"""<entry>
  <id>tag:blogger.com,1999:blog-{blog_id}.post-{n}</id>
  <published>{rec['published']}</published>
  <updated>{rec['updated']}</updated>
  <category scheme={quoteattr(KIND_SCHEME)} term={quoteattr(POST_TERM)}/>{labels}
  <title type='text'>{escape(rec['title'])}</title>
  <content type='html'>{escape(rec['content'])}</content>
  <link rel='alternate' type='text/html' href={quoteattr(blog_url + rec['permalink'])} title={quoteattr(rec['title'])}/>
  <author><name>{escape(author)}</name></author>{control}
</entry>"""


def build(recs, blog_id: str, author: str, blog_title: str, blog_url: str, draft: bool) -> str:
    entries = "\n".join(entry(r, blog_id, 1000 + i, author, blog_url, draft) for i, r in enumerate(recs))
    return f"""<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns='http://www.w3.org/2005/Atom'
      xmlns:openSearch='http://a9.com/-/spec/opensearchrss/1.0/'
      xmlns:georss='http://www.georss.org/georss'
      xmlns:gd='http://schemas.google.com/g/2005'
      xmlns:thr='http://purl.org/syndication/thread/1.0'
      xmlns:app='http://purl.org/atom/app#'>
<id>tag:blogger.com,1999:blog-{blog_id}.archive</id>
<updated>{recs[-1]['updated']}</updated>
<title type='text'>{escape(blog_title)}</title>
<link rel='alternate' type='text/html' href={quoteattr(blog_url + '/')}/>
<author><name>{escape(author)}</name></author>
<generator version='7.00' uri='http://www.blogger.com'>Blogger</generator>
{entries}
</feed>
"""


def verify(xml: str, recs) -> None:
    """Parse what we just wrote and prove each body survives the XML layer byte-for-byte.

    The bodies contain 17 raw '&' (query separators in source URLs) and 22 pre-existing '&amp;'.
    Escaping the HTML string once for XML turns those into '&amp;' and '&amp;amp;' respectively, and
    the parser must hand back the ORIGINAL string. If it doesn't, readers see '&amp;' as visible text.
    """
    ns = {"a": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(xml)
    entries = root.findall("a:entry", ns)
    assert len(entries) == len(recs), f"{len(entries)} entries for {len(recs)} posts"
    for e, r in zip(entries, recs):
        got = e.find("a:content", ns).text
        assert got == r["content"], f"{r['slug']}: content did not round-trip through XML"
        assert e.find("a:title", ns).text == r["title"], f"{r['slug']}: title mismatch"
        kinds = [c.get("term") for c in e.findall("a:category", ns) if c.get("scheme") == KIND_SCHEME]
        assert kinds == [POST_TERM], f"{r['slug']}: kind category missing"
        got_labels = [c.get("term") for c in e.findall("a:category", ns)
                      if c.get("scheme") == LABEL_SCHEME]
        assert got_labels == r["labels"], f"{r['slug']}: labels {got_labels} != {r['labels']}"
        assert e.find("a:published", ns).text == r["published"], f"{r['slug']}: published mismatch"
    print(f"  verified: {len(entries)} entries round-trip through an XML parser unchanged")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--posts", default=str(ROOT / "migration" / "out" / "posts.json"))
    ap.add_argument("--out", default=str(ROOT / "migration" / "out" / "blogger-import.xml"))
    ap.add_argument("--blog-id", default="1111111111111111111",
                    help="destination blog's numeric id; a placeholder is fine, Blogger reassigns "
                         "post ids on import (unconfirmed -- another reason to run --limit 2 first)")
    ap.add_argument("--blog-url", default="https://marathinazar.blogspot.com")
    ap.add_argument("--blog-title", default="मराठी नजर")
    ap.add_argument("--author", default="मराठी नजर")
    ap.add_argument("--limit", type=int, default=0, help="only the first N posts (use 2 for a trial)")
    ap.add_argument("--no-draft", action="store_true", help="do NOT mark entries as drafts (risky)")
    args = ap.parse_args()

    recs = json.loads(Path(args.posts).read_text(encoding="utf-8"))
    if args.limit:
        recs = recs[: args.limit]
    xml = build(recs, args.blog_id, args.author, args.blog_title,
                args.blog_url.rstrip("/"), draft=not args.no_draft)
    verify(xml, recs)
    Path(args.out).write_text(xml, encoding="utf-8")
    print(f"{len(recs)} posts -> {args.out}  ({len(xml.encode('utf-8')) / 1024:.0f} KB, "
          f"draft={not args.no_draft})")
