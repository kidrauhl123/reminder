#!/usr/bin/env python3
"""Local reminder store. Schema lives here; agents must not write SQL."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

SCHEMA_VERSION = "5"

REMINDER_STATUSES = ("active", "paused", "done", "cancelled", "snoozed")
REMINDER_KINDS = ("action", "event", "deadline")
REMINDER_KIND_SECTIONS = (
    ("action", "必做"),
    ("deadline", "截止"),
    ("event", "可选"),
)
EVENT_STATUSES = ("active", "cancelled", "done")
EVENT_KINDS = ("session", "holiday", "break", "marker")
EVENT_KIND_LABELS = {
    "holiday": "节日",
    "break": "假期",
    "marker": "日子",
}
INTENTION_STATUSES = ("open", "paused", "dropped", "done")
STRENGTHS = ("weak", "medium", "strong")
ANCHOR_KINDS = ("meal", "sleep", "class", "commute", "busy", "free")
NUDGE_OUTCOMES = ("sent", "accepted", "completed", "rejected", "annoyed", "skip")
JOB_KINDS = ("timer", "cron", "other")
EVENT_SOURCES = ("user", "cn", "cityu-dg", "lunar")
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
WEEKDAY_ZH = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
CN_HOLIDAY_URLS = (
    "https://cdn.jsdelivr.net/gh/NateScarlet/holiday-cn@master/{year}.json",
    "https://raw.githubusercontent.com/NateScarlet/holiday-cn/master/{year}.json",
)
HKO_LUNAR_URL = "https://www.hko.gov.hk/tc/gts/time/calendar/text/files/T{year}c.txt"
GAN = "甲乙丙丁戊己庚辛壬癸"
ZHI = "子丑寅卯辰巳午未申酉戌亥"
ZODIAC = "鼠牛虎兔龙蛇马羊猴鸡狗猪"
HANS = str.maketrans({
    "馬": "马",
    "龍": "龙",
    "雞": "鸡",
    "豬": "猪",
    "驚": "惊",
    "蟄": "蛰",
    "穀": "谷",
    "滿": "满",
    "種": "种",
    "處": "处",
    "閏": "闰",
    "曆": "历",
    "農": "农",
    "節": "节",
})
LUNAR_DAY_NAMES = (
    "初一,初二,初三,初四,初五,初六,初七,初八,初九,初十,"
    "十一,十二,十三,十四,十五,十六,十七,十八,十九,二十,"
    "廿一,廿二,廿三,廿四,廿五,廿六,廿七,廿八,廿九,三十"
).split(",")
LUNAR_DAY_NUM = {name: i + 1 for i, name in enumerate(LUNAR_DAY_NAMES)}
LUNAR_MONTH_NAMES = ("正月", "二月", "三月", "四月", "五月", "六月", "七月", "八月", "九月", "十月", "十一月", "十二月")
LUNAR_FESTIVALS = {
    (1, 1): "春节",
    (1, 15): "元宵节",
    (2, 2): "龙抬头",
    (5, 5): "端午节",
    (7, 7): "七夕",
    (7, 15): "中元节",
    (8, 15): "中秋节",
    (9, 9): "重阳节",
    (12, 8): "腊八",
    (12, 23): "小年",
}
LUNAR_EVENT_KINDS = {
    "除夕": "holiday",
    "元宵节": "holiday",
    "龙抬头": "marker",
    "七夕": "holiday",
    "中元节": "marker",
    "重阳节": "holiday",
    "腊八": "marker",
    "小年": "marker",
    "立春": "marker",
    "冬至": "marker",
}
HKO_ROW_RE = re.compile(r"^(\d{4})年(\d{1,2})月(\d{1,2})日\s+(\S+)\s+星期(\S+)\s*(.*)$")
HKO_HEADER_RE = re.compile(r"^(\d{4})\((.{2}) - 肖(.+)\)")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reminders (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  details TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  kind TEXT NOT NULL DEFAULT 'action',
  remind_at TEXT,
  due_at TEXT,
  repeat_rule TEXT,
  job_id TEXT,
  job_kind TEXT,
  intention_id TEXT,
  source_message TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS intentions (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  details TEXT,
  strength TEXT NOT NULL DEFAULT 'weak',
  weekly_target INTEGER NOT NULL DEFAULT 0,
  min_action TEXT,
  preferred_window TEXT,
  nudge_ok INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'open',
  last_mentioned_at TEXT,
  last_completed_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS life_anchors (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  kind TEXT NOT NULL,
  weekdays TEXT NOT NULL DEFAULT 'daily',
  start_time TEXT,
  end_time TEXT,
  details TEXT,
  blocks_nudge INTEGER NOT NULL DEFAULT 1,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS nudge_history (
  id TEXT PRIMARY KEY,
  intention_id TEXT,
  reminder_id TEXT,
  outcome TEXT NOT NULL,
  note TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  details TEXT,
  location TEXT,
  start_at TEXT NOT NULL,
  end_at TEXT,
  all_day INTEGER NOT NULL DEFAULT 0,
  optional INTEGER NOT NULL DEFAULT 1,
  kind TEXT NOT NULL DEFAULT 'session',
  status TEXT NOT NULL DEFAULT 'active',
  reminder_id TEXT,
  source TEXT NOT NULL DEFAULT 'user',
  source_message TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reminders_status ON reminders(status);
CREATE INDEX IF NOT EXISTS idx_reminders_remind_at ON reminders(remind_at);
CREATE INDEX IF NOT EXISTS idx_intentions_status ON intentions(status);
CREATE INDEX IF NOT EXISTS idx_anchors_active ON life_anchors(active);
CREATE INDEX IF NOT EXISTS idx_nudge_intention ON nudge_history(intention_id, created_at);
CREATE INDEX IF NOT EXISTS idx_events_start ON events(start_at);
CREATE INDEX IF NOT EXISTS idx_events_status ON events(status);
CREATE INDEX IF NOT EXISTS idx_events_reminder ON events(reminder_id);
"""


def skill_root() -> Path:
    return Path(__file__).resolve().parent.parent


def bundled_cn_dir() -> Path:
    return skill_root() / "data" / "cn"


def bundled_cn_path(year: int) -> Path:
    return bundled_cn_dir() / f"{year}.json"


def bundled_cn_years() -> list[int]:
    folder = bundled_cn_dir()
    if not folder.is_dir():
        return []
    years: list[int] = []
    for path in folder.glob("*.json"):
        try:
            years.append(int(path.stem))
        except ValueError:
            continue
    return sorted(set(years))


def bundled_lunar_dir() -> Path:
    return skill_root() / "data" / "lunar"


def bundled_lunar_path(year: int) -> Path:
    return bundled_lunar_dir() / f"{year}.json"


def bundled_lunar_years() -> list[int]:
    folder = bundled_lunar_dir()
    if not folder.is_dir():
        return []
    years: list[int] = []
    for path in folder.glob("*.json"):
        try:
            years.append(int(path.stem))
        except ValueError:
            continue
    return sorted(set(years))


def data_home() -> Path:
    return Path(os.environ.get("REMINDER_HOME", Path.home() / ".reminder"))


