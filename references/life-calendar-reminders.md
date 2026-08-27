# Life-calendar reminder backend notes

表已经在 `~/.reminder/reminder.sqlite`。当天这一页用 `scripts/reminder.py today`。轻扫描用 `scan` / `maybe-send`。

## Model

Durable state belongs in `~/.reminder/`, not in skill files and not as many flat scheduled jobs.

Tables:

- `events`: local calendar. Start/end/location; `optional=1` means go-or-not. May point at a `reminder_id` for the start-time ping.
- `reminders`: hard reminders mirrored from host scheduler jobs. `kind` is `action` (must-do), `event` (legacy ping; auto-copied into `events`), or `deadline` (due time; remind to start earlier).
- `life_anchors`: background blocks such as meals, sleep, class, commute, busy periods, and good activity windows. These usually do **not** send messages by themselves.
- `intentions`: long-running fuzzy goals such as fitness or study, with strength (`weak`/`medium`/`strong`), weekly target, preferred window, and proactive-nudge permission.
- `nudge_history`: every weak prompt and user response/outcome (`sent`, `accepted`, `completed`, `rejected`, `annoyed`, `skip`, etc.).

## Scanner pattern

`scripts/reminder.py scan` 决定发、推迟还是沉默；`maybe-send` 只在该叫时发消息。一天最多一声，每天的时刻不同，有时整天不叫。不要把时刻告诉用户。

Decision rules:

1. Do not nudge inside blocking life anchors (`meal`, `sleep`, `class`, `commute`, `busy`).
2. Only consider intentions inside their preferred time window.
3. Respect weekly targets; if enough accepted/completed nudges happened this week, stay silent.
4. Cool down after any recent sent/positive nudge, and cool down longer after rejected/annoyed/skip.

## Schedule format

创建时用宿主真正接受的格式（ISO 时间戳或 cron 表达式），不要把列表里的展示文案原样送回去。

## User-facing behavior

When the user dumps a schedule/policy notice, persist each timed item with `add-event` and ping at start time. Do not wait for “提醒我”. Overlapping optional sessions all get kept. Only `set-event --going` if the user says they will go. `deadline` items still get a start-prep ping; calendar events do not. Confirm with times, not internal job IDs. Behavior lives in `SKILL.md` §事项类型.
