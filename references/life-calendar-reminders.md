# Life-calendar reminder backend notes

这是后端设想，本 skill 不实现 scanner。当用户想要比扁平闹钟更聪明的提醒（日常锚点、模糊意愿、弱提醒、按反馈调整）时再读。

## Model

Durable state belongs in the host store, not in skill files and not as many flat scheduled jobs.

Recommended tables/objects:

- `reminders`: hard reminders mirrored from reminder-skill jobs.
- `reminder_events`: lifecycle/history for hard reminders.
- `life_anchors`: background blocks such as meals, sleep, class, commute, busy periods, and good activity windows. These usually do **not** send messages by themselves.
- `intentions`: long-running fuzzy goals such as fitness or study, with strength (`weak`/`medium`/`strong`), weekly target, minimum action, preferred window, and proactive-nudge permission.
- `nudge_history`: every weak prompt and user response/outcome (`sent`, `accepted`, `completed`, `rejected`, `annoyed`, `skip`, etc.).

## Scanner pattern

Create a small recurring scanner cron job. The scanner reads the DB and decides one of: send a gentle prompt, defer, or stay silent.

Decision rules used in the first implementation:

1. Do not nudge inside blocking life anchors (`meal`, `sleep`, `class`, `commute`, `busy`).
2. Only consider intentions inside their preferred time window.
3. Respect weekly targets; if enough accepted/completed nudges happened this week, stay silent.
4. Cool down after any recent sent/positive nudge, and cool down longer after rejected/annoyed/skip.
5. For weak intentions, phrase as readiness check, not command: “现在适合推进 X 吗？最低标准：Y。不想做也没关系。”

## Cron tool pitfall

The `cronjob` tool may reject natural display strings like `once at 2026-08-24 13:15` even though list output displays schedules that way. For creation, pass ISO timestamps such as `2026-08-24T13:15:00+08:00`.

## User-facing behavior

When the user dumps a schedule/policy notice, convert it into:

- current next action;
- start-prep reminders before opening windows/deadlines;
- deadline review reminders near the end;
- concise confirmation with times, not internal job IDs.
