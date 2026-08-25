#!/usr/bin/env python3
"""Local reminder store. Schema lives here; agents must not write SQL."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import uuid
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

SCHEMA_VERSION = "1"

REMINDER_STATUSES = ("active", "paused", "done", "cancelled", "snoozed")
INTENTION_STATUSES = ("open", "paused", "dropped", "done")
STRENGTHS = ("weak", "medium", "strong")
ANCHOR_KINDS = ("meal", "sleep", "class", "commute", "busy", "free")
NUDGE_OUTCOMES = ("sent", "accepted", "completed", "rejected", "annoyed", "skip")
JOB_KINDS = ("timer", "cron", "other")
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
WEEKDAY_ZH = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

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

CREATE INDEX IF NOT EXISTS idx_reminders_status ON reminders(status);
CREATE INDEX IF NOT EXISTS idx_reminders_remind_at ON reminders(remind_at);
CREATE INDEX IF NOT EXISTS idx_intentions_status ON intentions(status);
CREATE INDEX IF NOT EXISTS idx_anchors_active ON life_anchors(active);
CREATE INDEX IF NOT EXISTS idx_nudge_intention ON nudge_history(intention_id, created_at);
"""


def data_home() -> Path:
    return Path(os.environ.get("REMINDER_HOME", Path.home() / ".reminder"))


