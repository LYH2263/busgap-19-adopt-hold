"""Bus bunching: planned headway vs actual arrival gaps."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

@dataclass
class GapEvent:
    stop_name: str
    earlier_trip: str
    later_trip: str
    gap_min: float
    planned_headway_min: float
    status: str
    suggestion: str

def classify_gap(gap_min: float, planned_headway_min: float, bunch_threshold: float, large_threshold: float) -> tuple[str, str]:
    if gap_min < bunch_threshold:
        return ("bunching", f"间隔 {gap_min:.1f} 分钟低于串车阈值 {bunch_threshold}，建议后车缓行或抽稀。")
    if gap_min > large_threshold:
        return ("large_gap", f"间隔 {gap_min:.1f} 分钟超过大间隔阈值 {large_threshold}，建议前车减速或加发。")
    return ("normal", f"间隔接近计划 {planned_headway_min:.1f} 分钟，保持即可。")

def detect_bunching(arrivals: list[dict], planned_headway_min: float, bunch_threshold: float, large_threshold: float) -> list[GapEvent]:
    by_stop: dict[str, list[dict]] = {}
    for a in arrivals:
        by_stop.setdefault(a["stop_name"], []).append(a)
    events: list[GapEvent] = []
    for stop, items in by_stop.items():
        items = sorted(items, key=lambda x: x["actual_arrive"])
        for i in range(1, len(items)):
            prev, cur = items[i - 1], items[i]
            gap_min = (cur["actual_arrive"] - prev["actual_arrive"]).total_seconds() / 60.0
            status, suggestion = classify_gap(gap_min, planned_headway_min, bunch_threshold, large_threshold)
            events.append(GapEvent(stop, prev["trip_no"], cur["trip_no"], round(gap_min, 2), planned_headway_min, status, suggestion))
    return events

def events_to_dicts(events: list[GapEvent]) -> list[dict]:
    return [asdict(e) for e in events]

def validate_hold_minutes(hold_min: float, max_hold_min: float) -> str | None:
    """扣车分钟非法时返回错误信息，合法返回 None。"""
    if hold_min <= 0:
        return "扣车分钟需大于 0"
    if hold_min > max_hold_min:
        return f"扣车 {hold_min:g} 分钟超过上限 {max_hold_min:g} 分钟，采纳失败"
    return None

def apply_hold_shifts(arrivals: list[dict], holds: list[dict]) -> list[dict]:
    """按扣车记录把各班次扣车站及之后的到站时刻整体后移。

    arrivals 每项含 trip_id / stop_name / stop_seq / actual_arrive；
    holds 每项含 trip_id / stop_name / hold_min。
    返回新列表，actual_arrive 为扣车后的有效时刻；同一班次多站扣车时偏移累加。
    """
    seq_of: dict[tuple, int] = {}
    for a in arrivals:
        seq_of.setdefault((a["trip_id"], a["stop_name"]), a["stop_seq"])
    hold_by_trip: dict[int, list[tuple[int, float]]] = {}
    for h in holds:
        seq = seq_of.get((h["trip_id"], h["stop_name"]))
        if seq is None:
            continue
        hold_by_trip.setdefault(h["trip_id"], []).append((seq, float(h["hold_min"])))
    shifted: list[dict] = []
    for a in arrivals:
        delay = sum(m for seq, m in hold_by_trip.get(a["trip_id"], []) if seq <= a["stop_seq"])
        item = dict(a)
        if delay:
            item["actual_arrive"] = a["actual_arrive"] + timedelta(minutes=delay)
        shifted.append(item)
    return shifted
