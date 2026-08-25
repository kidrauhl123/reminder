# Reminder

一个中文个人助手 Skill：把随口说出的待办、拖延和混乱安排，变成低压力的下一步和真正会触发的提醒。

它是给 Agent 读的行为说明书（`SKILL.md` 约定），不是独立 App，也不绑定单一宿主。调度由宿主提供：有 [cc-connect](https://github.com/chenhg5/cc-connect) 时用它的 timer/cron；有 Hermes `cronjob` 时用 Hermes。没有调度后端时，这个 skill 仍能做规划和文案，只是没法到点叫醒。

当前版本用于验证单用户体验，不包含账号系统、GUI 或自建调度服务。

## 能做什么

- “明天下午三点提醒我交材料”——创建单次提醒
- “周五下午三点前要交报告”——优先提前提醒你开始做，而不是只在 DDL 时催交付
- “每周日晚上提醒我收拾房间”——创建重复提醒
- “十分钟后再叫我”——推迟本次行动，不破坏原有重复规则
- “取消健身提醒”——查找并管理已有任务
- “我今天很乱，不知道先做什么”——只留下一个必须做和两个可选项
- “提醒我学习/推进项目/变规律”——先转成一个 10 分钟内能开始的具体动作
- 晨间启动和晚间回顾——仅在用户主动要求时开启

没有脚本、额外依赖或 API Key。

## 安装

克隆完整目录，确保 `references/` 一起可用：

```bash
# Grok
git clone https://github.com/kidrauhl123/reminder.git ~/.grok/skills/reminder

# Claude Code
git clone https://github.com/kidrauhl123/reminder.git ~/.claude/skills/reminder

# Codex
git clone https://github.com/kidrauhl123/reminder.git ~/.codex/skills/reminder

# Hermes
git clone https://github.com/kidrauhl123/reminder.git ~/.hermes/skills/reminder
```

只装 raw `SKILL.md` 可能丢 `references/`，不推荐。

定时要响，对应宿主得常驻：cc-connect 用 `cc-connect daemon`；Hermes 用 `hermes gateway`。时区跟机器本地时间（cc-connect）或 `~/.hermes/config.yaml` 的 `timezone`（Hermes）。

## 使用

用户直接用自然语言说即可：

```text
明天下午三点提醒我交材料
我最近很乱，帮我只安排今天最重要的事
每晚十点半问我今天做成了什么
```

对话型提醒默认打回创建时的会话。收到提醒后，可以直接回复“完成”“推迟 10 分钟”或“取消”。

## 设计取向

- 不要求用户先写好计划
- 能执行时少问问题
- 区分 DDL 和开始行动时间，避免只在截止时刻提醒
- 把模糊目标转成低阻力下一步，不发送空泛口号
- 不用羞耻感驱动行动
- 不把所有事情都排进日程
- 不擅自创建长期习惯
- 每条定时提示词都自包含，不依赖旧聊天记录

详细行为在 [SKILL.md](SKILL.md)。cc-connect 配方在 [references/cc-connect-recipes.md](references/cc-connect-recipes.md)，Hermes 配方在 [references/cron-recipes.md](references/cron-recipes.md)。

## 当前限制

- 调度精度大约一分钟；cc-connect daemon 或 Hermes Gateway 必须常驻。
- 到点后的会话不一定看得到创建时的聊天，所以提醒内容要写进任务提示词。
- cc-connect 的循环任务是五段 cron，没有“从现在起每 2 小时”这种 interval。
- 这是体验原型，尚未验证长期记忆、跨渠道同步和复杂日程冲突。

## License

[MIT](LICENSE)
