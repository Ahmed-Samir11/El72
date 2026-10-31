"""Account deletion tests (plans/p4 WS1 erasure rule).

``DELETE /auth/me`` anonymizes the account and must also cut every behavior
fact loose from it: alerts and trackers are deleted, affiliate clicks and app
events keep their rows (cohort counts stay true) but lose the user link. If the
event store cannot be updated, nothing is anonymized and the caller can retry.
"""

import atexit
import os

os.environ["DATABASE_URL"] = f"sqlite:///./test_auth_deletion_{os.getpid()}.db"
os.environ["SECRET_KEY"] = "test-auth-deletion-secret"
os.environ.setdefault("APP_ENV", "dev")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from services.api.dependencies import (
    create_access_token,
    get_db,
    get_optional_timescale_db,
)
from services.api.main import app
from services.api.models import AffiliateClick, Alert, User
from services.api.test_events import APP_EVENTS_DDL
from services.api.tracked_items_models import TrackedItem

DELETED_PHONE = "+201000000001"
KEPT_PHONE = "+201000000002"


def _remove_db_file() -> None:
    name = os.environ["DATABASE_URL"].split("///", 1)[-1].lstrip("./")
    try:
        os.remove(name)
    except OSError:
        pass


atexit.register(_remove_db_file)


def _engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


@pytest.fixture
def pg_engine():
    engine = _engine()
    from services.api.models import Base

    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture
def ts_engine():
    engine = _engine()
    with engine.begin() as conn:
        conn.execute(text(APP_EVENTS_DDL))
    yield engine
    engine.dispose()


def _override(engine):
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def dependency():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    return dependency


@pytest.fixture
def client(pg_engine, ts_engine):
    app.dependency_overrides[get_db] = _override(pg_engine)
    app.dependency_overrides[get_optional_timescale_db] = _override(ts_engine)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _seed_user(pg_engine, ts_engine, phone):
    """One user with an alert, a tracker, a click and two events."""
    Session = sessionmaker(bind=pg_engine)
    db = Session()
    user = User(phone=phone, password_hash="x", salt="y", tier="free")
    db.add(user)
    db.commit()
    db.refresh(user)
    db.add(Alert(user_id=user.id, sku="SKU1"))
    db.add(TrackedItem(user_id=user.id, canonical_product_id=f"item-{user.id}"))
    db.add(
        AffiliateClick(
            store_id="amazon_eg",
            user_id=user.id,
            source="deal_feed",
            target_url="https://www.amazon.eg/dp/X",
            affiliate_url="https://www.amazon.eg/dp/X",
        )
    )
    db.commit()
    user_id = user.id
    db.close()
    with ts_engine.begin() as conn:
        for event in ("search", "track_created"):
            conn.execute(
                text(
                    "INSERT INTO app_events (user_id, session_id, event) "
                    "VALUES (:uid, 'session-1', :event)"
                ),
                {"uid": str(user_id), "event": event},
            )
    from services.api.dependencies import SECRET_KEY

    return user_id, create_access_token({"sub": phone}, secret_key=SECRET_KEY)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_deletion_detaches_every_behavior_fact_from_the_user(
    client, pg_engine, ts_engine
):
    user_id, token = _seed_user(pg_engine, ts_engine, DELETED_PHONE)
    kept_id, _ = _seed_user(pg_engine, ts_engine, KEPT_PHONE)

    assert client.delete("/auth/me", headers=_auth(token)).status_code == 204

    Session = sessionmaker(bind=pg_engine)
    db = Session()
    assert db.query(Alert).filter_by(user_id=user_id).count() == 0
    assert db.query(TrackedItem).filter_by(user_id=user_id).count() == 0
    # The click rows survive (cohort counts stay true) without the user link.
    clicks = db.query(AffiliateClick).all()
    assert len(clicks) == 2
    assert [c.user_id for c in clicks if c.user_id is not None] == [kept_id]
    user = db.get(User, user_id)
    assert user.status == "DELETED" and user.phone == f"deleted:{user_id}"
    db.close()

    with ts_engine.connect() as conn:
        rows = conn.execute(text("SELECT user_id, event FROM app_events")).all()
    assert len(rows) == 4
    assert sorted(r.user_id for r in rows if r.user_id is not None) == [
        str(kept_id),
        str(kept_id),
    ]


def test_a_deleted_account_cannot_be_used_again(client, pg_engine, ts_engine):
    _, token = _seed_user(pg_engine, ts_engine, DELETED_PHONE)
    assert client.delete("/auth/me", headers=_auth(token)).status_code == 204

    assert client.delete("/auth/me", headers=_auth(token)).status_code == 401
    login = client.post(
        "/auth/login", json={"phone": DELETED_PHONE, "password": "whatever1"}
    )
    assert login.status_code in (400, 401)


def test_if_events_cannot_be_detached_nothing_is_anonymized(
    client, pg_engine, ts_engine
):
    user_id, token = _seed_user(pg_engine, ts_engine, DELETED_PHONE)
    with ts_engine.begin() as conn:
        conn.execute(text("DROP TABLE app_events"))

    resp = client.delete("/auth/me", headers=_auth(token))
    assert resp.status_code == 503

    Session = sessionmaker(bind=pg_engine)
    db = Session()
    user = db.get(User, user_id)
    assert user.status == "ACTIVE" and user.phone == DELETED_PHONE
    assert db.query(AffiliateClick).filter_by(user_id=user_id).count() == 1
    assert db.query(Alert).filter_by(user_id=user_id).count() == 1
    db.close()


def test_without_an_event_store_deletion_still_completes(client, pg_engine, ts_engine):
    user_id, token = _seed_user(pg_engine, ts_engine, DELETED_PHONE)

    def no_store():
        yield None

    app.dependency_overrides[get_optional_timescale_db] = no_store
    assert client.delete("/auth/me", headers=_auth(token)).status_code == 204

    Session = sessionmaker(bind=pg_engine)
    db = Session()
    assert db.get(User, user_id).status == "DELETED"
    assert db.query(AffiliateClick).filter_by(user_id=user_id).count() == 0
    db.close()
