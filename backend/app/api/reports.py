import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Arrival, BunchReport, HoldAction, Line, Trip
from app.services.bunch_engine import apply_hold_shifts, detect_bunching, events_to_dicts, validate_hold_minutes
router = APIRouter(prefix="/reports", tags=["reports"])

def _effective_payload(db: Session, line_id: int, stop_name: str | None) -> list[dict]:
    """取线路到站记录，应用已保存的扣车后得到有效到站时刻。"""
    trips = db.scalars(select(Trip).where(Trip.line_id == line_id)).all()
    trip_ids = [t.id for t in trips]
    trip_no_map = {t.id: t.trip_no for t in trips}
    if not trip_ids:
        return []
    arrivals = db.scalars(select(Arrival).where(Arrival.trip_id.in_(trip_ids))).all()
    holds = db.scalars(select(HoldAction).where(HoldAction.trip_id.in_(trip_ids))).all()
    raw = [{"trip_id": a.trip_id, "stop_name": a.stop_name, "stop_seq": a.stop_seq,
            "actual_arrive": a.actual_arrive}
           for a in arrivals if stop_name is None or a.stop_name == stop_name]
    hold_rows = [{"trip_id": h.trip_id, "stop_name": h.stop_name, "hold_min": h.hold_min} for h in holds]
    shifted = apply_hold_shifts(raw, hold_rows)
    return [{"stop_name": a["stop_name"], "trip_no": trip_no_map[a["trip_id"]],
             "actual_arrive": a["actual_arrive"]} for a in shifted]

@router.get("")
def list_reports(db: Session = Depends(get_db)):
    rows = db.scalars(select(BunchReport).order_by(BunchReport.id.desc())).all()
    return [{"id": r.id, "line_id": r.line_id, "stop_name": r.stop_name,
             "created_at": r.created_at.isoformat(), "events": json.loads(r.summary_json)} for r in rows]

@router.post("/run")
def run_detection(line_id: int, stop_name: str | None = None, db: Session = Depends(get_db)):
    line = db.get(Line, line_id)
    if not line: raise HTTPException(404, "线路不存在")
    payload = _effective_payload(db, line_id, stop_name)
    events = detect_bunching(payload, line.planned_headway_min, line.bunch_threshold, line.large_threshold)
    data = events_to_dicts(events)
    report = BunchReport(line_id=line_id, stop_name=stop_name or "*", created_at=datetime.utcnow(),
                         summary_json=json.dumps(data, ensure_ascii=False))
    db.add(report); db.commit(); db.refresh(report)
    return {"id": report.id, "events": data}

@router.get("/suggestions")
def suggestions(line_id: int, db: Session = Depends(get_db)):
    line = db.get(Line, line_id)
    if not line: raise HTTPException(404, "线路不存在")
    # 建议按扣车后的有效时刻实时检测，但不写报告行；报告只由 /run 落库。
    payload = _effective_payload(db, line_id, None)
    events = events_to_dicts(detect_bunching(payload, line.planned_headway_min, line.bunch_threshold, line.large_threshold))
    return {"line_id": line_id, "max_hold_min": line.max_hold_min,
            "suggestions": [e for e in events if e["status"] != "normal"]}

class AdoptHoldIn(BaseModel):
    line_id: int
    stop_name: str
    later_trip: str
    hold_min: float

@router.post("/adopt-hold")
def adopt_hold(body: AdoptHoldIn, db: Session = Depends(get_db)):
    """把针对串车的建议采纳为扣车：只保存扣车，不新增报告行。"""
    line = db.get(Line, body.line_id)
    if not line: raise HTTPException(404, "线路不存在")
    err = validate_hold_minutes(body.hold_min, line.max_hold_min)
    if err: raise HTTPException(400, err)
    trip = db.scalars(
        select(Trip).where(Trip.line_id == body.line_id, Trip.trip_no == body.later_trip)
    ).first()
    if not trip: raise HTTPException(404, "后车班次不存在")
    exists = db.scalars(
        select(Arrival).where(Arrival.trip_id == trip.id, Arrival.stop_name == body.stop_name)
    ).first()
    if not exists: raise HTTPException(404, "该班次在指定站点无到站记录")
    hold = db.scalars(
        select(HoldAction).where(HoldAction.trip_id == trip.id, HoldAction.stop_name == body.stop_name)
    ).first()
    if hold:
        hold.hold_min = body.hold_min
        hold.created_at = datetime.utcnow()
    else:
        hold = HoldAction(trip_id=trip.id, stop_name=body.stop_name, hold_min=body.hold_min,
                          created_at=datetime.utcnow())
        db.add(hold)
    db.commit(); db.refresh(hold)
    return {"id": hold.id, "trip_id": trip.id, "trip_no": trip.trip_no,
            "stop_name": hold.stop_name, "hold_min": hold.hold_min}

@router.get("/timeline")
def timeline(line_id: int, stop_name: str = "市民中心", db: Session = Depends(get_db)):
    payload = _effective_payload(db, line_id, stop_name)
    arrivals = sorted(payload, key=lambda a: a["actual_arrive"])
    if not arrivals: return {"stop_name": stop_name, "marks": []}
    t0 = arrivals[0]["actual_arrive"]
    span = max((arrivals[-1]["actual_arrive"] - t0).total_seconds(), 1)
    marks = [{"trip_no": a["trip_no"], "actual_arrive": a["actual_arrive"].isoformat(),
              "pct": round((a["actual_arrive"] - t0).total_seconds() / span * 100, 2)} for a in arrivals]
    return {"stop_name": stop_name, "marks": marks}
