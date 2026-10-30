"""Affiliate attribution tests: URL tagging rules + the redirect contract.

The redirect contract (plan p1, Gate 3/4): every accepted click writes a
row that answers who/where/why; the *unauthenticated* path is still logged
(user_id NULL); the *misconfigured* path (no tag) passes the URL through
but still logs the click; and hostile input (unknown host, store mismatch,
URLs smuggled into opaque ids, over-limit rate) is refused.
"""

import atexit
import os

# Same pattern as services/api/test_main.py: force a SQLite URL for main's
# module-level engine before any services.api import (an earlier test
# package may already have pointed DATABASE_URL at Postgres, and TestClient
# startup needs the same database visible across threads, so a file URL).
# The router itself talks to the in-memory StaticPool engine below. The
# pid-keyed filename keeps concurrent/parallel runs from sharing state.
os.environ["DATABASE_URL"] = f"sqlite:///./test_affiliate_{os.getpid()}.db"
os.environ["SECRET_KEY"] = "test-affiliate-secret"
os.environ.setdefault("APP_ENV", "dev")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from services.api.affiliate import (
    build_affiliate_url,
    is_opaque_id,
    missing_affiliate_tags,
    normalize_category,
    normalize_click_source,
    store_for_url,
    tag_presence,
)
from services.api.dependencies import create_access_token, get_db, get_password_hash
from services.api.main import app
from services.api.models import AffiliateClick, Alert, User

AMAZON_URL = "https://www.amazon.eg/dp/ABC123?ref=search"
NOON_URL = "https://www.noon.com/egypt-en/item/P9"
EVIL_URL = "https://evil.example/item/x"


def _remove_db_file() -> None:
    # Best-effort: the file DB exists so startup is thread-visible; once the
    # test process exits it is garbage (a locked file just stays, like the
    # other *.db test artefacts already ignored by git).
    name = os.environ["DATABASE_URL"].split("///", 1)[-1].lstrip("./")
    try:
        os.remove(name)
    except OSError:
        pass


atexit.register(_remove_db_file)


@pytest.fixture
def db_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    from services.api.models import Base

    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture
def client(db_engine):
    Session = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _db():
    gen = app.dependency_overrides[get_db]()
    return next(gen)


def _rows(client):
    db = _db()
    return db.query(AffiliateClick).order_by(AffiliateClick.id).all()


def _user_token(client, db_engine, phone):
    """Seed an ACTIVE user row in the test DB and mint a valid user JWT."""
    db = _db()
    db.add(User(phone=phone, password_hash="x", salt="y", tier="free"))
    db.commit()
    from services.api.dependencies import SECRET_KEY

    return create_access_token({"sub": phone}, secret_key=SECRET_KEY)


# --- URL/tagging rules ---------------------------------------------------------


def test_amazon_tag_is_added(monkeypatch):
    monkeypatch.setenv("AMAZON_AFFILIATE_TAG", "el72-20")

    result = build_affiliate_url("amazon_eg", AMAZON_URL)

    assert "tag=el72-20" in result
    assert "ref=search" in result


def test_noon_campaign_is_added(monkeypatch):
    monkeypatch.setenv("NOON_AFFILIATE_TAG", "noon-demo")

    result = build_affiliate_url("noon_eg", NOON_URL)

    assert "utm_source=el72" in result
    assert "utm_medium=affiliate" in result
    assert "utm_campaign=noon-demo" in result


def test_missing_tag_preserves_supported_url(monkeypatch):
    monkeypatch.delenv("JUMIA_AFFILIATE_TAG", raising=False)
    url = "https://www.jumia.com.eg/item?sku=J1"

    assert build_affiliate_url("jumia_eg", url) == url


def test_unsupported_host_is_rejected():
    with pytest.raises(ValueError):
        build_affiliate_url("amazon_eg", "https://evil.example/item")


def test_store_for_url_rejects_open_redirect_target():
    with pytest.raises(ValueError):
        store_for_url(EVIL_URL)


# --- attribution helpers -------------------------------------------------------


