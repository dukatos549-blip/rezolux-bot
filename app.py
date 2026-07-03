import os
import requests
from datetime import date, timedelta
from flask import Flask, request, jsonify

app = Flask(__name__)

# === НАСТРОЙКИ ===
BOT_TOKEN = os.getenv("BOT_TOKEN", "8638519756:AAFMJ3mbfVH-ldftxF9SvpIUfOL7enxzsl4")
CHAT_ID = os.getenv("CHAT_ID", "535732426")
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")

OZON_SHOPS = {
    "rezolux": {
        "name": "Резолюкс",
        "client_id": "1359079",
        "api_key": "e815cb6c-6ffa-4173-89cb-af40a891f4fa",
    },
    "gidro": {
        "name": "Гидроспецкраска",
        "client_id": "2190280",
        "api_key": "f0373a97-27c0-4cd9-bfa3-06f56da3b916",
    }
}

BASE = "https://api-seller.ozon.ru"
TG_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"


def tg(text, chat_id=CHAT_ID):
    requests.post(f"{TG_URL}/sendMessage",
                  json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"})


def ozon_post(shop_key, path, payload=None):
    shop = OZON_SHOPS[shop_key]
    headers = {
        "Client-Id": shop["client_id"],
        "Api-Key": shop["api_key"],
        "Content-Type": "application/json",
    }
    r = requests.post(f"{BASE}{path}", json=payload or {}, headers=headers, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"{r.status_code}: {r.text[:200]}")
    return r.json()


def get_analytics(shop_key, days=7):
    date_to = date.today().strftime("%Y-%m-%d")
    date_from = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    resp = ozon_post(shop_key, "/v1/analytics/data", {
        "date_from": date_from, "date_to": date_to,
        "metrics": ["revenue", "ordered_units", "session_view_pdp"],
        "dimension": ["sku"], "limit": 10, "offset": 0,
        "sort": [{"key": "revenue", "order": "DESC"}]
    })
    return resp.get("result", {}).get("data", []), date_from, date_to


def build_report(shop_key, days=7):
    shop_name = OZON_SHOPS[shop_key]["name"]
    rows, date_from, date_to = get_analytics(shop_key, days)
    total_rev = sum(r["metrics"][0] for r in rows)
    total_units = sum(int(r["metrics"][1]) for r in rows)
    top = ""
    for i, row in enumerate(rows[:5], 1):
        name = row["dimensions"][0].get("name", "?")[:30]
        rev = int(row["metrics"][0])
        units = int(row["metrics"][1])
        views = int(row["metrics"][2]) if len(row["metrics"]) > 2 else 0
        conv = f"{units/views*100:.1f}%" if views > 0 else "—"
        top += f"{i}. {name}\n   {rev:,} руб / {units} шт / конв {conv}\n"

    return f"""<b>{shop_name} - отчет за {days} дней</b>
{date_from} / {date_to}

Выручка: {int(total_rev):,} руб
Продаж: {total_units} шт
Средний чек: {int(total_rev/max(1,total_units)):,} руб

<b>Топ-5 товаров:</b>
{top}"""


def ask_claude(user_message):
    if not CLAUDE_API_KEY:
        return "Claude API ключ не настроен. Добавь CLAUDE_API_KEY в переменные окружения Railway."

    system = """Ты помощник владельца магазинов красок на Ozon (Резолюкс и Гидроспецкраска).
Отвечай кратко и по делу. Магазин продаёт краски, эмали, стеклошарики для дорожной разметки.
Выручка Резолюкс: 3.5 млн/мес. Конверсия 2.4% (цель 5%). 543 товара.
Помогай с SEO, карточками, аналитикой, рекламой."""

    resp = requests.post("https://api.anthropic.com/v1/messages",
                         headers={
                             "x-api-key": CLAUDE_API_KEY,
                             "anthropic-version": "2023-06-01",
                             "content-type": "application/json"
                         },
                         json={
                             "model": "claude-sonnet-4-6",
                             "max_tokens": 500,
                             "system": system,
                             "messages": [{"role": "user", "content": user_message}]
                         })
    if resp.status_code == 200:
        return resp.json()["content"][0]["text"]
    return f"Ошибка Claude: {resp.status_code}"


@app.route(f"/webhook", methods=["POST"])
def webhook():
    data = request.json
    message = data.get("message", {})
    chat_id = str(message.get("chat", {}).get("id", ""))
    text = message.get("text", "").strip()

    if str(chat_id) != str(CHAT_ID):
        return jsonify({"ok": True})

    if text == "/start":
        tg("""<b>Привет! Я агент магазина Rezolux</b>

Команды:
/отчет - отчет Резолюкс за 7 дней
/отчет30 - отчет за 30 дней
/гидро - отчет Гидроспецкраска
/статус - статус всех магазинов
/помощь - помощь с карточками и SEO

Или просто напиши вопрос - отвечу!""", chat_id)

    elif text in ["/отчет", "/report"]:
        tg("Снимаю аналитику...", chat_id)
        try:
            report = build_report("rezolux", 7)
            tg(report, chat_id)
        except Exception as e:
            tg(f"Ошибка: {e}", chat_id)

    elif text in ["/отчет30"]:
        tg("Снимаю аналитику за 30 дней...", chat_id)
        try:
            report = build_report("rezolux", 30)
            tg(report, chat_id)
        except Exception as e:
            tg(f"Ошибка: {e}", chat_id)

    elif text in ["/гидро", "/gidro"]:
        tg("Снимаю аналитику Гидроспецкраска...", chat_id)
        try:
            report = build_report("gidro", 7)
            tg(report, chat_id)
        except Exception as e:
            tg(f"Ошибка: {e}", chat_id)

    elif text in ["/статус", "/status"]:
        msg = "<b>Статус магазинов:</b>\n\n"
        for key, shop in OZON_SHOPS.items():
            try:
                resp = ozon_post(key, "/v3/product/list",
                                 {"filter": {"visibility": "ALL"}, "last_id": "", "limit": 1})
                msg += f"✅ {shop['name']} - работает\n"
            except Exception as e:
                msg += f"❌ {shop['name']} - ошибка\n"
        tg(msg, chat_id)

    elif text in ["/помощь", "/help"]:
        answer = ask_claude("Дай 3 главных совета по улучшению карточек красок на Ozon")
        tg(answer, chat_id)

    else:
        answer = ask_claude(text)
        tg(answer, chat_id)

    return jsonify({"ok": True})


@app.route("/", methods=["GET"])
def index():
    return "Rezolux Bot работает!"


@app.route("/set_webhook", methods=["GET"])
def set_webhook():
    url = request.args.get("url")
    if not url:
        return "Укажи ?url=https://твой-домен.railway.app/webhook"
    resp = requests.get(f"{TG_URL}/setWebhook?url={url}/webhook")
    return resp.json()


@app.route("/daily_report", methods=["GET"])
def daily_report():
    for key in OZON_SHOPS:
        try:
            report = build_report(key, 1)
            tg(report)
        except Exception as e:
            tg(f"Ошибка отчета {key}: {e}")
    return "OK"


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
