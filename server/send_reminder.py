#!/usr/bin/env python3
"""
远近通记 - 微信每日提醒发送脚本
由 GitHub Actions 每天北京时间 08:00 自动执行
"""

import json, os, sys, requests
from datetime import datetime, timedelta, date

# ============================================================
# 配置
# ============================================================
WECHAT_APPID     = "wxc735fc7d373f0bdc"
WECHAT_APPSECRET = os.getenv("WECHAT_APPSECRET", "b1a4478548607091a5375b829e0ae31f")
WECHAT_OPENID    = "oB_Zf5uPmrwJKe7bOUkJ3WSr26LM"
TEMPLATE_ID      = os.getenv("TEMPLATE_ID", "")  # 公众号后台申请模板消息后填入
TASKS_FILE       = os.path.join(os.path.dirname(__file__), "..", "tasks_sync.json")

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
# 微信
# ============================================================
def get_token():
    r = requests.get("https://api.weixin.qq.com/cgi-bin/token", params={
        "grant_type": "client_credential",
        "appid": WECHAT_APPID,
        "secret": WECHAT_APPSECRET
    }, timeout=10).json()
    return r.get("access_token")

def send_template(token, today, today_tasks, previews):
    if not TEMPLATE_ID:
        print("⚠️ 未配置 TEMPLATE_ID，跳过发送")
        return

    today_names = [t.get("title","") for t in today_tasks[:8]]
    preview_lines = [f'{p["daysUntil"]}天后·{p["title"]}' for p in previews[:5]]

    today_text = "\n".join(f"  {i+1}. {n}" for i, n in enumerate(today_names)) if today_names else "  暂无"
    preview_text = "\n".join(f"  📢 {l}" for l in preview_lines) if preview_lines else "  暂无"

    payload = {
        "touser": WECHAT_OPENID,
        "template_id": TEMPLATE_ID,
        "data": {
            "first":    {"value": f"☀️ 早上好！{today.strftime('%m月%d日')} 待办提醒", "color": "#333333"},
            "keyword1": {"value": f"{len(today_tasks)} 项", "color": "#1a73e8"},
            "keyword2": {"value": today_text,  "color": "#333333"},
            "keyword3": {"value": preview_text, "color": "#6b7280"},
            "remark":   {"value": "打开远近通记查看详情", "color": "#9ca3af"},
        }
    }

    url = f"https://api.weixin.qq.com/cgi-bin/message/template/send?access_token={token}"
    r = requests.post(url, json=payload, timeout=10).json()
    print("发送结果:", r)

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

    # 今日 + 预告
    today_tasks = get_todays_tasks(tasks, today)
    previews = get_preview_tasks(tasks, today)

    print(f"今日待办: {len(today_tasks)} 项")
    for t in today_tasks:
        print(f"  - {t.get('title','')}")

    print(f"预告: {len(previews)} 项")
    for p in previews:
        print(f"  - {p['daysUntil']}天后: {p['title']}")

    if not today_tasks and not previews:
        print("无待办，跳过发送")
        return

    # 发微信
    token = get_token()
    if not token:
        print("❌ 获取 access_token 失败")
        sys.exit(1)

    send_template(token, today, today_tasks, previews)
    print("✅ 提醒发送完成")

if __name__ == "__main__":
    main()
