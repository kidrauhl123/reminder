# Reminder

以**提醒**为核心的个人智能助手。Clone 进 Agent 的 skills 目录就能用：替用户记住生活，该叫的时候叫，不该催的时候闭嘴。

不是待办清单，也不是日历 App。用户不必先会计划。助手负责听懂、分类、记住、到点叫醒；用户只负责要不要做。

任何认 `SKILL.md` 的 Agent 都可以当壳。到点消息打在当前对话里（Telegram / 飞书 / 终端都行）。

## 开箱即有

对话这一条路径不需要邮箱、不需要第三方日历：

- 随口说「明天下午三点提醒我交材料」
- 把群通知、课表丢进来，有钟点的场次自动记、到点轻喊
- 问今天 / 明天有什么
- 说出想早睡、想健身：收成一个具体动作并挂到点消息
- 想一起聊拖延、条理、钱、关系：走 wiki，默认不布置作业

行为细则在 [SKILL.md](SKILL.md)。密钥、邮箱密码、会话 token **不要**放进本仓库；每个人的留在自己机器上。

## 可选：更多入口

同一套脑子，可以再接别的输入。合同在 [references/ingest.md](references/ingest.md)：

- **邮件**：自己机器上的监听（IMAP / 转发 / MCP 均可）。建议先脚本发一句标题、不走模型，再把正文交给 Agent 按本 skill 处理。
- **赛程**：仓库里有不走模型的周报脚本；关注名单按自己的改，见 [happening-events.md](references/happening-events.md)。

没接这些，助手仍然完整。接了也不要另搞一套分类。

## 仓库里有什么

| 给谁 | 路径 | 干什么 |
| --- | --- | --- |
| Agent | `SKILL.md` | 怎么判断、怎么叫。运行时只认这一份。 |
| Agent | `references/` | 输入合同、本地库、调度配方、成长与 wiki |
| 本机 | `scripts/reminder.py` | sqlite CLI：日历、硬提醒镜像、意愿、作息锚点 |
| 所有人 | `data/` | 法定假日、农历。校历和生日只存在使用者自己的 `~/.reminder/` |

```
SKILL.md
README.md
references/
scripts/
data/
```

运行时数据在 `~/.reminder/`，不进 git。

## 安装

```bash
git clone https://github.com/kidrauhl123/reminder.git ~/.grok/skills/reminder
# 或 ~/.claude/skills/reminder 、 ~/.codex/skills/reminder ，以及其他认 SKILL.md 的目录
```

只拷 raw `SKILL.md` 会丢参考、脚本和节日数据。定时要响，宿主得有可用的调度（有 `cc-connect` 就用它，否则用本机 cron；配方在 `references/`）。没有调度时仍能整理和写文案，只是没法到点叫醒。时间按使用者本地时区。

```bash
python3 scripts/reminder.py today
```

## 设计取向

- 用户不必先成为擅长计划的人
- 能执行时少问；一次最多一个关键问题
- 区分「开始做」和「该交了」
- 对用户只报事实，不说教、不羞辱
- 不把所有事情排进日程
- 每条定时提示词自包含，不依赖旧聊天记录

无账号系统、无 GUI。日历是每位使用者自己的 sqlite，不接 Google / Apple 日历。这是刻意保持可 clone、可单机跑，不是功能缺失。

## License

[MIT](LICENSE)
