# 远近通记 - 微信公众号提醒后端
# 部署到 CloudStudio 或其他 Python 托管平台
# 每天早上8点通过微信公众号模板消息推送今日待办 + 预告

import os
import json
import logging
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
import requests as http_requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ============================================================
# 配置 — 部署前填写
# ============================================================
WECHAT_APPID     = os.getenv("WECHAT_APPID",     "wxc735fc7d373f0bdc")
WECHAT_APPSECRET = os.getenv("WECHAT_APPSECRET", "b1a4478548607091a5375b829e0ae31f")
WECHAT_OPENID    = os.getenv("WECHAT_OPENID",    "oB_Zf5uPmrwJKe7bOUkJ3WSr26LM")
TEMPLATE_ID      = os.getenv("TEMPLATE_ID",      "申请后填这里")
API_KEY          = os.getenv("API_KEY",          "yjtj-reminder-2026")

# ============================================================
# 内存存储（重启丢失；生产环境应换 SQLite）
# ============================================================
tasks_data = {"tasks": [], "updatedAt": None}

# ============================================================
# 微信 access_token
# ============================================================
_access_token = {"value": None, "expires_at": 0}


def get_access_token():
    """获取微信公众号 access_token"""
    now = datetime.now().timestamp()
    if _access_token["value"] and now < _access_token["expires_at"]:
        return _access_token["value"]

    url = "https://api.weixin.qq.com/cgi-bin/token"
    params = {
        "grant_type": "client_credential",
        "appid": WECHAT_APPID,
        "secret": WECHAT_APPSECRET,
    }
    resp = http_requests.get(url, params=params, timeout=10).json()
    token = resp.get("access_token")
    expires = resp.get("expires_in", 7200)
    if token:
        _access_token["value"] = token
        _access_token["expires_at"] = now + expires - 300  # 提前5分钟刷新
        logger.info("access_token 获取成功")
        return token
    logger.error("获取 access_token 失败: %s", resp)
    return None


# ============================================================
# Task helpers（复刻前端逻辑）
# ============================================================
def parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date()

def days_between(d1, d2):
    return (d2 - d1).days

def get_repeat_interval(task):
    n = int(task.get("repeatInterval", 1) or 1)
    return n if n > 0 else 1

def task_covers_date(task, date_val):
    """判断任务是否在指定日期出现"""
    start = parse_date(task["startDate"])
    end   = parse_date(task["endDate"])
    if task.get("continuous") is True:
        interval = get_repeat_interval(task)
        if date_val < start or date_val > end:
            return False
        return days_between(start, date_val) % interval == 0
    return date_val == end

def categorize_task(task):
    span = days_between(parse_date(task["startDate"]), parse_date(task["endDate"])) + 1
    if span >= 365: return "year"
    if span >= 30:  return "month"
    if span >= 7:   return "week"
    return "day"

def find_next_occurrence(task, from_date):
    """找到任务在 from_date 之后的下一次出现日期"""
    start = parse_date(task["startDate"])
    end   = parse_date(task["endDate"])
    if from_date > end:
        return None
    if task.get("continuous") is True:
        interval = get_repeat_interval(task)
        offset = max(0, days_between(start, from_date))
        k = (offset + interval - 1) // interval  # ceil
        day = k * interval
        if day > days_between(start, end):
            return None
        d = start + timedelta(days=day)
        return d
    if from_date <= end:
        return end
    return None

def get_todays_tasks(tasks, today):
    """获取今天实际要执行的任务"""
    return [t for t in tasks
            if t.get("status") == "active" and task_covers_date(t, today)]

def get_preview_tasks(tasks, today):
    """获取未来3天的预告任务（仅年/月级别）"""
    preview = []
    for t in tasks:
        if t.get("status") != "active":
            continue
        cat = categorize_task(t)
        if cat not in ("year", "month"):
            continue
        next_date = find_next_occurrence(t, today)
        if next_date is None:
            continue
        days_until = days_between(today, next_date)
        if 0 < days_until <= 3:
            preview.append({"task": t, "date": next_date, "daysUntil": days_until})
    return preview


