# 通用日历数据

仓库只预填**所有人都会用到**的日子。学校校历、个人生日不要放进来，那些只在使用者本机 `~/.reminder/`。

- [`cn/`](cn/)：国务院法定节假日和调休补班（[holiday-cn](https://github.com/NateScarlet/holiday-cn)，`papers` 是官网链接）。
- [`lunar/`](lunar/)：公历对照农历、二十四节气、传统节日。原始表来自[香港天文台](https://www.hko.gov.hk/tc/gts/time/calendar/text/files/T2026c.txt)。

脚本启动时会把法定假和农历节日写入本机 sqlite。更新：

```bash
python3 scripts/reminder.py sync-days --source cn --refresh --year 2027
python3 scripts/reminder.py sync-days --source lunar --refresh --year 2027
git add data/cn/2027.json data/lunar/2027.json
```

