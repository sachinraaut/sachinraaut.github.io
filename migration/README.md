# मराठी नजर → Blogger migration

## Status

- [x] Blog created — `marathinazar.blogspot.com`, blog id `6343443919394120759`
- [x] Trial import verified: **original post dates survive the import** (a 20 Sept post stayed
      20 Sept) and the post formatting — tables, callout boxes, FAQ accordion — renders correctly,
      so the inline styles were not stripped and `theme.css` is not needed
- [x] `.github/workflows/blogger-sync.yml` installed on `main`. It runs after "Build and deploy"
      and currently exits cleanly because no credentials are set, so it cannot fail the Actions tab
- [ ] **Three repository secrets** — the only thing left, see "Step 2" below
- [ ] Migrate the 41 posts (one manual workflow run, once the secrets exist)
- [ ] Redirect stubs on the old site, GA4, Search Console

Chosen route: the **API**, not the XML import. The importer cannot pin a post's slug, and Blogger
freezes the permalink at first publish — so an imported post would keep a `blog-post_3044.html` URL
forever. Delete the two trial drafts before the migration run; the script recreates them properly.

Everything needed to move the 41 posts from `sachinraaut.github.io` to `marathinazar.blogspot.com`
and to keep publishing there daily.

**What I could not do from the Claude session:** there are no Google credentials in that sandbox and
its egress proxy blocks every Google domain, so I could not create the blog, authenticate, or publish
anything. The steps below are the parts that need your Google account; everything else is built.

---

## The one trap that is expensive to get wrong

**Blogger freezes a post's permalink the moment it is first published.** Changing it afterwards means
reverting the post to a draft and re-publishing it, one at a time, against a post-publishing rate
limit.

And Blogger derives the slug from the **title** — a Devanagari title does not transliterate, it falls
back to `blog-post.html`, `blog-post_3044.html`, and so on.

Put together: importing all 41 posts with auto-publish ON gives you 41 permanently broken URLs, every
internal link pointing at a 404, and no quick way back. So:

- In the import dialog, **turn OFF "Automatically publish all imported posts and pages."**
- Prefer `publish_blogger.py` (below) over the XML import — it is the only path that pins the slug.