def load_config() -> dict:
    cfg = data_home() / "config.json"
    if not cfg.is_file():
        return {}
    try:
        data = json.loads(cfg.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def load_tz():
    name = os.environ.get("REMINDER_TZ") or load_config().get("tz") or os.environ.get("TZ")
    if name:
        return ZoneInfo(name)
    return datetime.now().astimezone().tzinfo


def quiet_hours() -> tuple[str, str]:
    raw = load_config().get("quiet_hours")
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        return (str(raw[0])[:5], str(raw[1])[:5])
    return QUIET_HOURS


def local_now() -> datetime:
    return datetime.now(load_tz()).replace(microsecond=0)


def now_iso() -> str:
    return local_now().isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def default_db_path() -> Path:
    return data_home() / "reminder.sqlite"


def parse_when(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    text = value.strip()
    if "T" not in text and " " in text:
        text = text.replace(" ", "T", 1)
    if "T" not in text:
        try:
            return datetime.strptime(text[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError as exc:
            raise SystemExit(f"无法解析时间: {value}（用 2026-08-26T15:00）") from exc
    date_part, time_part = text.split("T", 1)
    time_part = time_part.replace("Z", "")
    if "+" in time_part:
        time_part = time_part.split("+", 1)[0]
    elif len(time_part) >= 6 and time_part[-6] == "-" and time_part[-3] == ":":
        time_part = time_part[:-6]
    time_part = time_part.strip()
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            tm = datetime.strptime(time_part, fmt)
            datetime.strptime(date_part, "%Y-%m-%d")
            return f"{date_part}T{tm.strftime('%H:%M:%S')}"
        except ValueError:
            continue
    raise SystemExit(f"无法解析时间: {value}（用 2026-08-26T15:00）")


def parse_date(value: str | None) -> datetime:
    tz = load_tz()
    if not value:
        return local_now()
    text = value.strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=tz)
        except ValueError:
            continue
    raise SystemExit(f"无法解析日期: {value}（用 2026-08-26）")


def parse_weekdays(value: str | None) -> str:
    raw = (value or "daily").strip().lower().replace("，", ",")
    if raw in ("*", "daily", "every", "每天"):
        return "daily"
    if raw in ("weekdays", "weekday", "工作日"):
        return "mon,tue,wed,thu,fri"
    if raw in ("weekends", "weekend", "周末"):
        return "sat,sun"
    names = []
    aliases = {
        "monday": "mon",
        "tuesday": "tue",
        "wednesday": "wed",
        "thursday": "thu",
        "friday": "fri",
        "saturday": "sat",
        "sunday": "sun",
        "一": "mon",
        "二": "tue",
        "三": "wed",
        "四": "thu",
        "五": "fri",
        "六": "sat",
        "日": "sun",
        "天": "sun",
    }
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        token = aliases.get(token, token)
        token = token[:3]
        if token not in WEEKDAYS:
            raise SystemExit(f"未知星期: {part}")
        if token not in names:
            names.append(token)
    if not names:
        raise SystemExit("weekdays 不能为空")
    return ",".join(names)


def weekday_matches(stored: str, day: datetime) -> bool:
    if not stored or stored in ("daily", "*"):
        return True
    return WEEKDAYS[day.weekday()] in stored.split(",")


def date_of(iso: str | None) -> str | None:
    if not iso:
        return None
    return iso[:10]


def require_enum(name: str, value: str | None, allowed: tuple[str, ...], default: str | None = None) -> str | None:
    if value is None:
        return default
    if value not in allowed:
        raise SystemExit(f"{name} 只能是: {', '.join(allowed)}")
    return value


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def reminder_status_to_event(status: str | None) -> str:
    if status in ("cancelled", "done"):
        return status
    return "active"


def ensure_event_for_reminder(conn: sqlite3.Connection, reminder_id: str) -> str | None:
    rem = conn.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
    if rem is None or rem["kind"] != "event":
        return None
    existing = conn.execute("SELECT id FROM events WHERE reminder_id = ?", (reminder_id,)).fetchone()
    if existing:
        return existing["id"]
    start = rem["remind_at"] or rem["due_at"]
    if not start:
        return None
    item_id = new_id("e")
    stamp = now_iso()
    conn.execute(
        """INSERT INTO events(
            id, title, details, location, start_at, end_at, all_day, optional,
            kind, status, reminder_id, source, source_message, created_at, updated_at
        ) VALUES (?, ?, ?, NULL, ?, ?, 0, 1, 'session', ?, ?, 'user', ?, ?, ?)""",
        (
            item_id,
            rem["title"],
            rem["details"],
            start,
            rem["due_at"],
            reminder_status_to_event(rem["status"]),
            reminder_id,
            rem["source_message"],
            rem["created_at"] or stamp,
            stamp,
        ),
    )
    return item_id


def migrate(conn: sqlite3.Connection) -> None:
    cols = table_columns(conn, "reminders")
    if "kind" not in cols:
        conn.execute("ALTER TABLE reminders ADD COLUMN kind TEXT NOT NULL DEFAULT 'action'")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reminders_kind ON reminders(kind)")
    event_cols = table_columns(conn, "events")
    if "kind" not in event_cols:
        conn.execute("ALTER TABLE events ADD COLUMN kind TEXT NOT NULL DEFAULT 'session'")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_kind ON events(kind)")
    if "source" not in event_cols:
        conn.execute("ALTER TABLE events ADD COLUMN source TEXT NOT NULL DEFAULT 'user'")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_source ON events(source)")
    for row in conn.execute("SELECT id FROM reminders WHERE kind = 'event'"):
        ensure_event_for_reminder(conn, row["id"])
    seed_bundled_cn(conn)
    seed_bundled_lunar(conn)
    stamp = now_iso()
    conn.execute(
        "INSERT INTO schema_meta(key, value, updated_at) VALUES(?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        ("version", SCHEMA_VERSION, stamp),
    )


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_SQL)
    migrate(conn)
    conn.commit()
    return conn


def row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}


def emit(args: argparse.Namespace, data: Any, human: str) -> None:
    if args.json:
        json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(human.rstrip() + "\n")


def get_one(conn: sqlite3.Connection, table: str, item_id: str) -> sqlite3.Row:
    row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        raise SystemExit(f"找不到 {table} id={item_id}")
    return row


def cmd_init(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    emit(args, {"db": str(args.db_path), "version": SCHEMA_VERSION}, f"已就绪 {args.db_path}")


def cmd_status(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    version = conn.execute("SELECT value FROM schema_meta WHERE key = 'version'").fetchone()[0]
    counts = {
        "reminders": conn.execute("SELECT COUNT(*) FROM reminders").fetchone()[0],
        "events": conn.execute("SELECT COUNT(*) FROM events").fetchone()[0],
        "intentions": conn.execute("SELECT COUNT(*) FROM intentions").fetchone()[0],
        "life_anchors": conn.execute("SELECT COUNT(*) FROM life_anchors").fetchone()[0],
        "nudge_history": conn.execute("SELECT COUNT(*) FROM nudge_history").fetchone()[0],
    }
    tz = str(load_tz())
    data = {"db": str(args.db_path), "version": version, "tz": tz, "counts": counts}
    lines = [f"db {args.db_path}", f"version {version}", f"tz {tz}"]
    lines.extend(f"{k} {v}" for k, v in counts.items())
    emit(args, data, "\n".join(lines))


def cmd_add_reminder(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    item_id = new_id("r")
    stamp = now_iso()
    status = require_enum("status", args.status, REMINDER_STATUSES, "active")
    kind = require_enum("kind", args.kind, REMINDER_KINDS, "action")
    job_kind = require_enum("job-kind", args.job_kind, JOB_KINDS) if args.job_kind else None
    conn.execute(
        """INSERT INTO reminders(
            id, title, details, status, kind, remind_at, due_at, repeat_rule,
            job_id, job_kind, intention_id, source_message, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            item_id,
            args.title,
            args.details,
            status,
            kind,
            parse_when(args.remind_at),
            parse_when(args.due_at),
            args.repeat_rule,
            args.job_id,
            job_kind,
            args.intention_id,
            args.source_message,
            stamp,
            stamp,
        ),
    )
    conn.commit()
    if kind == "event":
        ensure_event_for_reminder(conn, item_id)
        conn.commit()
    row = row_dict(get_one(conn, "reminders", item_id))
    emit(args, row, f"reminder {item_id}  [{kind}]  {args.title}")


def cmd_set_reminder(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    get_one(conn, "reminders", args.id)
    fields: dict[str, Any] = {}
    if args.title is not None:
        fields["title"] = args.title
    if args.details is not None:
        fields["details"] = args.details
    if args.status is not None:
        fields["status"] = require_enum("status", args.status, REMINDER_STATUSES)
    if args.kind is not None:
        fields["kind"] = require_enum("kind", args.kind, REMINDER_KINDS)
    if args.remind_at is not None:
        fields["remind_at"] = parse_when(args.remind_at)
    if args.due_at is not None:
        fields["due_at"] = parse_when(args.due_at)
    if args.repeat_rule is not None:
        fields["repeat_rule"] = args.repeat_rule
    if args.job_id is not None:
        fields["job_id"] = args.job_id
    if args.job_kind is not None:
        fields["job_kind"] = require_enum("job-kind", args.job_kind, JOB_KINDS)
    if args.intention_id is not None:
        fields["intention_id"] = args.intention_id
    if args.source_message is not None:
        fields["source_message"] = args.source_message
    if not fields:
        raise SystemExit("set-reminder 需要至少一个要改的字段")
    fields["updated_at"] = now_iso()
    assignments = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE reminders SET {assignments} WHERE id = ?", [*fields.values(), args.id])
    conn.commit()
    row = row_dict(get_one(conn, "reminders", args.id))
    if row["kind"] == "event":
        event_id = ensure_event_for_reminder(conn, args.id)
        if event_id:
            ev_fields: dict[str, Any] = {"updated_at": now_iso()}
            if "title" in fields:
                ev_fields["title"] = fields["title"]
            if "details" in fields:
                ev_fields["details"] = fields["details"]
            if "source_message" in fields:
                ev_fields["source_message"] = fields["source_message"]
            if "remind_at" in fields or "due_at" in fields:
                ev_fields["start_at"] = row["remind_at"] or row["due_at"]
                ev_fields["end_at"] = row["due_at"]
            if "status" in fields:
                ev_fields["status"] = reminder_status_to_event(row["status"])
            sets = ", ".join(f"{k} = ?" for k in ev_fields)
            conn.execute(f"UPDATE events SET {sets} WHERE id = ?", [*ev_fields.values(), event_id])
            conn.commit()
    emit(args, row, f"reminder {args.id}  [{row['kind']}/{row['status']}]  {row['title']}")


def cmd_list_reminders(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    clauses: list[str] = []
    params: list[Any] = []
    if args.status == "all":
        pass
    elif args.status:
        require_enum("status", args.status, REMINDER_STATUSES)
        clauses.append("status = ?")
        params.append(args.status)
    else:
        clauses.append("status NOT IN ('done', 'cancelled')")
    if args.kind:
        require_enum("kind", args.kind, REMINDER_KINDS)
        clauses.append("kind = ?")
        params.append(args.kind)
    sql = "SELECT * FROM reminders"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY remind_at IS NULL, remind_at, created_at"
    rows = conn.execute(sql, params).fetchall()
    items = [row_dict(r) for r in rows]
    lines = [
        f"{r['id']}  [{r.get('kind') or 'action'}/{r['status']}]  {r['title']}"
        + (f"  {r['remind_at']}" if r["remind_at"] else "")
        + (f"  due {r['due_at']}" if r["due_at"] else "")
        for r in items
    ]
    emit(args, items, "\n".join(lines) if lines else "(没有提醒)")


def event_label(row: dict[str, Any]) -> str:
    if row["status"] != "active":
        return row["status"]
    kind = row.get("kind") or "session"
    if kind in EVENT_KIND_LABELS:
        return EVENT_KIND_LABELS[kind]
    return "可选" if row.get("optional", 1) else "要去"


def is_day_event(row: dict[str, Any]) -> bool:
    return bool(row.get("all_day")) or (row.get("kind") or "session") != "session"


def format_event_span(row: dict[str, Any]) -> str:
    if row.get("all_day"):
        start = date_of(row["start_at"]) or "?"
        end = date_of(row["end_at"])
        if end and end != start:
            return f"{start}–{end}"
        return start
    start = row["start_at"] or "?"
    end = row["end_at"]
    if end and date_of(end) == date_of(start):
        return f"{start[11:16]}–{end[11:16]}"
    if end:
        return f"{start}–{end}"
    if "T" in start:
        return start[11:16]
    return start


def spans_day(start_at: str | None, end_at: str | None, day_key: str) -> bool:
    start = date_of(start_at)
    if not start:
        return False
    end = date_of(end_at) or start
    return start <= day_key <= end


def insert_event(
    conn: sqlite3.Connection,
    *,
    title: str,
    details: str | None,
    location: str | None,
    start_at: str,
    end_at: str | None,
    all_day: int,
    optional: int,
    kind: str,
    status: str,
    reminder_id: str | None,
    source: str,
    source_message: str | None,
    created_at: str | None = None,
) -> str:
    item_id = new_id("e")
    stamp = now_iso()
    created = created_at or stamp
    conn.execute(
        """INSERT INTO events(
            id, title, details, location, start_at, end_at, all_day, optional,
            kind, status, reminder_id, source, source_message, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            item_id,
            title,
            details,
            location,
            start_at,
            end_at,
            all_day,
            optional,
            kind,
            status,
            reminder_id,
            source,
            source_message,
            created,
            stamp,
        ),
    )
    return item_id


def cmd_add_event(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    start_at = parse_when(args.start_at)
    if not start_at:
        raise SystemExit("add-event 需要 --start-at")
    end_at = parse_when(args.end_at)
    status = require_enum("status", args.status, EVENT_STATUSES, "active")
    kind = require_enum("kind", args.kind, EVENT_KINDS)
    if kind is None:
        kind = "marker" if args.all_day else "session"
    all_day = 1 if args.all_day or kind != "session" else 0
    optional = 0 if args.going else 1
    if args.optional is not None:
        optional = int(args.optional)
    if kind != "session":
        optional = 0 if args.optional is None and not args.going else optional
    reminder_id = args.reminder_id
    if args.job_id and not reminder_id:
        reminder_id = new_id("r")
        stamp = now_iso()
        rem_kind = "action" if optional == 0 else "event"
        conn.execute(
            """INSERT INTO reminders(
                id, title, details, status, kind, remind_at, due_at, repeat_rule,
                job_id, job_kind, intention_id, source_message, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, NULL, ?, ?, ?)""",
            (
                reminder_id,
                args.title,
                args.details,
                "active" if status == "active" else status,
                rem_kind,
                start_at,
                end_at,
                args.job_id,
                require_enum("job-kind", args.job_kind, JOB_KINDS) if args.job_kind else "timer",
                args.source_message,
                stamp,
                stamp,
            ),
        )
    elif reminder_id:
        get_one(conn, "reminders", reminder_id)
    item_id = insert_event(
        conn,
        title=args.title,
        details=args.details,
        location=args.location,
        start_at=start_at,
        end_at=end_at,
        all_day=all_day,
        optional=optional,
        kind=kind,
        status=status,
        reminder_id=reminder_id,
        source=require_enum("source", args.source, EVENT_SOURCES, "user") or "user",
        source_message=args.source_message,
    )
    conn.commit()
    row = row_dict(get_one(conn, "events", item_id))
    loc = f"  @ {row['location']}" if row["location"] else ""
    emit(args, row, f"event {item_id}  [{event_label(row)}]  {format_event_span(row)}  {args.title}{loc}")


def cmd_set_event(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    get_one(conn, "events", args.id)
    fields: dict[str, Any] = {}
    if args.title is not None:
        fields["title"] = args.title
    if args.details is not None:
        fields["details"] = args.details
    if args.location is not None:
        fields["location"] = args.location
    if args.start_at is not None:
        fields["start_at"] = parse_when(args.start_at)
    if args.end_at is not None:
        fields["end_at"] = parse_when(args.end_at)
    if args.all_day is not None:
        fields["all_day"] = int(args.all_day)
    if args.kind is not None:
        fields["kind"] = require_enum("kind", args.kind, EVENT_KINDS)
        if fields["kind"] != "session" and args.all_day is None:
            fields["all_day"] = 1
    if args.optional is not None:
        fields["optional"] = int(args.optional)
    if args.going:
        fields["optional"] = 0
    if args.status is not None:
        fields["status"] = require_enum("status", args.status, EVENT_STATUSES)
    if args.reminder_id is not None:
        if args.reminder_id:
            get_one(conn, "reminders", args.reminder_id)
        fields["reminder_id"] = args.reminder_id or None
    if args.source_message is not None:
        fields["source_message"] = args.source_message
    if not fields:
        raise SystemExit("set-event 需要至少一个要改的字段")
    fields["updated_at"] = now_iso()
    assignments = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE events SET {assignments} WHERE id = ?", [*fields.values(), args.id])
    conn.commit()
    row = row_dict(get_one(conn, "events", args.id))
    if row["reminder_id"]:
        rem_fields: dict[str, Any] = {"updated_at": now_iso()}
        if "title" in fields:
            rem_fields["title"] = row["title"]
        if "details" in fields:
            rem_fields["details"] = row["details"]
        if "start_at" in fields:
            rem_fields["remind_at"] = row["start_at"]
        if "end_at" in fields:
            rem_fields["due_at"] = row["end_at"]
        if "status" in fields:
            rem_fields["status"] = row["status"] if row["status"] in REMINDER_STATUSES else "cancelled"
        if "optional" in fields:
            rem_fields["kind"] = "action" if row["optional"] == 0 else "event"
        if len(rem_fields) > 1:
            sets = ", ".join(f"{k} = ?" for k in rem_fields)
            conn.execute(
                f"UPDATE reminders SET {sets} WHERE id = ?",
                [*rem_fields.values(), row["reminder_id"]],
            )
            conn.commit()
            row = row_dict(get_one(conn, "events", args.id))
    loc = f"  @ {row['location']}" if row["location"] else ""
    emit(args, row, f"event {args.id}  [{event_label(row)}]  {row['title']}{loc}")


def cmd_list_events(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    clauses: list[str] = []
    params: list[Any] = []
    if args.status == "all":
        pass
    elif args.status:
        require_enum("status", args.status, EVENT_STATUSES)
        clauses.append("status = ?")
        params.append(args.status)
    else:
        clauses.append("status = 'active'")
    if args.kind:
        require_enum("kind", args.kind, EVENT_KINDS)
        clauses.append("kind = ?")
        params.append(args.kind)
    if args.source:
        clauses.append("source = ?")
        params.append(args.source)
    day_from = parse_date(args.date).strftime("%Y-%m-%d") if args.date else None
    range_from = parse_date(args.start).strftime("%Y-%m-%d") if args.start else day_from
    range_to = parse_date(args.end).strftime("%Y-%m-%d") if args.end else day_from
    sql = "SELECT * FROM events"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY start_at IS NULL, start_at, created_at"
    rows = [row_dict(r) for r in conn.execute(sql, params).fetchall()]
    if range_from:
        end_key = range_to or range_from
        rows = [r for r in rows if r["start_at"] and date_of(r["start_at"]) <= end_key and (date_of(r["end_at"]) or date_of(r["start_at"])) >= range_from]
    lines = [
        f"{r['id']}  [{event_label(r)}]  {format_event_span(r)}  {r['title']}"
        + (f"  @ {r['location']}" if r["location"] else "")
        for r in rows
    ]
    emit(args, rows, "\n".join(lines) if lines else "(没有日程)")


def http_get_text(urls: list[str] | tuple[str, ...]) -> str:
    last: Exception | None = None
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "reminder-sync/1.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                return resp.read().decode("utf-8")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = exc
    raise SystemExit(f"拉不到数据: {last}")


def collapse_named_days(days: list[dict[str, Any]]) -> list[dict[str, Any]]:
    parsed: list[tuple[date, str, bool]] = []
    for item in days:
        try:
            parsed.append((date.fromisoformat(item["date"][:10]), str(item["name"]), bool(item["isOffDay"])))
        except (KeyError, TypeError, ValueError):
            continue
    parsed.sort()
    groups: list[dict[str, Any]] = []
    for day, name, off in parsed:
        if groups:
            prev = groups[-1]
            if prev["name"] == name and prev["off"] == off and day == prev["end"] + timedelta(days=1):
                prev["end"] = day
                continue
        groups.append({"name": name, "start": day, "end": day, "off": off})
    return groups


def upsert_sourced_event(
    conn: sqlite3.Connection,
    *,
    source: str,
    title: str,
    start_at: str,
    end_at: str | None,
    kind: str,
    details: str | None,
) -> str:
    existing = conn.execute(
        "SELECT id FROM events WHERE source = ? AND title = ? AND start_at = ?",
        (source, title, start_at),
    ).fetchone()
    stamp = now_iso()
    if existing:
        conn.execute(
            """UPDATE events SET end_at = ?, kind = ?, details = ?, all_day = 1, optional = 0,
               status = 'active', updated_at = ? WHERE id = ?""",
            (end_at, kind, details, stamp, existing["id"]),
        )
        return existing["id"]
    return insert_event(
        conn,
        title=title,
        details=details,
        location=None,
        start_at=start_at,
        end_at=end_at,
        all_day=1,
        optional=0,
        kind=kind,
        status="active",
        reminder_id=None,
        source=source,
        source_message=None,
    )


def cancel_missing_sourced(conn: sqlite3.Connection, source: str, keep_ids: set[str]) -> int:
    rows = conn.execute(
        "SELECT id FROM events WHERE source = ? AND status = 'active'",
        (source,),
    ).fetchall()
    n = 0
    stamp = now_iso()
    for row in rows:
        if row["id"] not in keep_ids:
            conn.execute(
                "UPDATE events SET status = 'cancelled', updated_at = ? WHERE id = ?",
                (stamp, row["id"]),
            )
            n += 1
    return n


def read_cn_json(raw: str, year: int) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{year} 节假日 JSON 无效") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"{year} 节假日 JSON 无效")
    return data


def load_cn_year(year: int, *, refresh: bool = False) -> dict[str, Any] | None:
    path = bundled_cn_path(year)
    if not refresh:
        if path.is_file():
            return read_cn_json(path.read_text(encoding="utf-8"), year)
        return None
    try:
        data = read_cn_json(http_get_text([u.format(year=year) for u in CN_HOLIDAY_URLS]), year)
    except SystemExit:
        if path.is_file():
            return read_cn_json(path.read_text(encoding="utf-8"), year)
        raise
    if data.get("days"):
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "year": data.get("year", year),
            "papers": data.get("papers") or [],
            "source": "https://github.com/NateScarlet/holiday-cn",
            "days": data["days"],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return payload
    return data


def apply_cn_payloads(
    conn: sqlite3.Connection,
    payloads: list[dict[str, Any]],
    *,
    prune: bool,
) -> tuple[int, int, list[int]]:
    rows: list[dict[str, Any]] = []
    empty: list[int] = []
    for payload in payloads:
        chunk = events_from_cn(payload)
        year = payload.get("year")
        if not chunk:
            if isinstance(year, int):
                empty.append(year)
            continue
        rows.extend(chunk)
    keep: set[str] = set()
    for row in rows:
        keep.add(
            upsert_sourced_event(
                conn,
                source="cn",
                title=row["title"],
                start_at=row["start_at"],
                end_at=row["end_at"],
                kind=row["kind"],
                details=row["details"],
            )
        )
    cancelled = cancel_missing_sourced(conn, "cn", keep) if prune else 0
    return len(keep), cancelled, empty


def seed_bundled_cn(conn: sqlite3.Connection) -> None:
    payloads = []
    for year in bundled_cn_years():
        payload = load_cn_year(year, refresh=False)
        if payload:
            payloads.append(payload)
    if payloads:
        apply_cn_payloads(conn, payloads, prune=False)


def hans(text: str) -> str:
    return text.translate(HANS)


def ganzhi_index(name: str) -> int:
    if len(name) < 2:
        raise SystemExit(f"干支无效: {name}")
    gan, zhi = name[0], name[1]
    for i in range(60):
        if GAN[i % 10] == gan and ZHI[i % 12] == zhi:
            return i
    raise SystemExit(f"干支无效: {name}")


def shift_ganzhi(name: str, delta: int) -> str:
    i = (ganzhi_index(name) + delta) % 60
    return GAN[i % 10] + ZHI[i % 12]


def zodiac_of(ganzhi: str) -> str:
    return ZODIAC[ZHI.index(ganzhi[1])]


def parse_lunar_month_token(token: str) -> tuple[int, bool] | None:
    text = hans(token)
    leap = text.startswith("闰")
    if leap:
        text = text[1:]
    if text == "腊月":
        return 12, leap
    if text in LUNAR_MONTH_NAMES:
        return LUNAR_MONTH_NAMES.index(text) + 1, leap
    return None


def lunar_label(month: int, day: int, leap: bool) -> str:
    month_name = LUNAR_MONTH_NAMES[month - 1]
    if month == 12 and not leap:
        month_name = "腊月"
    if leap:
        month_name = "闰" + month_name
    return month_name + LUNAR_DAY_NAMES[day - 1]


def parse_hko_lunar(text: str, year: int) -> dict[str, Any]:
    header = hans(text.splitlines()[0].lstrip("\ufeff").strip())
    matched = HKO_HEADER_RE.match(header)
    if not matched:
        raise SystemExit(f"{year} 农历表头无法解析: {header}")
    file_year = int(matched.group(1))
    ganzhi = matched.group(2)
    raw_rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        row = HKO_ROW_RE.match(line.strip())
        if not row:
            continue
        raw_rows.append(
            {
                "date": date(int(row.group(1)), int(row.group(2)), int(row.group(3))),
                "token": hans(row.group(4)),
                "jieqi": hans(row.group(6).strip()) or None,
            }
        )
    if not raw_rows:
        raise SystemExit(f"{year} 农历表没有日期行")
    month = 0
    leap = False
    filled: list[dict[str, Any]] = []
    for item in raw_rows:
        parsed_month = parse_lunar_month_token(item["token"])
        if parsed_month:
            month, leap = parsed_month
            day = 1
        else:
            day = LUNAR_DAY_NUM.get(item["token"])
            if not day:
                raise SystemExit(f"{item['date']} 农历无法解析: {item['token']}")
        filled.append(
            {
                "date": item["date"],
                "month": month,
                "day": day,
                "leap": leap,
                "jieqi": item["jieqi"],
            }
        )
    first_start = next((i for i, item in enumerate(filled) if item["day"] == 1 and item["month"]), None)
    if first_start is None:
        raise SystemExit(f"{year} 农历表没有月初")
    if first_start:
        start_month = filled[first_start]["month"] - 1 or 12
        for item in filled[:first_start]:
            item["month"] = start_month
            item["leap"] = False
    prev_gz = shift_ganzhi(ganzhi, -1)
    seen_spring = False
    days: list[dict[str, Any]] = []
    for i, item in enumerate(filled):
        if item["month"] == 1 and item["day"] == 1 and not item["leap"]:
            seen_spring = True
        gz = ganzhi if seen_spring else prev_gz
        festivals: list[str] = []
        if not item["leap"]:
            name = LUNAR_FESTIVALS.get((item["month"], item["day"]))
            if name:
                festivals.append(name)
        nxt = filled[i + 1] if i + 1 < len(filled) else None
        if nxt and nxt["month"] == 1 and nxt["day"] == 1 and not nxt["leap"]:
            festivals.append("除夕")
        entry: dict[str, Any] = {
            "date": item["date"].isoformat(),
            "lunar": lunar_label(item["month"], item["day"], item["leap"]),
            "ganzhi": gz,
        }
        if item["jieqi"]:
            entry["jieqi"] = item["jieqi"]
        if festivals:
            entry["festivals"] = festivals
        days.append(entry)
    return {
        "year": file_year,
        "ganzhi": ganzhi,
        "zodiac": zodiac_of(ganzhi),
        "source": HKO_LUNAR_URL.format(year=file_year),
        "days": days,
    }


def load_lunar_year(year: int, *, refresh: bool = False) -> dict[str, Any] | None:
    path = bundled_lunar_path(year)
    if not refresh:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
        return None
    raw = http_get_text([HKO_LUNAR_URL.format(year=year)])
    payload = parse_hko_lunar(raw, year)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def events_from_lunar(payload: dict[str, Any]) -> list[dict[str, Any]]:
    origin = payload.get("source") or HKO_LUNAR_URL.format(year=payload.get("year"))
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in payload.get("days") or []:
        start = item.get("date")
        if not start:
            continue
        names = list(item.get("festivals") or [])
        jieqi = item.get("jieqi")
        if jieqi in LUNAR_EVENT_KINDS:
            names.append(jieqi)
        for name in names:
            kind = LUNAR_EVENT_KINDS.get(name)
            if not kind:
                continue
            key = (name, start)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "title": name,
                    "kind": kind,
                    "start_at": start,
                    "end_at": None,
                    "details": f"农历 {item.get('lunar')}；{origin}",
                }
            )
    return rows


def apply_lunar_payloads(
    conn: sqlite3.Connection,
    payloads: list[dict[str, Any]],
    *,
    prune: bool,
) -> tuple[int, int]:
    rows: list[dict[str, Any]] = []
    for payload in payloads:
        rows.extend(events_from_lunar(payload))
    keep: set[str] = set()
    for row in rows:
        keep.add(
            upsert_sourced_event(
                conn,
                source="lunar",
                title=row["title"],
                start_at=row["start_at"],
                end_at=row["end_at"],
                kind=row["kind"],
                details=row["details"],
            )
        )
    cancelled = cancel_missing_sourced(conn, "lunar", keep) if prune else 0
    return len(keep), cancelled


def seed_bundled_lunar(conn: sqlite3.Connection) -> None:
    payloads = []
    for year in bundled_lunar_years():
        payload = load_lunar_year(year, refresh=False)
        if payload:
            payloads.append(payload)
    if payloads:
        apply_lunar_payloads(conn, payloads, prune=False)


def lunar_day_lookup(day_key: str) -> dict[str, Any] | None:
    try:
        year = int(day_key[:4])
    except ValueError:
        return None
    payload = load_lunar_year(year, refresh=False)
    if not payload:
        return None
    for item in payload.get("days") or []:
        if item.get("date") == day_key:
            return item
    return None


def events_from_cn(payload: dict[str, Any]) -> list[dict[str, Any]]:
    papers = payload.get("papers") or []
    origin = papers[0] if papers else "https://github.com/NateScarlet/holiday-cn"
    year = payload.get("year")
    details = f"国务院放假安排 {year}；{origin}"
    rows: list[dict[str, Any]] = []
    for group in collapse_named_days(payload.get("days") or []):
        start = group["start"].isoformat()
        end = group["end"].isoformat() if group["end"] != group["start"] else None
        if group["off"]:
            rows.append(
                {
                    "title": group["name"],
                    "kind": "holiday",
                    "start_at": start,
                    "end_at": end,
                    "details": details,
                }
            )
        else:
            rows.append(
                {
                    "title": f"补班（{group['name']}）",
                    "kind": "marker",
                    "start_at": start,
                    "end_at": end,
                    "details": details,
                }
            )
    return rows


def events_from_file(path: Path) -> tuple[str, list[dict[str, Any]]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"读不了 {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("days"), list):
        raise SystemExit(f"{path} 需要 {{source, origin, days: [...]}}")
    source = str(data.get("source") or "file")
    origin = data.get("origin")
    rows: list[dict[str, Any]] = []
    for item in data["days"]:
        if not isinstance(item, dict) or not item.get("title") or not item.get("start"):
            continue
        kind = item.get("kind") or "marker"
        if kind not in EVENT_KINDS or kind == "session":
            kind = "marker"
        start = parse_when(str(item["start"]))
        end = parse_when(str(item["end"])) if item.get("end") else None
        details = item.get("details") or origin
        rows.append(
            {
                "title": str(item["title"]),
                "kind": kind,
                "start_at": start,
                "end_at": end,
                "details": details,
            }
        )
    return source, rows


def cmd_sync_days(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    source_name = args.source
    if source_name == "cn":
        refresh = bool(getattr(args, "refresh", False))
        years = args.year or (None if refresh else bundled_cn_years())
        if not years:
            now = local_now()
            years = [now.year, now.year + 1]
        payloads = []
        missing: list[int] = []
        for year in years:
            payload = load_cn_year(year, refresh=refresh)
            if payload is None:
                missing.append(year)
            else:
                payloads.append(payload)
        upserted, cancelled, empty = apply_cn_payloads(conn, payloads, prune=True)
        empty = sorted(set(empty + missing))
        source = "cn"
        note = "data/cn（仓库预填）" if not refresh else "holiday-cn 刷新"
        conn.commit()
        empty_note = f"；{', '.join(str(y) for y in empty)} 年还没公布" if empty else ""
        emit(
            args,
            {
                "source": source,
                "upserted": upserted,
                "cancelled": cancelled,
                "empty_years": empty,
                "from": note,
            },
            f"已同步 {source}  {upserted} 条{empty_note}"
            + (f"；收掉过期 {cancelled} 条" if cancelled else ""),
        )
        return
    if source_name == "lunar":
        refresh = bool(getattr(args, "refresh", False))
        years = args.year or bundled_lunar_years()
        if not years:
            now = local_now()
            years = [now.year, now.year + 1]
        payloads = []
        missing: list[int] = []
        for year in years:
            try:
                payload = load_lunar_year(year, refresh=refresh)
            except SystemExit:
                if refresh:
                    raise
                payload = None
            if payload is None:
                missing.append(year)
            else:
                payloads.append(payload)
        upserted, cancelled = apply_lunar_payloads(conn, payloads, prune=True)
        conn.commit()
        miss = f"；缺 {', '.join(str(y) for y in missing)} 年" if missing else ""
        emit(
            args,
            {
                "source": "lunar",
                "upserted": upserted,
                "cancelled": cancelled,
                "missing_years": missing,
                "from": "data/lunar" if not refresh else "香港天文台年历",
            },
            f"已同步 lunar  {upserted} 条{miss}"
            + (f"；收掉过期 {cancelled} 条" if cancelled else ""),
        )
        return
    if source_name != "file":
        raise SystemExit("sync-days --source 只能是 cn、lunar 或 file")
    if not args.path:
        raise SystemExit("sync-days --source file 需要 --path")
    source, rows = events_from_file(Path(args.path).expanduser())
    keep: set[str] = set()
    for row in rows:
        keep.add(
            upsert_sourced_event(
                conn,
                source=source,
                title=row["title"],
                start_at=row["start_at"],
                end_at=row["end_at"],
                kind=row["kind"],
                details=row["details"],
            )
        )
    cancelled = cancel_missing_sourced(conn, source, keep)
    conn.commit()
    emit(
        args,
        {"source": source, "upserted": len(keep), "cancelled": cancelled, "from": args.path},
        f"已同步 {source}  {len(keep)} 条" + (f"；收掉过期 {cancelled} 条" if cancelled else ""),
    )


def cmd_add_intention(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    item_id = new_id("i")
    stamp = now_iso()
    conn.execute(
        """INSERT INTO intentions(
            id, title, details, strength, weekly_target, min_action, preferred_window,
            nudge_ok, status, last_mentioned_at, last_completed_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            item_id,
            args.title,
            args.details,
            require_enum("strength", args.strength, STRENGTHS, "weak"),
            args.weekly_target,
            args.min_action,
            args.preferred_window,
            0 if args.no_nudge else 1,
            require_enum("status", args.status, INTENTION_STATUSES, "open"),
            stamp,
            None,
            stamp,
            stamp,
        ),
    )
    conn.commit()
    row = row_dict(get_one(conn, "intentions", item_id))
    emit(args, row, f"intention {item_id}  {args.title}")


def cmd_set_intention(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    get_one(conn, "intentions", args.id)
    fields: dict[str, Any] = {}
    if args.title is not None:
        fields["title"] = args.title
    if args.details is not None:
        fields["details"] = args.details
    if args.strength is not None:
        fields["strength"] = require_enum("strength", args.strength, STRENGTHS)
    if args.weekly_target is not None:
        fields["weekly_target"] = args.weekly_target
    if args.min_action is not None:
        fields["min_action"] = args.min_action
    if args.preferred_window is not None:
        fields["preferred_window"] = args.preferred_window
    if args.nudge_ok is not None:
        fields["nudge_ok"] = 1 if args.nudge_ok else 0
    if args.status is not None:
        fields["status"] = require_enum("status", args.status, INTENTION_STATUSES)
    if not fields:
        raise SystemExit("set-intention 需要至少一个要改的字段")
    fields["updated_at"] = now_iso()
    assignments = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE intentions SET {assignments} WHERE id = ?", [*fields.values(), args.id])
    conn.commit()
    row = row_dict(get_one(conn, "intentions", args.id))
    emit(args, row, f"intention {args.id}  {row['title']}  [{row['status']}]")


def cmd_mention_intention(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    get_one(conn, "intentions", args.id)
    stamp = now_iso()
    conn.execute(
        "UPDATE intentions SET last_mentioned_at = ?, updated_at = ? WHERE id = ?",
        (stamp, stamp, args.id),
    )
    conn.commit()
    row = row_dict(get_one(conn, "intentions", args.id))
    emit(args, row, f"intention {args.id}  mentioned {stamp}")


def cmd_complete_intention(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    get_one(conn, "intentions", args.id)
    stamp = now_iso()
    conn.execute(
        "UPDATE intentions SET last_completed_at = ?, last_mentioned_at = ?, updated_at = ? WHERE id = ?",
        (stamp, stamp, stamp, args.id),
    )
    nudge_id = new_id("n")
    conn.execute(
        "INSERT INTO nudge_history(id, intention_id, reminder_id, outcome, note, created_at) "
        "VALUES (?, ?, NULL, 'completed', ?, ?)",
        (nudge_id, args.id, args.note, stamp),
    )
    conn.commit()
    row = row_dict(get_one(conn, "intentions", args.id))
    emit(args, row, f"intention {args.id}  completed {stamp}")


def cmd_list_intentions(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    if args.status == "all":
        rows = conn.execute("SELECT * FROM intentions ORDER BY updated_at DESC").fetchall()
    elif args.status:
        require_enum("status", args.status, INTENTION_STATUSES)
        rows = conn.execute(
            "SELECT * FROM intentions WHERE status = ? ORDER BY updated_at DESC", (args.status,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM intentions WHERE status = 'open' ORDER BY updated_at DESC"
        ).fetchall()
    items = [row_dict(r) for r in rows]
    lines = [
        f"{r['id']}  [{r['status']}/{r['strength']}]  {r['title']}"
        for r in items
    ]
    emit(args, items, "\n".join(lines) if lines else "(没有意愿)")


def cmd_add_anchor(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    item_id = new_id("a")
    stamp = now_iso()
    kind = require_enum("kind", args.kind, ANCHOR_KINDS)
    blocks = 0 if args.kind == "free" and args.blocks_nudge is None else (1 if args.blocks_nudge is None else int(args.blocks_nudge))
    conn.execute(
        """INSERT INTO life_anchors(
            id, title, kind, weekdays, start_time, end_time, details,
            blocks_nudge, active, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
        (
            item_id,
            args.title,
            kind,
            parse_weekdays(args.weekdays),
            args.start_time,
            args.end_time,
            args.details,
            blocks,
            stamp,
            stamp,
        ),
    )
    conn.commit()
    row = row_dict(get_one(conn, "life_anchors", item_id))
    emit(args, row, f"anchor {item_id}  {args.title}  {row['weekdays']} {args.start_time or '?'}-{args.end_time or '?'}")


def cmd_set_anchor(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    get_one(conn, "life_anchors", args.id)
    fields: dict[str, Any] = {}
    if args.title is not None:
        fields["title"] = args.title
    if args.kind is not None:
        fields["kind"] = require_enum("kind", args.kind, ANCHOR_KINDS)
    if args.weekdays is not None:
        fields["weekdays"] = parse_weekdays(args.weekdays)
    if args.start_time is not None:
        fields["start_time"] = args.start_time
    if args.end_time is not None:
        fields["end_time"] = args.end_time
    if args.details is not None:
        fields["details"] = args.details
    if args.blocks_nudge is not None:
        fields["blocks_nudge"] = int(args.blocks_nudge)
    if args.active is not None:
        fields["active"] = 1 if args.active else 0
    if not fields:
        raise SystemExit("set-anchor 需要至少一个要改的字段")
    fields["updated_at"] = now_iso()
    assignments = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE life_anchors SET {assignments} WHERE id = ?", [*fields.values(), args.id])
    conn.commit()
    row = row_dict(get_one(conn, "life_anchors", args.id))
    emit(args, row, f"anchor {args.id}  {row['title']}")


def cmd_list_anchors(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    if args.all:
        rows = conn.execute("SELECT * FROM life_anchors ORDER BY start_time IS NULL, start_time").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM life_anchors WHERE active = 1 ORDER BY start_time IS NULL, start_time"
        ).fetchall()
    items = [row_dict(r) for r in rows]
    lines = [
        f"{r['id']}  [{r['kind']}]  {r['title']}  {r['weekdays']} {r['start_time'] or '?'}-{r['end_time'] or '?'}"
        + ("" if r["active"] else "  (inactive)")
        for r in items
    ]
    emit(args, items, "\n".join(lines) if lines else "(没有背景锚点)")


def cmd_remove_anchor(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    get_one(conn, "life_anchors", args.id)
    conn.execute("DELETE FROM life_anchors WHERE id = ?", (args.id,))
    conn.commit()
    emit(args, {"id": args.id, "deleted": True}, f"deleted anchor {args.id}")


def cmd_log_nudge(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    outcome = require_enum("outcome", args.outcome, NUDGE_OUTCOMES)
    if args.intention_id:
        get_one(conn, "intentions", args.intention_id)
    if args.reminder_id:
        get_one(conn, "reminders", args.reminder_id)
    item_id = new_id("n")
    stamp = now_iso()
    conn.execute(
        "INSERT INTO nudge_history(id, intention_id, reminder_id, outcome, note, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (item_id, args.intention_id, args.reminder_id, outcome, args.note, stamp),
    )
    if args.intention_id and outcome in ("accepted", "completed"):
        conn.execute(
            "UPDATE intentions SET last_completed_at = CASE WHEN ? = 'completed' THEN ? ELSE last_completed_at END, "
            "last_mentioned_at = ?, updated_at = ? WHERE id = ?",
            (outcome, stamp, stamp, stamp, args.intention_id),
        )
    elif args.intention_id:
        conn.execute(
            "UPDATE intentions SET last_mentioned_at = ?, updated_at = ? WHERE id = ?",
            (stamp, stamp, args.intention_id),
        )
    conn.commit()
    row = row_dict(conn.execute("SELECT * FROM nudge_history WHERE id = ?", (item_id,)).fetchone())
    emit(args, row, f"nudge {item_id}  {outcome}")


def cmd_list_nudges(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    sql = "SELECT * FROM nudge_history"
    params: list[Any] = []
    if args.intention_id:
        sql += " WHERE intention_id = ?"
        params.append(args.intention_id)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(args.limit)
    rows = conn.execute(sql, params).fetchall()
    items = [row_dict(r) for r in rows]
    lines = [f"{r['created_at']}  {r['outcome']}  {r['intention_id'] or r['reminder_id'] or '-'}" for r in items]
    emit(args, items, "\n".join(lines) if lines else "(没有记录)")


def week_start(day: datetime) -> datetime:
    monday = day.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=day.weekday())
    return monday


NAMED_WINDOWS = {
    "morning": ("07:00", "11:00"),
    "上午": ("07:00", "11:00"),
    "afternoon": ("13:00", "17:30"),
    "下午": ("13:00", "17:30"),
    "evening": ("18:00", "22:00"),
    "晚上": ("18:00", "22:00"),
    "night": ("21:00", "23:30"),
}
DEFAULT_OPEN_WINDOWS = (("10:00", "12:00"), ("16:00", "21:30"))
QUIET_HOURS = ("23:00", "07:30")
CATCH_MINUTES = 22
SKIP_DAY_PERCENT = 18
COOLDOWN_HOURS = {
    "sent": 16,
    "accepted": 24,
    "completed": 24,
    "rejected": 48,
    "skip": 48,
    "annoyed": 96,
}


def parse_hhmm(text: str) -> time:
    return datetime.strptime(text.strip()[:5], "%H:%M").time()


def time_in_span(now_t: time, start: time, end: time) -> bool:
    if start <= end:
        return start <= now_t < end
    return now_t >= start or now_t < end


def parse_stored_dt(text: str | None, tz) -> datetime | None:
    if not text:
        return None
    dt = datetime.fromisoformat(text.strip())
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def preferred_windows(text: str | None) -> tuple[tuple[str, str], ...]:
    if not text or not text.strip():
        return DEFAULT_OPEN_WINDOWS
    raw = text.strip().lower()
    if raw in NAMED_WINDOWS:
        return (NAMED_WINDOWS[raw],)
    if "-" in raw:
        start, end = raw.split("-", 1)
        return ((start.strip(), end.strip()),)
    return DEFAULT_OPEN_WINDOWS


def in_windows(now_t: time, windows: tuple[tuple[str, str], ...]) -> bool:
    return any(time_in_span(now_t, parse_hhmm(a), parse_hhmm(b)) for a, b in windows)


def blocking_anchor(conn: sqlite3.Connection, now: datetime) -> dict[str, Any] | None:
    for row in conn.execute("SELECT * FROM life_anchors WHERE active = 1 AND blocks_nudge = 1"):
        if not weekday_matches(row["weekdays"], now):
            continue
        if not row["start_time"] or not row["end_time"]:
            continue
        if time_in_span(now.time(), parse_hhmm(row["start_time"]), parse_hhmm(row["end_time"])):
            return row_dict(row)
    return None


def sent_today(conn: sqlite3.Connection, now: datetime) -> bool:
    for row in conn.execute(
        "SELECT created_at FROM nudge_history WHERE outcome = 'sent' ORDER BY created_at DESC LIMIT 30"
    ):
        dt = parse_stored_dt(row["created_at"], now.tzinfo)
        if dt and dt.date() == now.date():
            return True
    return False


def last_nudge(conn: sqlite3.Connection, intention_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM nudge_history WHERE intention_id = ? ORDER BY created_at DESC LIMIT 1",
        (intention_id,),
    ).fetchone()


def week_counts(conn: sqlite3.Connection, intention_id: str, now: datetime) -> dict[str, int]:
    start = week_start(now).strftime("%Y-%m-%dT%H:%M:%S")
    rows = conn.execute(
        "SELECT outcome, COUNT(*) AS n FROM nudge_history "
        "WHERE intention_id = ? AND created_at >= ? GROUP BY outcome",
        (intention_id, start),
    ).fetchall()
    return {r["outcome"]: r["n"] for r in rows}


def digest_int(*parts: str) -> int:
    return int.from_bytes(hashlib.sha256("|".join(parts).encode()).digest()[:8], "big")


def open_minutes(windows: tuple[tuple[str, str], ...]) -> list[int]:
    q = quiet_hours()
    quiet_s, quiet_e = parse_hhmm(q[0]), parse_hhmm(q[1])
    minutes: list[int] = []
    for total in range(24 * 60):
        t = time(total // 60, total % 60)
        if time_in_span(t, quiet_s, quiet_e):
            continue
        if in_windows(t, windows):
            minutes.append(total)
    return minutes


def todays_slot(intention_id: str, now: datetime, windows: tuple[tuple[str, str], ...]) -> datetime | None:
    minutes = open_minutes(windows)
    if not minutes:
        return None
    pick = minutes[digest_int(now.date().isoformat(), intention_id, "slot") % len(minutes)]
    return now.replace(hour=pick // 60, minute=pick % 60, second=0, microsecond=0)


def skip_this_day(intention_id: str, now: datetime) -> bool:
    return digest_int(now.date().isoformat(), intention_id, "skip") % 100 < SKIP_DAY_PERCENT


def compose_nudge(intention: dict[str, Any]) -> str | None:
    action = (intention.get("min_action") or "").strip()
    if not action:
        return None
    if action.startswith("主人"):
        return action
    return f"主人，{action}"


def decide_scan(conn: sqlite3.Connection, now: datetime) -> dict[str, Any]:
    q = quiet_hours()
    if time_in_span(now.time(), parse_hhmm(q[0]), parse_hhmm(q[1])):
        return {"action": "silent", "reason": "quiet_hours"}
    blocked = blocking_anchor(conn, now)
    if blocked:
        return {"action": "silent", "reason": f"anchor:{blocked['title']}"}
    if sent_today(conn, now):
        return {"action": "silent", "reason": "already_sent_today"}

    candidates: list[tuple[float, dict[str, Any]]] = []
    for row in conn.execute("SELECT * FROM intentions WHERE status = 'open' AND nudge_ok = 1"):
        item = row_dict(row)
        last_done = parse_stored_dt(item["last_completed_at"], now.tzinfo)
        if last_done and last_done.date() == now.date():
            continue
        counts = week_counts(conn, item["id"], now)
        completed = counts.get("completed", 0)
        if item["weekly_target"] and completed >= item["weekly_target"]:
            continue
        windows = preferred_windows(item["preferred_window"])
        slot = todays_slot(item["id"], now, windows)
        if slot is None:
            continue
        if not (slot <= now < slot + timedelta(minutes=CATCH_MINUTES)):
            continue
        if skip_this_day(item["id"], now):
            continue
        last = last_nudge(conn, item["id"])
        if last:
            last_at = parse_stored_dt(last["created_at"], now.tzinfo)
            wait = COOLDOWN_HOURS.get(last["outcome"], 16)
            if last_at and (now - last_at) < timedelta(hours=wait):
                continue
        message = compose_nudge(item)
        if not message:
            continue
        item["week_completed"] = completed
        item["message"] = message
        candidates.append(((now - slot).total_seconds(), item))

    if not candidates:
        return {"action": "silent", "reason": "no_eligible_intention"}
    candidates.sort(key=lambda pair: pair[0])
    chosen = candidates[0][1]
    return {
        "action": "nudge",
        "reason": "eligible",
        "intention_id": chosen["id"],
        "title": chosen["title"],
        "min_action": chosen["min_action"],
        "strength": chosen["strength"],
        "message": chosen["message"],
    }


def resolve_now(value: str | None) -> datetime:
    if not value:
        return local_now()
    stamp = parse_when(value)
    tz = load_tz()
    if stamp and "T" in stamp:
        return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=tz)
    if stamp:
        return datetime.strptime(stamp, "%Y-%m-%d").replace(tzinfo=tz)
    return local_now()


def cmd_scan(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    result = decide_scan(conn, resolve_now(args.at))
    if result["action"] == "silent":
        emit(args, result, f"silent  {result['reason']}")
    else:
        emit(args, result, f"nudge  {result['intention_id']}  {result['title']}\n{result['message']}")


def cmd_maybe_send(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    result = decide_scan(conn, resolve_now(args.at))
    if args.dry_run:
        human = result.get("message") or f"silent  {result['reason']}"
        emit(args, result, human)
        return
    if result["action"] != "nudge":
        return
    cmd = ["cc-connect", "send", "-m", result["message"]]
    project = args.project or os.environ.get("CC_PROJECT")
    session = args.session or os.environ.get("CC_SESSION_KEY")
    if project:
        cmd.extend(["-p", project])
    if session:
        cmd.extend(["-s", session])
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        err = exc.stderr if isinstance(exc, subprocess.CalledProcessError) else str(exc)
        raise SystemExit(f"发送失败: {err}") from exc
    stamp = now_iso()
    nudge_id = new_id("n")
    conn.execute(
        "INSERT INTO nudge_history(id, intention_id, reminder_id, outcome, note, created_at) "
        "VALUES (?, ?, NULL, 'sent', ?, ?)",
        (nudge_id, result["intention_id"], result["reason"], stamp),
    )
    conn.execute(
        "UPDATE intentions SET last_mentioned_at = ?, updated_at = ? WHERE id = ?",
        (stamp, stamp, result["intention_id"]),
    )
    conn.commit()


def cmd_today(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    day = parse_date(args.date)
    day_key = day.strftime("%Y-%m-%d")
    anchors = []
    for row in conn.execute("SELECT * FROM life_anchors WHERE active = 1 ORDER BY start_time IS NULL, start_time"):
        if weekday_matches(row["weekdays"], day):
            anchors.append(row_dict(row))
    events = []
    for row in conn.execute(
        "SELECT * FROM events WHERE status = 'active' ORDER BY start_at IS NULL, start_at"
    ):
        if spans_day(row["start_at"], row["end_at"], day_key):
            events.append(row_dict(row))
    linked = {e["reminder_id"] for e in events if e.get("reminder_id")}
    reminders = []
    for row in conn.execute(
        "SELECT * FROM reminders WHERE status NOT IN ('done', 'cancelled') "
        "ORDER BY remind_at IS NULL, remind_at"
    ):
        if row["id"] in linked:
            continue
        if date_of(row["remind_at"]) == day_key or date_of(row["due_at"]) == day_key:
            reminders.append(row_dict(row))
        elif row["repeat_rule"] and weekday_matches("daily", day):
            # repeating jobs without a dated remind_at still show on today
            if not row["remind_at"] and not row["due_at"]:
                reminders.append(row_dict(row))
    start = week_start(day).strftime("%Y-%m-%dT%H:%M:%S")
    intentions = []
    for row in conn.execute("SELECT * FROM intentions WHERE status = 'open' ORDER BY strength DESC, updated_at DESC"):
        item = row_dict(row)
        counts = conn.execute(
            "SELECT outcome, COUNT(*) AS n FROM nudge_history "
            "WHERE intention_id = ? AND created_at >= ? GROUP BY outcome",
            (row["id"], start),
        ).fetchall()
        by = {c["outcome"]: c["n"] for c in counts}
        item["week_completed"] = by.get("completed", 0)
        item["week_accepted"] = by.get("accepted", 0)
        item["week_sent"] = by.get("sent", 0)
        item["week_rejected"] = by.get("rejected", 0) + by.get("annoyed", 0) + by.get("skip", 0)
        intentions.append(item)

    payload = {
        "date": day_key,
        "weekday": WEEKDAY_ZH[day.weekday()],
        "lunar": lunar_day_lookup(day_key),
        "anchors": anchors,
        "events": events,
        "reminders": reminders,
        "intentions": intentions,
    }
    emit(args, payload, format_today(payload))


def format_today(payload: dict[str, Any]) -> str:
    title = f"# {payload['date']} {payload['weekday']}"
    lunar = payload.get("lunar") or {}
    if lunar.get("lunar"):
        extra = f"农历{lunar['lunar']}"
        if lunar.get("festivals"):
            extra += " " + "、".join(lunar["festivals"])
        elif lunar.get("jieqi"):
            extra += " " + lunar["jieqi"]
        title += f" · {extra}"
    lines = [title, "", "## 背景"]
    if payload["anchors"]:
        for a in payload["anchors"]:
            block = "挡住弱提醒" if a["blocks_nudge"] else "不挡"
            lines.append(
                f"- {a['start_time'] or '?'}–{a['end_time'] or '?'}  {a['title']}  ({a['kind']}, {block})"
            )
    else:
        lines.append("- （还没有日常锚点）")
    events = payload.get("events") or []
    if events:
        lines.extend(["", "## 日历"])
        days = [e for e in events if is_day_event(e)]
        sessions = [e for e in events if not is_day_event(e)]
        for e in days + sessions:
            loc = f"  @ {e['location']}" if e.get("location") else ""
            lines.append(f"- {format_event_span(e)}  {e['title']}  [{event_label(e)}]{loc}")
    reminders = payload["reminders"]
    if reminders:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for r in reminders:
            grouped.setdefault(r.get("kind") or "action", []).append(r)
        known = {key for key, _ in REMINDER_KIND_SECTIONS}
        for key, title in REMINDER_KIND_SECTIONS:
            items = grouped.get(key) or []
            if not items:
                continue
            lines.extend(["", f"## {title}"])
            for r in items:
                when = r["remind_at"] or "未定时"
                due = f"  DDL {r['due_at']}" if r["due_at"] else ""
                lines.append(f"- {when}  {r['title']}  [{r['status']}]{due}")
        extras = [r for r in reminders if (r.get("kind") or "action") not in known]
        if extras:
            lines.extend(["", "## 其他提醒"])
            for r in extras:
                when = r["remind_at"] or "未定时"
                lines.append(f"- {when}  {r['title']}  [{r.get('kind')}/{r['status']}]")
    else:
        lines.extend(["", "## 必做", "- （今天没有硬提醒）"])
    lines.extend(["", "## 意愿"])
    if payload["intentions"]:
        for i in payload["intentions"]:
            target = i["weekly_target"] or 0
            progress = f"本周 {i['week_completed']}/{target}" if target else f"本周完成 {i['week_completed']}"
            last_m = i["last_mentioned_at"][:10] if i["last_mentioned_at"] else "无"
            last_c = i["last_completed_at"][:10] if i["last_completed_at"] else "无"
            lines.append(
                f"- {i['title']}（{i['strength']}）：{progress}；上次提到 {last_m}；上次完成 {last_c}"
            )
    else:
        lines.append("- （还没有记下的意愿）")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Reminder 本地库")
    p.add_argument("--db", dest="db_path", default=None, help="SQLite 路径，默认 ~/.reminder/reminder.sqlite")
    p.add_argument("--json", action="store_true", help="输出 JSON")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="创建库（其他命令也会自动建表）")
    sub.add_parser("status", help="路径、版本、条数")

    t = sub.add_parser("today", help="今天的背景 / 日历 / 必做 / 截止 / 意愿")
    t.add_argument("--date", help="YYYY-MM-DD，默认今天")

    sc = sub.add_parser("scan", help="判断现在该不该轻轻叫一声")
    sc.add_argument("--at", help="假装当前时间，如 2026-08-26T20:00")
    ms = sub.add_parser("maybe-send", help="该叫才发；不该叫就完全静默")
    ms.add_argument("--at", help="假装当前时间")
    ms.add_argument("--dry-run", action="store_true")
    ms.add_argument("--project")
    ms.add_argument("--session")

    ar = sub.add_parser("add-reminder", help="记下一条硬提醒")
    ar.add_argument("--title", required=True)
    ar.add_argument("--details")
    ar.add_argument("--status", default="active")
    ar.add_argument("--kind", default="action", help="action 必做 / event 可选到点叫 / deadline 截止")
    ar.add_argument("--remind-at")
    ar.add_argument("--due-at")
    ar.add_argument("--repeat-rule")
    ar.add_argument("--job-id")
    ar.add_argument("--job-kind")
    ar.add_argument("--intention-id")
    ar.add_argument("--source-message")

    sr = sub.add_parser("set-reminder", help="改硬提醒")
    sr.add_argument("id")
    sr.add_argument("--title")
    sr.add_argument("--details")
    sr.add_argument("--status")
    sr.add_argument("--kind", help="action / event / deadline")
    sr.add_argument("--remind-at")
    sr.add_argument("--due-at")
    sr.add_argument("--repeat-rule")
    sr.add_argument("--job-id")
    sr.add_argument("--job-kind")
    sr.add_argument("--intention-id")
    sr.add_argument("--source-message")

    lr = sub.add_parser("list-reminders", help="列出硬提醒")
    lr.add_argument("--status", help="active/paused/done/cancelled/snoozed/all，默认不含 done/cancelled")
    lr.add_argument("--kind", help="action/event/deadline")

    ae = sub.add_parser("add-event", help="记下一条日历场次")
    ae.add_argument("--title", required=True)
    ae.add_argument("--start-at", required=True)
    ae.add_argument("--end-at")
    ae.add_argument("--location")
    ae.add_argument("--details")
    ae.add_argument("--all-day", action="store_true")
    ae.add_argument("--kind", help="session 场次 / holiday 节日 / break 假期 / marker 特殊日子")
    ae.add_argument("--source", default="user", help="user / cn / cityu-dg")
    ae.add_argument("--optional", type=int, choices=(0, 1))
    ae.add_argument("--going", action="store_true", help="主人说要去，记成必去而不是可选")
    ae.add_argument("--status", default="active")
    ae.add_argument("--job-id", help="到点轻喊的调度 id；有则同时写一条 kind=event 提醒")
    ae.add_argument("--job-kind")
    ae.add_argument("--reminder-id")
    ae.add_argument("--source-message")

    se = sub.add_parser("set-event", help="改日历场次")
    se.add_argument("id")
    se.add_argument("--title")
    se.add_argument("--start-at")
    se.add_argument("--end-at")
    se.add_argument("--location")
    se.add_argument("--details")
    se.add_argument("--all-day", type=int, choices=(0, 1))
    se.add_argument("--kind", help="session / holiday / break / marker")
    se.add_argument("--optional", type=int, choices=(0, 1))
    se.add_argument("--going", action="store_true")
    se.add_argument("--status", help="active/cancelled/done")
    se.add_argument("--reminder-id")
    se.add_argument("--source-message")

    le = sub.add_parser("list-events", help="列出日历场次")
    le.add_argument("--status", help="active/cancelled/done/all，默认 active")
    le.add_argument("--kind", help="session/holiday/break/marker")
    le.add_argument("--source", help="user/cn/cityu-dg")
    le.add_argument("--date", help="只看这一天")
    le.add_argument("--start", help="范围起点 YYYY-MM-DD")
    le.add_argument("--end", help="范围终点 YYYY-MM-DD")

    ai = sub.add_parser("add-intention", help="记下一条意愿")
    ai.add_argument("--title", required=True)
    ai.add_argument("--details")
    ai.add_argument("--strength", default="weak")
    ai.add_argument("--weekly-target", type=int, default=0)
    ai.add_argument("--min-action")
    ai.add_argument("--preferred-window")
    ai.add_argument("--no-nudge", action="store_true")
    ai.add_argument("--status", default="open")

    si = sub.add_parser("set-intention", help="改意愿")
    si.add_argument("id")
    si.add_argument("--title")
    si.add_argument("--details")
    si.add_argument("--strength")
    si.add_argument("--weekly-target", type=int)
    si.add_argument("--min-action")
    si.add_argument("--preferred-window")
    si.add_argument("--nudge-ok", type=int, choices=(0, 1))
    si.add_argument("--status")

    mi = sub.add_parser("mention-intention", help="用户又提到这条意愿")
    mi.add_argument("id")
    ci = sub.add_parser("complete-intention", help="记下一次完成")
    ci.add_argument("id")
    ci.add_argument("--note")
    li = sub.add_parser("list-intentions", help="列出意愿")
    li.add_argument("--status", help="open/paused/dropped/done/all，默认 open")

    aa = sub.add_parser("add-anchor", help="记下日常锚点")
    aa.add_argument("--title", required=True)
    aa.add_argument("--kind", required=True, help="meal/sleep/class/commute/busy/free")
    aa.add_argument("--weekdays", default="daily")
    aa.add_argument("--start-time", help="HH:MM")
    aa.add_argument("--end-time", help="HH:MM")
    aa.add_argument("--details")
    aa.add_argument("--blocks-nudge", type=int, choices=(0, 1))

    sa = sub.add_parser("set-anchor", help="改锚点")
    sa.add_argument("id")
    sa.add_argument("--title")
    sa.add_argument("--kind")
    sa.add_argument("--weekdays")
    sa.add_argument("--start-time")
    sa.add_argument("--end-time")
    sa.add_argument("--details")
    sa.add_argument("--blocks-nudge", type=int, choices=(0, 1))
    sa.add_argument("--active", type=int, choices=(0, 1))

    la = sub.add_parser("list-anchors")
    la.add_argument("--all", action="store_true")
    ra = sub.add_parser("remove-anchor")
    ra.add_argument("id")

    ln = sub.add_parser("log-nudge", help="记下一次弱提醒或反馈")
    ln.add_argument("--outcome", required=True, help="sent/accepted/completed/rejected/annoyed/skip")
    ln.add_argument("--intention-id")
    ln.add_argument("--reminder-id")
    ln.add_argument("--note")
    lns = sub.add_parser("list-nudges")
    lns.add_argument("--intention-id")
    lns.add_argument("--limit", type=int, default=20)

    sd = sub.add_parser("sync-days", help="从官方源刷新节日/假期")
    sd.add_argument("--source", default="cn", help="cn=法定假；lunar=农历；file=本地 JSON")
    sd.add_argument("--year", action="append", type=int, help="可重复；默认用仓库 data 里已有的年份")
    sd.add_argument("--refresh", action="store_true", help="联网拉取并写回 data/cn 或 data/lunar")
    sd.add_argument("--path", help="--source file 时的 JSON 路径")
    return p


COMMANDS = {
    "init": cmd_init,
    "status": cmd_status,
    "today": cmd_today,
    "scan": cmd_scan,
    "maybe-send": cmd_maybe_send,
    "add-reminder": cmd_add_reminder,
    "set-reminder": cmd_set_reminder,
    "list-reminders": cmd_list_reminders,
    "add-event": cmd_add_event,
    "set-event": cmd_set_event,
    "list-events": cmd_list_events,
    "sync-days": cmd_sync_days,
    "add-intention": cmd_add_intention,
    "set-intention": cmd_set_intention,
    "mention-intention": cmd_mention_intention,
    "complete-intention": cmd_complete_intention,
    "list-intentions": cmd_list_intentions,
    "add-anchor": cmd_add_anchor,
    "set-anchor": cmd_set_anchor,
    "list-anchors": cmd_list_anchors,
    "remove-anchor": cmd_remove_anchor,
    "log-nudge": cmd_log_nudge,
    "list-nudges": cmd_list_nudges,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.db_path = Path(args.db_path).expanduser() if args.db_path else default_db_path()
    conn = connect(args.db_path)
    try:
        COMMANDS[args.cmd](conn, args)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
