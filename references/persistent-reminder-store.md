# Persistent reminder store notes

这是可选的后端设想，不是本 skill 的运行时实现。调度状态由宿主自己保存；skill 目录只放说明书。

## 原则

- skill 目录是包装/文档：`SKILL.md`、`references/`、`templates/`、`scripts/`。
- 可变状态不要写进 skill 文件。
- cc-connect 的一次性任务在 `~/.cc-connect/timers/`，循环任务在 `~/.cc-connect/crons/`。
- Hermes 若自建提醒库，默认路径是 `~/.hermes/data/reminders/reminders.sqlite`，并按当前 profile/cron store 推导，不要硬编码 `/root/.hermes`。

## Hermes 侧曾用过的表形

若在 Hermes 里做状态镜像，最小有用的表：

- `schema_meta(key, value, updated_at)` — schema version.
- `reminders` — 一条提醒对应一个 cron job。重要列：`id`、`cron_job_id`、`title`、`details`、`status`、`remind_at`、`due_at`、`repeat_rule`、`platform`、`chat_id`、`thread_id`、`user_id`、`source_message`、时间戳。
- `reminder_events` — 只追加的生命周期：`created`、`updated`、`paused`、`resumed`、`fired`、`failed`、`completed`、`cancelled`、`snoozed`。

只镜像明确加载 reminder skill 的任务，避免把无关自动化写进提醒库。宿主调度失败时，提醒库错误必须是 best-effort、非致命。
