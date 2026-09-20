import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BODY = ("## पहिला विभाग\n\n" + "हा लेख चाचणीसाठी लिहिलेला मराठी मजकूर आहे आणि त्यात पुरेसे शब्द आहेत. " * 40
        + "\n\n## दुसरा विभाग\n\n" + "आणखी काही माहिती येथे दिली आहे जेणेकरून लेख पुरेसा मोठा ठरेल. " * 25 + "\n")


def make_post(slug="test-post", date="2026-09-20T07:30:00+05:30", category="tech", title=None, body=BODY, extra=None,
              sources=True, tags=("एक", "दोन", "तीन")):
    title = title or f"चाचणी लेखाचे शीर्षक {slug}"
    desc = "हे या चाचणी लेखाचे वर्णन आहे आणि ते शोध निकालांमध्ये दिसण्यासाठी पुरेसे लांब लिहिलेले आहे, जेणेकरून नियम पाळले जातील."
    fm = {"title": title, "description": desc, "date": date, "category": category, "slug": slug, "tags": list(tags)}
    if sources:
        fm["sources"] = [{"name": "चाचणी स्रोत", "url": "https://example.com/a"}]
    fm.update(extra or {})
    import yaml
    return "---\n" + yaml.safe_dump(fm, allow_unicode=True, sort_keys=False) + "---\n" + body


@pytest.fixture
def blog(tmp_path):
    """A throwaway blog folder with the real templates/static/site.json and no posts."""
    for name in ("templates", "static", "content/pages", "assets"):
        shutil.copytree(ROOT / name, tmp_path / name)
    # start every test without the project's generated images
    shutil.rmtree(tmp_path / "static" / "images", ignore_errors=True)
    (tmp_path / "static" / "og-default.jpg").unlink(missing_ok=True)
    shutil.copy(ROOT / "site.json", tmp_path / "site.json")
    shutil.copy(ROOT / "feeds.json", tmp_path / "feeds.json")
    (tmp_path / "content" / "posts").mkdir(parents=True, exist_ok=True)

    class B:
        root = tmp_path

        def add(self, filename=None, **kw):
            text = make_post(**kw)
            date = kw.get("date", "2026-09-20T07:30:00+05:30")[:10]
            slug = kw.get("slug", "test-post")
            p = tmp_path / "content" / "posts" / (filename or f"{date}-{slug}.md")
            p.write_text(text, encoding="utf-8")
            return p

        def set_site(self, **kw):
            f = tmp_path / "site.json"
            d = json.loads(f.read_text(encoding="utf-8"))
            d.update(kw)
            f.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")

    return B()


NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
