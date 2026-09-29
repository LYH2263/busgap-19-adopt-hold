from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.config import settings
from app.database import get_db
from app.models.models import Arrival, Hold, Line, Trip

router = APIRouter(prefix="/holds", tags=["holds"])

class HoldRequest(BaseModel):
    line_id: int
    trip_no: str
    stop_name: str
    hold_min: float

@router.post("")
def adopt_hold(req: HoldRequest, db: Session = Depends(get_db)):
    if not (0 < req.hold_min <= settings.max_hold_min):
        raise HTTPException(400, f"扣车分钟需在 0~{settings.max_hold_min:g} 之间")
    if not db.get(Line, req.line_id):
        raise HTTPException(404, "线路不存在")
    trip = db.scalar(select(Trip).where(Trip.line_id == req.line_id, Trip.trip_no == req.trip_no))
    if not trip:
        raise HTTPException(404, "该线路下不存在该班次")
    arrival = db.scalar(select(Arrival).where(Arrival.trip_id == trip.id, Arrival.stop_name == req.stop_name))
    if not arrival:
        raise HTTPException(400, "该班次未经过该站")
    hold = db.scalar(select(Hold).where(Hold.trip_id == trip.id, Hold.stop_name == req.stop_name))
    if hold:
        hold.hold_min = req.hold_min
    else:
        hold = Hold(trip_id=trip.id, stop_name=req.stop_name, stop_seq=arrival.stop_seq, hold_min=req.hold_min)
        db.add(hold)
    db.commit()
    return {"trip_no": trip.trip_no, "stop_name": req.stop_name, "stop_seq": arrival.stop_seq,
            "hold_min": req.hold_min, "max_hold_min": settings.max_hold_min}