# ============================================================
# API 路由
# ============================================================

@app.route("/", methods=["GET"])
def index():
    return jsonify({"service": "远近通记-微信提醒", "status": "running"})


@app.route("/sync", methods=["POST"])
def sync_tasks():
    """接收前端同步的任务数据"""
    if request.headers.get("X-API-Key") != API_KEY:
        return jsonify({"error": "unauthorized"}), 401

    data = request.get_json(force=True)
    if not data or "tasks" not in data:
        return jsonify({"error": "invalid payload"}), 400

    global tasks_data
    tasks_data = {
        "tasks": data["tasks"],
        "updatedAt": datetime.now().isoformat()
    }
    logger.info("收到 %d 条任务同步", len(data["tasks"]))
    return jsonify({"ok": True, "count": len(data["tasks"])})


@app.route("/send-reminders", methods=["GET", "POST"])
def send_reminders():
    """触发发送微信提醒（可被外部 cron 调用）"""
    key = request.args.get("key") or (request.get_json(silent=True) or {}).get("key")
    if key != API_KEY:
        return jsonify({"error": "unauthorized"}), 401

    return _do_send_reminders()


def _do_send_reminders():
    today = datetime.now().date()
    active_tasks = [t for t in tasks_data.get("tasks", []) if t.get("status") == "active"]

    today_tasks = get_todays_tasks(active_tasks, today)
    preview_tasks = get_preview_tasks(active_tasks, today)

    # 构建消息文本
    today_names = [t.get("title", "无标题") for t in today_tasks[:8]]
    preview_lines = [f'{p["daysUntil"]}天后·{p["task"].get("title","")}' for p in preview_tasks[:5]]

    today_text = "\n".join(f"  {i+1}. {n}" for i, n in enumerate(today_names)) if today_names else "  暂无"
    preview_text = "\n".join(f"  📢 {l}" for l in preview_lines) if preview_lines else "  暂无"

    first = f"☀️ 早上好！{today.strftime('%m月%d日')} 待办提醒"
    remark = "打开远近通记查看详情 ↗"

    # 发送微信模板消息
    token = get_access_token()
    if not token:
        return jsonify({"error": "获取 access_token 失败"}), 500

    url = f"https://api.weixin.qq.com/cgi-bin/message/template/send?access_token={token}"
    payload = {
        "touser": WECHAT_OPENID,
        "template_id": TEMPLATE_ID,
        "data": {
            "first":    {"value": first,        "color": "#333333"},
            "keyword1": {"value": str(len(today_tasks)) + " 项", "color": "#1a73e8"},
            "keyword2": {"value": today_text,    "color": "#333333"},
            "keyword3": {"value": preview_text,  "color": "#6b7280"},
            "remark":   {"value": remark,        "color": "#9ca3af"},
        }
    }
    resp = http_requests.post(url, json=payload, timeout=10).json()
    logger.info("模板消息发送结果: %s", resp)

    if resp.get("errcode") == 0:
        return jsonify({"ok": True, "todayCount": len(today_tasks), "previewCount": len(preview_tasks)})
    return jsonify({"error": resp.get("errmsg", "unknown"), "code": resp.get("errcode")})


# ============================================================
# 定时任务（APScheduler）
# ============================================================
def scheduled_reminder():
    logger.info("⏰ 执行每日提醒任务")
    result = _do_send_reminders()
    logger.info("提醒结果: %s", result)


try:
    from apscheduler.schedulers.background import BackgroundScheduler
    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    scheduler.add_job(scheduled_reminder, "cron", hour=8, minute=0, id="daily_reminder")
    scheduler.start()
    logger.info("APScheduler 已启动，每日 08:00 发送提醒")
except Exception as e:
    logger.warning("APScheduler 启动失败，请用外部 cron 触发 /send-reminders: %s", e)

# ============================================================
# 启动
# ============================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info("远近通记微信提醒服务启动，端口 %s", port)
    app.run(host="0.0.0.0", port=port, debug=False)
