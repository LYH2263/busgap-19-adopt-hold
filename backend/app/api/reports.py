import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Arrival, BunchReport, Hold, Line, Trip
from app.services.bunch_engine import apply_holds, detect_bunching, events_to_dicts
router = APIRouter(prefix="/reports", tags=["reports"])

def _get_line(db: Session, line_id: int) -> Line:
    line = db.get(Line, line_id)
    if not line:
        raise HTTPException(404, "线路不存在")
    return line

def _load_holds(db: Session, trip_ids: list[int]) -> list[dict]:
    rows = db.scalars(select(Hold).where(Hold.trip_id.in_(trip_ids))).all()
    return [{"trip_id": h.trip_id, "stop_seq": h.stop_seq, "hold_min": h.hold_min} for h in rows]

def _load_events(db: Session, line_id: int, stop_name: str | None = None) -> tuple[Line, list[dict]]:
    """Run detection on hold-adjusted arrival times. Does not persist a report."""
    line = _get_line(db, line_id)
    trips = db.scalars(select(Trip).where(Trip.line_id == line_id)).all()
    trip_ids = [t.id for t in trips]
    trip_no_map = {t.id: t.trip_no for t in trips}
    holds = _load_holds(db, trip_ids)
    arrivals = db.scalars(select(Arrival).where(Arrival.trip_id.in_(trip_ids))).all()
    payload = [{"stop_name": a.stop_name, "stop_seq": a.stop_seq, "trip_id": a.trip_id,
                "trip_no": trip_no_map[a.trip_id], "actual_arrive": a.actual_arrive}
               for a in arrivals if stop_name is None or a.stop_name == stop_name]
    adjusted = apply_holds(payload, holds)
    events = detect_bunching(adjusted, line.planned_headway_min, line.bunch_threshold, line.large_threshold)
    return line, events_to_dicts(events)

@router.get("")
def list_reports(db: Session = Depends(get_db)):
    rows = db.scalars(select(BunchReport).order_by(BunchReport.id.desc())).all()
    return [{"id": r.id, "line_id": r.line_id, "stop_name": r.stop_name,
             "created_at": r.created_at.isoformat(), "events": json.loads(r.summary_json)} for r in rows]

@router.post("/run")
def run_detection(line_id: int, stop_name: str | None = None, db: Session = Depends(get_db)):
    _, data = _load_events(db, line_id=line_id, stop_name=stop_name)
    report = BunchReport(line_id=line_id, stop_name=stop_name or "*", created_at=datetime.utcnow(),
                         summary_json=json.dumps(data, ensure_ascii=False))
    db.add(report); db.commit(); db.refresh(report)
    return {"id": report.id, "events": data}

@router.get("/suggestions")
def suggestions(line_id: int, db: Session = Depends(get_db)):
    _, data = _load_events(db, line_id=line_id, stop_name=None)
    return {"line_id": line_id, "suggestions": [e for e in data if e["status"] != "normal"]}

@router.get("/timeline")
def timeline(line_id: int, stop_name: str = "市民中心", db: Session = Depends(get_db)):
    _get_line(db, line_id)
    trips = db.scalars(select(Trip).where(Trip.line_id == line_id)).all()
    trip_ids = [t.id for t in trips]
    trip_no_map = {t.id: t.trip_no for t in trips}
    holds = _load_holds(db, trip_ids)
    holds_by_trip: dict[int, list[dict]] = {}
    for h in holds:
        holds_by_trip.setdefault(h["trip_id"], []).append(h)
    arrivals = db.scalars(select(Arrival).where(Arrival.trip_id.in_(trip_ids), Arrival.stop_name == stop_name)).all()
    payload = [{"stop_name": a.stop_name, "stop_seq": a.stop_seq, "trip_id": a.trip_id,
                "trip_no": trip_no_map[a.trip_id], "actual_arrive": a.actual_arrive} for a in arrivals]
    adjusted = {a["trip_id"]: a for a in apply_holds(payload, holds)}
    rows = []
    for a in payload:
        delay = sum(h["hold_min"] for h in holds_by_trip.get(a["trip_id"], []) if h["stop_seq"] <= a["stop_seq"])
        rows.append({"trip_no": a["trip_no"], "actual_arrive": adjusted[a["trip_id"]]["actual_arrive"],
                     "hold_min": round(delay, 2), "held": delay > 0})
    rows.sort(key=lambda r: r["actual_arrive"])
    if not rows:
        return {"stop_name": stop_name, "marks": []}
    t0 = rows[0]["actual_arrive"]
    span = max((rows[-1]["actual_arrive"] - t0).total_seconds(), 1)
    marks = [{"trip_no": r["trip_no"], "actual_arrive": r["actual_arrive"].isoformat(),
              "pct": round((r["actual_arrive"] - t0).total_seconds() / span * 100, 2),
              "held": r["held"], "hold_min": r["hold_min"]} for r in rows]
    return {"stop_name": stop_name, "marks": marks}
