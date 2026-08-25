# Persistent reminder store notes

这是可选的后端设想，不是本 skill 的运行时实现。调度状态由宿主自己保存；skill 目录只放说明书。

## 原则

- skill 目录是包装/文档：`SKILL.md`、`references/`、`templates/`、`scripts/`。
- 可变状态不要写进 skill 文件。
- 一次性与循环任务的记录放在宿主自己的数据目录，例如 cc-connect 用 `~/.cc-connect/timers/` 和 `~/.cc-connect/crons/`。

## 若宿主要做状态镜像

最小有用的表：

- `schema_meta(key, value, updated_at)` — schema version.
- `reminders` — 一条提醒对应一个调度任务。重要列：`id`、`job_id`、`title`、`details`、`status`、`remind_at`、`due_at`、`repeat_rule`、投递目标、`source_message`、时间戳。
- `reminder_events` — 只追加的生命周期：`created`、`updated`、`paused`、`resumed`、`fired`、`failed`、`completed`、`cancelled`、`snoozed`。

只镜像明确按 reminder skill 创建的任务，避免把无关自动化写进提醒库。宿主调度失败时，提醒库错误必须是 best-effort、非致命。
