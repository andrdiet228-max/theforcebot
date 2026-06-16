import logging
import random
import sqlite3
import uuid
import json
import os
import time
from datetime import date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Poll
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, PollAnswerHandler, MessageHandler, filters
)

TOKEN = os.environ.get("TOKEN")
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
    for col in ["session_type TEXT DEFAULT 'quiz'", "duel_id TEXT DEFAULT NULL"]:
        try:
            c.execute(f"ALTER TABLE active_polls ADD COLUMN {col}")
        except: pass
    c.execute("""CREATE TABLE IF NOT EXISTS user_cards (
        user_id INTEGER, card_id TEXT,
        PRIMARY KEY (user_id, card_id)
    )""")
    # Дуэли — новая схема с поддержкой групп
    c.execute("""CREATE TABLE IF NOT EXISTS duels (
        duel_id TEXT PRIMARY KEY,
        p1_id INTEGER, p2_id INTEGER, level TEXT,
        p1_score INTEGER DEFAULT 0, p2_score INTEGER DEFAULT 0,
        p1_index INTEGER DEFAULT 0, p2_index INTEGER DEFAULT 0,
        p1_done INTEGER DEFAULT 0, p2_done INTEGER DEFAULT 0,
        questions TEXT, status TEXT DEFAULT 'waiting',
        chat_id INTEGER DEFAULT NULL,
        current_q_msg_id INTEGER DEFAULT NULL,
        current_q_index INTEGER DEFAULT 0,
        p1_answered INTEGER DEFAULT 0, p2_answered INTEGER DEFAULT 0
    )""")
    for col_def in [
        "chat_id INTEGER DEFAULT NULL",
        "current_q_msg_id INTEGER DEFAULT NULL",
        "current_q_index INTEGER DEFAULT 0",
        "p1_answered INTEGER DEFAULT 0",
        "p2_answered INTEGER DEFAULT 0"
    ]:
        try:
            c.execute(f"ALTER TABLE duels ADD COLUMN {col_def}")
        except: pass
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
        c.execute("UPDATE users SET total=total+1, streak=0, last_play=? WHERE user_id=?",
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
    if not r:
        return None
    return {
        "duel_id":r[0],"p1":r[1],"p2":r[2],"level":r[3],
        "p1s":r[4],"p2s":r[5],"p1i":r[6],"p2i":r[7],
        "p1d":r[8],"p2d":r[9],"questions":json.loads(r[10]),"status":r[11],
        "chat_id":r[12],"cur_msg":r[13],"cur_qi":r[14],
        "p1a":r[15],"p2a":r[16]
    }

def update_duel(duel_id, **kwargs):
    col_map = {
        "p2_id":"p2_id","p1s":"p1_score","p2s":"p2_score",
        "p1i":"p1_index","p2i":"p2_index",
        "p1d":"p1_done","p2d":"p2_done","status":"status",
        "chat_id":"chat_id","cur_msg":"current_q_msg_id",
        "cur_qi":"current_q_index","p1a":"p1_answered","p2a":"p2_answered"
    }
    conn = sqlite3.connect("quiz.db")
    c = conn.cursor()
    mapped = {col_map.get(k,k): v for k,v in kwargs.items()}
    sets = ", ".join(f"{k}=?" for k in mapped)
    c.execute(f"UPDATE duels SET {sets} WHERE duel_id=?", list(mapped.values())+[duel_id])
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
        {"q":"Кто создал правило двух ситхов?","o":["Дарт Бейн","Дарт Плэгас","Тенебрус","Сидиус"],"a":0,"p":40},
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
    # ⚪ ОБЫЧНЫЕ (Шанс 50%)
    "clone":{"name":"Клон-солдат","side":"Республика","rarity":"common","emoji":"⚪","img":"https://example.com/clone.jpg","quote":"За Республику!"},
    "droid":{"name":"Боевой дроид","side":"Торговая федерация","rarity":"common","emoji":"⚪","img":"https://example.com/droid.jpg","quote":"Роже, роже!"},
    "stormtrooper":{"name":"Штурмовик","side":"Империя","rarity":"common","emoji":"⚪","img":"https://example.com/storm.jpg","quote":"Переоденьтесь и идите за ними!"},
    
    # 🔹 РЕДКИЕ (Шанс 30%)
    "maul":{"name":"Дарт Мол","side":"Тёмная","rarity":"rare","emoji":"🔹","img":"https://example.com/maul.jpg","quote":"Страдания — пища ситха."},
    "rey":{"name":"Рей","side":"Светлая","rarity":"rare","emoji":"🔹","img":"https://example.com/rey.jpg","quote":"Я никто."},
    "mando":{"name":"Мандалорец","side":"Нейтральная","rarity":"rare","emoji":"🔹","img":"https://example.com/mando.jpg","quote":"Таков путь."},
    
    # 🟣 ЭПИЧЕСКИЕ (Шанс 15%)
    "yoda":{"name":"Йода","side":"Светлая","rarity":"epic","emoji":"🟣","img":"https://example.com/yoda.jpg","quote":"Делай или не делай."},
    "obi":{"name":"Оби-Ван Кеноби","side":"Светлая","rarity":"epic","emoji":"🟣","img":"https://example.com/obi.jpg","quote":"Да прибудет с тобой Сила."},
    "luke":{"name":"Люк Скайуокер","side":"Светлая","rarity":"epic","emoji":"🟣","img":"https://example.com/luke.jpg","quote":"Я джедай."},
    
    # 🟡 ЛЕГЕНДАРНЫЕ (Шанс 5%)
    "vader":{"name":"Дарт Вейдер","side":"Тёмная","rarity":"legendary","emoji":"🟡","img":"https://example.com/vader.jpg","quote":"Я — твой отец."},
    "palp":{"name":"Палпатин","side":"Тёмная","rarity":"legendary","emoji":"🟡","img":"https://example.com/palp.jpg","quote":"Неограниченная власть!"},
}

