# 本地提醒库

运行时数据在 `~/.reminder/reminder.sqlite`（可用 `REMINDER_HOME` 改目录）。时区：`REMINDER_TZ`，否则 `~/.reminder/config.json` 的 `tz`，否则机器时区。skill 目录只放说明书和脚本，不要往 skill 里写状态。

用 `scripts/reminder.py`，不要手写 SQL。其他命令会自动建表。`--json` 可改成 JSON。

```bash
python3 scripts/reminder.py status
python3 scripts/reminder.py today
python3 scripts/reminder.py today --date 2026-08-26
```

硬提醒（闹钟仍由宿主调度；这里只镜像）：

```bash
python3 scripts/reminder.py add-reminder --title "准备提交材料" --remind-at "2026-08-26T09:00" --due-at "2026-08-26T15:00" --job-id "<timer-id>" --job-kind timer
python3 scripts/reminder.py list-reminders
python3 scripts/reminder.py set-reminder r_xxxxxxxx --status done
```

意愿（说过想做、还没变成闹钟的背景）：

```bash
python3 scripts/reminder.py add-intention --title "健身" --strength weak --min-action "换鞋出门 10 分钟" --weekly-target 3 --preferred-window "19:00-21:00"
python3 scripts/reminder.py mention-intention i_xxxxxxxx
python3 scripts/reminder.py complete-intention i_xxxxxxxx
python3 scripts/reminder.py list-intentions
```

日常锚点（吃饭/睡觉/上课等，默认自己不响，只挡住乱叫）：

```bash
python3 scripts/reminder.py add-anchor --title "午睡" --kind sleep --weekdays daily --start-time 13:00 --end-time 14:00
python3 scripts/reminder.py list-anchors
```

`kind`：`meal` / `sleep` / `class` / `commute` / `busy` / `free`。`weekdays`：`daily`、`weekdays`、`weekends`，或 `mon,tue`。

反馈（只记事实，不记「又没做」这种判断）：

```bash
python3 scripts/reminder.py log-nudge --intention-id i_xxxxxxxx --outcome sent
python3 scripts/reminder.py log-nudge --intention-id i_xxxxxxxx --outcome skip
```

`outcome`：`sent` / `accepted` / `completed` / `rejected` / `annoyed` / `skip`。

`today` 会列出当天锚点、当天硬提醒、未关闭意愿，以及本周完成次数。不要把「本周 0/3」说成责备。
