from datetime import datetime, timezone

import pytest

from blogtool import mr
from blogtool.content import ContentError, load_post, load_posts, load_site, parse_front
from tests.conftest import NOW, ROOT, make_post


def test_devanagari_digits_and_dates():
    assert mr.num(2026) == "२०२६"
    assert mr.date(datetime(2026, 9, 20)) == "२० सप्टेंबर २०२६"
    assert mr.month_year(datetime(2026, 1, 5)) == "जानेवारी २०२६"


def test_reading_time_and_ratio():
    assert mr.reading_minutes("शब्द " * 300) == 2 and mr.reading_minutes("") == 1
    assert mr.devanagari_ratio("मराठी लेख") == 1.0 and mr.devanagari_ratio("english only") == 0.0
    assert 0.6 < mr.devanagari_ratio("मराठी लेख आणि UPI") < 1.0
    assert mr.devanagari_ratio("123 !!") == 0.0


def test_front_matter_errors():
    with pytest.raises(ContentError):
        parse_front("no front matter")
    with pytest.raises(ContentError):
        parse_front("---\n: bad: yaml: [\n---\nbody")
    meta, body = parse_front("---\ntitle: x\n---\nहॅलो")
    assert meta == {"title": "x"} and body == "हॅलो"


def test_unquoted_colon_in_title_is_recovered():
    meta, body = parse_front('---\ntitle: UPI: फसवणूक टाळण्याचे सोपे उपाय\ndescription: सुरक्षा: "महत्त्वाची" माहिती\n'
                             'tags: [एक, दोन]\n---\nमजकूर')
    assert meta["title"] == "UPI: फसवणूक टाळण्याचे सोपे उपाय" and meta["description"] == 'सुरक्षा: "महत्त्वाची" माहिती'
    assert meta["tags"] == ["एक", "दोन"] and body == "मजकूर"
    with pytest.raises(ContentError):                                    # genuinely broken YAML still fails
        parse_front("---\ntags: [a, b\n---\nx")


def test_load_post_and_visibility(blog):
    site = load_site(blog.root)
    blog.add(slug="a", date="2026-09-20T07:30:00+05:30")
    blog.add(slug="future", date="2026-09-20T21:00:00+05:30")            # after NOW (17:30 IST)
    blog.add(slug="draft", date="2026-09-19T07:30:00+05:30", extra={"draft": True})
    shown = load_posts(blog.root, site, NOW)
    assert [p.slug for p in shown] == ["a"]
    assert len(load_posts(blog.root, site, NOW, include_hidden=True)) == 3
    p = shown[0]
    assert p.date.utcoffset().total_seconds() == 19800 and p.minutes >= 1 and "<h2>" in p.html


def test_naive_date_gets_site_timezone(blog):
    blog.add(slug="naive", date="2026-09-19T08:00:00")
    p = load_posts(blog.root, load_site(blog.root), NOW)[0]
    assert p.date.utcoffset().total_seconds() == 19800


def test_missing_field_and_bad_date(tmp_path):
    site = load_site(ROOT)
    f = tmp_path / "x.md"
    f.write_text("---\ntitle: t\n---\nbody", encoding="utf-8")
    with pytest.raises(ContentError, match="missing"):
        load_post(f, site)
    f.write_text(make_post().replace("2026-09-20T07:30:00+05:30", "not-a-date"), encoding="utf-8")
    with pytest.raises(ContentError, match="invalid date"):
        load_post(f, site)


def test_base_path():
    from blogtool.content import Site
    s = Site("t", "t", "d", "a", "https://u.github.io/repo")
    assert s.base_path == "/repo" and s.origin == "https://u.github.io"
    assert Site("t", "t", "d", "a", "https://u.github.io").base_path == ""