# Шансы выпадения (в сумме должно быть 100)
PACK_CHANCES = {
    "common": 50,
    "rare": 30,
    "epic": 15,
    "legendary": 5
}

def get_rank(score):
    if score < 50:   return "🌱 Новичок"
    if score < 150:  return "⚔️ Падаван"
    if score < 350:  return "🔵 Рыцарь"
    if score < 700:  return "🟣 Мастер"
    return "⭐ Великий магистр"

# ─────────────────────────────────────────
# ОТПРАВКА ОПРОСА (для личного квиза)
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
        explanation=f"+{q['p']} монет за правильный ответ"
    )
    save_poll(msg.poll.id, user_id, q["a"], q["p"], session_type, duel_id)

# ─────────────────────────────────────────
# ОТПРАВКА ВОПРОСА ДУЭЛИ (кнопки для групп)
# ─────────────────────────────────────────
async def send_duel_question(context, chat_id, duel_id, q_index, duel):
    q = duel["questions"][q_index]
    total = len(duel["questions"])

    try:
        p1_name = (await context.bot.get_chat(duel["p1"])).first_name
        p2_name = (await context.bot.get_chat(duel["p2"])).first_name
    except:
        p1_name, p2_name = "Игрок 1", "Игрок 2"

    p1s = duel["p1s"]
    p2s = duel["p2s"]

    text = (
        f"⚔️ Дуэль: {p1_name} {p1s} — {p2s} {p2_name}\n"
        f"[{LEVEL_NAMES[duel['level']]}] Вопрос {q_index+1}/{total}\n\n"
        f"❓ {q['q']}"
    )

    kb = []
    for i, opt in enumerate(q["o"]):
        kb.append([InlineKeyboardButton(opt, callback_data=f"da_{duel_id}_{q_index}_{i}")])

    msg = await context.bot.send_message(chat_id, text, reply_markup=InlineKeyboardMarkup(kb))
    update_duel(duel_id, cur_msg=msg.message_id, cur_qi=q_index, p1a=0, p2a=0)
    return msg

