#!/usr/bin/env python3
"""
远近通记 - 每日提醒发送脚本
由 GitHub Actions 每天北京时间 08:00 自动执行
通过 Server酱 推送到微信
"""

import json, os, sys, requests
from datetime import datetime, timedelta, date

# ============================================================
# 配置
# ============================================================
SERVER_KEY = "SCT386301TOhwCVMnccBFYpIVPm6lN9RFs"
TASKS_FILE = os.path.join(os.path.dirname(__file__), "..", "tasks_sync.json")

# ============================================================
# 工具函数
# ============================================================
def parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date()

def days_between(d1, d2):
    return (d2 - d1).days

def get_repeat_interval(task):
    n = int(task.get("repeatInterval", 1) or 1)
    return n if n > 0 else 1

def task_covers_date(task, day):
    start = parse_date(task["startDate"])
    end   = parse_date(task["endDate"])
    if task.get("continuous") is True:
        interval = get_repeat_interval(task)
        if day < start or day > end:
            return False
        return days_between(start, day) % interval == 0
    return day == end

def get_todays_tasks(tasks, today):
    return [t for t in tasks if t.get("status") == "active" and task_covers_date(t, today)]

def find_next_occurrence(task, from_date):
    start = parse_date(task["startDate"])
    end   = parse_date(task["endDate"])
    if from_date > end:
        return None
    if task.get("continuous") is True:
        interval = get_repeat_interval(task)
        offset = max(0, days_between(start, from_date))
        k = (offset + interval - 1) // interval
        day = k * interval
        if day > days_between(start, end):
            return None
        return start + timedelta(days=day)
    if from_date <= end:
        return end
    return None

def categorize_task(task):
    span = days_between(parse_date(task["startDate"]), parse_date(task["endDate"])) + 1
    if span >= 365: return "year"
    if span >= 30:  return "month"
    if span >= 7:   return "week"
    return "day"

def get_preview_tasks(tasks, today):
    preview = []
    for t in tasks:
        if t.get("status") != "active":
            continue
        cat = categorize_task(t)
        if cat not in ("year", "month"):
            continue
        next_d = find_next_occurrence(t, today)
        if next_d is None:
            continue
        dn = days_between(today, next_d)
        if 0 < dn <= 3:
            preview.append({"title": t.get("title",""), "date": next_d, "daysUntil": dn})
    return preview

# ============================================================
# 通过 Server酱 发送微信消息
# ============================================================
def send_server_chan(title, desp):
    url = f"https://sctapi.ftqq.com/{SERVER_KEY}.send"
    resp = requests.post(url, data={"title": title, "desp": desp}, timeout=15)
    result = resp.json()
    print(f"Server酱返回: {result}")
    return result.get("code") == 0

# ============================================================
# 主流程
# ============================================================
def main():
    today = date.today()

    # 加载任务
    tasks = []
    if os.path.exists(TASKS_FILE):
        with open(TASKS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            tasks = data.get("tasks", [])
    print(f"加载 {len(tasks)} 条任务")

    today_tasks = get_todays_tasks(tasks, today)
    previews = get_preview_tasks(tasks, today)

    print(f"今日待办: {len(today_tasks)} 项, 预告: {len(previews)} 项")

    if not today_tasks and not previews:
        print("无待办，跳过")
        return

    # 构建 Markdown 消息
    title = f"☀️ {today.strftime('%m月%d日')} 待办 · {len(today_tasks)}项"

    lines = []
    if today_tasks:
        lines.append(f"## 今日待办（{len(today_tasks)} 项）\n")
        for i, t in enumerate(today_tasks[:10]):
            tag = ""
            if t.get("priority") == "high": tag = "🔴"
            elif t.get("priority") == "low": tag = "🟢"
            lines.append(f"{i+1}. {tag} **{t.get('title','')}**")

    if previews:
        lines.append(f"\n## 📢 即将开始\n")
        for p in previews[:5]:
            lines.append(f"- {p['daysUntil']}天后 · {p['title']}（{p['date'].strftime('%m/%d')}）")

    lines.append(f"\n---\n📅 {today.strftime('%Y-%m-%d')} · 远近通记")

    desp = "\n".join(lines)

    # 发送
    ok = send_server_chan(title, desp)
    if ok:
        print("✅ 微信消息已发送")
    else:
        print("❌ 发送失败")
        sys.exit(1)

if __name__ == "__main__":
    main()
