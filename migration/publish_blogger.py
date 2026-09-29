"""Publish posts to Blogger through the Blogger API v3.

Used for both halves of the move: the one-off migration of the existing posts, and the daily job that
pushes each new post after it lands in content/posts/.

WHY THE API AND NOT THE XML IMPORT
Blogger derives a post's slug from its title, and a Devanagari title degrades to blog-post_1234.html.
Worse, the permalink FREEZES the moment a post is first published. The only mechanism that reliably
pins an ASCII slug is:

    1. insert  with isDraft=true and title = the slug          -> draft, no URL yet
    2. publish with publishDate = the post's real datetime      -> URL locks to /YYYY/MM/<slug>.html
    3. update  with the real Marathi title                      -> title fixed, URL survives

Step 2's publishDate is also what preserves chronology (and schedules the posts whose hour has not
arrived). Steps 1 and 3 are a community-reported workaround, not documented behaviour -- so this
script VERIFIES the URL it got back against the URL it wanted and stops the run on the first mismatch
rather than plough through 41 posts building a broken link graph.

AUTH
Service accounts cannot post to a personal Blogger blog: the Blogger API does not support domain-wide
delegation, and Blogger only grants authorship to accounts that accept an emailed invitation, which a
service account cannot do. So this needs a user OAuth refresh token. See migration/README.md.

  BLOGGER_CLIENT_ID  BLOGGER_CLIENT_SECRET  BLOGGER_REFRESH_TOKEN  BLOGGER_BLOG_ID
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = "https://www.googleapis.com/blogger/v3"
TOKEN_URL = "https://oauth2.googleapis.com/token"
STATE = ROOT / "migration" / "out" / "state.json"


def _req(url: str, *, method="GET", token=None, body=None, form=None, retries=4):
    data, headers = None, {}
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=UTF-8"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:400]
            # 403 quotaExceeded is Blogger's undocumented per-blog post-creation throttle; backing off
            # and retrying is right. 4xx auth/validation errors are not worth retrying.
            retryable = e.code in (429, 500, 502, 503) or (e.code == 403 and "quota" in detail.lower())
            if not retryable or attempt == retries - 1:
                raise SystemExit(f"HTTP {e.code} {method} {url}\n{detail}")
            wait = 5 * 2 ** attempt
            print(f"  HTTP {e.code}, retrying in {wait}s ... {detail[:120]}", file=sys.stderr)
            time.sleep(wait)
        except urllib.error.URLError as e:
            if attempt == retries - 1:
                raise SystemExit(f"network error {method} {url}: {e}")
            time.sleep(5 * 2 ** attempt)


def access_token() -> str:
    for k in ("BLOGGER_CLIENT_ID", "BLOGGER_CLIENT_SECRET", "BLOGGER_REFRESH_TOKEN"):
        if not os.environ.get(k):
            raise SystemExit(f"missing environment variable {k} (see migration/README.md)")
    try:
        out = _req(TOKEN_URL, method="POST", form={
            "client_id": os.environ["BLOGGER_CLIENT_ID"],
            "client_secret": os.environ["BLOGGER_CLIENT_SECRET"],
            "refresh_token": os.environ["BLOGGER_REFRESH_TOKEN"],
            "grant_type": "refresh_token",
        })
    except SystemExit as exc:
        # The two ways this realistically fails both look cryptic, so name the actual cause.
        msg = str(exc)
        if "unauthorized_client" in msg:
            raise SystemExit(
                f"{msg}\n\n"
                "unauthorized_client means the refresh token was NOT issued to this client id and\n"
                "secret. The usual causes:\n"
                "  * the token came from the OAuth Playground WITHOUT ticking 'Use your own OAuth\n"
                "    credentials' first, so it belongs to Google's demo client;\n"
                "  * the client id and the client secret are from two different OAuth clients.\n"
                "Fix: redo the Playground flow with your own credentials ticked BEFORE authorizing,\n"
                "then update all three BLOGGER_* secrets from that one client in one go."
            ) from None
        if "invalid_grant" in msg:
            raise SystemExit(
                f"{msg}\n\n"
                "invalid_grant means the refresh token was revoked or expired. If the OAuth consent\n"
                "screen is still in 'Testing', Google expires tokens 7 days after consent -- publish\n"
                "the app on the Audience page, then mint a new refresh token."
            ) from None
        raise
    return out["access_token"]


# marathinazar.blogspot.com, read off the post-editor URL during the trial import.
# Not a secret -- a Blogger blog id appears in the public page source of the blog itself.
DEFAULT_BLOG_ID = "6343443919394120759"


def diagnose() -> None:
    """Work out WHICH credential is wrong, without printing any of them.

    `unauthorized_client` does not say whether the client pair or the refresh token is at fault, so
    this probes them separately: a deliberately invalid refresh token sent with a VALID client pair
    comes back `invalid_grant`, while a bad client pair comes back `invalid_client`/
    `unauthorized_client` regardless of the token. That one extra request splits the two cases.
    """
    import urllib.error

    cid = os.environ.get("BLOGGER_CLIENT_ID", "")
    sec = os.environ.get("BLOGGER_CLIENT_SECRET", "")
    rt = os.environ.get("BLOGGER_REFRESH_TOKEN", "")

    def shape(name, value, want_prefix=None, want_suffix=None):
        if not value:
            print(f"  {name}: MISSING")
            return
        notes = [f"{len(value)} chars"]
        if value != value.strip():
            notes.append("HAS LEADING/TRAILING WHITESPACE - re-paste it")
        if want_prefix and not value.startswith(want_prefix):
            notes.append(f"does NOT start with {want_prefix!r}")
        if want_suffix and not value.endswith(want_suffix):
            notes.append(f"does NOT end with {want_suffix!r}")
        print(f"  {name}: " + "; ".join(notes))

    # An OAuth *client id* is public -- Google embeds it in page source for Sign-In -- so showing
    # enough of it to identify which client it is leaks nothing. The client SECRET never appears.
    # This exists because GitHub secrets are write-only: without it there is no way to tell which
    # of several OAuth clients the stored id belongs to.
    if cid:
        head = cid.split("-", 1)
        proj = head[0]
        rest = head[1][:8] if len(head) > 1 else ""
        print(f"Stored client id identifies as:  {proj}-{rest}...apps.googleusercontent.com")
        print("  ^ find THIS client in https://console.cloud.google.com/auth/clients")
        print("    and use it -- and only it -- in the OAuth Playground.\n")

    print("Shape of each secret (values themselves are never printed):")
    shape("BLOGGER_CLIENT_ID", cid, want_suffix=".apps.googleusercontent.com")
    shape("BLOGGER_CLIENT_SECRET", sec, want_prefix="GOCSPX-")
    shape("BLOGGER_REFRESH_TOKEN", rt, want_prefix="1//")

    # The three values people paste by mistake are all instantly recognisable.
    if rt.startswith("ya29."):
        print("\n  !! BLOGGER_REFRESH_TOKEN is an ACCESS token, not a refresh token.")
        print("     In the Playground response, copy the \"refresh_token\" line, not \"access_token\".")
    elif rt.startswith("4/"):
        print("\n  !! BLOGGER_REFRESH_TOKEN is an AUTHORIZATION CODE, not a refresh token.")
        print("     You copied it from Step 1. Click 'Exchange authorization code for tokens' first.")

    def probe(token):
        data = urllib.parse.urlencode({
            "client_id": cid, "client_secret": sec,
            "refresh_token": token, "grant_type": "refresh_token"}).encode()
        req = urllib.request.Request(TOKEN_URL, data=data, method="POST",
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                json.loads(r.read().decode())
                return "OK"
        except urllib.error.HTTPError as e:
            try:
                return json.loads(e.read().decode()).get("error", f"http_{e.code}")
            except Exception:
                return f"http_{e.code}"

    print("\nProbing Google's token endpoint:")
    real = probe(rt)
    print(f"  with your refresh token      -> {real}")
    if real == "OK":
        print("\nVERDICT: all three are correct. Re-run the publish.")
        return
    fake = probe("1//0-definitely-not-a-real-token")
    print(f"  with a deliberately bad one  -> {fake}")

    print("\nVERDICT:")
    if fake in ("invalid_client", "unauthorized_client"):
        print("  The CLIENT ID + CLIENT SECRET pair is rejected on its own, so the refresh token is")
        print("  not the problem. They are almost certainly from two DIFFERENT OAuth clients, or the")
        print("  client was deleted. Open one client, use 'Add secret', and copy the id and the new")
        print("  secret from that same page.")
    elif fake == "invalid_grant":
        print("  The client id + secret pair is GOOD -- Google accepted them and only rejected the")
        print("  dummy token. So BLOGGER_REFRESH_TOKEN is the wrong value.")
        if real == "unauthorized_client":
            print("  Getting 'unauthorized_client' for your real token means it was issued to a")
            print("  DIFFERENT client: the OAuth Playground was used without ticking 'Use your own")
            print("  OAuth credentials' BEFORE authorizing, so the token belongs to Google's demo")
            print("  client. Only BLOGGER_REFRESH_TOKEN needs replacing.")
        elif real == "invalid_grant":
            print("  Your token is expired or revoked. If the consent screen is still in 'Testing',")
            print("  tokens die 7 days after consent -- publish the app on the Audience page first.")
    else:
        print(f"  Unexpected: real={real}, control={fake}. Check the Blogger API is enabled.")


def blog_id(token: str, blog_url: str) -> str:
    if os.environ.get("BLOGGER_BLOG_ID"):
        return os.environ["BLOGGER_BLOG_ID"]
    if DEFAULT_BLOG_ID:
        return DEFAULT_BLOG_ID
    q = urllib.parse.urlencode({"url": blog_url})
    return _req(f"{API}/blogs/byurl?{q}", token=token)["id"]


def remote_state(token: str, bid: str) -> dict:
    """Rebuild "what is already on the blog" from the blog itself, keyed by slug.

    The daily CI job has no durable local state -- persisting state.json would mean committing it back
    to main on every run. Reconciling against Blogger instead makes the job idempotent for free: a
    re-run after a half-finished migration picks up exactly where it stopped, and a post that was
    created but whose title update failed is visible as already-present.
    """
    out, token_page = {}, None
    for status in ("LIVE", "SCHEDULED", "DRAFT"):
        token_page = None
        while True:
            q = {"fetchBodies": "false", "maxResults": "100", "status": status,
                 "fields": "items(id,url,title,published,status),nextPageToken"}
            if token_page:
                q["pageToken"] = token_page
            page = _req(f"{API}/blogs/{bid}/posts?{urllib.parse.urlencode(q)}", token=token) or {}
            for p in page.get("items", []):
                url = p.get("url", "")
                # /2026/09/<slug>.html -> <slug>
                slug = url.rsplit("/", 1)[-1][:-5] if url.endswith(".html") else ""
                if slug:
                    out[slug] = {"id": p["id"], "url": url, "published": p.get("published", ""),
                                 "status": p.get("status", status)}
            token_page = page.get("nextPageToken")
            if not token_page:
                break
    return out


def load_state() -> dict:
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}


def save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def publish_one(token: str, bid: str, rec: dict, state: dict, pause: float, dry: bool) -> dict:
    """Idempotent: a slug already in state is skipped, so a re-run after a failure resumes cleanly."""
    slug = rec["slug"]
    if slug in state and state[slug].get("url"):
        print(f"  = {slug} already on Blogger ({state[slug]['url']})")
        return state[slug]
    if dry:
        print(f"  + {slug}  -> would insert(draft, title={slug!r}), "
              f"publish(publishDate={rec['published']}), update(title={rec['title'][:40]!r})")
        return {"url": rec["url"], "dry": True}

    # 1. draft, titled with the slug so Blogger derives the permalink from ASCII
    post = _req(f"{API}/blogs/{bid}/posts?isDraft=true", method="POST", token=token,
                body={"kind": "blogger#post", "blog": {"id": bid}, "title": slug,
                      "content": rec["content"], "labels": rec["labels"]})
    pid = post["id"]

    # 2. publish at the post's real datetime -- past dates preserve chronology, future dates schedule
    q = urllib.parse.urlencode({"publishDate": rec["published"]})
    post = _req(f"{API}/blogs/{bid}/posts/{pid}/publish?{q}", method="POST", token=token)
    got = post.get("url", "")

    # 3. swap in the real Marathi title; the URL is frozen by now and should not move
    post = _req(f"{API}/blogs/{bid}/posts/{pid}", method="PUT", token=token,
                body={"kind": "blogger#post", "id": pid, "blog": {"id": bid},
                      "title": rec["title"], "content": rec["content"], "labels": rec["labels"]})
    final = post.get("url", got)

    want = rec["permalink"]
    if not final.endswith(want):
        raise SystemExit(
            f"\nPERMALINK MISMATCH on the first post -- stopping before this breaks the link graph.\n"
            f"  wanted ...{want}\n  got     {final}\n"
            f"The insert-as-slug trick did not hold on this blog. Re-run to_blogger.py with\n"
            f"  --link-mode old-site\n"
            f"so internal links point at the still-live GitHub Pages URLs, then re-run this script.\n"
            f"The post that was just created is at {final} -- delete it before retrying.")

    rounded = {"id": pid, "url": final, "published": post.get("published", rec["published"]),
               "status": post.get("status", "")}
    state[slug] = rounded
    save_state(state)
    print(f"  + {slug} -> {final}  [{rounded['status'] or 'LIVE'}]")
    time.sleep(pause)
    return rounded


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--posts",
                    default=str(ROOT / "migration" / "out" / "posts-pinned-links.json"),
                    help="this route pins permalinks, so the pinned-links variant is correct")
    ap.add_argument("--blog-url", default="https://marathinazar.blogspot.com")
    ap.add_argument("--only", default="", help="comma-separated slugs (the daily job passes today's)")
    ap.add_argument("--trial", type=int, default=0, help="only the first N posts -- use 1 first")
    ap.add_argument("--pause", type=float, default=5.0,
                    help="seconds between posts; Blogger throttles bursts of post creation")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, touch no network")
    ap.add_argument("--diagnose", action="store_true",
                    help="work out which credential is wrong; prints no secret values")
    args = ap.parse_args()

    if args.diagnose:
        diagnose()
        return

    recs = json.loads(Path(args.posts).read_text(encoding="utf-8"))
    if args.only:
        want = {s.strip() for s in args.only.split(",") if s.strip()}
        missing = want - {r["slug"] for r in recs}
        if missing:
            raise SystemExit(f"unknown slugs: {', '.join(sorted(missing))}")
        recs = [r for r in recs if r["slug"] in want]
    if args.trial:
        recs = recs[: args.trial]

    if args.dry_run:
        token = bid = None
        state = load_state()
    else:
        token = access_token()
        bid = blog_id(token, args.blog_url.rstrip("/"))
        state = {**load_state(), **remote_state(token, bid)}
        save_state(state)
        print(f"blog id {bid}; {len(state)} post(s) already on the blog")

    todo = [r for r in recs if r["slug"] not in state]
    print(f"{len(recs)} selected, {len(recs) - len(todo)} already published, {len(todo)} to do")

    for r in recs:
        publish_one(token, bid, r, state, args.pause, args.dry_run)

    sched = [r["slug"] for r in recs if r.get("scheduled")]
    if sched:
        print(f"\n{len(sched)} post(s) were scheduled for a future time, not published now: "
              + ", ".join(sched))
    print(f"\nstate -> {STATE}")


if __name__ == "__main__":
    main()
