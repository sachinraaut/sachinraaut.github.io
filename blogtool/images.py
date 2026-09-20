"""Post images: AI illustration (free Cloudflare Workers AI FLUX.1-schnell) with an always-available designed title card.

Runs at publish time in GitHub Actions (never in the visitor's browser, never in the writer's sandbox) and the result is
COMMITTED (static/images/posts/<slug>.jpg + data/images.json), so an image is generated once and never changes.

- AI provider is used only if CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN are set AND the post has an `image_prompt`.
- Otherwise (or if the provider fails / returns junk) a designed card with the post title is rendered with headless Chrome,
  which shapes Marathi (Devanagari) correctly. Nothing here can block publishing.
"""
from __future__ import annotations

import base64
import html as htmllib
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import requests

from .content import Post, Site

W, H = 1200, 630
# Cards show the picture in a ~300-500px box, so a 480w copy saves most of the bytes; AVIF and WebP
# save most of the rest. The 1200 JPEG stays the master because it is the Open Graph / social image.
WIDTHS = (480, 1200)
MODERN = ("avif", "webp")
IMG_DIR = Path("static/images/posts")
MANIFEST = Path("data/images.json")
FONT_DIR = Path("assets/fonts")
PHOTO_STYLE = ("Candid documentary photograph, natural daylight, shallow depth of field, 35mm lens, ",
               ", photorealistic, everyday Indian setting, warm natural colours, no text, no letters, no numbers, "
               "no logos, no brand names, no watermark, ordinary anonymous people only, "
               "no celebrities, no politicians, no public figures, no medical procedures, no injuries")
DRAWN_STYLE = ("Flat vector editorial illustration, simple shapes, ",
               ", warm saffron and deep blue palette, clean uncluttered composition, no text, no letters, no numbers, "
               "no logos, no watermark, no people, no faces")
# A photograph beside a news story reads as evidence of that story, so news keeps the drawn style; every other
# category gets the photographic one.
STYLES = {"news": DRAWN_STYLE}
DEFAULT_STYLE = PHOTO_STYLE
PROMPT_OK = re.compile(r"^[A-Za-z0-9 ,.'\-()]{15,300}$")
CHROME_CANDIDATES = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
                     "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]


class ImageError(RuntimeError):
    pass


def sanitize_prompt(prompt: str, category: str = "") -> str:
    """The writer's English scene description, wrapped in the category's style + safety wording.
    Raises if it isn't plain text."""
    p = " ".join(str(prompt).split())
    if not PROMPT_OK.match(p):
        raise ImageError("image_prompt must be 15-300 characters of plain English (letters, digits, , . ' - ( ))")
    prefix, suffix = STYLES.get(category, DEFAULT_STYLE)
    return f"{prefix}{p}{suffix}"


# ---------------------------------------------------------------------------------------------- AI provider
class CloudflareFlux:
    """Cloudflare Workers AI, model FLUX.1-schnell (Apache-2.0). Free plan: 10,000 neurons/day (about 100 images at 8 steps)."""
    name = "cloudflare-flux-1-schnell"
    MODEL = "@cf/black-forest-labs/flux-1-schnell"

    def __init__(self, account_id: str, token: str, session=None, timeout: int = 120, steps: int = 8):
        self.account_id, self.token, self.timeout, self.steps = account_id, token, timeout, steps
        self.session = session or requests.Session()

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        a, t = env.get("CLOUDFLARE_ACCOUNT_ID", "").strip(), env.get("CLOUDFLARE_API_TOKEN", "").strip()
        return cls(a, t) if a and t else None

    def generate(self, prompt: str) -> bytes:
        url = f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}/ai/run/{self.MODEL}"
        r = self.session.post(url, headers={"Authorization": f"Bearer {self.token}"},
                              json={"prompt": prompt, "steps": self.steps}, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        if not data.get("success", True) or not (data.get("result") or {}).get("image"):
            raise ImageError(f"Cloudflare returned no image: {str(data.get('errors'))[:200]}")
        return base64.b64decode(data["result"]["image"])


# ---------------------------------------------------------------------------------------------- image processing
def to_banner_jpeg(raw: bytes) -> bytes:
    """Any image bytes -> 1200x630 JPEG (center-crop to 1.91:1). Raises ImageError on unusable/blank images."""
    from PIL import Image, ImageStat
    try:
        im = Image.open(io.BytesIO(raw))
        im.load()
    except Exception as exc:
        raise ImageError(f"not a readable image: {exc}") from exc
    im = im.convert("RGB")
    if min(im.size) < 256:
        raise ImageError(f"image too small: {im.size}")
    if max(ImageStat.Stat(im.convert("L")).stddev) < 3:
        raise ImageError("image is blank/uniform")
    w, h = im.size
    target = W / H
    if w / h > target:
        nw = round(h * target)
        im = im.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
    else:
        nh = round(w / target)
        im = im.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))
    im = im.resize((W, H), Image.LANCZOS)
    out = io.BytesIO()
    im.save(out, "JPEG", quality=84, optimize=True, progressive=True)
    return out.getvalue()


