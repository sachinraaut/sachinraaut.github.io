# मराठी नजर: Marathi blog on GitHub Pages

A static Marathi blog (tech, finance, health, news), built by a small Python generator and hosted **free** on GitHub Pages.
Every day 4 new posts are written (AI-assisted), checked by automated rules, and published automatically.

```
content/posts/*.md   ->  python -m blogtool build  ->  public/  ->  GitHub Pages
        ^                       ^
   daily writer            validate (blocks bad posts)
```

## What you get
- Marathi UI, Devanagari fonts, mobile friendly, light/dark mode, fast static pages.
- SEO: `lang="mr"`, canonical URLs, Open Graph, JSON-LD (BlogPosting + breadcrumbs), sitemap.xml, robots.txt, RSS, clean English slugs.
- Category pages, archive, client-side search, About / Disclaimer / Privacy pages.
- Automatic disclaimers on finance, health and news posts. Sources are listed under each post.
- **Scheduled publishing:** a post appears when its `date` arrives (an hourly GitHub Action rebuilds the site).

## Commands
```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt   # once
.venv/bin/python -m blogtool topics      # today's trending topics per category -> topics/today.json
.venv/bin/python -m blogtool validate    # quality/safety gate for all posts
.venv/bin/python -m blogtool build       # build into public/
.venv/bin/python -m blogtool serve       # preview at http://127.0.0.1:8000
.venv/bin/python -m pytest -q            # tests
```

## Settings
- `site.json`: site name, tagline, categories, contact email (leave empty to hide the contact page), Google Search Console token.
- `feeds.json`: the free news feeds used to find topics (Google News RSS in Marathi/English, Google Trends India, RBI, PIB).
- `WRITING_GUIDE.md`: the instructions the daily writer follows.

## Cost
Everything here is free: GitHub Pages, GitHub Actions (public repo), the news feeds, the domain (`<user>.github.io`).
The only thing that can cost money is the AI that writes the posts each day. See the notes about automation in the setup steps.

## Limits worth knowing
- Google may treat large volumes of unreviewed AI-written content as low quality. Accurate, sourced, useful posts help. Sampling the daily
  posts yourself now and then is worthwhile, especially health and finance.
- Ad networks (e.g. AdSense) usually need original, reviewed content and time. Not set up.
