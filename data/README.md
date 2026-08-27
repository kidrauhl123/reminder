# 通用日历数据

仓库只预填**所有人都会用到**的日子：中国法定节假日和调休补班。

- [`cn/2026.json`](cn/2026.json)：国务院 2026 年放假安排。原始抓取来自 [holiday-cn](https://github.com/NateScarlet/holiday-cn)，`papers` 里是官网链接。
- 学校校历、个人生日**不要**放进这个目录。那些只存在使用者本机的 `~/.reminder/`。

脚本每次启动会把这里的日子写入本机 sqlite。国务院公布新一年时：

```bash
python3 scripts/reminder.py sync-days --source cn --refresh --year 2027
git add data/cn/2027.json
```
