import logging
import random
import sqlite3
import uuid
import json
import os
from datetime import date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Poll
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, PollAnswerHandler
)

TOKEN = os.getenv("TOKEN", "8905147513:AAEfEXBjIvC-BJrkyp4Bm1LO57xGentsyjg")
logging.basicConfig(level=logging.INFO)

# ─────────────────────────────────────────
# БД
# ─────────────────────────────────────────
def init_db():
    conn = sqlite3.connect("quiz.db")
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, username TEXT,
        score INTEGER DEFAULT 0, coins INTEGER DEFAULT 0,
        streak INTEGER DEFAULT 0, last_play TEXT,
        total INTEGER DEFAULT 0, correct INTEGER DEFAULT 0
    )""")
    # Миграция старой БД
    for col, default in [("coins","0"),("total","0"),("correct","0"),("streak","0")]:
        try:
            c.execute(f"ALTER TABLE users ADD COLUMN {col} INTEGER DEFAULT {default}")
        except: pass
    c.execute("""CREATE TABLE IF NOT EXISTS sessions (
        user_id INTEGER PRIMARY KEY, level TEXT,
        index_ INTEGER DEFAULT 0, coins INTEGER DEFAULT 0, questions TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS active_polls (
        poll_id TEXT PRIMARY KEY, user_id INTEGER,
        correct_id INTEGER, points INTEGER,
        session_type TEXT DEFAULT 'quiz',
        duel_id TEXT DEFAULT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS user_cards (
        user_id INTEGER, card_id TEXT,
        PRIMARY KEY (user_id, card_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS duels (
        duel_id TEXT PRIMARY KEY,
        p1_id INTEGER, p2_id INTEGER, level TEXT,
        p1_score INTEGER DEFAULT 0, p2_score INTEGER DEFAULT 0,
        p1_index INTEGER DEFAULT 0, p2_index INTEGER DEFAULT 0,
        p1_done INTEGER DEFAULT 0, p2_done INTEGER DEFAULT 0,
        questions TEXT, status TEXT DEFAULT 'waiting'
    )""")
    conn.commit()
    conn.close()

def get_user(user_id, username=""):
    conn = sqlite3.connect("quiz.db")
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?,?)", (user_id, username))
    c.execute("SELECT user_id, username, score, coins, streak, last_play, total, correct FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.commit()
    conn.close()
    return row

def add_result(user_id, coins, correct):
    conn = sqlite3.connect("quiz.db")
    c = conn.cursor()
    today = str(date.today())
    c.execute("SELECT streak, last_play FROM users WHERE user_id=?", (user_id,))
    r = c.fetchone()
    streak = (r[0]+1) if r and r[1]==today else 1
    if correct:
        c.execute("""UPDATE users SET coins=coins+?, score=score+?, streak=?,
            last_play=?, total=total+1, correct=correct+1 WHERE user_id=?""",
            (coins, coins, streak, today, user_id))
    else:
        c.execute("UPDATE users SET total=total+1, streak=1, last_play=? WHERE user_id=?",
            (today, user_id))
    conn.commit()
    conn.close()

def spend_coins(user_id, amount):
    conn = sqlite3.connect("quiz.db")
    c = conn.cursor()
    c.execute("SELECT coins FROM users WHERE user_id=?", (user_id,))
    r = c.fetchone()
    if not r or r[0] < amount:
        conn.close()
        return False
    c.execute("UPDATE users SET coins=coins-? WHERE user_id=?", (amount, user_id))
    conn.commit()
    conn.close()
    return True

def get_leaderboard():
    conn = sqlite3.connect("quiz.db")
    c = conn.cursor()
    c.execute("SELECT username, score, correct, total FROM users ORDER BY score DESC LIMIT 10")
    rows = c.fetchall()
    conn.close()
    return rows

def get_cards(user_id):
    conn = sqlite3.connect("quiz.db")
    c = conn.cursor()
    c.execute("SELECT card_id FROM user_cards WHERE user_id=?", (user_id,))
    rows = [r[0] for r in c.fetchall()]
    conn.close()
    return rows

def add_card(user_id, card_id):
    conn = sqlite3.connect("quiz.db")
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO user_cards VALUES (?,?)", (user_id, card_id))
    conn.commit()
    conn.close()

def save_session(user_id, level, index, coins, questions):
    conn = sqlite3.connect("quiz.db")
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO sessions VALUES (?,?,?,?,?)",
              (user_id, level, index, coins, json.dumps(questions)))
    conn.commit()
    conn.close()

def get_session(user_id):
    conn = sqlite3.connect("quiz.db")
    c = conn.cursor()
    c.execute("SELECT * FROM sessions WHERE user_id=?", (user_id,))
    r = c.fetchone()
    conn.close()
    if r:
        return {"level":r[1],"index":r[2],"coins":r[3],"questions":json.loads(r[4])}
    return None

def del_session(user_id):
    conn = sqlite3.connect("quiz.db")
    c = conn.cursor()
    c.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def save_poll(poll_id, user_id, correct_id, points, session_type="quiz", duel_id=None):
    conn = sqlite3.connect("quiz.db")
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO active_polls VALUES (?,?,?,?,?,?)",
              (poll_id, user_id, correct_id, points, session_type, duel_id))
    conn.commit()
    conn.close()

def get_poll(poll_id):
    conn = sqlite3.connect("quiz.db")
    c = conn.cursor()
    c.execute("SELECT * FROM active_polls WHERE poll_id=?", (poll_id,))
    r = c.fetchone()
    conn.close()
    if r:
        return {"poll_id":r[0],"user_id":r[1],"correct_id":r[2],"points":r[3],"type":r[4],"duel_id":r[5]}
    return None

def get_duel(duel_id):
    conn = sqlite3.connect("quiz.db")
    c = conn.cursor()
    c.execute("SELECT * FROM duels WHERE duel_id=?", (duel_id,))
    r = c.fetchone()
    conn.close()
    if r:
        return {"duel_id":r[0],"p1":r[1],"p2":r[2],"level":r[3],
                "p1s":r[4],"p2s":r[5],"p1i":r[6],"p2i":r[7],
                "p1d":r[8],"p2d":r[9],"questions":json.loads(r[10]),"status":r[11]}
    return None

def update_duel(duel_id, **kwargs):
    conn = sqlite3.connect("quiz.db")
    c = conn.cursor()
    sets = ", ".join(f"{k}=?" for k in kwargs)
    c.execute(f"UPDATE duels SET {sets} WHERE duel_id=?", list(kwargs.values())+[duel_id])
    conn.commit()
    conn.close()

# ─────────────────────────────────────────
# ДАННЫЕ
# ─────────────────────────────────────────
QUESTIONS = {
    "padawan": [
        {"q":"Какого цвета световой меч у Йоды?","o":["Зелёный","Синий","Красный","Фиолетовый"],"a":0,"p":10},
        {"q":"Кто сказал 'Я — твой отец'?","o":["Палпатин","Дарт Мол","Дарт Вейдер","Граф Дуку"],"a":2,"p":10},
        {"q":"На какой планете вырос Люк?","o":["Корусант","Татуин","Набу","Эндор"],"a":1,"p":10},
        {"q":"Кто пилот Сокола Тысячелетия?","o":["Люк","Лэндо","Хан Соло","Чубакка"],"a":2,"p":10},
        {"q":"Какое оружие у джедаев?","o":["Бластер","Световой меч","Арбалет","Копьё"],"a":1,"p":10},
        {"q":"На чьей стороне Дарт Вейдер?","o":["Светлой","Тёмной","Нейтральной","Республики"],"a":1,"p":10},
        {"q":"Кто такой Чубакка?","o":["Дроид","Вуки","Мандалорец","Джедай"],"a":1,"p":10},
        {"q":"Как называется орден рыцарей Силы?","o":["Ситхи","Мандалорцы","Орден джедаев","Республика"],"a":2,"p":10},
        {"q":"Что такое Сила?","o":["Технология","Энергетическое поле","Планета","Корабль"],"a":1,"p":10},
        {"q":"Цвет меча Дарта Вейдера?","o":["Синий","Зелёный","Красный","Фиолетовый"],"a":2,"p":10},
    ],
    "jedi": [
        {"q":"Что такое мидихлорианы?","o":["Оружие ситхов","Микроорганизмы Силы","Вид инопланетян","Двигатель"],"a":1,"p":20},
        {"q":"Кто обучал Оби-Вана?","o":["Йода","Квай-Гон","Мейс Винду","Кит Фисто"],"a":1,"p":20},
        {"q":"Где находится Храм джедаев?","o":["Набу","Дагоба","Корусант","Илум"],"a":2,"p":20},
        {"q":"Какой приказ уничтожил джедаев?","o":["Приказ 65","Приказ 66","Приказ 99","Приказ 77"],"a":1,"p":20},
        {"q":"Цвет меча Мейса Винду?","o":["Синий","Зелёный","Фиолетовый","Красный"],"a":2,"p":20},
        {"q":"Кто такая Асока Тано?","o":["Ситх","Падаван Энакина","Наёмник","Дроид"],"a":1,"p":20},
        {"q":"Что такое Голокрон?","o":["Корабль","Хранилище знаний","Оружие","Планета"],"a":1,"p":20},
        {"q":"Кто убил Квай-Гона?","o":["Вейдер","Дарт Мол","Палпатин","Дуку"],"a":1,"p":20},
        {"q":"Раса Йоды?","o":["Квермийцы","Тогрутане","Не раскрыта","Миральцы"],"a":2,"p":20},
        {"q":"Кто такой граф Дуку?","o":["Джедай","Отступник-ситх","Мандалорец","Дроид"],"a":1,"p":20},
    ],
    "master": [
        {"q":"Мать Энакина Скайуокера?","o":["Падме","Шми","Бару","Лира"],"a":1,"p":40},
        {"q":"Год Битвы при Явине?","o":["0 BBY","4 BBY","19 BBY","32 BBY"],"a":0,"p":40},
        {"q":"Кто разрушил правило двух ситхов?","o":["Дарт Бейн","Дарт Плэгас","Тенебрус","Сидиус"],"a":0,"p":40},
        {"q":"Мандалорский кодекс чести?","o":["Дин Джарин","Резол-наре","Бескар","Ковата"],"a":1,"p":40},
        {"q":"Кто создал армию клонов?","o":["Тиранус","Джанго Фетт","Сайфо-Диас","Камино"],"a":2,"p":40},
        {"q":"Планета скрытия Йоды после Приказа 66?","o":["Хот","Дагоба","Эндор","Набу"],"a":1,"p":40},
        {"q":"Что такое Дарксейбер?","o":["Красный меч","Чёрный меч","Меч Бейна","Артефакт Йоды"],"a":1,"p":40},
        {"q":"Кто такая Бо-Катан?","o":["Джедай","Мандалорка","Ситх","Дроид"],"a":1,"p":40},
        {"q":"Кто озвучил Вейдера в оригинале?","o":["Марк Хэмилл","Джеймс Эрл Джонс","Харрисон Форд","Алек Гиннесс"],"a":1,"p":40},
        {"q":"Настоящее имя Палпатина?","o":["Дарт Бейн","Дарт Плэгас","Шив Палпатин","Дарт Сидиус"],"a":2,"p":40},
    ]
}

LEVEL_NAMES = {"padawan":"🟢 Падаван","jedi":"🔵 Рыцарь джедай","master":"🔴 Мастер джедай"}

CARDS = {
    "vader":{"name":"Дарт Вейдер","side":"Тёмная","price":100,"emoji":"🔴","quote":"Я — твой отец."},
    "yoda":{"name":"Йода","side":"Светлая","price":80,"emoji":"🟢","quote":"Делай или не делай."},
    "luke":{"name":"Люк Скайуокер","side":"Светлая","price":80,"emoji":"⚔️","quote":"Я джедай."},
    "obi":{"name":"Оби-Ван Кеноби","side":"Светлая","price":90,"emoji":"🔵","quote":"Да пребудет с тобой Сила."},
    "mando":{"name":"Мандалорец","side":"Нейтральная","price":120,"emoji":"⚙️","quote":"Таков путь."},
    "palp":{"name":"Палпатин","side":"Тёмная","price":150,"emoji":"⚡","quote":"Неограниченная власть!"},
    "maul":{"name":"Дарт Мол","side":"Тёмная","price":110,"emoji":"🖤","quote":"Страдания — пища ситха."},
    "rey":{"name":"Рей","side":"Светлая","price":90,"emoji":"🌟","quote":"Я никто."},
}

def get_rank(score):
    if score < 50:   return "🌱 Новичок"
    if score < 150:  return "⚔️ Падаван"
    if score < 350:  return "🔵 Рыцарь"
    if score < 700:  return "🟣 Мастер"
    return "⭐ Великий магистр"

# ─────────────────────────────────────────
# ОТПРАВКА ОПРОСА
# ─────────────────────────────────────────
async def send_poll(context, chat_id, user_id, question, index, total, level, session_type="quiz", duel_id=None):
    q = question
    msg = await context.bot.send_poll(
        chat_id=chat_id,
        question=f"[{LEVEL_NAMES[level]}] Вопрос {index+1}/{total}\n{q['q']}",
        options=q["o"],
        type=Poll.QUIZ,
        correct_option_id=q["a"],
        is_anonymous=False,
        explanation=f"+{q['p']} монет за правильный ответ 🪙"
    )
    save_poll(msg.poll.id, user_id, q["a"], q["p"], session_type, duel_id)

# ─────────────────────────────────────────
# ХЕНДЛЕРЫ
# ─────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    get_user(user.id, user.username or user.first_name)
    if context.args and context.args[0].startswith("duel_"):
        await join_duel_handler(update, context, context.args[0].replace("duel_",""))
        return
    await show_menu(update.message.reply_text)

async def show_menu(send_func):
    kb = [
        [InlineKeyboardButton("⚔️ Квиз", callback_data="choose_level"),
         InlineKeyboardButton("🤺 Дуэль", callback_data="duel_menu")],
        [InlineKeyboardButton("🛒 Магазин", callback_data="shop"),
         InlineKeyboardButton("🎴 Коллекция", callback_data="collection")],
        [InlineKeyboardButton("🏆 Топ", callback_data="leaderboard"),
         InlineKeyboardButton("👤 Профиль", callback_data="profile")],
    ]
    await send_func(
        "⚔️ Главное меню\nДа прибудет с тобой Сила! ✨",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def btn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = q.data
    user = q.from_user

    if d == "menu":
        kb = [
            [InlineKeyboardButton("⚔️ Квиз", callback_data="choose_level"),
             InlineKeyboardButton("🤺 Дуэль", callback_data="duel_menu")],
            [InlineKeyboardButton("🛒 Магазин", callback_data="shop"),
             InlineKeyboardButton("🎴 Коллекция", callback_data="collection")],
            [InlineKeyboardButton("🏆 Топ", callback_data="leaderboard"),
             InlineKeyboardButton("👤 Профиль", callback_data="profile")],
        ]
        await q.edit_message_text("⚔️ Главное меню\nДа прибудет с тобой Сила! ✨",
                                   reply_markup=InlineKeyboardMarkup(kb))

    elif d == "choose_level":
        kb = [
            [InlineKeyboardButton("🟢 Падаван — 10 монет/вопрос", callback_data="quiz_padawan")],
            [InlineKeyboardButton("🔵 Рыцарь джедай — 20 монет", callback_data="quiz_jedi")],
            [InlineKeyboardButton("🔴 Мастер джедай — 40 монет", callback_data="quiz_master")],
            [InlineKeyboardButton("◀️ Назад", callback_data="menu")],
        ]
        await q.edit_message_text("Выбери уровень — 10 вопросов:", reply_markup=InlineKeyboardMarkup(kb))

    elif d.startswith("quiz_"):
        level = d.replace("quiz_", "")
        questions = random.sample(QUESTIONS[level], 10)
        save_session(user.id, level, 0, 0, questions)
        await q.edit_message_text(f"Начинаем! {LEVEL_NAMES[level]}\n10 вопросов. Удачи! 🚀")
        await send_poll(context, q.message.chat_id, user.id, questions[0], 0, 10, level)

    # ── СЛЕДУЮЩИЙ ВОПРОС КВИЗА ──
    elif d == "next_question":
        session = get_session(user.id)
        if not session:
            await q.edit_message_text("Сессия не найдена. Начни новый квиз через /start")
            return
        index = session["index"]
        questions = session["questions"]
        level = session["level"]
        if index >= len(questions):
            del_session(user.id)
            await q.edit_message_text(
                f"🏁 Квиз завершён!\nЗаработано: {session['coins']} монет 🪙",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Меню", callback_data="menu")]])
            )
        else:
            await q.edit_message_text(f"Вопрос {index+1}/10...")
            await send_poll(context, q.message.chat_id, user.id, questions[index], index, 10, level)

    # ── СЛЕДУЮЩИЙ ВОПРОС ДУЭЛИ ──
    elif d.startswith("duel_next_"):
        duel_id = d.replace("duel_next_", "")
        duel = get_duel(duel_id)
        if not duel:
            return
        is_p1 = user.id == duel["p1"]
        index = duel["p1i"] if is_p1 else duel["p2i"]
        questions = duel["questions"]
        if index < len(questions):
            await q.edit_message_text(f"Вопрос {index+1}/5...")
            await send_poll(context, q.message.chat_id, user.id,
                           questions[index], index, 5, duel["level"], "duel", duel_id)

    elif d == "duel_menu":
        kb = [
            [InlineKeyboardButton("⚔️ Создать дуэль", callback_data="duel_create")],
            [InlineKeyboardButton("🔗 Ввести код", callback_data="duel_code")],
            [InlineKeyboardButton("◀️ Назад", callback_data="menu")],
        ]
        await q.edit_message_text(
            "🤺 Дуэль с другом\n\nСоздай дуэль, отправь другу код — кто наберёт больше очков, тот победит!\nПобедитель получает бонусные монеты 🪙",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    elif d == "duel_create":
        kb = [
            [InlineKeyboardButton("🟢 Падаван", callback_data="duel_lvl_padawan")],
            [InlineKeyboardButton("🔵 Рыцарь", callback_data="duel_lvl_jedi")],
            [InlineKeyboardButton("🔴 Мастер", callback_data="duel_lvl_master")],
        ]
        await q.edit_message_text("Выбери уровень дуэли:", reply_markup=InlineKeyboardMarkup(kb))

    elif d.startswith("duel_lvl_"):
        level = d.replace("duel_lvl_", "")
        duel_id = str(uuid.uuid4())[:8].upper()
        questions = random.sample(QUESTIONS[level], 5)
        conn = sqlite3.connect("quiz.db")
        c = conn.cursor()
        c.execute("INSERT INTO duels VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  (duel_id, user.id, None, level, 0, 0, 0, 0, 0, 0, json.dumps(questions), "waiting"))
        conn.commit()
        conn.close()
        bot_info = await context.bot.get_me()
        link = f"https://t.me/{bot_info.username}?start=duel_{duel_id}"
        await q.edit_message_text(
            f"⚔️ Дуэль создана!\n\nУровень: {LEVEL_NAMES[level]}\nКод: {duel_id}\n\nОтправь другу ссылку:\n{link}\n\nИли пусть напишет: /join {duel_id}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Меню", callback_data="menu")]])
        )

    elif d == "duel_code":
        await q.edit_message_text(
            "Введи команду:\n/join КОД",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="duel_menu")]])
        )

    elif d == "shop":
        row = get_user(user.id)
        coins = row[3]
        owned = get_cards(user.id)
        kb = []
        for cid, card in CARDS.items():
            if cid in owned:
                kb.append([InlineKeyboardButton(f"✅ {card['emoji']} {card['name']}", callback_data=f"card_{cid}")])
            else:
                kb.append([InlineKeyboardButton(f"{card['emoji']} {card['name']} — {card['price']} монет", callback_data=f"buy_{cid}")])
        kb.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
        await q.edit_message_text(f"🛒 Магазин карточек\nУ тебя: {coins} монет 🪙",
                                   reply_markup=InlineKeyboardMarkup(kb))

    elif d.startswith("buy_"):
        cid = d.replace("buy_","")
        card = CARDS[cid]
        if cid in get_cards(user.id):
            await q.answer("Уже есть!", show_alert=True)
            return
        if spend_coins(user.id, card["price"]):
            add_card(user.id, cid)
            await q.answer(f"✅ {card['name']} добавлена в коллекцию!", show_alert=True)
        else:
            await q.answer("❌ Недостаточно монет!", show_alert=True)
        row = get_user(user.id)
        coins = row[3]
        owned = get_cards(user.id)
        kb = []
        for c_id, c in CARDS.items():
            if c_id in owned:
                kb.append([InlineKeyboardButton(f"✅ {c['emoji']} {c['name']}", callback_data=f"card_{c_id}")])
            else:
                kb.append([InlineKeyboardButton(f"{c['emoji']} {c['name']} — {c['price']} монет", callback_data=f"buy_{c_id}")])
        kb.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
        await q.edit_message_text(f"🛒 Магазин карточек\nУ тебя: {coins} монет 🪙",
                                   reply_markup=InlineKeyboardMarkup(kb))

    elif d.startswith("card_"):
        cid = d.replace("card_","")
        card = CARDS[cid]
        await q.edit_message_text(
            f"{card['emoji']} {card['name']}\n\nСторона: {card['side']}\n\n{card['quote']}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="collection")]])
        )

    elif d == "collection":
        owned = get_cards(user.id)
        if not owned:
            await q.edit_message_text(
                "🎴 Коллекция пуста\n\nЗарабатывай монеты и покупай карточки в магазине!",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🛒 Магазин", callback_data="shop")],
                    [InlineKeyboardButton("◀️ Меню", callback_data="menu")]
                ])
            )
        else:
            kb = [[InlineKeyboardButton(f"{CARDS[cid]['emoji']} {CARDS[cid]['name']}", callback_data=f"card_{cid}")] for cid in owned]
            kb.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
            await q.edit_message_text(f"🎴 Моя коллекция ({len(owned)}/{len(CARDS)})",
                                       reply_markup=InlineKeyboardMarkup(kb))

    elif d == "leaderboard":
        rows = get_leaderboard()
        medals = ["🥇","🥈","🥉"]+["▫️"]*7
        text = "🏆 Таблица лидеров\n\n"
        for i,(name,score,cor,tot) in enumerate(rows):
            acc = f"{round(cor/tot*100)}%" if tot>0 else "—"
            text += f"{medals[i]} {name} — {score} монет ({acc})\n"
        if not rows: text += "Пока никого нет!"
        await q.edit_message_text(text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Меню", callback_data="menu")]]))

    elif d == "profile":
        row = get_user(user.id)
        uid, name, score, coins, streak, lp, total, correct = row
        acc = f"{round(correct/total*100)}%" if total>0 else "—"
        owned = get_cards(user.id)
        await q.edit_message_text(
            f"👤 {name}\n\n"
            f"🎖 {get_rank(score)}\n"
            f"⭐ Очки: {score}\n"
            f"🪙 Монеты: {coins}\n"
            f"📊 Точность: {acc} ({correct}/{total})\n"
            f"🔥 Стрик: {streak} дн.\n"
            f"🎴 Карточки: {len(owned)}/{len(CARDS)}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⚔️ Квиз", callback_data="choose_level")],
                [InlineKeyboardButton("◀️ Меню", callback_data="menu")],
            ])
        )

# ─────────────────────────────────────────
# ОБРАБОТКА ОТВЕТА НА ОПРОС
# ─────────────────────────────────────────
async def poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer = update.poll_answer
    poll_id = answer.poll_id
    user_id = answer.user.id
    chosen = answer.option_ids[0] if answer.option_ids else -1

    poll = get_poll(poll_id)
    if not poll:
        return

    is_correct = chosen == poll["correct_id"]
    points = poll["points"] if is_correct else 0

    if poll["type"] == "quiz":
        session = get_session(user_id)
        if not session:
            return
        add_result(user_id, points, is_correct)
        new_coins = session["coins"] + points
        new_index = session["index"] + 1
        save_session(user_id, session["level"], new_index, new_coins, session["questions"])

        if is_correct:
            result = f"✅ Верно! +{points} монет 🪙"
        else:
            q = session["questions"][session["index"]]
            result = f"❌ Неверно. Правильный ответ: {q['o'][q['a']]}"

        if new_index >= len(session["questions"]):
            kb = [[InlineKeyboardButton("🔄 Ещё раз", callback_data="choose_level"),
                   InlineKeyboardButton("🏠 Меню", callback_data="menu")]]
            text = f"{result}\n\n🏁 Квиз завершён!\nЗаработано: {new_coins} монет 🪙"
        if new_index < len(session["questions"]):
            try:
                await context.bot.send_message(user_id, result)
            except Exception as e:
                logging.error(f"poll_answer error: {e}")
            try:
                await send_poll(context, user_id, user_id,
                               session["questions"][new_index], new_index,
                               len(session["questions"]), session["level"])
            except Exception as e:
                logging.error(f"send next poll error: {e}")
            return

        try:
            await context.bot.send_message(user_id, text, reply_markup=InlineKeyboardMarkup(kb))
        except Exception as e:
            logging.error(f"poll_answer error: {e}")

    elif poll["type"] == "duel":
        duel_id = poll["duel_id"]
        duel = get_duel(duel_id)
        if not duel:
            return
        add_result(user_id, points, is_correct)
        is_p1 = user_id == duel["p1"]
        cur_score = (duel["p1s"] if is_p1 else duel["p2s"]) + points
        new_index = (duel["p1i"] if is_p1 else duel["p2i"]) + 1
        done = 1 if new_index >= len(duel["questions"]) else 0

        if is_p1:
            update_duel(duel_id, p1s=cur_score, p1i=new_index, p1d=done)
        else:
            update_duel(duel_id, p2s=cur_score, p2i=new_index, p2d=done)

        duel = get_duel(duel_id)

        if is_correct:
            result = f"✅ Верно! +{points} монет 🪙"
        else:
            q = duel["questions"][new_index-1]
            result = f"❌ Неверно. Правильный: {q['o'][q['a']]}"

        if done:
            if duel["p1d"] and duel["p2d"]:
                # Оба закончили
                p1s, p2s = duel["p1s"], duel["p2s"]
                try:
                    p1_chat = await context.bot.get_chat(duel["p1"])
                    p2_chat = await context.bot.get_chat(duel["p2"])
                    p1_name = p1_chat.first_name
                    p2_name = p2_chat.first_name
                except:
                    p1_name, p2_name = "Игрок 1", "Игрок 2"

                if p1s > p2s:
                    res = f"🏆 Победил {p1_name}!\n{p1_name}: {p1s} — {p2s} :{p2_name}"
                    add_result(duel["p1"], 50, True)
                elif p2s > p1s:
                    res = f"🏆 Победил {p2_name}!\n{p1_name}: {p1s} — {p2s} :{p2_name}"
                    add_result(duel["p2"], 50, True)
                else:
                    res = f"🤝 Ничья!\n{p1_name}: {p1s} — {p2s} :{p2_name}"

                kb = [[InlineKeyboardButton("🏠 Меню", callback_data="menu")]]
                for pid in [duel["p1"], duel["p2"]]:
                    try:
                        await context.bot.send_message(pid, f"⚔️ Дуэль завершена!\n\n{res}", reply_markup=InlineKeyboardMarkup(kb))
                    except: pass
            else:
                try:
                    await context.bot.send_message(user_id, f"{result}\n\nТы закончил! Ждём соперника... ⏳")
                except: pass
        else:
            try:
                await context.bot.send_message(user_id, result)
            except: pass
            try:
                await send_poll(context, user_id, user_id,
                               duel["questions"][new_index], new_index, len(duel["questions"]),
                               duel["level"], "duel", duel_id)
            except: pass

# ─────────────────────────────────────────
# ПРИСОЕДИНЕНИЕ К ДУЭЛИ
# ─────────────────────────────────────────
async def join_duel_handler(update, context, duel_id):
    user = update.effective_user
    get_user(user.id, user.username or user.first_name)
    duel = get_duel(duel_id)

    if not duel:
        await update.message.reply_text("❌ Дуэль не найдена. Проверь код.")
        return
    if duel["status"] != "waiting":
        await update.message.reply_text("❌ Дуэль уже началась.")
        return
    if duel["p1"] == user.id:
        await update.message.reply_text("❌ Нельзя присоединиться к своей дуэли!")
        return

    update_duel(duel_id, p2_id=user.id, status="active")
    duel = get_duel(duel_id)
    level = duel["level"]
    questions = duel["questions"]

    try:
        p1_name = (await context.bot.get_chat(duel["p1"])).first_name
    except:
        p1_name = "соперник"

    # Отправить первый вопрос обоим
    kb = [[InlineKeyboardButton("Следующий вопрос 1/5 ➡️", callback_data=f"duel_next_{duel_id}")]]

    await context.bot.send_message(duel["p1"],
        f"⚔️ {user.first_name} принял вызов! Начинаем!\nУровень: {LEVEL_NAMES[level]}")
    await send_poll(context, duel["p1"], duel["p1"], questions[0], 0, 5, level, "duel", duel_id)

    await update.message.reply_text(
        f"⚔️ Дуэль с {p1_name}! Начинаем!\nУровень: {LEVEL_NAMES[level]}")
    await send_poll(context, update.effective_chat.id, user.id, questions[0], 0, 5, level, "duel", duel_id)

async def join_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Укажи код: /join КОД")
        return
    await join_duel_handler(update, context, context.args[0].upper())

def main():
    init_db()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("join", join_cmd))
    app.add_handler(CallbackQueryHandler(btn))
    app.add_handler(PollAnswerHandler(poll_answer))
    print("✅ TheForceQuizBot запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()