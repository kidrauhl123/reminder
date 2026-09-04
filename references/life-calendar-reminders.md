# Life-calendar reminder backend notes

表已经在 `~/.reminder/reminder.sqlite`。当天这一页用 `scripts/reminder.py today`。

## Model

Durable state belongs in `~/.reminder/`, not in skill files and not as many flat scheduled jobs.

Tables:

- `events`: local calendar. `kind` is `session` (timed, optional, may ping), `holiday`, `break`, or `marker` (all-day days; no ping). `source` is `user`, `cn` (`data/cn/`), `lunar` (`data/lunar/`), or a local school file. National holidays and lunar festivals ship in the git repo; school/personal days stay on the machine.
- `reminders`: hard reminders mirrored from host scheduler jobs. `kind` is `action` (must-do), `event` (legacy ping; auto-copied into `events`), or `deadline` (due time; remind to start earlier).
- `life_anchors`: background blocks such as meals, sleep, class, commute, busy periods, and good activity windows. These usually do **not** send messages by themselves.
- `intentions`: long-running fuzzy goals such as fitness or study, with strength (`weak`/`medium`/`strong`), weekly target, preferred window, and whether unsolicited pings are allowed (`nudge_ok`). Ping those with an explicit scheduled message, not a background scanner.
- `nudge_history`: user response/outcome on an intention (`sent`, `accepted`, `completed`, `rejected`, `annoyed`, `skip`, etc.).

## Schedule format

创建时用宿主真正接受的格式（ISO 时间戳或 cron 表达式），不要把列表里的展示文案原样送回去。

## User-facing behavior

When the user dumps a schedule/policy notice, persist each timed item with `add-event` and ping at start time. Do not wait for “提醒我”. Overlapping optional sessions all get kept. Only `set-event --going` if the user says they will go. `deadline` items still get a start-prep ping; calendar events do not. Confirm with times, not internal job IDs. Behavior lives in `SKILL.md` §事项类型.
