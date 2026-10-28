
import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TR = ZoneInfo("Europe/Istanbul")
STATE_FILE = "state.json"

LEAGUES = {
    "nba": ("🏀 NBA", "basketball", "nba"),
    "nfl": ("🏈 NFL", "football", "nfl"),
    "ncaam": ("🎓 NCAA Erkek Basketbol", "basketball", "mens-college-basketball"),
    "ncaaw": ("🎓 NCAA Kadın Basketbol", "basketball", "womens-college-basketball"),
    "ncaaf": ("🏈 NCAA Football", "football", "college-football"),
}

LEAGUE_ORDER = [
    ("nba", "🏀 NBA"),
    ("nfl", "🏈 NFL"),
    ("ncaam", "🎓 NCAA ERKEK BASKETBOL"),
    ("ncaaw", "🎓 NCAA KADIN BASKETBOL"),
    ("ncaaf", "🏈 NCAA FOOTBALL"),
    ("mlb", "⚾ MLB"),
]


def request_json(url, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None

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
    response = request_json(
        f"https://api.telegram.org/bot{TOKEN}/{method}",
        payload
    )

    if not response.get("ok"):
        raise RuntimeError(response.get("description", "Telegram API hatası"))

    return response["result"]


def keyboard():
    buttons = [
        [("📅 Bugün", "today"), ("🌙 Yarın", "tomorrow")],
        [("📋 7 Gün", "week"), ("📊 Yoğunluk", "density")],
        [("🏀 NBA", "nba"), ("🏈 NFL", "nfl")],
        [("⚾ MLB", "mlb"), ("🎓 NCAA", "ncaa")],
    ]

    return {
        "inline_keyboard": [
            [
                {"text": title, "callback_data": value}
                for title, value in row
            ]
            for row in buttons
        ]
    }


def send(chat, text, markup=None):
    # Telegram mesaj sınırını aşmamak için satır bazında böl.
    chunks = []
    current = ""

    for line in text.splitlines(keepends=True):
        if len(current) + len(line) > 3500:
            if current:
                chunks.append(current)
            current = ""

        while len(line) > 3500:
            chunks.append(line[:3500])
            line = line[3500:]

        current += line

    if current:
        chunks.append(current)

    if not chunks:
        chunks = ["Gösterilecek bilgi bulunamadı."]

    for index, chunk in enumerate(chunks):
        payload = {
            "chat_id": chat,
            "text": chunk,
        }

        if markup and index == len(chunks) - 1:
            payload["reply_markup"] = markup

        telegram("sendMessage", payload)


def iso_date(value):
    if not value:
        raise ValueError("Maç tarihi boş")

    return datetime.fromisoformat(
        value.replace("Z", "+00:00")
    ).astimezone(TR)


def espn_games(code, first_day, days):
    label, sport, league = LEAGUES[code]
    results = {}

    for shift in range(-1, days + 1):
        date = first_day + timedelta(days=shift)

        params = {
            "dates": date.strftime("%Y%m%d"),
            "limit": "500",
        }

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
            raise ValueError(f"{code}: ESPN maç listesi bulunamadı")

        for event in events:
            try:
                competition = event["competitions"][0]
                competitors = competition["competitors"]

                home = next(
                    team for team in competitors
                    if team["homeAway"] == "home"
                )

                away = next(
                    team for team in competitors
                    if team["homeAway"] == "away"
                )

                start = iso_date(event["date"])

                if not (
                    first_day <= start.date()
                    < first_day + timedelta(days=days)
                ):
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

                if not (
                    first_day <= start_time.date()
                    < first_day + timedelta(days=days)
                ):
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

    unique = {
        game["id"]: game
        for game in games
    }

    return (
        sorted(unique.values(), key=lambda game: game["time"]),
        errors,
    )


def grouped_games(games):
    """
    Maçları liglere ayırır.
    Her ligin başında maç sayısını gösterir.
    Her lig içinde saat sıralaması yapar.
    """

    if not games:
        return "Bu tarih için maç bulunamadı.\n"

    text = ""

    for code, title in LEAGUE_ORDER:
        league_games = [
            game for game in games
            if game["code"] == code
        ]

        if not league_games:
            continue

        league_games.sort(key=lambda game: game["time"])

        text += (
            "━━━━━━━━━━━━━━━━\n"
            f"{title} — {len(league_games)} MAÇ\n"
            "━━━━━━━━━━━━━━━━\n\n"
        )

        for game in league_games:
            text += (
                f"🕒 {game['time']:%H:%M} | "
                f"{game['away']} - {game['home']}\n"
            )

        text += "\n"

    return text


def warning(errors):
    if not errors:
        return ""

    return (
        "\n⚠️ VERİ ALINAMAYAN LİGLER\n"
        + "\n".join(errors)
        + "\nBu nedenle maç listesi eksik olabilir.\n"
    )


def show_day(chat, offset=0, only=None):
    day = datetime.now(TR).date() + timedelta(days=offset)

    games, errors = fetch_games(day, 1, only)

    if offset == 0:
        heading = "📅 BUGÜN"
    elif offset == 1:
        heading = "🌙 YARIN"
    else:
        heading = "📅 MAÇ TAKVİMİ"

    text = (
        f"{heading} — {day:%d.%m.%Y}\n"
        "🇹🇷 Saatler Türkiye saatine göredir.\n"
        f"🏆 TOPLAM: {len(games)} MAÇ\n\n"
    )

    text += grouped_games(games)
    text += warning(errors)

    send(chat, text, keyboard())


def show_week(chat, density=False):
    today = datetime.now(TR).date()

    games, errors = fetch_games(today, 7)

    if density:
        text = (
            "📊 HAFTALIK MAÇ YOĞUNLUĞU\n"
            "🇹🇷 Türkiye saati\n\n"
        )
    else:
        text = (
            "📋 7 GÜNLÜK MAÇ TAKVİMİ\n"
            "🇹🇷 Türkiye saati\n"
            f"🏆 TOPLAM: {len(games)} MAÇ\n\n"
        )

    busiest_day = None
    busiest_count = -1

    for offset in range(7):
        day = today + timedelta(days=offset)

        daily = [
            game for game in games
            if game["time"].date() == day
        ]

        count = len(daily)

        if count > busiest_count:
            busiest_day = day
            busiest_count = count

        text += (
            f"📅 {day:%d.%m.%Y}\n"
            f"🏆 {count} MAÇ\n\n"
        )

        if density:
            for code, title in LEAGUE_ORDER:
                league_count = sum(
                    game["code"] == code
                    for game in daily
                )

                if league_count:
                    text += f"{title}: {league_count} maç\n"

        else:
            text += grouped_games(daily)

        text += "\n"

    if density and busiest_day:
        text += (
            "🔥 EN YOĞUN GÜN\n"
            f"{busiest_day:%d.%m.%Y} — "
            f"{busiest_count} MAÇ\n"
        )

    text += warning(errors)

    send(chat, text, keyboard())


def ncaa_keyboard():
    return {
        "inline_keyboard": [
            [
                {
                    "text": "🏀 Erkek Basketbol",
                    "callback_data": "ncaam",
                }
            ],
            [
                {
                    "text": "🏀 Kadın Basketbol",
                    "callback_data": "ncaaw",
                }
            ],
            [
                {
                    "text": "🏈 NCAA Football",
                    "callback_data": "ncaaf",
                }
            ],
            [
                {
                    "text": "⬅️ Ana Menü",
                    "callback_data": "menu",
                }
            ],
        ]
    }


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
        send(
            chat,
            "🎓 NCAA\n\nGörmek istediğin branşı seç:",
            ncaa_keyboard(),
        )

    elif command in LEAGUES or command == "mlb":
        show_day(chat, 0, command)

    else:
        send(
            chat,
            "🏆 MAÇLAR2121\n\n"
            "🏀 NBA\n"
            "🏈 NFL\n"
            "⚾ MLB\n"
            "🎓 NCAA Basketbol ve Football\n\n"
            "🇹🇷 Bütün saatler Türkiye saatidir.\n\n"
            "Bir bölüm seç:",
            keyboard(),
        )


def load_offset():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            return int(json.load(file).get("offset", 0))

    except (
        FileNotFoundError,
        ValueError,
        json.JSONDecodeError,
    ):
        return 0


def save_offset(offset):
    with open(STATE_FILE, "w", encoding="utf-8") as file:
        json.dump({"offset": offset}, file)


def main():
    if os.environ.get("TEST_ONLY") == "1":
        today = datetime.now(TR).date()

        games, errors = fetch_games(today, 2)

        print("TOPLAM:", len(games))
        print("HATALAR:", errors)

        for game in games:
            print(
                game["time"],
                game["league"],
                game["away"],
                "-",
                game["home"],
            )

        if errors:
            raise RuntimeError(
                "Bir veya daha fazla ligden veri alınamadı"
            )

        return

    offset = load_offset()

    updates = telegram("getUpdates", {
        "offset": offset,
        "limit": 20,
        "timeout": 0,
        "allowed_updates": [
            "message",
            "callback_query",
        ],
    })

    print(f"Telegram'dan gelen güncelleme: {len(updates)}")

    for update in updates:
        next_offset = update["update_id"] + 1

        try:
            if "callback_query" in update:
                query = update["callback_query"]

                try:
                    telegram("answerCallbackQuery", {
                        "callback_query_id": query["id"]
                    })

                except Exception as error:
                    print("Buton onayı:", error)

                chat = query["message"]["chat"]["id"]
                action(chat, query["data"])

            elif "message" in update:
                message = update["message"]

                if "text" in message:
                    chat = message["chat"]["id"]

                    cmd = (
                        message["text"]
                        .split()[0]
                        .split("@")[0]
                        .lower()
                    )

                    mapping = {
                        "/start": "menu",
                        "/menu": "menu",
                        "/bugun": "today",
                        "/yarin": "tomorrow",
                        "/hafta": "week",
                        "/yogunluk": "density",
                    }

                    action(chat, mapping.get(cmd, "menu"))

        except Exception as error:
            print("Güncelleme işleme hatası:", error)

        finally:
            offset = next_offset
            save_offset(offset)


if __name__ == "__main__":
    main()
