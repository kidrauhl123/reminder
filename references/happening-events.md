# Happening → reminder 事件源

Happening 是事实层（正在发生什么）。reminder 是个人层（要不要叫主人、几点叫）。不要把 Happening 的世界动态整库写进日历。

## 个人过滤：国内适合看的足球

每周跑一次脚本，不走模型。

- 每天同一套开球窗口：东八区 **15:00–00:00**（0 点整算进，0:30 不算）
- 周一东八区 14:00 推**本周一条**：足球关注的队 + F1 正赛
- 五大联赛 / 欧战 / 世预赛 / 亚冠里，只盯这些队：英超 Big 6（阿森纳、切尔西、利物浦、曼城、曼联、热刺），西甲三强（皇马、巴萨、马竞），德甲拜仁/多特，法甲大巴黎，意甲国米/AC米兰/尤文。不收录中超。
- 至少一方在名单里才进周报和开球提醒；**两队都在名单里 = 强强对决**，文案要写出来
- F1 只收 **正赛**（练习 / 排位 / 冲刺不进周报、不喊）
- 队名用国内常用中文；同一开球时刻只喊一声
- 到点轻喊提前约 **5 分钟**（开球时刻仍写在日历里；只有球赛和 F1 正赛，校园讲座仍到点喊）

```bash
python3 scripts/golden_football.py                 # 打印本周场次
python3 scripts/golden_football.py --notify        # 推周报并挂到点提醒
python3 scripts/golden_football.py --notify --dry-run
```

调度：`cc-connect cron add --cron "0 6 * * 1" --exec "python3 scripts/golden_football.py --notify"`（主机 UTC，对应东八区周一 14:00）。不要用 `--prompt`。
