import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.models import BunchReport, Hold
from app.services.seed import seed_if_empty


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    seed_if_empty(db)
    yield db
    db.close()


@pytest.fixture()
def client(db_session):
    def _get_db():
        yield db_session
    app.dependency_overrides[get_db] = _get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _event(events, stop, later):
    return next(e for e in events if e["stop_name"] == stop and e["later_trip"] == later)


def test_suggestions_do_not_write_report(client, db_session):
    res = client.get("/api/reports/suggestions?line_id=1")
    assert res.status_code == 200
    assert any(e["later_trip"] == "T02" and e["status"] == "bunching"
               for e in res.json()["suggestions"])
    assert db_session.scalar(select(func.count()).select_from(BunchReport)) == 0


def test_adopt_hold_shifts_detection_without_report(client, db_session):
    assert client.post("/api/holds", json={"line_id": 1, "trip_no": "T02",
                                           "stop_name": "市民中心", "hold_min": 5}).status_code == 200
    # Adoption itself never writes a report row.
    assert db_session.scalar(select(func.count()).select_from(BunchReport)) == 0

    run = client.post("/api/reports/run?line_id=1").json()
    event = _event(run["events"], "市民中心", "T02")
    assert event["gap_min"] == 7.0          # 2 + 5 minutes
    assert event["status"] == "normal"
    assert db_session.scalar(select(func.count()).select_from(BunchReport)) == 1

    assert not any(e["status"] == "bunching" and e["stop_name"] == "市民中心"
                   for e in client.get("/api/reports/suggestions?line_id=1").json()["suggestions"])


def test_over_cap_rejects_and_keeps_trip_unchanged(client, db_session):
    before = client.get("/api/reports/timeline?line_id=1&stop_name=市民中心").json()["marks"]
    t02_before = next(m for m in before if m["trip_no"] == "T02")

    bad = client.post("/api/holds", json={"line_id": 1, "trip_no": "T02",
                                          "stop_name": "市民中心", "hold_min": 6})
    assert bad.status_code == 400
    assert db_session.scalar(select(func.count()).select_from(Hold)) == 0

    assert client.post("/api/holds", json={"line_id": 1, "trip_no": "T02",
                                           "stop_name": "市民中心", "hold_min": 0}).status_code == 400

    after = client.get("/api/reports/timeline?line_id=1&stop_name=市民中心").json()["marks"]
    t02_after = next(m for m in after if m["trip_no"] == "T02")
    assert t02_after["pct"] == t02_before["pct"]
    assert not t02_after["held"]


def test_timeline_shifts_later_trip_right(client):
    marks = client.get("/api/reports/timeline?line_id=1&stop_name=市民中心").json()["marks"]
    t02_before = next(m for m in marks if m["trip_no"] == "T02")["pct"]

    client.post("/api/holds", json={"line_id": 1, "trip_no": "T02",
                                    "stop_name": "市民中心", "hold_min": 5})
    marks = client.get("/api/reports/timeline?line_id=1&stop_name=市民中心").json()["marks"]
    t02 = next(m for m in marks if m["trip_no"] == "T02")
    assert t02["held"] is True
    assert t02["hold_min"] == 5.0
    assert "07:13:00" in t02["actual_arrive"]      # 07:08 + 5
    assert t02["pct"] > t02_before
