from datetime import datetime, timedelta
from app.services.bunch_engine import apply_holds, classify_gap, detect_bunching

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

def _arrivals(base):
    return [
        {"trip_id": 1, "stop_seq": 0, "stop_name": "S0", "trip_no": "T1", "actual_arrive": base},
        {"trip_id": 1, "stop_seq": 1, "stop_name": "S1", "trip_no": "T1", "actual_arrive": base + timedelta(minutes=6)},
        {"trip_id": 1, "stop_seq": 2, "stop_name": "S2", "trip_no": "T1", "actual_arrive": base + timedelta(minutes=12)},
    ]

def test_apply_holds_delays_held_stop_and_downstream():
    base = datetime(2026, 1, 1, 8, 0)
    arrivals = _arrivals(base)
    out = apply_holds(arrivals, [{"trip_id": 1, "stop_seq": 1, "hold_min": 5}])
    assert out[0]["actual_arrive"] == base                                  # upstream unchanged
    assert out[1]["actual_arrive"] == base + timedelta(minutes=11)          # held stop +5
    assert out[2]["actual_arrive"] == base + timedelta(minutes=17)          # downstream +5

def test_apply_holds_accumulates_multiple_holds():
    base = datetime(2026, 1, 1, 8, 0)
    arrivals = _arrivals(base)
    holds = [{"trip_id": 1, "stop_seq": 1, "hold_min": 2}, {"trip_id": 1, "stop_seq": 2, "hold_min": 3}]
    out = apply_holds(arrivals, holds)
    assert out[0]["actual_arrive"] == base
    assert out[1]["actual_arrive"] == base + timedelta(minutes=8)           # +2 only
    assert out[2]["actual_arrive"] == base + timedelta(minutes=17)          # +2+3

def test_apply_holds_does_not_mutate_input():
    base = datetime(2026, 1, 1, 8, 0)
    arrivals = _arrivals(base)
    apply_holds(arrivals, [{"trip_id": 1, "stop_seq": 1, "hold_min": 5}])
    assert arrivals[1]["actual_arrive"] == base + timedelta(minutes=6)
