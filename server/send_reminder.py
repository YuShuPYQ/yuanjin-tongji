#!/usr/bin/env python3
"""
远近通记 - 每日提醒发送脚本
由 GitHub Actions 每天北京时间 08:00 自动执行
发送浏览器推送通知
"""

import json, os, sys, requests
from datetime import datetime, timedelta, date

# ============================================================
# VAPID 密钥（Web Push）
# ============================================================
VAPID_PRIVATE_KEY = "dM7d45LlIjFl7TzqtxzpaQmGd6yhWToT0-9RSfU28J8"
VAPID_SUBJECT = "mailto:yushupyq@gmail.com"
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
# Web Push 发送
# ============================================================
def send_web_push(subscription, title, body):
    """使用 pywebpush 发送浏览器推送通知"""
    try:
        from pywebpush import WebPush, WebPushException
    except ImportError:
        print("pywebpush 未安装，请在 requirements 中添加")
        return False

    try:
        wp = WebPush({
            "vapid_private_key": VAPID_PRIVATE_KEY,
            "vapid_claims": {"sub": VAPID_SUBJECT}
        })
        payload = json.dumps({"title": title, "body": body})
        wp.send(
            json.dumps(payload).encode(),
            subscription,
            ttl=86400
        )
        print("✅ 推送通知已发送")
        return True
    except WebPushException as e:
        print(f"推送失败: {e}")
        if hasattr(e, 'response') and e.response:
            print(f"响应: {e.response.status_code} {e.response.text}")
        return False

# ============================================================
# 主流程
# ============================================================
def main():
    today = date.today()

    # 加载任务
    tasks = []
    push_sub = None
    if os.path.exists(TASKS_FILE):
        with open(TASKS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            tasks = data.get("tasks", [])
            push_sub = data.get("pushSubscription")
    print(f"加载 {len(tasks)} 条任务, push_sub={'有' if push_sub else '无'}")

    # 今日 + 预告
    today_tasks = get_todays_tasks(tasks, today)
    previews = get_preview_tasks(tasks, today)

    print(f"今日待办: {len(today_tasks)} 项")
    for t in today_tasks:
        print(f"  - {t.get('title','')}")
    print(f"预告: {len(previews)} 项")

    if not today_tasks and not previews:
        print("无待办，跳过发送")
        return

    # 构建通知内容
    today_lines = [f"{i+1}. {t.get('title','')}" for i, t in enumerate(today_tasks[:8])]
    preview_lines = [f"📢 {p['daysUntil']}天后·{p['title']}" for p in previews[:4]]

    title = f"☀️ {today.strftime('%m月%d日')} 待办 · {len(today_tasks)}项"
    body_parts = []
    if today_lines:
        body_parts.append("今日:\n" + "\n".join(today_lines))
    if preview_lines:
        body_parts.append("预告:\n" + "\n".join(preview_lines))
    body = "\n\n".join(body_parts)

    # 发送推送通知
    if push_sub:
        send_web_push(push_sub, title, body)
    else:
        print("⚠️ 未找到 push subscription，无法发送推送")

if __name__ == "__main__":
    main()