Sources: [permalink locked after publish](https://support.google.com/blogger/thread/133631133/how-to-change-permalink-in-blogger-website?hl=en) ·
[fallback `blog-post_NNNN.html` slugs](https://support.google.com/blogger/thread/200388803/when-i-add-custom-permalink-in-blogspot-section-its-show-default-blog-post-3044-html-like-this-why?hl=en) ·
[Custom Permalink feature](https://blogger.googleblog.com/2012/07/customize-your-posts-with-permalinks.html)

---

## Files

| File | What it is |
|---|---|
| `to_blogger.py` | Markdown + front matter → Blogger post HTML. Reuses `blogtool.render_markdown()`, so prose matches the live site exactly. |
| `build_atom.py` | `posts.json` → Blogger Atom import XML. Verifies every body round-trips through an XML parser. |
| `publish_blogger.py` | Blogger API v3 publisher. Used for both the migration and the daily job. |
| `theme.css` | Paste into Theme → Customize → Advanced → Add CSS. |
| `blogger-sync.yml` | **Proposed** GitHub Actions workflow. Not installed — see "Ongoing posting". |
| `build_all.py` | Regenerates every artefact below in one go. |
| `out/preview.html` | Visual preview of 3 representative posts. |

Each artefact comes in two variants, differing only in where the 66 internal
post-to-post links point:

| Variant | Internal links point at | Use when |
|---|---|---|
| `…-pinned-links` / `blogger-import-pinned.xml` | `marathinazar.blogspot.com/2026/09/<slug>.html` | the permalink really is `<slug>` — i.e. the API route, or Custom Permalink set by hand on each draft |
| `…-safe-links` / `blogger-import-safe.xml` | the existing `sachinraaut.github.io/posts/<slug>/` | **plain XML import.** Always correct, because the old site stays live anyway |
| `blogger-import-trial.xml` | (safe variant, first 2 posts) | the trial import |

If you are not sure, use **safe**. Nothing in it can break.

Regenerate everything: `.venv/bin/python migration/build_all.py`

---

## Step 1 — create the blog

Sign in to Blogger → **New blog** → address `marathinazar`. Blogger validates availability inline.

I could not check whether that address is free: web search found nothing at that hostname, but an
existing blog can be unindexed, so that is not proof. If it is taken, pick another address and pass
`--blog-url` to both scripts.

## Step 2 — one-time OAuth setup

Service accounts **cannot** post to a personal Blogger blog — the API does not support domain-wide
delegation, and Blogger only grants authorship to accounts that accept an emailed invitation, which a
service account cannot do. You need a user refresh token.

1. [Google Cloud console](https://console.cloud.google.com/) → new project.
2. Enable the **Blogger API v3**.
3. **Google Auth Platform** (this replaced "OAuth consent screen"; direct link
   https://console.cloud.google.com/auth/audience ) → **Audience** page → User type **External**.
   **Set publishing status to "In Production."** Left in "Testing", refresh tokens die after 7 days
   and the daily job breaks every week with `invalid_grant`. Production does *not* require Google
   verification for a single user — you just see an "unverified app" warning once.
4. **Clients** page → *Create client* → type **Web application**.
   Under **Authorized redirect URIs** add exactly:
   `https://developers.google.com/oauthplayground`
   Not "Desktop app": the OAuth Playground sends you back to that URL, and only a Web
   application client lets you register it. A Desktop client fails with
   `Error 400: redirect_uri_mismatch`.
   Copy the **Client ID** and **Client secret** shown after creating it (re-openable any time
   from the Clients page).
5. Get a refresh token once, authorising with
   `scope=https://www.googleapis.com/auth/blogger`, `access_type=offline`, `prompt=consent`.
   [OAuth Playground](https://developers.google.com/oauthplayground/) works: gear icon → "Use your own
   OAuth credentials" → paste client ID/secret → authorise that scope → exchange for tokens.
6. Keep `client_id`, `client_secret`, `refresh_token`.

## Step 3 — trial with ONE post

```bash
export BLOGGER_CLIENT_ID=... BLOGGER_CLIENT_SECRET=... BLOGGER_REFRESH_TOKEN=...
.venv/bin/python migration/publish_blogger.py --trial 1
```

The script inserts a draft titled with the slug, publishes it with the post's real datetime, then
swaps in the Marathi title. It then **checks the URL it got back** and aborts if the slug did not
stick — this is a community-reported workaround, not documented behaviour, so it is verified rather
than assumed.

Then look at the published post and confirm:

- URL is `…/2026/09/upi-mdr-explained.html`, not `blog-post.html`
- the date is **20 Sept 2026**, not today (backdating on publish is unverified — this is the check)
- the callout box, the table and the FAQ accordion render
- **the inline `style=` attributes survived.** There is a filed report of Blogger stripping them. If
  the post looks unstyled, paste `theme.css` into Theme → Add CSS; the same constructs also carry
  `mn-` classes for exactly this reason.

If the URL check fails, regenerate with internal links pointing at the still-live old site and retry:

```bash
.venv/bin/python migration/to_blogger.py --link-mode old-site
```

## Step 4 — migrate the rest

```bash
.venv/bin/python migration/publish_blogger.py --pause 8
```

Idempotent: it reconciles against the blog first, so a re-run after any failure resumes where it
stopped. `--pause` matters — Blogger has an undocumented per-blog post-creation throttle that returns
`403 quotaExceeded`, reportedly around 100 posts in a short window, and 41 is close enough to respect
it. The two posts whose publish time has not arrived are **scheduled**, not published early.

**Fallback if the API route fails:** import `out/blogger-import-trial.xml` via Settings → Import &
back up → Import content with auto-publish **OFF**, and see what slugs the two drafts get. The XML
carries a `<link rel='alternate'>` with the intended permalink, but nothing documents that Blogger
honours it. Also note the `app:draft` namespace ambiguity: a real Blogger export uses
`http://purl.org/atom/app#` (what `build_atom.py` emits) while current docs use
`http://www.w3.org/2007/app` — another reason the dialog toggle is the real safeguard.

---

## Step 5 — keep the old URLs alive

Search Console's **Change of Address tool cannot be used here.** It is domain-level only, and
`github.io` is on the Public Suffix List, so you cannot create or verify a Domain property for it.

Blogger's own Custom Redirects only redirect paths *within* the blog, so they cannot help either. And
GitHub Pages is static — it cannot emit a real 301.

What remains is the mechanism Google explicitly supports: a **zero-delay meta refresh**, which Google
treats as a permanent redirect, plus a **cross-domain `rel=canonical`**. The repo already has
`templates/redirect.html` doing exactly that.

The practical consequence, worth being explicit about: **the GitHub repo and Pages site have to stay
live.** Google says keep redirects up for at least 180 days; in practice, indefinitely. The post
images are also served from `sachinraaut.github.io` — Blogger allows external image URLs, but the day
that site goes away, 41 hero images 404 with it.

So "move off GitHub" realistically means *GitHub stops being the reader-facing site*, not *GitHub goes
away*. If you want a true clean break, the images need re-hosting into Blogger first.

Sources: [meta refresh as permanent redirect](https://developers.google.com/search/docs/crawling-indexing/301-redirects) ·
[site moves with URL changes](https://developers.google.com/search/docs/crawling-indexing/site-move-with-url-changes) ·
[Change of Address prerequisites](https://support.google.com/webmasters/answer/9370220?hl=en)

## Step 6 — analytics

- **Blogger Stats** is built in, no setup.
- **GA4:** Blogger → Settings → Basic → *Google Analytics Measurement ID* → paste the `G-…` id. Data
  can take up to 24 hours to appear.
- Add the blog to Search Console. A blogspot.com property is a Google product, so it verifies
  **without DNS access**.
- Expect "Page with redirect" notices in Search Console — Blogger 302s mobile traffic to `?m=1`. That
  is normal Blogger behaviour, not a migration fault.

Worth knowing: GA4 works on the current GitHub Pages site too. `site.json` has an empty `ga4_id`
field, so if daily analytics was the main reason to move, that is a one-line change instead.

---

## Ongoing posting

The writer routine pushes a `claude/…` branch; `publish-daily.yml` validates it, generates images,
merges to `main`; `deploy.yml` builds Pages. The Blogger sync has to come **after** that, because the
post bodies reference images at `sachinraaut.github.io` that do not exist until Pages deploys.

`.github/workflows/blogger-sync.yml` does that. It is installed and triggers on
**"Build and deploy"** completing — note that is the workflow's actual name; `"Deploy"` would never
have matched. It needs three repo secrets:

```
BLOGGER_CLIENT_ID  BLOGGER_CLIENT_SECRET  BLOGGER_REFRESH_TOKEN
```

`BLOGGER_BLOG_ID` is not needed — the id is baked into `publish_blogger.py`. Until the refresh token
exists the workflow exits cleanly at its first step, so it stays green while you set this up.

It publishes 4 posts a day (`daily_categories` is technology, ai, finance, health), each taking 3 API
calls, and it is idempotent — already-published slugs are skipped, so a re-run is harmless.

Note it schedules posts inside Blogger via `publishDate` rather than relying on the runner firing on
time. GitHub documents that scheduled workflows can be delayed under load and queued runs may be
dropped, so a 07:30 IST go-live driven by cron timing would be unreliable.

---

## Verified vs. assumed

Checked against a real Blogger export file and official Google docs:

- Atom structure, the `g/2005#kind` post category, labels under `blogger.com/atom/ns#`, RFC 3339
  timestamps with a `+05:30` offset
- `posts.insert` / `posts.publish?publishDate=` / scope `https://www.googleapis.com/auth/blogger`
- service accounts ruled out; refresh tokens expire in 7 days under "Testing"
- Blogger accepts external image URLs; post bodies are arbitrary HTML
- Change of Address unusable for `github.io`; meta refresh accepted as permanent

Assumed, and checked by the trial run rather than trusted:

- that insert-as-slug → publish → retitle pins the permalink (community-reported)
- that a past `publishDate` backdates rather than stamps today
- that Blogger does not strip inline `style=` attributes
- that an import XML's `<link rel='alternate'>` influences the slug (probably not)
- that `marathinazar.blogspot.com` is available
