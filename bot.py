
import os
import json
import time
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TR = ZoneInfo("Europe/Istanbul")
STATE_FILE = "state.json"

LEAGUES = {
    "nba": ("🏀 NBA", "basketball", "nba"),
    "nfl": ("🏈 NFL", "football", "nfl"),
    "ncaam": ("🎓 NCAA Erkek", "basketball", "mens-college-basketball"),
    "ncaaw": ("🎓 NCAA Kadın", "basketball", "womens-college-basketball"),
    "ncaaf": ("🏈 NCAA Football", "football", "college-football"),
}

def request_json(url, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=25) as response:
        return json.load(response)

def telegram(method, payload):
    return request_json(
        f"https://api.telegram.org/bot{TOKEN}/{method}",
        payload
    )["result"]

def keyboard():
    buttons = [
        [("📅 Bugün", "today"), ("🌙 Yarın", "tomorrow")],
        [("📋 7 Gün", "week"), ("📊 Yoğunluk", "density")],
        [("🏀 NBA", "nba"), ("🏈 NFL", "nfl")],
        [("⚾ MLB", "mlb"), ("🎓 NCAA", "ncaa")],
    ]
    return {
        "inline_keyboard": [
            [{"text": title, "callback_data": value} for title, value in row]
            for row in buttons
        ]
    }

def send(chat, text, markup=None):
    chunks = []
    current = ""
    for line in text.splitlines(keepends=True):
        if len(current) + len(line) > 3500:
            if current:
                chunks.append(current)
            current = ""
        current += line
    if current:
        chunks.append(current)

    for i, chunk in enumerate(chunks):
        payload = {"chat_id": chat, "text": chunk}
        if markup and i == len(chunks) - 1:
            payload["reply_markup"] = markup
        telegram("sendMessage", payload)

def iso_date(value):
    if not value:
        raise ValueError("Maç tarihi boş")
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(TR)

def espn_games(code, first_day, days):
    label, sport, league = LEAGUES[code]
    results = {}

    # ABD ve Türkiye arasındaki gün farkını kapsar.
    for shift in range(-1, days + 1):
        date = first_day + timedelta(days=shift)
        date_arg = date.strftime("%Y%m%d")

        params = {"dates": date_arg, "limit": "500"}
        if code in ("ncaam", "ncaaw"):
            params["groups"] = "50"
        elif code == "ncaaf":
            params["groups"] = "80"

        url = (
            f"https://site.api.espn.com/apis/site/v2/sports/"
            f"{sport}/{league}/scoreboard?"
            + urllib.parse.urlencode(params)
        )

        data = request_json(url)
        events = data.get("events")

        if not isinstance(events, list):
            raise ValueError(f"{code}: ESPN yanıtında events yok")

        for event in events:
            try:
                comp = event["competitions"][0]
                teams = comp["competitors"]
                home = next(t for t in teams if t["homeAway"] == "home")
                away = next(t for t in teams if t["homeAway"] == "away")
                start = iso_date(event["date"])

                if not first_day <= start.date() < first_day + timedelta(days=days):
                    continue

                game_id = f"{code}_{event['id']}"
                results[game_id] = {
                    "id": game_id,
                    "league": label,
                    "code": code,
                    "home": home["team"]["displayName"],
                    "away": away["team"]["displayName"],
                    "time": start,
                }
            except (KeyError, IndexError, StopIteration, ValueError):
                continue

    return list(results.values())

def mlb_games(first_day, days):
    start = first_day - timedelta(days=1)
    end = first_day + timedelta(days=days + 1)

    params = urllib.parse.urlencode({
        "sportId": "1",
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
    })

    data = request_json(
        "https://statsapi.mlb.com/api/v1/schedule?" + params
    )

    if not isinstance(data.get("dates"), list):
        raise ValueError("MLB takvim yanıtı geçersiz")

    results = []
    for date in data["dates"]:
        for event in date.get("games", []):
            try:
                start_time = iso_date(event["gameDate"])
                if not first_day <= start_time.date() < first_day + timedelta(days=days):
                    continue

                results.append({
                    "id": f"mlb_{event['gamePk']}",
                    "league": "⚾ MLB",
                    "code": "mlb",
                    "home": event["teams"]["home"]["team"]["name"],
                    "away": event["teams"]["away"]["team"]["name"],
                    "time": start_time,
                })
            except (KeyError, ValueError):
                continue

    return results

def fetch_games(first_day, days, only=None):
    codes = [only] if only else list(LEAGUES) + ["mlb"]
    games = []
    errors = []

    for code in codes:
        try:
            if code == "mlb":
                found = mlb_games(first_day, days)
            else:
                found = espn_games(code, first_day, days)
            games.extend(found)
            print(f"{code}: {len(found)} maç")
        except Exception as error:
            errors.append(f"{code.upper()}: {error}")
            print(f"HATA {code}: {error}")

    unique = {game["id"]: game for game in games}
    return sorted(unique.values(), key=lambda g: g["time"]), errors

def game_line(game):
    return (
        f"🕒 {game['time']:%H:%M} | {game['league']}\n"
        f"{game['away']} - {game['home']}\n"
    )

