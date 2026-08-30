#!/usr/bin/env python3
"""Weekly China-hours sports digest + start pings.

No model: --notify sends via `cc-connect send` and schedules worthy
kickoffs with `cc-connect timer add --exec`.

Viewing window (every day, Asia/Shanghai): kickoff 15:00 through 00:00 inclusive.
Pings fire about 5 minutes before start.

Football: only watched clubs; both sides watched = 强强对决.
F1: race only (no practice / qualifying / sprint).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from football_names_zh import zh_team

TZ = ZoneInfo("Asia/Shanghai")
UTC = ZoneInfo("UTC")
ESPN_UA = "Happening/0.1 (+https://github.com/kidrauhl123/Happening)"
STATE_PATH = Path.home() / ".reminder" / "golden_football_state.json"
REMINDER_PY = Path(__file__).resolve().parent / "reminder.py"
WEEKDAY_ZH = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
WINDOW_START = time(15, 0)
KICKOFF_LEAD = timedelta(minutes=5)

DEFAULT_LEAGUES = (
    ("eng.1", "英超"),
    ("esp.1", "西甲"),
    ("ger.1", "德甲"),
    ("ita.1", "意甲"),
    ("fra.1", "法甲"),
    ("uefa.champions", "欧冠"),
    ("uefa.europa", "欧联"),
    ("fifa.worldq", "世预赛"),
    ("afc.champions", "亚冠"),
)

WORTHY_LEAGUES = {code for code, _name in DEFAULT_LEAGUES}

# 只盯这些队：英超 Big 6、西甲三强、拜仁/多特、大巴黎、意甲三强。
FOCUS_ZH = {
    "拜仁",
    "多特蒙德",
    "阿森纳",
    "切尔西",
    "利物浦",
    "曼城",
    "曼联",
    "热刺",
    "皇马",
    "巴萨",
    "马竞",
    "巴黎圣日耳曼",
    "国米",
    "AC米兰",
    "尤文图斯",
}

F1_RACE_ABBR = {"RACE", "R"}
F1_SKIP_ABBR = {"FP1", "FP2", "FP3", "FP4", "QUAL", "Q", "SQ", "SPRINT", "SPR", "SS"}

# 分站英文名里的关键词 → 中文。对不上就退回原名。
F1_GP_ZH = (
    ("Australian", "澳大利亚大奖赛"),
    ("China", "中国大奖赛"),
    ("Japanese", "日本大奖赛"),
    ("Bahrain", "巴林大奖赛"),
    ("Saudi", "沙特大奖赛"),
    ("Miami", "迈阿密大奖赛"),
    ("Emilia", "艾米利亚-罗马涅大奖赛"),
    ("Imola", "艾米利亚-罗马涅大奖赛"),
    ("Monaco", "摩纳哥大奖赛"),
    ("Spanish", "西班牙大奖赛"),
    ("Canada", "加拿大大奖赛"),
    ("Austrian", "奥地利大奖赛"),
    ("British", "英国大奖赛"),
    ("Belgian", "比利时大奖赛"),
    ("Hungarian", "匈牙利大奖赛"),
    ("Dutch", "荷兰大奖赛"),
    ("Italian", "意大利大奖赛"),
    ("Azerbaijan", "阿塞拜疆大奖赛"),
    ("Singapore", "新加坡大奖赛"),
    ("United States", "美国大奖赛"),
    ("Mexico", "墨西哥大奖赛"),
    ("São Paulo", "圣保罗大奖赛"),
    ("Sao Paulo", "圣保罗大奖赛"),
    ("Brazil", "圣保罗大奖赛"),
    ("Las Vegas", "拉斯维加斯大奖赛"),
    ("Qatar", "卡塔尔大奖赛"),
    ("Abu Dhabi", "阿布扎比大奖赛"),
    ("Malaysia", "马来西亚大奖赛"),
)

MARQUEE_RANK = {
    "uefa.champions": 100,
    "fifa.worldq": 95,
    "eng.1": 90,
    "esp.1": 80,
    "ita.1": 70,
    "ger.1": 70,
    "fra.1": 60,
    "uefa.europa": 55,
    "afc.champions": 50,
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="国内适合观看时段的足球 + F1 正赛（默认本周）")
    p.add_argument("--hours", type=int, default=0, help="从现在起往后看多少小时；0 表示看到本周日夜 0 点")
    p.add_argument("--json", action="store_true")
    p.add_argument("--include-ended", action="store_true")
    p.add_argument("--marquee", type=int, default=0, help="只输出最重磅的 N 场，0 表示全部")
    p.add_argument("--notify", action="store_true", help="推本周完整赛程，并给值得看的场挂到点 send，不走模型")
    p.add_argument("--force", action="store_true", help="忽略本周已推送记录，再发一次")
    p.add_argument("--dry-run", action="store_true", help="只打印将要发送/挂上的内容")
    return p.parse_args()


def fetch_json(url: str) -> Any:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": ESPN_UA, "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def in_watchable(dt: datetime) -> bool:
    clock = dt.replace(second=0, microsecond=0).time()
    if clock == time(0, 0):
        return True
    return WINDOW_START <= clock


def parse_iso(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = raw.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(TZ)


def viewing_day(dt: datetime) -> str:
    if dt.hour == 0 and dt.minute == 0:
        return (dt.date() - timedelta(days=1)).isoformat()
    return dt.date().isoformat()


def iso_week_id(dt: datetime) -> str:
    iso = dt.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def week_close(now: datetime) -> datetime:
    """Next Monday 00:00 (Sunday night's last acceptable kickoff)."""
    days = (7 - now.weekday()) % 7
    if days == 0:
        days = 7
    return datetime.combine(now.date() + timedelta(days=days), time(0, 0), tzinfo=TZ)


def day_header(day: str) -> str:
    d = date.fromisoformat(day)
    return f"{WEEKDAY_ZH[d.weekday()]} {d.strftime('%m-%d')}"


def sides_from(title: str, participants: list[Any]) -> list[str]:
    names = [str(p).strip() for p in participants if p]
    if len(names) >= 2:
        return names[:2]
    parts = re.split(r"\s+vs\.?\s+", title or "", maxsplit=1, flags=re.I)
    return [part.strip() for part in parts if part.strip()][:2]


def focus_key(name: str | None) -> str | None:
    if not name:
        return None
    zh = zh_team(name.strip())
    if zh in FOCUS_ZH:
        return zh
    return None


def focus_sides(title: str, participants: list[Any]) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    for raw in sides_from(title, participants):
        key = focus_key(raw)
        if key and key not in seen:
            seen.add(key)
            keys.append(key)
    return keys


def zh_gp(name: str | None) -> str:
    text = (name or "").strip()
    if not text:
        return "大奖赛"
    for key, zh in F1_GP_ZH:
        if key.lower() in text.lower():
            return zh
    cleaned = re.sub(r"\s*Grand Prix\s*", "大奖赛", text, flags=re.I)
    cleaned = re.sub(r"\s*GP\s*$", "大奖赛", cleaned, flags=re.I)
    return cleaned.strip() or text


def is_f1_race(comp: dict[str, Any]) -> bool:
    kind = comp.get("type") if isinstance(comp.get("type"), dict) else {}
    abbr = str(kind.get("abbreviation") or "").upper()
    label = str(kind.get("text") or kind.get("name") or "")
    if abbr in F1_SKIP_ABBR or "sprint" in label.lower() or "practice" in label.lower():
        return False
    if "qual" in label.lower():
        return False
    return abbr in F1_RACE_ABBR or label.lower() == "race"


def map_event(
    *,
    event_id: str,
    title: str,
    league: str,
    league_name: str,
    kickoff: datetime | None,
    status: str,
    participants: list[Any],
    source: str,
    now: datetime,
    until: datetime,
    include_ended: bool,
    kind: str = "soccer",
) -> dict[str, Any] | None:
    if not event_id or kickoff is None or not in_watchable(kickoff):
        return None
    if kickoff < now - timedelta(minutes=5) or kickoff > until:
        return None
    if status == "ended" and not include_ended:
        return None
    people = [zh_team(str(p)) for p in participants if p]
    watched = focus_sides(title, people or participants)
    if kind == "f1":
        worthy = True
        clash = False
        watched = []
    else:
        worthy = bool(watched) and league in WORTHY_LEAGUES
        clash = len(watched) >= 2
    return {
        "id": event_id,
        "title": title,
        "league": league,
        "league_name": league_name,
        "kickoff": kickoff.isoformat(),
        "kickoff_text": kickoff.strftime("%m-%d %H:%M"),
        "kickoff_hm": kickoff.strftime("%H:%M"),
        "status": status,
        "participants": people,
        "source": source,
        "kind": kind,
        "viewing_day": viewing_day(kickoff),
        "focus": watched,
        "clash": clash,
        "worthy": worthy,
    }


def from_happening(now: datetime, until: datetime, include_ended: bool) -> list[dict[str, Any]]:
    base = os.environ.get("HAPPENING_URL", "").rstrip("/")
    if not base:
        return []
    url = f"{base}/api/happenings?category=sports&sport=soccer"
    try:
        payload = fetch_json(url)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return []
    groups = payload if isinstance(payload, dict) else {}
    raw_events: list[Any] = []
    if isinstance(payload, list):
        raw_events = payload
    else:
        for key in ("live", "upcoming", "recent", "events", "items"):
            value = groups.get(key)
            if isinstance(value, list):
                raw_events.extend(value)
    out: list[dict[str, Any]] = []
    for event in raw_events:
        if not isinstance(event, dict):
            continue
        mapped = map_event(
            event_id=str(event.get("id") or ""),
            title=str(event.get("title") or ""),
            league=str(event.get("league") or ""),
            league_name=str(event.get("league") or ""),
            kickoff=parse_iso(event.get("startsAt") or event.get("updatedAt")),
            status=str(event.get("status") or "scheduled"),
            participants=event.get("participants") if isinstance(event.get("participants"), list) else [],
            source="happening",
            now=now,
            until=until,
            include_ended=include_ended,
        )
        if mapped:
            out.append(mapped)
    return out


def from_espn(now: datetime, until: datetime, include_ended: bool) -> list[dict[str, Any]]:
    dates = f"{now:%Y%m%d}-{until:%Y%m%d}"
    out: list[dict[str, Any]] = []
    for code, name in DEFAULT_LEAGUES:
        url = (
            "https://site.api.espn.com/apis/site/v2/sports/soccer/"
            f"{code}/scoreboard?dates={dates}&limit=200"
        )
        try:
            data = fetch_json(url)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            continue
        for event in data.get("events") or []:
            kickoff = parse_iso(event.get("date"))
            status_type = (event.get("status") or {}).get("type") or {}
            state = status_type.get("state")
            if state == "post" and not include_ended:
                continue
            status = {"in": "live", "pre": "scheduled", "post": "ended"}.get(state, "unknown")
            comps = (event.get("competitions") or [{}])[0]
            home_name = None
            away_name = None
            teams: list[str] = []
            for competitor in comps.get("competitors") or []:
                team = (competitor.get("team") or {}).get("displayName")
                if not team:
                    continue
                teams.append(team)
                if competitor.get("homeAway") == "home":
                    home_name = team
                elif competitor.get("homeAway") == "away":
                    away_name = team
            home_zh = zh_team(home_name)
            away_zh = zh_team(away_name)
            if home_zh and away_zh:
                title = f"{home_zh} vs {away_zh}"
            else:
                raw = event.get("name") or event.get("shortName") or " vs ".join(teams)
                title = " vs ".join(zh_team(part) for part in str(raw).replace(" at ", " vs ").split(" vs "))
            mapped = map_event(
                event_id=f"espn-soccer-{code}-{event.get('id')}",
                title=str(title),
                league=code,
                league_name=name,
                kickoff=kickoff,
                status=status,
                participants=[n for n in (home_name, away_name) if n] or teams,
                source="espn",
                now=now,
                until=until,
                include_ended=include_ended,
            )
            if mapped:
                out.append(mapped)
    return out


def from_espn_f1(now: datetime, until: datetime, include_ended: bool) -> list[dict[str, Any]]:
    dates = f"{now:%Y%m%d}-{until:%Y%m%d}"
    url = (
        "https://site.api.espn.com/apis/site/v2/sports/racing/f1/scoreboard"
        f"?dates={dates}&limit=50"
    )
    try:
        data = fetch_json(url)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return []
    out: list[dict[str, Any]] = []
    for event in data.get("events") or []:
        gp_title = zh_gp(str(event.get("shortName") or event.get("name") or ""))
        for comp in event.get("competitions") or []:
            if not isinstance(comp, dict) or not is_f1_race(comp):
                continue
            kickoff = parse_iso(str(comp.get("date") or comp.get("startDate") or ""))
            status_type = (comp.get("status") or {}).get("type") or {}
            state = status_type.get("state")
            if state == "post" and not include_ended:
                continue
            status = {"in": "live", "pre": "scheduled", "post": "ended"}.get(state, "scheduled")
            mapped = map_event(
                event_id=f"espn-f1-{event.get('id')}-{comp.get('id')}",
                title=f"{gp_title}正赛",
                league="f1",
                league_name="F1",
                kickoff=kickoff,
                status=status,
                participants=[],
                source="espn",
                now=now,
                until=until,
                include_ended=include_ended,
                kind="f1",
            )
            if mapped:
                out.append(mapped)
    return out


def collect_events(now: datetime, until: datetime, include_ended: bool) -> list[dict[str, Any]]:
    events = from_happening(now, until, include_ended)
    if not events:
        events = from_espn(now, until, include_ended)
    events.extend(from_espn_f1(now, until, include_ended))
    events.sort(key=lambda e: e.get("kickoff") or "")
    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for event in events:
        key = (event.get("kickoff") or "", event.get("title") or "")
        if key in seen:
            continue
        seen.add(key)
        unique.append(event)
    return unique


def pick_marquee(events: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    def score(event: dict[str, Any]) -> tuple[int, int, str]:
        kickoff = parse_iso(event.get("kickoff"))
        minutes = (kickoff.hour * 60 + kickoff.minute) if kickoff else 0
        if minutes == 0:
            minutes = 24 * 60
        closeness = -abs(minutes - (20 * 60))
        return (MARQUEE_RANK.get(event.get("league") or "", 0), closeness, event.get("kickoff") or "")

    ranked = sorted(events, key=score, reverse=True)
    seen_days: set[str] = set()
    picked: list[dict[str, Any]] = []
    for event in ranked:
        day = event.get("viewing_day") or ""
        if day in seen_days:
            continue
        seen_days.add(day)
        picked.append(event)
        if len(picked) >= n:
            break
    return sorted(picked, key=lambda e: e.get("kickoff") or "")


def worthy_slots(events: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        if not event.get("worthy"):
            continue
        key = (event.get("kickoff") or "")[:16]
        grouped.setdefault(key, []).append(event)
    return [grouped[key] for key in sorted(grouped)]


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"digests": {}, "kickoffs": {}}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"digests": {}, "kickoffs": {}}
    if not isinstance(data, dict):
        return {"digests": {}, "kickoffs": {}}
    data.setdefault("digests", {})
    data.setdefault("kickoffs", {})
    return data


def save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def format_digest(events: list[dict[str, Any]]) -> str:
    watched = [event for event in events if event.get("worthy")]
    lines = [
        "主人，本周适合看的比赛 ⚽🏎️",
        "足球只喊关注的队，强强对决会标出来；F1只喊正赛。开赛前约5分钟再喊。",
        "",
    ]
    if not watched:
        lines.append("这周 15:00–0:00 没有关注的足球，也没有 F1 正赛。")
        return "\n".join(lines)
    current_day = None
    for event in watched:
        day = event.get("viewing_day")
        if day != current_day:
            current_day = day
            lines.append(day_header(day or datetime.now(TZ).date().isoformat()))
        mark = "★强强 " if event.get("clash") else "★ "
        lines.append(f"{mark}{event['kickoff_hm']}  {event['league_name']}  {event['title']}")
    return "\n".join(lines)


def format_kickoff_slot(slot: list[dict[str, Any]]) -> str:
    ordered = sorted(
        slot,
        key=lambda event: (not event.get("clash"), event.get("kind") != "f1", event.get("title") or ""),
    )
    head = ordered[0]
    rest = ordered[1:]
    titles = " / ".join(f"{event['league_name']} {event['title']}" for event in ordered[:3])
    extra = f" 等{len(slot)}场" if len(slot) > 3 else ""
    only_f1 = all(event.get("kind") == "f1" for event in ordered)
    has_f1 = any(event.get("kind") == "f1" for event in ordered)
    if head.get("clash"):
        line = (
            f"主人，强强对决，还有大约5分钟开球 ⚽ "
            f"{head['kickoff_hm']} {head['league_name']} {head['title']}"
        )
        if rest:
            extras = " / ".join(f"{event['league_name']} {event['title']}" for event in rest[:2])
            line += f"；还有 {extras}"
        return line
    if only_f1:
        return f"主人，还有大约5分钟发车 🏎️ {head['kickoff_hm']} {titles}{extra}"
    if has_f1:
        return f"主人，还有大约5分钟开赛 ⚽🏎️ {head['kickoff_hm']} {titles}{extra}"
    return f"主人，还有大约5分钟开赛 ⚽ {head['kickoff_hm']} {titles}{extra}"


def cc_send(text: str, dry_run: bool) -> None:
    if dry_run:
        print("--- send ---\n" + text)
        return
    subprocess.run(
        ["cc-connect", "send", "--stdin"],
        input=text.encode("utf-8"),
        check=True,
    )


def timer_list_text() -> str:
    try:
        result = subprocess.run(
            ["cc-connect", "timer", "list"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return ""
    return (result.stdout or "") + (result.stderr or "")


def notify_at(kickoff: datetime) -> datetime:
    return kickoff - KICKOFF_LEAD


def already_has_kickoff_timer(slot: list[dict[str, Any]], existing: str) -> bool:
    kickoff = parse_iso(slot[0].get("kickoff"))
    if kickoff is None:
        return False
    at_utc = notify_at(kickoff).astimezone(UTC).strftime("%Y-%m-%dT%H:%M")
    kick_utc = kickoff.astimezone(UTC).strftime("%Y-%m-%dT%H:%M")
    if at_utc in existing or kick_utc in existing:
        return True
    for event in slot:
        title = event.get("title") or ""
        if title and title in existing:
            return True
    return False


def schedule_kickoff_slot(slot: list[dict[str, Any]], dry_run: bool) -> str | None:
    kickoff = parse_iso(slot[0].get("kickoff"))
    if kickoff is None:
        return None
    ping_at = notify_at(kickoff)
    if ping_at <= datetime.now(TZ):
        return None
    at_utc = ping_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M")
    msg = format_kickoff_slot(slot)
    desc = f"开球 {slot[0]['kickoff_hm']} {slot[0]['title']}"[:80]
    exec_cmd = f"cc-connect send -m {shlex.quote(msg)}"
    if dry_run:
        print(f"--- timer {at_utc}Z ---\n{exec_cmd}")
        return "dry-run"
    result = subprocess.run(
        [
            "cc-connect",
            "timer",
            "add",
            "--at",
            at_utc,
            "--exec",
            exec_cmd,
            "--desc",
            desc,
            "--mute",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    output = (result.stdout or "") + (result.stderr or "")
    if result.returncode != 0:
        print(output, file=sys.stderr)
        return None
    match = re.search(r"created:\s*([0-9a-f]+)", output, re.I)
    return match.group(1) if match else "ok"


def add_calendar_slot(slot: list[dict[str, Any]], job_id: str | None, dry_run: bool) -> None:
    kickoff = parse_iso(slot[0].get("kickoff"))
    if kickoff is None:
        return
    if len(slot) == 1:
        title = slot[0]["title"]
        details = slot[0]["league_name"]
        source_message = slot[0].get("id") or "golden-football"
    else:
        title = " / ".join(event["title"] for event in slot[:3])[:80]
        details = " / ".join(f"{event['league_name']} {event['title']}" for event in slot[:4])
        source_message = slot[0].get("id") or "golden-football"
    hours = 2.5 if slot[0].get("kind") == "f1" else 2
    end = kickoff + timedelta(hours=hours)
    cmd = [
        sys.executable,
        str(REMINDER_PY),
        "add-event",
        "--title",
        title,
        "--start-at",
        kickoff.strftime("%Y-%m-%dT%H:%M"),
        "--end-at",
        end.strftime("%Y-%m-%dT%H:%M"),
        "--details",
        details,
        "--source-message",
        source_message,
    ]
    if job_id and job_id not in {"dry-run", "ok"}:
        cmd.extend(["--job-id", job_id, "--job-kind", "timer"])
    if dry_run:
        print("--- calendar ---\n" + " ".join(shlex.quote(c) for c in cmd))
        return
    subprocess.run(cmd, check=False, capture_output=True, text=True)


def notify(events: list[dict[str, Any]], dry_run: bool, week_id: str, force: bool) -> int:
    watched = [event for event in events if event.get("worthy")]
    if not watched:
        return 0
    state = load_state()
    digest_sent = bool(state.get("digests", {}).get(week_id))
    if (not digest_sent) or force:
        cc_send(format_digest(watched), dry_run)
        if not dry_run:
            state.setdefault("digests", {})[week_id] = datetime.now(TZ).isoformat()
            save_state(state)

    existing = timer_list_text()
    for slot in worthy_slots(watched):
        slot_key = (slot[0].get("kickoff") or "")[:16]
        if slot_key in (state.get("kickoffs") or {}) and not dry_run:
            continue
        if already_has_kickoff_timer(slot, existing) and not dry_run:
            continue
        job_id = schedule_kickoff_slot(slot, dry_run)
        if not job_id:
            continue
        add_calendar_slot(slot, job_id, dry_run)
        if not dry_run:
            state.setdefault("kickoffs", {})[slot_key] = job_id
            save_state(state)
    return 0


def main() -> int:
    args = parse_args()
    now = datetime.now(TZ)
    until = now + timedelta(hours=args.hours) if args.hours > 0 else week_close(now)
    events = collect_events(now, until, args.include_ended)
    if args.marquee > 0:
        events = pick_marquee(events, args.marquee)
    if args.notify:
        return notify(events, args.dry_run, iso_week_id(now), args.force)
    if args.json:
        json.dump(
            {"now": now.isoformat(), "until": until.isoformat(), "events": events},
            sys.stdout,
            ensure_ascii=False,
            indent=2,
        )
        sys.stdout.write("\n")
        return 0
    if not events:
        return 0
    for event in events:
        print(f"{event['kickoff_text']}  {event['league_name']}  {event['title']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