# ─────────────────────────────────────────
# ХЕНДЛЕРЫ
# ─────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    get_user(user.id, user.username or user.first_name)
    
    if context.args and context.args[0].startswith("duel_"):
        await join_duel_handler(update, context, context.args[0].replace("duel_",""))
        return

    kb = [
        [InlineKeyboardButton("⚔️ Квиз", callback_data="choose_level"),
         InlineKeyboardButton("🤺 Дуэль", callback_data="duel_menu")],
        [InlineKeyboardButton("🛒 Магазин", callback_data="shop"),
         InlineKeyboardButton("🎴 Коллекция", callback_data="collection")],
        [InlineKeyboardButton("🏆 Топ", callback_data="leaderboard"),
         InlineKeyboardButton("👤 Профиль", callback_data="profile")],
    ]
    
    await update.message.reply_text(
        "⚔️ Главное меню\nДа прибудет с тобой Сила! ✨",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def btn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = q.data
    user = q.from_user

    # ── ОТВЕТ НА ВОПРОС ДУЭЛИ В ГРУППЕ ──
    if d.startswith("da_"):
        parts = d.split("_")
        duel_id = parts[1]
        q_index = int(parts[2])
        chosen = int(parts[3])

        duel = get_duel(duel_id)
        if not duel or duel["status"] != "active":
            await q.answer("Дуэль не найдена или уже завершена.", show_alert=True)
            return

        if user.id not in [duel["p1"], duel["p2"]]:
            await q.answer("Ты не участник этой дуэли!", show_alert=True)
            return

        if q_index != duel["cur_qi"]:
            await q.answer("Этот вопрос уже закрыт.", show_alert=True)
            return

        is_p1 = user.id == duel["p1"]

        if is_p1 and duel["p1a"]:
            await q.answer("Ты уже ответил на этот вопрос!", show_alert=True)
            return
        if not is_p1 and duel["p2a"]:
            await q.answer("Ты уже ответил на этот вопрос!", show_alert=True)
            return

        question = duel["questions"][q_index]
        is_correct = chosen == question["a"]
        points = question["p"] if is_correct else 0

        add_result(user.id, points, is_correct)

        if is_p1:
            update_duel(duel_id, p1s=duel["p1s"]+points, p1a=1)
            if is_correct:
                await q.answer(f"✅ Верно! +{points} монет", show_alert=True)
            else:
                await q.answer(f"❌ Неверно. Правильный: {question['o'][question['a']]}", show_alert=True)
        else:
            update_duel(duel_id, p2s=duel["p2s"]+points, p2a=1)
            if is_correct:
                await q.answer(f"✅ Верно! +{points} монет", show_alert=True)
            else:
                await q.answer(f"❌ Неверно. Правильный: {question['o'][question['a']]}", show_alert=True)

        duel = get_duel(duel_id)
        both_answered = duel["p1a"] and duel["p2a"]

        if both_answered:
            next_index = q_index + 1
            if next_index < len(duel["questions"]):
                try:
                    p1_name = (await context.bot.get_chat(duel["p1"])).first_name
                    p2_name = (await context.bot.get_chat(duel["p2"])).first_name
                except:
                    p1_name, p2_name = "Игрок 1", "Игрок 2"

                update_duel(duel_id, p1i=next_index, p2i=next_index)
                duel = get_duel(duel_id)

                try:
                    await context.bot.edit_message_reply_markup(
                        chat_id=duel["chat_id"],
                        message_id=duel["cur_msg"],
                        reply_markup=None
                    )
                except: pass

                await send_duel_question(context, duel["chat_id"], duel_id, next_index, duel)
            else:
                update_duel(duel_id, p1d=1, p2d=1, status="finished")
                duel = get_duel(duel_id)

                try:
                    p1_name = (await context.bot.get_chat(duel["p1"])).first_name
                    p2_name = (await context.bot.get_chat(duel["p2"])).first_name
                except:
                    p1_name, p2_name = "Игрок 1", "Игрок 2"

                p1s, p2s = duel["p1s"], duel["p2s"]

                if p1s > p2s:
                    res = f"🏆 Победил {p1_name}!\n{p1_name}: {p1s} — {p2_name}: {p2s}"
                    add_result(duel["p1"], 50, True)
                elif p2s > p1s:
                    res = f"🏆 Победил {p2_name}!\n{p1_name}: {p1s} — {p2_name}: {p2s}"
                    add_result(duel["p2"], 50, True)
                else:
                    res = f"🤝 Ничья!\n{p1_name}: {p1s} — {p2_name}: {p2s}"

                try:
                    await context.bot.edit_message_reply_markup(
                        chat_id=duel["chat_id"],
                        message_id=duel["cur_msg"],
                        reply_markup=None
                    )
                except: pass

                await context.bot.send_message(
                    duel["chat_id"],
                    f"⚔️ Дуэль завершена!\n\n{res}\n\nПобедитель получает +50 монет 🪙",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Меню", callback_data="menu")]])
                )

    elif d == "menu":
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

    elif d == "duel_menu":
        kb = [
            [InlineKeyboardButton("⚔️ Создать дуэль", callback_data="duel_create")],
            [InlineKeyboardButton("🔗 Ввести код", callback_data="duel_code")],
            [InlineKeyboardButton("◀️ Назад", callback_data="menu")],
        ]
        await q.edit_message_text(
            "🤺 Дуэль с другом\n\nМожно играть прямо в беседе! Создай дуэль, отправь другу код — кто наберёт больше монет, тот победил!",
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
        c.execute(
            "INSERT INTO duels (duel_id,p1_id,p2_id,level,p1_score,p2_score,p1_index,p2_index,p1_done,p2_done,questions,status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (duel_id, user.id, None, level, 0, 0, 0, 0, 0, 0, json.dumps(questions), "waiting")
        )
        conn.commit()
        conn.close()
        bot_info = await context.bot.get_me()
        link = f"https://t.me/{bot_info.username}?start=duel_{duel_id}"
        await q.edit_message_text(
            f"⚔️ Дуэль создана!\n\nУровень: {LEVEL_NAMES[level]}\nКод: {duel_id}\n\nОтправь другу ссылку или код:\n{link}\n\nИли пусть нажмёт /join {duel_id}",
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
        kb = [
            [InlineKeyboardButton("📦 Открыть пак (50 монет)", callback_data="open_pack")],
            [InlineKeyboardButton("◀️ Меню", callback_data="menu")]
        ]
        await q.edit_message_text(
            f"🛒 Магазин карточек\n\nУ тебя: {coins} монет 🪙\n\nПокупай паки и собирай коллекцию!\n⚪ Обычные - 50%\n🔹 Редкие - 30%\n🟣 Эпические - 15%\n🟡 Легендарные - 5%",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    elif d == "open_pack":
        pack_price = 50
        if not spend_coins(user.id, pack_price):
            await q.answer("❌ Недостаточно монет для пака!", show_alert=True)
            return

        roll = random.randint(1, 100)
        current_chance = 0
        chosen_rarity = "common"
        
        for rarity, chance in PACK_CHANCES.items():
            current_chance += chance
            if roll <= current_chance:
                chosen_rarity = rarity
                break

        possible_cards = [cid for cid, c in CARDS.items() if c["rarity"] == chosen_rarity]
        won_card_id = random.choice(possible_cards)
        card = CARDS[won_card_id]

        is_new = won_card_id not in get_cards(user.id)
        add_card(user.id, won_card_id)
        
        bonus = 0
        if not is_new:
            bonus = pack_price // 2
            add_result(user.id, bonus, False)

        rarity_names = {"common": "Обычная", "rare": "Редкая", "epic": "Эпическая", "legendary": "Легендарная"}
        text = (
            f"🎉 Выпала карточка!\n\n"
            f"{card['emoji']} {card['name']}\n"
            f"Редкость: {rarity_names[card['rarity']]}\n"
            f"Сторона: {card['side']}\n\n"
            f"«{card['quote']}»"
        )
        if not is_new:
            text += f"\n\n⚡ Дубль! Возвращено {bonus} монет."

        kb = [[InlineKeyboardButton("📦 Ещё пак", callback_data="open_pack")],
              [InlineKeyboardButton("🎴 Коллекция", callback_data="collection")],
              [InlineKeyboardButton("◀️ В магазин", callback_data="shop")]]

        try:
            await context.bot.send_photo(
                chat_id=q.message.chat_id, 
                photo=card["img"], 
                caption=text, 
                reply_markup=InlineKeyboardMarkup(kb)
            )
            await q.message.delete()
        except Exception as e:
            await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

    elif d == "collection":
        owned = get_cards(user.id)
        if not owned:
            await q.edit_message_text(
                "🎴 Коллекция пуста\n\nОткрывай паки в магазине!",
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

    elif d.startswith("card_"):
        cid = d.replace("card_","")
        card = CARDS[cid]
        await q.edit_message_text(
            f"{card['emoji']} {card['name']}\n\nСторона: {card['side']}\n\n{card['quote']}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="collection")]]),
        )

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
# ОБРАБОТКА ОТВЕТА НА ОПРОС (личный квиз)
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

    session = get_session(user_id)
    if not session:
        return

    add_result(user_id, points, is_correct)
    new_coins = session["coins"] + points
    new_index = session["index"] + 1
    save_session(user_id, session["level"], new_index, new_coins, session["questions"])

    if is_correct:
        result_text = f"✅ Верно! +{points} монет 🪙"
    else:
        q_data = session["questions"][session["index"]]
        result_text = f"❌ Неверно. Правильный ответ: {q_data['o'][q_data['a']]}"

    if new_index < len(session["questions"]):
        try:
            await context.bot.send_message(user_id, result_text)
        except Exception as e:
            logging.error(f"send result error: {e}")
        try:
            await send_poll(context, user_id, user_id,
                            session["questions"][new_index], new_index,
                            len(session["questions"]), session["level"])
        except Exception as e:
            logging.error(f"send next poll error: {e}")
    else:
        del_session(user_id)
        kb = [[InlineKeyboardButton("🔄 Ещё раз", callback_data="choose_level"),
               InlineKeyboardButton("🏠 Меню", callback_data="menu")]]
        try:
            await context.bot.send_message(
                user_id,
                f"{result_text}\n\n🏁 Квиз завершён!\nЗаработано: {new_coins} монет 🪙",
                reply_markup=InlineKeyboardMarkup(kb)
            )
        except Exception as e:
            logging.error(f"send final error: {e}")

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

    chat_id = update.effective_chat.id
    update_duel(duel_id, p2_id=user.id, status="active", chat_id=chat_id)
    duel = get_duel(duel_id)

    try:
        p1_name = (await context.bot.get_chat(duel["p1"])).first_name
    except:
        p1_name = "соперник"

    await update.message.reply_text(
        f"⚔️ {user.first_name} принял вызов {p1_name}!\n"
        f"Уровень: {LEVEL_NAMES[duel['level']]}\n"
        f"5 вопросов — отвечайте оба на каждый!\n\nДа прибудет с вами Сила! ✨"
    )

    await send_duel_question(context, chat_id, duel_id, 0, duel)

async def join_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Укажи код: /join КОД")
        return
    await join_duel_handler(update, context, context.args[0].upper())

async def get_file_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        file_id = update.photo[-1].file_id
        await update.message.reply_text(f"file_id:\n`{file_id}`", parse_mode="Markdown")

def main():
    time.sleep(5)
    init_db()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("join", join_cmd))
    app.add_handler(CallbackQueryHandler(btn))
    app.add_handler(PollAnswerHandler(poll_answer))
    app.add_handler(MessageHandler(filters.PHOTO, get_file_id))
    print("✅ TheForceQuizBot запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()