# ---------------------------------------------------------------------------------------------- designed card
def _shade(hex_color: str, k: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return "#%02x%02x%02x" % (round(r * k), round(g * k), round(b * k))


def card_html(title: str, label: str, brand: str, color: str, font_b64: str, font_reg_b64: str = "") -> str:
    size = 68 if len(title) <= 40 else 58 if len(title) <= 70 else 50
    reg = (f"@font-face{{font-family:ND;font-weight:400;src:url(data:font/ttf;base64,{font_reg_b64})}}"
           if font_reg_b64 else "")
    return f"""<!doctype html><html lang="mr"><head><meta charset="utf-8"><style>
@font-face{{font-family:ND;font-weight:700;src:url(data:font/ttf;base64,{font_b64})}}{reg}
html,body{{margin:0;width:{W}px;height:{H}px;overflow:hidden}}
body{{font-family:ND,sans-serif;color:#fff;position:relative;background:linear-gradient(135deg,{color} 0%,{_shade(color, .55)} 100%)}}
.c1{{position:absolute;right:-140px;top:-160px;width:560px;height:560px;border-radius:50%;background:rgba(255,255,255,.10)}}
.c2{{position:absolute;right:120px;bottom:-220px;width:420px;height:420px;border-radius:50%;background:rgba(255,255,255,.07)}}
.chip{{position:absolute;left:68px;top:58px;padding:2px 26px 8px;border:2px solid rgba(255,255,255,.9);border-radius:99px;font-size:32px;font-weight:700}}
.t{{position:absolute;left:68px;right:120px;top:130px;bottom:150px;display:flex;align-items:center}}
h1{{margin:0;font-size:{size}px;line-height:1.4;font-weight:700;display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden}}
.brand{{position:absolute;left:68px;bottom:44px;font-size:32px;font-weight:700;opacity:.95}}
.bar{{position:absolute;left:68px;bottom:100px;width:90px;height:6px;border-radius:3px;background:rgba(255,255,255,.85)}}
</style></head><body><div class="c1"></div><div class="c2"></div>
<div class="chip">{htmllib.escape(label)}</div><div class="t"><h1>{htmllib.escape(title)}</h1></div><div class="bar"></div>
<div class="brand">{htmllib.escape(brand)}</div></body></html>"""


def find_chrome() -> str | None:
    env = os.environ.get("CHROME_BIN")
    if env and shutil.which(env):
        return shutil.which(env)
    for c in CHROME_CANDIDATES:
        p = shutil.which(c) or (c if os.path.exists(c) else None)
        if p:
            return p
    return None


def render_card_png(html: str, out_png: Path, timeout: int = 60) -> None:
    chrome = find_chrome()
    if not chrome:
        raise ImageError("no Chrome/Chromium found to render the title card")
    with tempfile.TemporaryDirectory() as d:
        page = Path(d) / "card.html"
        page.write_text(html, encoding="utf-8")
        cmd = [chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--hide-scrollbars",
               f"--window-size={W},{H}", "--force-device-scale-factor=1", "--virtual-time-budget=4000",
               f"--screenshot={out_png}", f"file://{page}"]
        subprocess.run(cmd, check=False, timeout=timeout, capture_output=True)
    if not out_png.exists() or out_png.stat().st_size < 2000:
        raise ImageError("Chrome did not produce a card image")


def make_card(root: Path, title: str, label: str, brand: str, color: str, render=render_card_png) -> bytes:
    fb = (root / FONT_DIR / "NotoSansDevanagari-Bold.ttf")
    fr = (root / FONT_DIR / "NotoSansDevanagari-Regular.ttf")
    if not fb.exists():
        raise ImageError(f"font missing: {fb}")
    html = card_html(title, label, brand, color, base64.b64encode(fb.read_bytes()).decode(),
                     base64.b64encode(fr.read_bytes()).decode() if fr.exists() else "")
    with tempfile.TemporaryDirectory() as d:
        png = Path(d) / "card.png"
        render(html, png)
        return to_banner_jpeg(png.read_bytes())


def _encode(im, fmt: str) -> dict:
    """Per-format encoder settings, tuned for photographic banners at these sizes."""
    return {"avif": {"format": "AVIF", "quality": 55},
            "webp": {"format": "WEBP", "quality": 76, "method": 6},
            "jpg": {"format": "JPEG", "quality": 82, "optimize": True, "progressive": True}}[fmt]


def derivative_name(slug: str, width: int, fmt: str) -> str:
    return f"{slug}-{width}.{fmt}"


def ensure_derivatives(root: Path, slug: str, log=print) -> int:
    """Create whatever responsive copies of <slug>.jpg are missing. Returns how many were written.

    Runs for every post that has a master, so images made before this existed get backfilled.
    """
    from PIL import Image
    master = root / IMG_DIR / f"{slug}.jpg"
    if not master.exists():
        return 0
    wanted = [(w, f) for w in WIDTHS for f in MODERN] + [(WIDTHS[0], "jpg")]
    missing = [(w, f) for w, f in wanted if not (root / IMG_DIR / derivative_name(slug, w, f)).exists()]
    if not missing:
        return 0
    im = Image.open(master)
    im.load()
    im = im.convert("RGB")
    written = 0
    for width, fmt in missing:
        out = root / IMG_DIR / derivative_name(slug, width, fmt)
        try:
            img = im if width == im.width else im.resize((width, round(width * im.height / im.width)), Image.LANCZOS)
            img.save(out, **_encode(img, fmt))
            written += 1
        except Exception as exc:                 # a missing encoder must never stop publishing
            log(f"[{slug}] {width}w {fmt} not written ({type(exc).__name__}: {str(exc)[:120]})")
    return written


# ---------------------------------------------------------------------------------------------- orchestration
def load_manifest(root: Path) -> dict:
    p = root / MANIFEST
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def save_manifest(root: Path, data: dict) -> None:
    p = root / MANIFEST
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def ensure_images(root: Path, site: Site, posts: list[Post], provider=None, render=render_card_png,
                  upgrade: bool = False, log=print) -> dict:
    """Create the missing image for every post (also future-dated ones, so it exists at publish time).
    upgrade=True replaces existing designed cards with an AI image when a provider and `image_prompt` are available."""
    manifest = load_manifest(root)
    out_dir = root / IMG_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    stats = {"ai": 0, "card": 0, "kept": 0, "ai_failed": 0, "failed": 0, "derived": 0}
    for p in posts:
        path = out_dir / f"{p.slug}.jpg"
        entry = manifest.get(p.slug, {})
        has = path.exists()
        want_ai = bool(provider and p.raw.get("image_prompt"))
        if has and not (upgrade and want_ai and entry.get("kind") == "card"):
            stats["kept"] += 1
            stats["derived"] += ensure_derivatives(root, p.slug, log)
            continue
        data, kind, prompt = None, None, None
        if want_ai:
            try:
                prompt = sanitize_prompt(p.raw["image_prompt"], p.category)
                data, kind = to_banner_jpeg(provider.generate(prompt)), "ai"
            except Exception as exc:
                stats["ai_failed"] += 1
                log(f"[{p.slug}] AI image failed ({type(exc).__name__}: {str(exc)[:160]}); using a designed card")
        if data is None:
            if has:                       # upgrade attempt failed: keep the existing card
                stats["kept"] += 1
                stats["derived"] += ensure_derivatives(root, p.slug, log)
                continue
            try:
                cat = site.categories[p.category]
                data = make_card(root, p.title, cat["name"], site.title, cat["color"], render)
                kind = "card"
            except Exception as exc:
                stats["failed"] += 1
                log(f"[{p.slug}] no image created: {exc}")
                continue
        path.write_bytes(data)
        for stale in (root / IMG_DIR).glob(f"{p.slug}-*.*"):   # the picture changed: its copies are wrong now
            stale.unlink()
        manifest[p.slug] = {"kind": kind, **({"provider": provider.name, "prompt": prompt} if kind == "ai" else {})}
        stats[kind] += 1
        stats["derived"] += ensure_derivatives(root, p.slug, log)
        log(f"[{p.slug}] {kind} image saved ({len(data) // 1024} KB)")
    save_manifest(root, manifest)
    return stats


def make_site_card(root: Path, site: Site, render=render_card_png) -> Path:
    """Default social-preview image for pages without their own (home, categories)."""
    data = make_card(root, site.title, site.tagline[:60], site.base_url.split("//")[-1], "#c2410c", render)
    out = root / "static" / "og-default.jpg"
    out.write_bytes(data)
    return out