def test_normalize_source_allowlist():
    assert normalize_click_source("deal_feed") == "deal_feed"
    assert normalize_click_source("TRACKER_CARD") == "tracker_card"
    # Unknown client context becomes 'unknown', never dropped or injected.
    assert normalize_click_source("evil'; DROP") == "unknown"
    assert normalize_click_source(None) == "unknown"


def test_is_opaque_id_refuses_urls():
    assert is_opaque_id("B0XYZ")
    assert is_opaque_id(None)
    assert not is_opaque_id("https://amazon.eg/dp/B0XYZ")
    assert not is_opaque_id("www.amazon.eg/dp/B0XYZ")
    # Allowlisting beats blacklisting: schemeless/host-shaped and other URL-
    # shaped probes are refused too.
    assert not is_opaque_id("mailto:x")
    assert not is_opaque_id("example.com/path")
    assert not is_opaque_id("//evil")
    assert not is_opaque_id("ftp://x/y")
    assert not is_opaque_id("B0XYZ?next=https")
    assert not is_opaque_id("")
    assert not is_opaque_id("x" * 300)


def test_normalize_category_clamps_to_safe_display_text():
    assert normalize_category(" laptops ") == "laptops"
    assert normalize_category("Phone & Tablets (big)") == "Phone & Tablets (big)"
    assert normalize_category(None) is None
    assert normalize_category("   ") is None
    # Markup, scheme-shaped probes and oversized labels never reach the row.
    assert normalize_category("<script>alert(1)</script>") is None
    assert normalize_category("https://evil.example/x") is None
    assert normalize_category("example.com/path") is None
    assert (
        normalize_category("x" * 101) is None
    )  # Unicode word characters pass (the app ships an Arabic UI): escape
    # written here to keep the test source locale-proof.
    assert normalize_category("ال laptops") == "ال laptops"


def test_tag_presence_and_missing(monkeypatch):
    monkeypatch.setenv("AMAZON_AFFILIATE_TAG", "el72-20")
    monkeypatch.setenv("NOON_AFFILIATE_TAG", "   ")
    monkeypatch.delenv("JUMIA_AFFILIATE_TAG", raising=False)

    assert tag_presence() == {
        "amazon_eg": True,
        "noon_eg": False,
        "jumia_eg": False,
    }
    assert missing_affiliate_tags() == [
        ("noon_eg", "NOON_AFFILIATE_TAG"),
        ("jumia_eg", "JUMIA_AFFILIATE_TAG"),
    ]


# --- the redirect contract -----------------------------------------------------


def test_authenticated_click_is_attributed(client, monkeypatch):
    monkeypatch.setenv("AMAZON_AFFILIATE_TAG", "el72-20")
    token = _user_token(client, None, "+201000000042")

    resp = client.get(
        "/affiliate/redirect",
        params={
            "target_url": AMAZON_URL,
            "sku": "ABC123",
            "deal_id": "deal-7",
            "category": "laptops",
            "source": "deal_feed",
            "session_id": "sess-42",
        },
        headers={"Authorization": f"Bearer {token}"},
        follow_redirects=False,
    )

    assert resp.status_code == 307
    assert "tag=el72-20" in resp.headers["location"]

    (row,) = _rows(client)
    assert row.user_id is not None
    assert row.source == "deal_feed"
    assert row.session_id == "sess-42"
    assert row.category == "laptops"
    assert row.store_id == "amazon_eg"
    assert row.sku == "ABC123"
    assert row.deal_id == "deal-7"
    # created_at is the canonical column; the ORM keeps a clicked_at alias
    # for one release (plan p1 MS1) so pre-rename callers keep working.
    assert row.created_at is not None
    assert row.clicked_at == row.created_at


def test_unauthenticated_caller_is_still_logged(client, monkeypatch):
    monkeypatch.delenv("AMAZON_AFFILIATE_TAG", raising=False)

    resp = client.get(
        "/affiliate/redirect",
        params={"target_url": AMAZON_URL, "source": "web"},
        follow_redirects=False,
    )

    assert resp.status_code == 307
    # Misconfigured tag: URL passthrough, but the click is NOT lost.
    assert resp.headers["location"] == AMAZON_URL

    (row,) = _rows(client)
    assert row.user_id is None
    assert row.source == "web"
    assert row.affiliate_url == row.target_url


