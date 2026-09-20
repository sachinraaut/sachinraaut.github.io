import base64
import io
import json
import shutil

import pytest
from PIL import Image

from blogtool import images
from blogtool.build import Builder
from blogtool.content import load_posts, load_site
from blogtool.validate import check_post
from tests.conftest import NOW, ROOT, make_post

PROMPT = "A smartphone with a shield and a padlock, digital payment security"


def noisy(size=(1024, 1024), fmt="JPEG"):
    """A non-uniform test picture (gradient) so it passes the blank-image check."""
    im = Image.new("RGB", size)
    px = im.load()
    for x in range(size[0]):
        for y in range(0, size[1]):
            px[x, y] = ((x * 255) // size[0], (y * 255) // size[1], 120)
    buf = io.BytesIO()
    im.save(buf, fmt)
    return buf.getvalue()


def fake_render(html, out_png):
    """Stands in for headless Chrome in unit tests."""
    out_png.write_bytes(noisy((1200, 630), "PNG"))


class FakeProvider:
    name = "fake-ai"

    def __init__(self, fail_for=()):
        self.calls, self.fail_for = [], fail_for

    def generate(self, prompt):
        self.calls.append(prompt)
        if any(f in prompt for f in self.fail_for):
            raise images.ImageError("boom")
        return noisy()


def site_posts(blog, **posts):
    for slug, extra in posts.items():
        blog.add(slug=slug, extra=extra)
    site = load_site(blog.root)
    return site, load_posts(blog.root, site, NOW, include_hidden=True)


# ---------------------------------------------------------------- prompt safety
def test_sanitize_prompt_wraps_style_and_safety_words():
    p = images.sanitize_prompt(PROMPT, "finance")
    assert p.startswith(images.PHOTO_STYLE[0]) and PROMPT in p
    for word in ("no text", "no logos", "no watermark", "no celebrities", "no politicians"):
        assert word in p


def test_news_prompts_stay_drawn_not_photographic():
    """A photograph beside a news story would read as evidence of it."""
    p = images.sanitize_prompt(PROMPT, "news")
    assert p.startswith(images.DRAWN_STYLE[0]) and PROMPT in p
    for word in ("no people", "no faces", "no text", "no logos"):
        assert word in p
    assert "photorealistic" not in p


@pytest.mark.parametrize("category", ["tech", "finance", "health", "", "unknown-category"])
def test_every_other_category_is_photographic(category):
    assert images.sanitize_prompt(PROMPT, category).startswith(images.PHOTO_STYLE[0])


@pytest.mark.parametrize("bad", ["short", "मराठी वर्णन जे इंग्रजी नाही आहे पण लांब आहे", "x" * 301,
                                 "Prompt with <script> tags inside it", "line\nbreak is fine but ; semicolons are not"])
def test_sanitize_prompt_rejects(bad):
    with pytest.raises(images.ImageError):
        images.sanitize_prompt(bad)


# ---------------------------------------------------------------- Cloudflare provider
class FakeResp:
    def __init__(self, data, status=200):
        self._d, self.status = data, status

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(self.status)

    def json(self):
        return self._d


class FakeSession:
    def __init__(self, resp):
        self.resp, self.calls = resp, []

    def post(self, url, **kw):
        self.calls.append((url, kw))
        return self.resp


def test_cloudflare_request_and_decode():
    raw = noisy()
    s = FakeSession(FakeResp({"success": True, "result": {"image": base64.b64encode(raw).decode()}}))
    prov = images.CloudflareFlux("acct123", "tok456", session=s)
    assert prov.generate("a prompt") == raw
    url, kw = s.calls[0]
    assert url == "https://api.cloudflare.com/client/v4/accounts/acct123/ai/run/@cf/black-forest-labs/flux-1-schnell"
    assert kw["headers"]["Authorization"] == "Bearer tok456" and kw["json"] == {"prompt": "a prompt", "steps": 8}


def test_cloudflare_errors_and_env():
    with pytest.raises(images.ImageError):
        images.CloudflareFlux("a", "t", session=FakeSession(FakeResp({"success": False, "errors": ["x"]}))).generate("p")
    with pytest.raises(RuntimeError):
        images.CloudflareFlux("a", "t", session=FakeSession(FakeResp({}, status=429))).generate("p")
    assert images.CloudflareFlux.from_env({}) is None
    assert images.CloudflareFlux.from_env({"CLOUDFLARE_ACCOUNT_ID": "a"}) is None
    assert images.CloudflareFlux.from_env({"CLOUDFLARE_ACCOUNT_ID": "a", "CLOUDFLARE_API_TOKEN": "t"}).account_id == "a"


# ---------------------------------------------------------------- image processing
def test_banner_crop_and_rejections():
    for size in ((1024, 1024), (2000, 800), (1200, 630), (640, 1000)):
        out = Image.open(io.BytesIO(images.to_banner_jpeg(noisy(size))))
        assert out.size == (1200, 630) and out.format == "JPEG"
    blank = io.BytesIO()
    Image.new("RGB", (1024, 1024), (200, 200, 200)).save(blank, "JPEG")
    for bad, msg in ((b"not an image", "readable"), (noisy((100, 100)), "small"), (blank.getvalue(), "blank")):
        with pytest.raises(images.ImageError, match=msg):
            images.to_banner_jpeg(bad)


def test_card_html_escapes_and_sizes():
    h = images.card_html('शीर्षक <b>&"</b>', "आरोग्य", "मराठी नजर", "#0f766e", "AAAA")
    assert "<b>" not in h.split("<h1>")[1].split("</h1>")[0] and "&lt;b&gt;" in h and "#0f766e" in h
    assert "font-size:68px" in images.card_html("लहान", "x", "y", "#123456", "A")
    assert "font-size:50px" in images.card_html("अ" * 90, "x", "y", "#123456", "A")


# ---------------------------------------------------------------- orchestration
def test_ai_used_only_with_provider_and_prompt_else_card(blog):
    site, posts = site_posts(blog, with_prompt={"image_prompt": PROMPT}, no_prompt={})
    prov = FakeProvider()
    stats = images.ensure_images(blog.root, site, posts, prov, render=fake_render, log=lambda *_: 0)
    assert stats["ai"] == 1 and stats["card"] == 1 and len(prov.calls) == 1
    man = json.loads((blog.root / "data/images.json").read_text())
    assert man["with_prompt"]["kind"] == "ai" and man["with_prompt"]["provider"] == "fake-ai"
    assert man["no_prompt"] == {"kind": "card"}
    for slug in ("with_prompt", "no_prompt"):
        assert Image.open(blog.root / f"static/images/posts/{slug}.jpg").size == (1200, 630)


def test_category_style_reaches_the_provider(blog):
    blog.add(slug="a-news-story", category="news", extra={"image_prompt": PROMPT})
    blog.add(slug="a-tech-story", category="tech", extra={"image_prompt": PROMPT})
    site = load_site(blog.root)
    prov = FakeProvider()
    images.ensure_images(blog.root, site, load_posts(blog.root, site, NOW, include_hidden=True), prov,
                         render=fake_render, log=lambda *_: 0)
    assert len(prov.calls) == 2
    news = next(c for c in prov.calls if "no people" in c)
    assert news.startswith(images.DRAWN_STYLE[0]) and "photorealistic" not in news
    tech = next(c for c in prov.calls if c is not news)
    assert tech.startswith(images.PHOTO_STYLE[0]) and "photorealistic" in tech


def test_no_provider_gives_cards_and_existing_images_are_kept(blog):
    site, posts = site_posts(blog, a={"image_prompt": PROMPT})
    s1 = images.ensure_images(blog.root, site, posts, None, render=fake_render, log=lambda *_: 0)
    assert s1["card"] == 1
    before = (blog.root / "static/images/posts/a.jpg").read_bytes()
    s2 = images.ensure_images(blog.root, site, posts, FakeProvider(), render=fake_render, log=lambda *_: 0)
    assert s2["kept"] == 1 and (blog.root / "static/images/posts/a.jpg").read_bytes() == before


def test_upgrade_replaces_card_with_ai_and_failure_keeps_card(blog):
    site, posts = site_posts(blog, good={"image_prompt": PROMPT}, bad={"image_prompt": PROMPT + " FAILME"})
    images.ensure_images(blog.root, site, posts, None, render=fake_render, log=lambda *_: 0)
    prov = FakeProvider(fail_for=("FAILME",))
    stats = images.ensure_images(blog.root, site, posts, prov, render=fake_render, upgrade=True, log=lambda *_: 0)
    man = json.loads((blog.root / "data/images.json").read_text())
    assert man["good"]["kind"] == "ai" and man["bad"]["kind"] == "card"
    assert stats["ai"] == 1 and stats["ai_failed"] == 1


def test_ai_failure_falls_back_to_card_and_never_raises(blog):
    site, posts = site_posts(blog, x={"image_prompt": PROMPT})
    stats = images.ensure_images(blog.root, site, posts, FakeProvider(fail_for=("smartphone",)), render=fake_render,
                                 log=lambda *_: 0)
    assert stats["ai_failed"] == 1 and stats["card"] == 1 and stats["failed"] == 0


def test_render_failure_is_counted_not_fatal(blog):
    site, posts = site_posts(blog, x={})

    def broken(html, out):
        raise images.ImageError("no chrome")
    stats = images.ensure_images(blog.root, site, posts, None, render=broken, log=lambda *_: 0)
    assert stats["failed"] == 1 and not (blog.root / "static/images/posts/x.jpg").exists()


def test_hidden_and_future_posts_also_get_images(blog):
    blog.add(slug="later", date="2026-09-25T09:00:00+05:30")
    blog.add(slug="wip", extra={"draft": True})
    site = load_site(blog.root)
    stats = images.ensure_images(blog.root, site, load_posts(blog.root, site, NOW, include_hidden=True), None,
                                 render=fake_render, log=lambda *_: 0)
    assert stats["card"] == 2


# ---------------------------------------------------------------- real Chrome rendering (skipped if Chrome is absent)
@pytest.mark.skipif(images.find_chrome() is None, reason="Chrome/Chromium not installed")
def test_real_chrome_renders_marathi_card(blog):
    data = images.make_card(blog.root, "चांगल्या झोपेसाठी १० सोप्या सवयी", "आरोग्य", "मराठी नजर", "#0f766e")
    im = Image.open(io.BytesIO(data))
    assert im.size == (1200, 630) and len(data) > 8_000
    px = im.convert("RGB").getpixel((300, 300))
    assert px != (255, 255, 255)


# ---------------------------------------------------------------- build integration
def build(blog, **kw):
    b = Builder(blog.root, "https://user.github.io", now=NOW)
    b.build()
    return blog.root / "public"


def test_post_page_with_image(blog):
    blog.add(slug="pic", extra={"image_alt": "वर्णन मराठीत"})
    img = blog.root / "static/images/posts"
    img.mkdir(parents=True)
    (img / "pic.jpg").write_bytes(images.to_banner_jpeg(noisy()))
    (blog.root / "data").mkdir()
    (blog.root / "data/images.json").write_text(json.dumps({"pic": {"kind": "ai"}}))
    out = build(blog)
    html = (out / "posts/pic/index.html").read_text(encoding="utf-8")
    assert 'class="hero-img"' in html and 'alt="वर्णन मराठीत"' in html and 'src="/images/posts/pic.jpg"' in html
    assert "चित्र: AI ने तयार केलेले" in html
    assert 'property="og:image" content="https://user.github.io/images/posts/pic.jpg"' in html
    assert 'name="twitter:card" content="summary_large_image"' in html
    assert '"image": ["https://user.github.io/images/posts/pic.jpg"]' in html
    assert (out / "images/posts/pic.jpg").exists()
    home = (out / "index.html").read_text(encoding="utf-8")
    assert 'class="thumb" src="/images/posts/pic.jpg"' in home and 'loading="lazy"' in home


def test_card_kind_has_no_ai_caption_and_alt_defaults_to_title(blog):
    blog.add(slug="c", title="शीर्षक जे अल्ट म्हणून वापरले जाईल")
    (blog.root / "static/images/posts").mkdir(parents=True)
    (blog.root / "static/images/posts/c.jpg").write_bytes(images.to_banner_jpeg(noisy()))
    html = (build(blog) / "posts/c/index.html").read_text(encoding="utf-8")
    assert "चित्र: AI" not in html and 'alt="शीर्षक जे अल्ट म्हणून वापरले जाईल"' in html


def test_no_image_no_figure_and_default_og(blog):
    blog.add(slug="plain")
    html = (build(blog) / "posts/plain/index.html").read_text(encoding="utf-8")
    assert "hero-img" not in html and 'og:image"' not in html and 'twitter:card" content="summary"' in html
    (blog.root / "static/og-default.jpg").write_bytes(images.to_banner_jpeg(noisy()))
    home = (build(blog) / "index.html").read_text(encoding="utf-8")
    assert 'og:image" content="https://user.github.io/og-default.jpg"' in home


def test_project_page_base_path_for_images(blog):
    blog.add(slug="p")
    (blog.root / "static/images/posts").mkdir(parents=True)
    (blog.root / "static/images/posts/p.jpg").write_bytes(images.to_banner_jpeg(noisy()))
    Builder(blog.root, "https://user.github.io/blog", now=NOW).build()
    html = (blog.root / "public/posts/p/index.html").read_text(encoding="utf-8")
    assert 'src="/blog/images/posts/p.jpg"' in html and 'content="https://user.github.io/blog/images/posts/p.jpg"' in html


# ---------------------------------------------------------------- validator
def test_validator_checks_image_fields(tmp_path):
    from blogtool.content import load_post
    site = load_site(ROOT)

    def errs(**extra):
        f = tmp_path / "p.md"
        f.write_text(make_post(extra=extra), encoding="utf-8")
        return check_post(load_post(f, site), site)
    assert errs(image_prompt=PROMPT, image_alt="मोबाइलचे प्रतीकात्मक चित्र") == []
    assert any("image_prompt" in e for e in errs(image_prompt="मराठी प्रॉम्प्ट चालणार नाही हे लक्षात ठेवा"))
    assert any("image_prompt" in e for e in errs(image_prompt="too short"))
    assert any("image_alt" in e for e in errs(image_alt="x"))


def test_seed_posts_have_prompts():
    site = load_site(ROOT)
    for p in load_posts(ROOT, site, NOW, include_hidden=True):
        assert p.raw.get("image_prompt") and p.raw.get("image_alt"), p.slug
