from datetime import datetime, timedelta
from app.services.bunch_engine import apply_hold_shifts, classify_gap, detect_bunching, validate_hold_minutes

def test_classify_bunching():
    assert classify_gap(2.0, 8.0, 3.0, 15.0)[0] == "bunching"

def test_classify_large():
    assert classify_gap(16.0, 8.0, 3.0, 15.0)[0] == "large_gap"

def test_classify_normal():
    assert classify_gap(8.0, 8.0, 3.0, 15.0)[0] == "normal"

def test_detect_bunching_events():
    base = datetime(2026, 1, 1, 8, 0)
    arrivals = [
        {"stop_name": "A", "trip_no": "T1", "actual_arrive": base},
        {"stop_name": "A", "trip_no": "T2", "actual_arrive": base + timedelta(minutes=2)},
        {"stop_name": "A", "trip_no": "T3", "actual_arrive": base + timedelta(minutes=20)},
    ]
    events = detect_bunching(arrivals, 8.0, 3.0, 15.0)
    assert len(events) == 2
    assert events[0].status == "bunching"
    assert events[1].status == "large_gap"

def test_validate_hold_minutes():
    assert validate_hold_minutes(5.0, 5.0) is None
    assert validate_hold_minutes(5.1, 5.0) is not None
    assert validate_hold_minutes(0, 5.0) is not None

def test_apply_hold_shifts_from_hold_stop_onward():
    base = datetime(2026, 1, 1, 8, 0)
    arrivals = [
        {"trip_id": 2, "stop_name": "A", "stop_seq": 0, "actual_arrive": base + timedelta(minutes=2)},
        {"trip_id": 2, "stop_name": "B", "stop_seq": 1, "actual_arrive": base + timedelta(minutes=8)},
        {"trip_id": 2, "stop_name": "C", "stop_seq": 2, "actual_arrive": base + timedelta(minutes=14)},
        {"trip_id": 1, "stop_name": "A", "stop_seq": 0, "actual_arrive": base},
    ]
    holds = [{"trip_id": 2, "stop_name": "B", "hold_min": 4.0}]
    out = {(a["trip_id"], a["stop_name"]): a["actual_arrive"] for a in apply_hold_shifts(arrivals, holds)}
    assert out[(2, "A")] == base + timedelta(minutes=2)   # 扣站前不动
    assert out[(2, "B")] == base + timedelta(minutes=12)  # 扣车站右移
    assert out[(2, "C")] == base + timedelta(minutes=18)  # 后续站同样右移
    assert out[(1, "A")] == base                          # 其他班次不动

def test_hold_resolves_bunching_in_detection():
    base = datetime(2026, 1, 1, 8, 0)
    arrivals = [
        {"trip_id": 1, "stop_name": "A", "stop_seq": 0, "actual_arrive": base},
        {"trip_id": 2, "stop_name": "A", "stop_seq": 0, "actual_arrive": base + timedelta(minutes=2)},
    ]
    shifted = apply_hold_shifts(arrivals, [{"trip_id": 2, "stop_name": "A", "hold_min": 4.0}])
    payload = [{"stop_name": a["stop_name"], "trip_no": f"T{a['trip_id']}", "actual_arrive": a["actual_arrive"]} for a in shifted]
    events = detect_bunching(payload, 8.0, 3.0, 15.0)
    assert len(events) == 1
    assert events[0].gap_min == 6.0
    assert events[0].status == "normal"