def test_plain_http_merchant_link_is_refused(client):
    # The tagged URL carries the store's monetization credential; a
    # plaintext http hop could strip or intercept it, so attribution is
    # https-only (the client's fallback still opens the original link).
    resp = client.get(
        "/affiliate/redirect",
        params={"target_url": "http://www.amazon.eg/dp/ABC123", "source": "web"},
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert _rows(client) == []


def test_unknown_host_is_rejected_and_not_logged(client):
    resp = client.get(
        "/affiliate/redirect",
        params={"target_url": EVIL_URL, "source": "deal_feed"},
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert _rows(client) == []


def test_store_mismatch_is_rejected(client):
    resp = client.get(
        "/affiliate/redirect",
        params={"target_url": AMAZON_URL, "store": "noon_eg"},
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert _rows(client) == []


def test_blank_store_claim_is_treated_as_absent(client):
    # A client that sends an empty optional field must not be 400'd out of
    # its own attribution; blank means "not declared", like omitting it.
    resp = client.get(
        "/affiliate/redirect",
        params={"target_url": AMAZON_URL, "store": "  ", "source": "web"},
        follow_redirects=False,
    )
    assert resp.status_code == 307
    (row,) = _rows(client)
    assert row.store_id == "amazon_eg"


def test_url_smuggled_into_opaque_id_is_rejected(client):
    resp = client.get(
        "/affiliate/redirect",
        params={"target_url": AMAZON_URL, "sku": AMAZON_URL},
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert _rows(client) == []


def test_blank_optional_ids_are_treated_as_absent(client):
    # Honest clients send empty optional fields; that is "not declared",
    # not a malformed id: the click must still be logged.
    resp = client.get(
        "/affiliate/redirect",
        params={"target_url": AMAZON_URL, "sku": "  ", "deal_id": "", "source": "web"},
        follow_redirects=False,
    )
    assert resp.status_code == 307
    (row,) = _rows(client)
    assert row.sku is None and row.deal_id is None


def test_ids_are_stripped_before_storage(client):
    # One metric value per product: ' ABC123 ' must not split the CTR of
    # ABC123 across whitespace variants.
    resp = client.get(
        "/affiliate/redirect",
        params={"target_url": AMAZON_URL, "sku": "  ABC123  ", "source": "web"},
        follow_redirects=False,
    )
    assert resp.status_code == 307
    (row,) = _rows(client)
    assert row.sku == "ABC123"


def test_session_and_event_tokens_are_clamped(client):
    # Markup-shaped tokens never enter the log; padded real tokens are
    # stored trimmed so one session's CTR cannot split across variants.
    resp = client.get(
        "/affiliate/redirect",
        params={
            "target_url": AMAZON_URL,
            "session_id": "<script>s1</script>",
            "event_id": "",
            "source": "web",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 307
    (row,) = _rows(client)
    assert row.session_id is None and row.event_id is None

    resp = client.get(
        "/affiliate/redirect",
        params={"target_url": AMAZON_URL, "session_id": "  s-2 ", "source": "web"},
        follow_redirects=False,
    )
    assert resp.status_code == 307
    rows = _rows(client)
    assert rows[-1].session_id == "s-2"


def test_hostile_category_is_dropped_not_stored(client):
    resp = client.get(
        "/affiliate/redirect",
        params={"target_url": AMAZON_URL, "category": "<script>alert(1)</script>"},
        follow_redirects=False,
    )
    assert resp.status_code == 307
    (row,) = _rows(client)
    assert row.category is None


def test_client_source_outside_allowlist_recorded_as_unknown(client):
    resp = client.get(
        "/affiliate/redirect",
        params={"target_url": AMAZON_URL, "source": "totally-made-up"},
        follow_redirects=False,
    )
    assert resp.status_code == 307
    (row,) = _rows(client)
    assert row.source == "unknown"


def test_category_filled_from_server_context(client):
    # Seed a user (alerts.user_id is NOT NULL) plus that user's categorized
    # alert for the sku, then click with no client-supplied category.
    db = _db()
    user = User(phone="+201000000045", password_hash="x", salt="y", tier="free")
    db.add(user)
    db.commit()
    db.add(Alert(user_id=user.id, sku="ABC123", category="gaming-laptops"))
    db.commit()

    resp = client.get(
        "/affiliate/redirect",
        params={"target_url": AMAZON_URL, "sku": "ABC123"},
        follow_redirects=False,
    )
    assert resp.status_code == 307
    (row,) = _rows(client)
    assert row.category == "gaming-laptops"


def test_category_fill_from_alerts_is_deterministic(client):
    # Several alert rows for one sku must never make the stored category
    # depend on planner luck: same request twice yields the same fill.
    db = _db()
    user = User(phone="+201000000046", password_hash="x", salt="y", tier="free")
    db.add(user)
    db.commit()
    db.add(Alert(user_id=user.id, sku="DUPSKU", category="first-category"))
    db.commit()
    db.add(Alert(user_id=user.id, sku="DUPSKU", category="second-category"))
    db.commit()

    for _ in range(2):
        resp = client.get(
            "/affiliate/redirect",
            params={"target_url": AMAZON_URL, "sku": "DUPSKU", "source": "web"},
            follow_redirects=False,
        )
        assert resp.status_code == 307
    rows = _rows(client)
    assert len(rows) == 2
    assert rows[0].category == rows[1].category
    assert rows[0].category in ("first-category", "second-category")


def test_redirect_is_rate_limited(client, monkeypatch):
    from services.api.routers import affiliate as affiliate_routes

    monkeypatch.setattr(affiliate_routes, "REDIRECT_RATE_LIMIT", "3/minute")

    for i in range(3):
        resp = client.get(
            "/affiliate/redirect",
            params={"target_url": AMAZON_URL, "source": "web"},
            follow_redirects=False,
        )
        assert resp.status_code == 307, f"attempt {i}: {resp.text}"

    resp = client.get(
        "/affiliate/redirect",
        params={"target_url": AMAZON_URL, "source": "web"},
        follow_redirects=False,
    )
    assert resp.status_code == 429
    # The over-limit request must not have written a row.
    assert len(_rows(client)) == 3


# --- /affiliate/config: misconfiguration is loud, values stay secret ------


def test_affiliate_config_requires_admin_token(client):
    missing = client.get("/affiliate/config").status_code
    assert missing in (401, 403)

    # A USER token is not an admin token (separate credential domain).
    token = _user_token(client, None, "+201000000043")
    resp = client.get("/affiliate/config", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code in (401, 403)


def test_affiliate_config_reports_presence_not_values(client, monkeypatch):
    from services.api.admin_models import Admin
    from services.api.routers.payment import ADMIN_SECRET_KEY

    db = _db()
    db.add(
        Admin(
            username="admin-cfg",
            password_hash=get_password_hash("s3cret"),
        )
    )
    db.commit()

    monkeypatch.setenv("AMAZON_AFFILIATE_TAG", "secret-tag-value")
    monkeypatch.delenv("NOON_AFFILIATE_TAG", raising=False)
    monkeypatch.delenv("JUMIA_AFFILIATE_TAG", raising=False)

    admin_token = create_access_token(
        {"sub": "admin:admin-cfg"}, secret_key=ADMIN_SECRET_KEY
    )
    resp = client.get(
        "/affiliate/config",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200, resp.text
    stores = {s["store_id"]: s for s in resp.json()["stores"]}
    assert stores["amazon_eg"]["configured"] is True
    assert stores["noon_eg"]["configured"] is False
    assert stores["jumia_eg"]["configured"] is False
    # Presence only — the tag value itself never crosses this boundary.
    assert "secret-tag-value" not in resp.text