def warning(errors):
    if not errors:
        return ""
    return (
        "\n⚠️ VERİ ALINAMAYAN LİGLER\n"
        + "\n".join(errors)
        + "\nBu nedenle liste ve yoğunluk eksik olabilir."
    )

def show_day(chat, offset=0, only=None):
    day = datetime.now(TR).date() + timedelta(days=offset)
    games, errors = fetch_games(day, 1, only)

    text = (
        f"📅 {day:%d.%m.%Y}\n"
        f"🇹🇷 Türkiye saati\n"
        f"🏆 Bulunan maç: {len(games)}\n\n"
    )

    if not games:
        text += "Doğrulanmış maç bulunamadı.\n"

    for game in games:
        text += game_line(game) + "\n"

    send(chat, text + warning(errors), keyboard())

def show_week(chat, density=False):
    today = datetime.now(TR).date()
    games, errors = fetch_games(today, 7)

    text = (
        "📊 HAFTALIK YOĞUNLUK\n\n"
        if density else
        "📋 7 GÜNLÜK MAÇ LİSTESİ\n\n"
    )

    busiest = (None, -1)

    for offset in range(7):
        day = today + timedelta(days=offset)
        daily = [g for g in games if g["time"].date() == day]

        if len(daily) > busiest[1]:
            busiest = (day, len(daily))

        text += f"📅 {day:%d.%m.%Y} | {len(daily)} maç\n"

        if density:
            for code in list(LEAGUES) + ["mlb"]:
                count = sum(g["code"] == code for g in daily)
                if count:
                    label = "⚾ MLB" if code == "mlb" else LEAGUES[code][0]
                    text += f"• {label}: {count}\n"
        else:
            for game in daily:
                text += game_line(game) + "\n"

        text += "\n"

    if density and busiest[0]:
        text += (
            f"🔥 En yoğun gün: {busiest[0]:%d.%m.%Y}"
            f" ({busiest[1]} maç)\n"
        )

    send(chat, text + warning(errors), keyboard())

def action(chat, command):
    if command == "today":
        show_day(chat)
    elif command == "tomorrow":
        show_day(chat, 1)
    elif command == "week":
        show_week(chat)
    elif command == "density":
        show_week(chat, True)
    elif command == "ncaa":
        send(chat, "🎓 NCAA branşı seç:", {
            "inline_keyboard": [
                [{"text": "🏀 Erkek Basketbol", "callback_data": "ncaam"}],
                [{"text": "🏀 Kadın Basketbol", "callback_data": "ncaaw"}],
                [{"text": "🏈 NCAA Football", "callback_data": "ncaaf"}],
                [{"text": "⬅️ Menü", "callback_data": "menu"}],
            ]
        })
    elif command in LEAGUES or command == "mlb":
        show_day(chat, 0, command)
    else:
        send(
            chat,
            "🏆 MAÇLAR2121\n\n"
            "NBA • NFL • MLB • NCAA\n"
            "🇹🇷 Türkiye saatine göre\n\n"
            "Bir bölüm seç:",
            keyboard()
        )

def load_offset():
    try:
        with open(STATE_FILE, "r") as f:
            return int(json.load(f).get("offset", 0))
    except (FileNotFoundError, ValueError, json.JSONDecodeError):
        return 0

def save_offset(offset):
    with open(STATE_FILE, "w") as f:
        json.dump({"offset": offset}, f)

def main():
    # İlk kurulumda veri erişimini bağımsız test et.
    if os.environ.get("TEST_ONLY") == "1":
        today = datetime.now(TR).date()
        games, errors = fetch_games(today, 2)
        print("TOPLAM:", len(games))
        print("HATALAR:", errors)
        for game in games:
            print(game["time"], game["league"], game["away"], "-", game["home"])
        if errors:
            raise RuntimeError("Bir veya daha fazla ligden veri alınamadı")
        return

    offset = load_offset()

    updates = telegram("getUpdates", {
        "offset": offset,
        "limit": 20,
        "timeout": 0,
        "allowed_updates": ["message", "callback_query"]
    })

    for update in updates:
        next_offset = update["update_id"] + 1

        try:
            if "callback_query" in update:
                query = update["callback_query"]
                try:
                    telegram("answerCallbackQuery", {
                        "callback_query_id": query["id"]
                    })
                except Exception as e:
                    print("Buton onayı:", e)

                chat = query["message"]["chat"]["id"]
                action(chat, query["data"])

            elif "message" in update:
                message = update["message"]
                if "text" in message:
                    chat = message["chat"]["id"]
                    cmd = message["text"].split()[0].split("@")[0].lower()
                    mapping = {
                        "/start": "menu",
                        "/menu": "menu",
                        "/bugun": "today",
                        "/yarin": "tomorrow",
                        "/hafta": "week",
                        "/yogunluk": "density",
                    }
                    action(chat, mapping.get(cmd, "menu"))

        except Exception as e:
            print("Güncelleme işleme hatası:", e)

        finally:
            # Hatalı güncelleme sonsuz döngü oluşturmasın.
            offset = next_offset
            save_offset(offset)

if __name__ == "__main__":
    main()
