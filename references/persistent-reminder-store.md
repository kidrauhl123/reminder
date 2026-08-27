# 本地提醒库

运行时数据在 `~/.reminder/reminder.sqlite`（可用 `REMINDER_HOME` 改目录）。时区：`REMINDER_TZ`，否则 `~/.reminder/config.json` 的 `tz`，否则机器时区。深夜窗口看 `config.json` 的 `quiet_hours`。skill 目录只放说明书和脚本，不要往 skill 里写状态。

用 `scripts/reminder.py`，不要手写 SQL。其他命令会自动建表。`--json` 可改成 JSON。

```bash
python3 scripts/reminder.py status
python3 scripts/reminder.py today
python3 scripts/reminder.py today --date 2026-08-26
python3 scripts/reminder.py list-events --date 2026-08-26
```

日历场次（开始/结束/地点；默认可选。闹钟仍由宿主调度，用 `--job-id` 挂到点轻喊）：

```bash
python3 scripts/reminder.py add-event --title "破冰 综合楼三楼" --start-at "2026-08-26T14:00" --end-at "2026-08-26T16:00" --location "综合楼三楼" --job-id "<timer-id>"
python3 scripts/reminder.py list-events
python3 scripts/reminder.py list-events --start 2026-08-26 --end 2026-09-06
python3 scripts/reminder.py set-event e_xxxxxxxx --going
python3 scripts/reminder.py set-event e_xxxxxxxx --status cancelled
```

硬提醒（闹钟仍由宿主调度；这里只镜像）。`--kind`：`action` 必做、`event` 可选到点叫（旧路径，会自动补一条日历）、`deadline` 截止；默认 `action`。新的场次用 `add-event`，不要只写 reminder。

```bash
python3 scripts/reminder.py add-reminder --title "准备提交材料" --kind deadline --remind-at "2026-08-26T09:00" --due-at "2026-08-26T15:00" --job-id "<timer-id>" --job-kind timer
python3 scripts/reminder.py list-reminders
python3 scripts/reminder.py set-reminder r_xxxxxxxx --status done
```

意愿（说过想做、还没变成闹钟的背景）：

```bash
python3 scripts/reminder.py add-intention --title "健身" --strength weak --weekly-target 3 --preferred-window "19:00-21:00"
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

`today` 会先列当天日历，再按必做 / 截止列出其余硬提醒，并带当天锚点和未关闭意愿。不要把「本周 0/3」说成责备。问「明天有啥」时用 `--date`。

轻扫描（该叫才叫，一天最多一声，时刻每天不同）：

```bash
python3 scripts/reminder.py scan
python3 scripts/reminder.py maybe-send --dry-run
python3 scripts/reminder.py maybe-send
```

`maybe-send` 不该叫时不要打印任何内容，以免宿主把 stdout 发给用户。不要把扫描时刻或频率告诉用户。用户说「别再主动叫我」时停掉这个任务。
