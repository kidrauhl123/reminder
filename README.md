# Reminder

一个面向 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 的中文个人助手 Skill：把随口说出的待办、拖延和混乱安排，变成低压力的下一步和真正会触发的提醒。

当前版本用于验证单用户体验，不包含账号系统、GUI、App 或自建调度服务。

## 能做什么

- “明天下午三点提醒我交材料”——创建单次提醒
- “周五下午三点前要交报告”——优先提前提醒你开始做，而不是只在 DDL 时催交付
- “每周日晚上提醒我收拾房间”——创建重复提醒
- “十分钟后再叫我”——推迟本次行动，不破坏原有重复规则
- “取消健身提醒”——查找并管理已有任务
- “我今天很乱，不知道先做什么”——只留下一个必须做和两个可选项
- 晨间启动和晚间回顾——仅在用户主动要求时开启

Skill 使用 Hermes 原生 `cronjob` 工具，没有脚本、额外依赖或 API Key。

## 安装

推荐克隆完整目录安装，确保 `references/cron-recipes.md` 等支持文件一起可用：

```bash
git clone https://github.com/kidrauhl123/reminder.git ~/.hermes/skills/reminder
```

如果只想临时预览主文件，也可以安装 raw `SKILL.md`；但这种方式可能不会带上 `references/` 支持文件：

```bash
hermes skills install https://raw.githubusercontent.com/kidrauhl123/reminder/main/SKILL.md
```

建议确认 `~/.hermes/config.yaml` 中的时区符合你的实际使用场景，例如：

```yaml
timezone: "Asia/Shanghai"
```

确保 Gateway 持续运行，否则定时任务不会触发：

```bash
hermes gateway install
# 或在前台运行
hermes gateway
```

## 使用

为第一轮验证，推荐显式调用 Skill：

```text
/reminder 明天下午三点提醒我交材料
/reminder 我最近很乱，帮我只安排今天最重要的事
/reminder 每晚十点半问我今天做成了什么
```

Skill 创建的对话型提醒默认投递回创建任务的原会话。收到提醒后，可以直接回复“完成”“推迟 10 分钟”或“取消”。

## 设计取向

- 不要求用户先写好计划
- 能执行时少问问题
- 区分 DDL 和开始行动时间，避免只在截止时刻提醒
- 不用羞耻感驱动行动
- 不把所有事情都排进日程
- 不擅自创建长期习惯
- 每条定时提示词都自包含，不依赖旧聊天记录

详细行为在 [SKILL.md](SKILL.md)，Hermes Cron 调用方式在 [references/cron-recipes.md](references/cron-recipes.md)。

## 当前限制

- 依赖 Hermes Gateway 常驻，调度精度约为一分钟。
- 定时会话无法读取创建任务时的聊天上下文，所以提醒内容会被完整写入任务提示词。
- 这是体验原型，尚未验证长期记忆、跨渠道同步和复杂日程冲突。

## License

[MIT](LICENSE)