def load_tz():
    name = os.environ.get("REMINDER_TZ")
    if not name:
        cfg = data_home() / "config.json"
        if cfg.is_file():
            try:
                name = json.loads(cfg.read_text()).get("tz")
            except (OSError, json.JSONDecodeError):
                name = None
    if not name:
        name = os.environ.get("TZ")
    if name:
        return ZoneInfo(name)
    return datetime.now().astimezone().tzinfo


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


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_SQL)
    stamp = now_iso()
    conn.execute(
        "INSERT INTO schema_meta(key, value, updated_at) VALUES(?, ?, ?) "
        "ON CONFLICT(key) DO NOTHING",
        ("version", SCHEMA_VERSION, stamp),
    )
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
    job_kind = require_enum("job-kind", args.job_kind, JOB_KINDS) if args.job_kind else None
    conn.execute(
        """INSERT INTO reminders(
            id, title, details, status, remind_at, due_at, repeat_rule,
            job_id, job_kind, intention_id, source_message, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            item_id,
            args.title,
            args.details,
            status,
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
    row = row_dict(get_one(conn, "reminders", item_id))
    emit(args, row, f"reminder {item_id}  {args.title}")


def cmd_set_reminder(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    get_one(conn, "reminders", args.id)
    fields: dict[str, Any] = {}
    if args.title is not None:
        fields["title"] = args.title
    if args.details is not None:
        fields["details"] = args.details
    if args.status is not None:
        fields["status"] = require_enum("status", args.status, REMINDER_STATUSES)
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
    emit(args, row, f"reminder {args.id}  {row['title']}  [{row['status']}]")


def cmd_list_reminders(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    if args.status == "all":
        rows = conn.execute("SELECT * FROM reminders ORDER BY remind_at IS NULL, remind_at, created_at").fetchall()
    elif args.status:
        require_enum("status", args.status, REMINDER_STATUSES)
        rows = conn.execute(
            "SELECT * FROM reminders WHERE status = ? ORDER BY remind_at IS NULL, remind_at, created_at",
            (args.status,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM reminders WHERE status NOT IN ('done', 'cancelled') "
            "ORDER BY remind_at IS NULL, remind_at, created_at"
        ).fetchall()
    items = [row_dict(r) for r in rows]
    lines = [
        f"{r['id']}  [{r['status']}]  {r['title']}"
        + (f"  {r['remind_at']}" if r["remind_at"] else "")
        + (f"  due {r['due_at']}" if r["due_at"] else "")
        for r in items
    ]
    emit(args, items, "\n".join(lines) if lines else "(没有提醒)")


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
        + (f"  最低:{r['min_action']}" if r["min_action"] else "")
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
QUIET_HOURS = ("23:30", "07:30")
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


def compose_nudge(intention: dict[str, Any]) -> str:
    title = intention["title"]
    mini = intention["min_action"]
    if mini:
        return f"主人，现在适合推进一下「{title}」吗？最低标准：{mini}。不想做也没关系。"
    return f"主人，突然想起你说过想「{title}」。有空动一下就行，不想做也没关系。"


def decide_scan(conn: sqlite3.Connection, now: datetime) -> dict[str, Any]:
    if time_in_span(now.time(), parse_hhmm(QUIET_HOURS[0]), parse_hhmm(QUIET_HOURS[1])):
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
        if not in_windows(now.time(), windows):
            continue
        last = last_nudge(conn, item["id"])
        if last:
            last_at = parse_stored_dt(last["created_at"], now.tzinfo)
            wait = COOLDOWN_HOURS.get(last["outcome"], 16)
            if last_at and (now - last_at) < timedelta(hours=wait):
                continue
            age = (now - last_at).total_seconds() if last_at else 10**9
        else:
            mentioned = parse_stored_dt(item["last_mentioned_at"], now.tzinfo)
            age = (now - mentioned).total_seconds() if mentioned else 10**9
        item["week_completed"] = completed
        item["message"] = compose_nudge(item)
        candidates.append((age, item))

    if not candidates:
        return {"action": "silent", "reason": "no_eligible_intention"}
    candidates.sort(key=lambda pair: pair[0], reverse=True)
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
    reminders = []
    for row in conn.execute(
        "SELECT * FROM reminders WHERE status NOT IN ('done', 'cancelled') "
        "ORDER BY remind_at IS NULL, remind_at"
    ):
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
        "anchors": anchors,
        "reminders": reminders,
        "intentions": intentions,
    }
    emit(args, payload, format_today(payload))


def format_today(payload: dict[str, Any]) -> str:
    lines = [f"# {payload['date']} {payload['weekday']}", "", "## 背景"]
    if payload["anchors"]:
        for a in payload["anchors"]:
            block = "挡住弱提醒" if a["blocks_nudge"] else "不挡"
            lines.append(
                f"- {a['start_time'] or '?'}–{a['end_time'] or '?'}  {a['title']}  ({a['kind']}, {block})"
            )
    else:
        lines.append("- （还没有日常锚点）")
    lines.extend(["", "## 硬提醒"])
    if payload["reminders"]:
        for r in payload["reminders"]:
            when = r["remind_at"] or "未定时"
            due = f"  DDL {r['due_at']}" if r["due_at"] else ""
            lines.append(f"- {when}  {r['title']}  [{r['status']}]{due}")
    else:
        lines.append("- （今天没有硬提醒）")
    lines.extend(["", "## 意愿"])
    if payload["intentions"]:
        for i in payload["intentions"]:
            target = i["weekly_target"] or 0
            progress = f"本周 {i['week_completed']}/{target}" if target else f"本周完成 {i['week_completed']}"
            last_m = i["last_mentioned_at"][:10] if i["last_mentioned_at"] else "无"
            last_c = i["last_completed_at"][:10] if i["last_completed_at"] else "无"
            mini = i["min_action"] or "（未设最低动作）"
            lines.append(
                f"- {i['title']}（{i['strength']}）：最低 {mini}；{progress}；上次提到 {last_m}；上次完成 {last_c}"
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

    t = sub.add_parser("today", help="今天的背景 / 硬提醒 / 意愿")
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
    sr.add_argument("--remind-at")
    sr.add_argument("--due-at")
    sr.add_argument("--repeat-rule")
    sr.add_argument("--job-id")
    sr.add_argument("--job-kind")
    sr.add_argument("--intention-id")
    sr.add_argument("--source-message")

    lr = sub.add_parser("list-reminders", help="列出硬提醒")
    lr.add_argument("--status", help="active/paused/done/cancelled/snoozed/all，默认不含 done/cancelled")

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
