import logging
import random
import sqlite3
import uuid
import json
import os
from datetime import date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes
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
    # Миграция: добавить колонки если их нет
    for col, default in [("coins", "0"), ("total", "0"), ("correct", "0")]:
        try:
            c.execute(f"ALTER TABLE users ADD COLUMN {col} INTEGER DEFAULT {default}")
        except:
            pass
    c.execute("""CREATE TABLE IF NOT EXISTS sessions (
        user_id INTEGER PRIMARY KEY,
        level TEXT, index_ INTEGER DEFAULT 0,
        coins INTEGER DEFAULT 0, questions TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS user_cards (
        user_id INTEGER, card_id TEXT,
        PRIMARY KEY (user_id, card_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS duels (
        duel_id TEXT PRIMARY KEY,
        p1_id INTEGER, p2_id INTEGER,
        level TEXT,
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
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
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
        c.execute("UPDATE users SET coins=coins+?, score=score+?, streak=?, last_play=?, total=total+1, correct=correct+1 WHERE user_id=?",
                  (coins, coins, streak, today, user_id))
    else:
        c.execute("UPDATE users SET total=total+1, streak=1, last_play=? WHERE user_id=?", (today, user_id))
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
        return {"level": r[1], "index": r[2], "coins": r[3], "questions": json.loads(r[4])}
    return None

def del_session(user_id):
    conn = sqlite3.connect("quiz.db")
    c = conn.cursor()
    c.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

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
    c.execute(f"UPDATE duels SET {sets} WHERE duel_id=?", list(kwargs.values()) + [duel_id])
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
        {"q":"Мандалорский кодекс?","o":["Дин Джарин","Резол наре","Бескар","Ковата"],"a":1,"p":40},
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
    "obi":{"name":"Оби-Ван Кеноби","side":"Светлая","price":90,"emoji":"🔵","quote":"Да прибудет с тобой Сила."},
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
# ВОПРОС С КНОПКАМИ
# ─────────────────────────────────────────
def question_keyboard(q, index, total, context_data):
    """context_data = 'quiz' или 'duel_DUELID_PLAYER'"""
    buttons = []
    for i, opt in enumerate(q["o"]):
        buttons.append([InlineKeyboardButton(opt, callback_data=f"ans_{context_data}_{index}_{i}")])
    return InlineKeyboardMarkup(buttons)

def question_text(q, index, total, level_name):
    return (f"*{level_name}* | Вопрос {index+1}/{total}\n\n"
            f"❓ {q['q']}")

# ─────────────────────────────────────────
# ХЕНДЛЕРЫ
# ─────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    get_user(user.id, user.username or user.first_name)

    # Проверка на дуэль
    if context.args and context.args[0].startswith("duel_"):
        await handle_join_duel(update, context, context.args[0].replace("duel_",""))
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
        f"Привет, {user.first_name}! ⚔️\n\n"
        "*The Force Quiz* — квиз по Звёздным войнам!\n\n"
        "Отвечай на вопросы → зарабатывай 🪙 монеты → покупай карточки персонажей!\n\n"
        "Да пребудет с тобой Сила! ✨",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )

async def btn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = q.data
    user = q.from_user

    # ── ОТВЕТ НА ВОПРОС КВИЗА ──
    if d.startswith("ans_quiz_"):
        parts = d.split("_")
        # ans_quiz_INDEX_CHOSEN
        index = int(parts[2])
        chosen = int(parts[3])
        session = get_session(user.id)
        if not session or session["index"] != index:
            await q.answer("Этот вопрос уже пройден!", show_alert=True)
            return
        question = session["questions"][index]
        correct = chosen == question["a"]
        points = question["p"] if correct else 0
        add_result(user.id, points, correct)
        new_coins = session["coins"] + points
        new_index = index + 1
        total = len(session["questions"])

        if correct:
            result_text = f"✅ Верно! +{points} 🪙"
        else:
            result_text = f"❌ Неверно. Правильный ответ: *{question['o'][question['a']]}*"

        if new_index >= total:
            del_session(user.id)
            kb = [[InlineKeyboardButton("🔄 Ещё раз", callback_data="choose_level"),
                   InlineKeyboardButton("🏠 Меню", callback_data="menu")]]
            await q.edit_message_text(
                f"{result_text}\n\n"
                f"🏁 *Квиз завершён!*\n"
                f"Заработано: *{new_coins} монет* 🪙\n\n"
                f"Итого вопросов: {total}",
                reply_markup=InlineKeyboardMarkup(kb),
                parse_mode="Markdown"
            )
        else:
            save_session(user.id, session["level"], new_index, new_coins, session["questions"])
            next_q = session["questions"][new_index]
            kb = question_keyboard(next_q, new_index, total, "quiz")
            await q.edit_message_text(
                f"{result_text}\n\n" +
                question_text(next_q, new_index, total, LEVEL_NAMES[session["level"]]),
                reply_markup=kb,
                parse_mode="Markdown"
            )
        return

    # ── ОТВЕТ НА ВОПРОС ДУЭЛИ ──
    if d.startswith("ans_duel_"):
        parts = d.split("_")
        # ans_duel_DUELID_PLAYER_INDEX_CHOSEN
        duel_id = parts[2]
        player = int(parts[3])
        index = int(parts[4])
        chosen = int(parts[5])

        if user.id != player:
            await q.answer("Это не твоя дуэль!", show_alert=True)
            return

        duel = get_duel(duel_id)
        if not duel:
            await q.answer("Дуэль не найдена!", show_alert=True)
            return

        is_p1 = user.id == duel["p1"]
        cur_index = duel["p1i"] if is_p1 else duel["p2i"]

        if index != cur_index:
            await q.answer("Этот вопрос уже пройден!", show_alert=True)
            return

        question = duel["questions"][index]
        correct = chosen == question["a"]
        points = question["p"] if correct else 0
        add_result(user.id, points, correct)

        total = len(duel["questions"])
        new_index = index + 1
        new_score = (duel["p1s"] if is_p1 else duel["p2s"]) + points

        if correct:
            result_text = f"✅ Верно! +{points} 🪙"
        else:
            result_text = f"❌ Неверно. Правильный: *{question['o'][question['a']]}*"

        if is_p1:
            update_duel(duel_id, p1s=new_score, p1i=new_index, p1d=1 if new_index>=total else 0)
        else:
            update_duel(duel_id, p2s=new_score, p2i=new_index, p2d=1 if new_index>=total else 0)

        duel = get_duel(duel_id)

        if new_index >= total:
            # Этот игрок закончил
            if duel["p1d"] and duel["p2d"]:
                # Оба закончили — итог
                p1s, p2s = duel["p1s"], duel["p2s"]
                p1 = await context.bot.get_chat(duel["p1"])
                p2 = await context.bot.get_chat(duel["p2"])
                if p1s > p2s:
                    winner, loser = p1.first_name, p2.first_name
                    win_id, lose_id = duel["p1"], duel["p2"]
                elif p2s > p1s:
                    winner, loser = p2.first_name, p1.first_name
                    win_id, lose_id = duel["p2"], duel["p1"]
                else:
                    winner = None

                if winner:
                    bonus = total * question["p"]
                    add_result(win_id, bonus, True)
                    result_msg = (f"⚔️ *Дуэль завершена!*\n\n"
                                 f"🏆 Победитель: *{winner}*\n"
                                 f"💀 Проигравший: *{loser}*\n\n"
                                 f"Счёт: {p1.first_name} {p1s} — {p2s} {p2.first_name}\n"
                                 f"Бонус победителю: +{bonus} 🪙")
                else:
                    result_msg = (f"⚔️ *Дуэль завершена!*\n\n"
                                 f"🤝 Ничья!\n"
                                 f"Счёт: {p1.first_name} {p1s} — {p2s} {p2.first_name}")

                kb = [[InlineKeyboardButton("🏠 Меню", callback_data="menu")]]
                await q.edit_message_text(result_msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
                try:
                    other_id = duel["p2"] if is_p1 else duel["p1"]
                    await context.bot.send_message(other_id, result_msg, parse_mode="Markdown",
                                                   reply_markup=InlineKeyboardMarkup(kb))
                except:
                    pass
            else:
                await q.edit_message_text(
                    f"{result_text}\n\n⏳ Ты закончил! Ждём соперника...",
                    parse_mode="Markdown"
                )
        else:
            next_q = duel["questions"][new_index]
            context_str = f"duel_{duel_id}_{user.id}"
            kb = question_keyboard(next_q, new_index, total, context_str)
            await q.edit_message_text(
                f"{result_text}\n\n" +
                question_text(next_q, new_index, total, LEVEL_NAMES[duel["level"]]),
                reply_markup=kb,
                parse_mode="Markdown"
            )
        return

    # ── МЕНЮ ──
    if d == "menu":
        kb = [
            [InlineKeyboardButton("⚔️ Квиз", callback_data="choose_level"),
             InlineKeyboardButton("🤺 Дуэль", callback_data="duel_menu")],
            [InlineKeyboardButton("🛒 Магазин", callback_data="shop"),
             InlineKeyboardButton("🎴 Коллекция", callback_data="collection")],
            [InlineKeyboardButton("🏆 Топ", callback_data="leaderboard"),
             InlineKeyboardButton("👤 Профиль", callback_data="profile")],
        ]
        await q.edit_message_text("⚔️ Главное меню\nДа пребудет с тобой Сила! ✨",
                                   reply_markup=InlineKeyboardMarkup(kb))

    elif d == "choose_level":
        kb = [
            [InlineKeyboardButton("🟢 Падаван — 10 монет/вопрос", callback_data="quiz_padawan")],
            [InlineKeyboardButton("🔵 Рыцарь джедай — 20 монет", callback_data="quiz_jedi")],
            [InlineKeyboardButton("🔴 Мастер джедай — 40 монет", callback_data="quiz_master")],
            [InlineKeyboardButton("◀️ Назад", callback_data="menu")],
        ]
        await q.edit_message_text("Выбери уровень — 10 вопросов подряд:",
                                   reply_markup=InlineKeyboardMarkup(kb))

    elif d.startswith("quiz_"):
        level = d.replace("quiz_", "")
        questions = random.sample(QUESTIONS[level], 10)
        save_session(user.id, level, 0, 0, questions)
        first_q = questions[0]
        kb = question_keyboard(first_q, 0, 10, "quiz")
        await q.edit_message_text(
            question_text(first_q, 0, 10, LEVEL_NAMES[level]),
            reply_markup=kb,
            parse_mode="Markdown"
        )

    elif d == "duel_menu":
        kb = [
            [InlineKeyboardButton("⚔️ Создать дуэль", callback_data="duel_create")],
            [InlineKeyboardButton("🔗 Ввести код", callback_data="duel_enter_code")],
            [InlineKeyboardButton("◀️ Назад", callback_data="menu")],
        ]
        await q.edit_message_text(
            "🤺 *Дуэль с другом*\n\n"
            "Создай дуэль → отправь другу код → оба отвечают на одинаковые вопросы → "
            "победитель получает бонус! 🪙",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="Markdown"
        )

    elif d == "duel_create":
        kb = [
            [InlineKeyboardButton("🟢 Падаван", callback_data="duel_lvl_padawan")],
            [InlineKeyboardButton("🔵 Рыцарь", callback_data="duel_lvl_jedi")],
            [InlineKeyboardButton("🔴 Мастер", callback_data="duel_lvl_master")],
        ]
        await q.edit_message_text("Выбери уровень дуэли:",
                                   reply_markup=InlineKeyboardMarkup(kb))

    elif d.startswith("duel_lvl_"):
        level = d.replace("duel_lvl_", "")
        duel_id = str(uuid.uuid4())[:8].upper()
        questions = random.sample(QUESTIONS[level], 5)
        conn = sqlite3.connect("quiz.db")
        c = conn.cursor()
        c.execute("INSERT INTO duels VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  (duel_id, user.id, None, level, 0, 0, 0, 0, 0, 0,
                   json.dumps(questions), 'waiting'))
        conn.commit()
        conn.close()
        bot_info = await context.bot.get_me()
        link = f"https://t.me/{bot_info.username}?start=duel_{duel_id}"
        await q.edit_message_text(
            f"⚔️ *Дуэль создана!*\n\n"
            f"Уровень: {LEVEL_NAMES[level]}\n"
            f"Код дуэли: `{duel_id}`\n\n"
            f"Отправь другу:\n{link}\n\n"
            f"Или пусть напишет боту `/join {duel_id}`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Меню", callback_data="menu")]])
        )

    elif d == "duel_enter_code":
        await q.edit_message_text(
            "Введи команду:\n`/join КОД_ДУЭЛИ`",
            parse_mode="Markdown",
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
                kb.append([InlineKeyboardButton(f"{card['emoji']} {card['name']} — {card['price']}🪙", callback_data=f"buy_{cid}")])
        kb.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
        await q.edit_message_text(
            f"🛒 *Магазин карточек*\n💰 У тебя: *{coins} монет*\n\nВыбери карточку:",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="Markdown"
        )

    elif d.startswith("buy_"):
        cid = d.replace("buy_", "")
        card = CARDS[cid]
        if cid in get_cards(user.id):
            await q.answer("Уже есть!", show_alert=True)
            return
        if spend_coins(user.id, card["price"]):
            add_card(user.id, cid)
            await q.answer(f"✅ {card['name']} добавлена в коллекцию!", show_alert=True)
        else:
            await q.answer("❌ Недостаточно монет!", show_alert=True)
        # Обновить магазин
        row = get_user(user.id)
        coins = row[3]
        owned = get_cards(user.id)
        kb = []
        for c_id, c in CARDS.items():
            if c_id in owned:
                kb.append([InlineKeyboardButton(f"✅ {c['emoji']} {c['name']}", callback_data=f"card_{c_id}")])
            else:
                kb.append([InlineKeyboardButton(f"{c['emoji']} {c['name']} — {c['price']}🪙", callback_data=f"buy_{c_id}")])
        kb.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
        await q.edit_message_text(
            f"🛒 *Магазин карточек*\n💰 У тебя: *{coins} монет*\n\nВыбери карточку:",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="Markdown"
        )

    elif d.startswith("card_"):
        cid = d.replace("card_", "")
        card = CARDS[cid]
        await q.edit_message_text(
            f"{card['emoji']} *{card['name']}*\n\n"
            f"🌌 Сторона: {card['side']}\n"
            f"💬 _«{card['quote']}»_",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="collection")]]),
            parse_mode="Markdown"
        )

    elif d == "collection":
        owned = get_cards(user.id)
        if not owned:
            await q.edit_message_text(
                "🎴 *Коллекция пуста*\n\nЗарабатывай монеты и покупай карточки в магазине!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛒 Магазин", callback_data="shop")],
                                                   [InlineKeyboardButton("◀️ Меню", callback_data="menu")]]),
                parse_mode="Markdown"
            )
        else:
            kb = [[InlineKeyboardButton(f"{CARDS[cid]['emoji']} {CARDS[cid]['name']}", callback_data=f"card_{cid}")] for cid in owned]
            kb.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
            await q.edit_message_text(
                f"🎴 *Моя коллекция* ({len(owned)}/{len(CARDS)})",
                reply_markup=InlineKeyboardMarkup(kb),
                parse_mode="Markdown"
            )

    elif d == "leaderboard":
        rows = get_leaderboard()
        medals = ["🥇","🥈","🥉"]+["▫️"]*7
        text = "🏆 *Таблица лидеров*\n\n"
        for i,(name,score,cor,tot) in enumerate(rows):
            acc = f"{round(cor/tot*100)}%" if tot>0 else "—"
            text += f"{medals[i]} {name} — *{score}* 🪙 ({acc})\n"
        if not rows: text += "Пока никого нет!"
        await q.edit_message_text(text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Меню", callback_data="menu")]]),
            parse_mode="Markdown")

    elif d == "profile":
        row = get_user(user.id)
       row = row[:8]
       uid, name, score, coins, streak, lp, total, correct = row
        acc = f"{round(correct/total*100)}%" if total>0 else "—"
        owned = get_cards(user.id)
        await q.edit_message_text(
            f"👤 *{name}*\n\n"
            f"🎖 {get_rank(score)}\n"
            f"⭐ Очки: {score}\n"
            f"🪙 Монеты: {coins}\n"
            f"📊 Точность: {acc}\n"
            f"🔥 Стрик: {streak} дн.\n"
            f"🎴 Карточки: {len(owned)}/{len(CARDS)}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⚔️ Квиз", callback_data="choose_level")],
                [InlineKeyboardButton("◀️ Меню", callback_data="menu")],
            ]),
            parse_mode="Markdown"
        )

async def handle_join_duel(update, context, duel_id):
    user = update.effective_user
    get_user(user.id, user.username or user.first_name)
    duel = get_duel(duel_id)

    if not duel:
        await update.message.reply_text("❌ Дуэль не найдена.")
        return
    if duel["status"] != "waiting":
        await update.message.reply_text("❌ Дуэль уже начата.")
        return
    if duel["p1"] == user.id:
        await update.message.reply_text("❌ Нельзя присоединиться к своей дуэли!")
        return

    update_duel(duel_id, p2_id=user.id, status="active")
    duel = get_duel(duel_id)

    level = duel["level"]
    questions = duel["questions"]
    total = len(questions)
    first_q = questions[0]

    p1_name = (await context.bot.get_chat(duel["p1"])).first_name

    # Уведомить p1
    context_p1 = f"duel_{duel_id}_{duel['p1']}"
    kb_p1 = question_keyboard(first_q, 0, total, context_p1)
    await context.bot.send_message(
        duel["p1"],
        f"⚔️ *{user.first_name}* принял вызов! Начинаем!\n\n" +
        question_text(first_q, 0, total, LEVEL_NAMES[level]),
        reply_markup=kb_p1,
        parse_mode="Markdown"
    )

    # Отправить p2
    context_p2 = f"duel_{duel_id}_{user.id}"
    kb_p2 = question_keyboard(first_q, 0, total, context_p2)
    await update.message.reply_text(
        f"⚔️ Дуэль с *{p1_name}*! Начинаем!\n\n" +
        question_text(first_q, 0, total, LEVEL_NAMES[level]),
        reply_markup=kb_p2,
        parse_mode="Markdown"
    )

async def join_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Укажи код: `/join КОД`", parse_mode="Markdown")
        return
    await handle_join_duel(update, context, context.args[0].upper())

def main():
    init_db()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("join", join_cmd))
    app.add_handler(CallbackQueryHandler(btn))
    print("✅ TheForceQuizBot запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()