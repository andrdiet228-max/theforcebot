import logging
import random
import sqlite3
from datetime import date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, PollAnswerHandler
)

import os
TOKEN = os.getenv("TOKEN")

logging.basicConfig(level=logging.INFO)

# ─────────────────────────────────────────
# БАЗА ДАННЫХ
# ─────────────────────────────────────────
def init_db():
    conn = sqlite3.connect("quiz.db")
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, username TEXT,
        score INTEGER DEFAULT 0, coins INTEGER DEFAULT 0,
        streak INTEGER DEFAULT 0, last_play TEXT,
        total_games INTEGER DEFAULT 0, correct INTEGER DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS active_polls (
        poll_id TEXT PRIMARY KEY, user_id INTEGER,
        correct_id INTEGER, points INTEGER, level TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS user_cards (
        user_id INTEGER, card_id TEXT,
        PRIMARY KEY (user_id, card_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS duels (
        duel_id TEXT PRIMARY KEY, challenger_id INTEGER,
        opponent_id INTEGER, level TEXT,
        challenger_score INTEGER DEFAULT 0,
        opponent_score INTEGER DEFAULT 0,
        challenger_done INTEGER DEFAULT 0,
        opponent_done INTEGER DEFAULT 0,
        question_index INTEGER DEFAULT 0,
        questions TEXT, status TEXT DEFAULT 'waiting'
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS quiz_sessions (
        user_id INTEGER PRIMARY KEY,
        level TEXT, question_index INTEGER DEFAULT 0,
        score INTEGER DEFAULT 0, questions TEXT
    )""")
    conn.commit()
    conn.close()

def get_user(user_id, username=""):
    conn = sqlite3.connect("quiz.db")
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.commit()
    conn.close()
    return row

def add_coins(user_id, coins, correct=True):
    conn = sqlite3.connect("quiz.db")
    c = conn.cursor()
    today = str(date.today())
    c.execute("SELECT streak, last_play FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    streak = row[0] if row else 0
    last_play = row[1] if row else None
    new_streak = streak + 1 if last_play == today else 1
    if correct:
        c.execute("""UPDATE users SET coins=coins+?, score=score+?, streak=?,
            last_play=?, total_games=total_games+1, correct=correct+1
            WHERE user_id=?""", (coins, coins, new_streak, today, user_id))
    else:
        c.execute("""UPDATE users SET total_games=total_games+1,
            streak=1, last_play=? WHERE user_id=?""", (today, user_id))
    conn.commit()
    conn.close()

def spend_coins(user_id, amount):
    conn = sqlite3.connect("quiz.db")
    c = conn.cursor()
    c.execute("SELECT coins FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    if not row or row[0] < amount:
        conn.close()
        return False
    c.execute("UPDATE users SET coins=coins-? WHERE user_id=?", (amount, user_id))
    conn.commit()
    conn.close()
    return True

def get_leaderboard():
    conn = sqlite3.connect("quiz.db")
    c = conn.cursor()
    c.execute("SELECT username, score, correct, total_games FROM users ORDER BY score DESC LIMIT 10")
    rows = c.fetchall()
    conn.close()
    return rows

def get_user_cards(user_id):
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

# ─────────────────────────────────────────
# ВОПРОСЫ
# ─────────────────────────────────────────
QUESTIONS = {
    "padawan": [
        {"q": "Какого цвета световой меч у Йоды?", "options": ["Зелёный","Синий","Красный","Фиолетовый"], "answer": 0, "points": 10},
        {"q": "Кто сказал 'Я — твой отец'?", "options": ["Палпатин","Дарт Мол","Дарт Вейдер","Граф Дуку"], "answer": 2, "points": 10},
        {"q": "На какой планете вырос Люк Скайуокер?", "options": ["Корусант","Татуин","Набу","Эндор"], "answer": 1, "points": 10},
        {"q": "Как называется организация рыцарей Силы на светлой стороне?", "options": ["Ситхи","Мандалорцы","Орден джедаев","Новая Республика"], "answer": 2, "points": 10},
        {"q": "Кто является пилотом Сокола Тысячелетия?", "options": ["Люк","Лэндо","Хан Соло","Чубакка"], "answer": 2, "points": 10},
        {"q": "Какое оружие используют джедаи?", "options": ["Бластер","Световой меч","Арбалет","Копьё"], "answer": 1, "points": 10},
        {"q": "Что такое Сила?", "options": ["Технология","Энергетическое поле","Планета","Корабль"], "answer": 1, "points": 10},
        {"q": "Как зовут дроида R2-D2 в оригинальном фильме?", "options": ["Артутушка","Арту","Ар-Ду","Р2"], "answer": 1, "points": 10},
        {"q": "Кто такой Чубакка?", "options": ["Дроид","Вуки","Манд","Джедай"], "answer": 1, "points": 10},
        {"q": "На чьей стороне Дарт Вейдер?", "options": ["Светлой","Тёмной","Нейтральной","Мандалорской"], "answer": 1, "points": 10},
    ],
    "jedi": [
        {"q": "Что такое мидихлорианы?", "options": ["Оружие ситхов","Микроорганизмы связанные с Силой","Вид инопланетян","Двигатель"], "answer": 1, "points": 20},
        {"q": "Кто обучал Оби-Вана Кеноби?", "options": ["Йода","Квай-Гон Джинн","Мейс Винду","Кит Фисто"], "answer": 1, "points": 20},
        {"q": "На какой планете Храм джедаев?", "options": ["Набу","Дагоба","Корусант","Илум"], "answer": 2, "points": 20},
        {"q": "Какой приказ начал уничтожение джедаев?", "options": ["Приказ 65","Приказ 66","Приказ 99","Приказ 77"], "answer": 1, "points": 20},
        {"q": "Какова настоящая раса Йоды?", "options": ["Квермийцы","Тогрутане","Не раскрыта","Миральцы"], "answer": 2, "points": 20},
        {"q": "Кто такой граф Дуку?", "options": ["Джедай","Отступник-ситх","Мандалорец","Дроид"], "answer": 1, "points": 20},
        {"q": "Какой цвет светового меча у Мейса Винду?", "options": ["Синий","Зелёный","Фиолетовый","Красный"], "answer": 2, "points": 20},
        {"q": "Кто такой Асока Тано?", "options": ["Ситх","Падаван Энакина","Наёмник","Дроид"], "answer": 1, "points": 20},
        {"q": "Что такое Голокрон?", "options": ["Корабль","Хранилище знаний джедаев","Оружие","Планета"], "answer": 1, "points": 20},
        {"q": "Кто убил Квай-Гона Джинна?", "options": ["Вейдер","Дарт Мол","Палпатин","Граф Дуку"], "answer": 1, "points": 20},
    ],
    "master": [
        {"q": "Как звали мать Энакина Скайуокера?", "options": ["Падме","Шми","Бару","Лира"], "answer": 1, "points": 40},
        {"q": "В каком году (BBY) произошла Битва при Явине?", "options": ["0 BBY","4 BBY","19 BBY","32 BBY"], "answer": 0, "points": 40},
        {"q": "Кто разрушил правило двух ситхов?", "options": ["Дарт Бейн","Дарт Плэгас","Дарт Тенебрус","Дарт Сидиус"], "answer": 0, "points": 40},
        {"q": "Как называется мандалорский кодекс чести?", "options": ["Дин Джарин","Резол'наре","Бескар","Ковата"], "answer": 1, "points": 40},
        {"q": "Кто создал армию клонов для Республики?", "options": ["Дарт Тиранус","Джанго Фетт","Сайфо-Диас","Камино"], "answer": 2, "points": 40},
        {"q": "Как зовут императора в оригинальной трилогии?", "options": ["Таркин","Палпатин","Вейдер","Дуку"], "answer": 1, "points": 40},
        {"q": "На какой планете Йода скрывался после Приказа 66?", "options": ["Хот","Дагоба","Эндор","Набу"], "answer": 1, "points": 40},
        {"q": "Кто такой Бо-Катан Крайз?", "options": ["Джедай","Мандалорка","Ситх","Дроид"], "answer": 1, "points": 40},
        {"q": "Что такое Дарксейбер?", "options": ["Красный меч","Чёрный световой меч","Меч Бейна","Артефакт Йоды"], "answer": 1, "points": 40},
        {"q": "Кто озвучил Дарта Вейдера в оригинале?", "options": ["Марк Хэмилл","Джеймс Эрл Джонс","Харрисон Форд","Алек Гиннесс"], "answer": 1, "points": 40},
    ]
}

LEVEL_NAMES = {"padawan": "🟢 Падаван", "jedi": "🔵 Рыцарь джедай", "master": "🔴 Мастер джедай"}
LEVEL_EMOJI = {"padawan": "🟢", "jedi": "🔵", "master": "🔴"}

# ─────────────────────────────────────────
# КАРТОЧКИ ПЕРСОНАЖЕЙ (магазин)
# ─────────────────────────────────────────
CARDS = {
    "vader": {"name": "Дарт Вейдер", "side": "Тёмная", "price": 100, "emoji": "🔴", "quote": "Я — твой отец."},
    "yoda": {"name": "Йода", "side": "Светлая", "price": 80, "emoji": "🟢", "quote": "Делай или не делай."},
    "luke": {"name": "Люк Скайуокер", "side": "Светлая", "price": 80, "emoji": "⚔️", "quote": "Я джедай, как и мой отец."},
    "obi": {"name": "Оби-Ван Кеноби", "side": "Светлая", "price": 90, "emoji": "🔵", "quote": "Да пребудет с тобой Сила."},
    "mando": {"name": "Мандалорец", "side": "Нейтральная", "price": 120, "emoji": "⚙️", "quote": "Таков путь."},
    "palp": {"name": "Палпатин", "side": "Тёмная", "price": 150, "emoji": "⚡", "quote": "Власть! Неограниченная власть!"},
    "maul": {"name": "Дарт Мол", "side": "Тёмная", "price": 110, "emoji": "🖤", "quote": "Страдания — это пища для ситха."},
    "rey": {"name": "Рей", "side": "Светлая", "price": 90, "emoji": "🌟", "quote": "Я никто."},
}

def get_rank(score):
    if score < 50:   return "🌱 Новичок"
    if score < 150:  return "⚔️ Падаван"
    if score < 350:  return "🔵 Рыцарь джедай"
    if score < 700:  return "🟣 Мастер джедай"
    return "⭐ Великий магистр"

# ─────────────────────────────────────────
# СЕССИЯ КВИЗА (автоматический следующий вопрос)
# ─────────────────────────────────────────
def save_session(user_id, level, index, score, questions):
    import json
    conn = sqlite3.connect("quiz.db")
    c = conn.cursor()
    c.execute("""INSERT OR REPLACE INTO quiz_sessions VALUES (?,?,?,?,?)""",
              (user_id, level, index, score, json.dumps(questions)))
    conn.commit()
    conn.close()

def get_session(user_id):
    import json
    conn = sqlite3.connect("quiz.db")
    c = conn.cursor()
    c.execute("SELECT * FROM quiz_sessions WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"level": row[1], "index": row[2], "score": row[3], "questions": json.loads(row[4])}
    return None

def delete_session(user_id):
    conn = sqlite3.connect("quiz.db")
    c = conn.cursor()
    c.execute("DELETE FROM quiz_sessions WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

async def send_question(context, chat_id, user_id, session):
    import json
    questions = session["questions"]
    index = session["index"]
    level = session["level"]
    if index >= len(questions):
        # Конец квиза
        delete_session(user_id)
        keyboard = [
            [InlineKeyboardButton("🔄 Сыграть ещё", callback_data="choose_level")],
            [InlineKeyboardButton("🏆 Таблица лидеров", callback_data="leaderboard")],
            [InlineKeyboardButton("🏠 Меню", callback_data="menu")],
        ]
        await context.bot.send_message(
            chat_id,
            f"🏁 *Квиз завершён!*\n\nТы ответил на {len(questions)} вопросов!\nНаграда: *+{session['score']} монет* 🪙\n\nПроверь свой профиль — /start",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return

    q = questions[index]
    msg = await context.bot.send_poll(
        chat_id,
        question=f"[{LEVEL_NAMES[level]}] Вопрос {index+1}/{len(questions)}\n{q['q']}",
        options=q["options"],
        type="quiz",
        correct_option_id=q["answer"],
        explanation=f"За правильный ответ: +{q['points']} монет 🪙",
        is_anonymous=False,
    )
    conn = sqlite3.connect("quiz.db")
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO active_polls VALUES (?,?,?,?,?)",
              (msg.poll.id, user_id, q["answer"], q["points"], level))
    conn.commit()
    conn.close()

# ─────────────────────────────────────────
# ДУЭЛИ
# ─────────────────────────────────────────
import json, uuid

def create_duel(challenger_id, level):
    duel_id = str(uuid.uuid4())[:8]
    questions = random.sample(QUESTIONS[level], 5)
    conn = sqlite3.connect("quiz.db")
    c = conn.cursor()
    c.execute("""INSERT INTO duels VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
              (duel_id, challenger_id, None, level, 0, 0, 0, 0, 0,
               json.dumps(questions), 'waiting'))
    conn.commit()
    conn.close()
    return duel_id

def get_duel(duel_id):
    conn = sqlite3.connect("quiz.db")
    c = conn.cursor()
    c.execute("SELECT * FROM duels WHERE duel_id=?", (duel_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "duel_id": row[0], "challenger_id": row[1], "opponent_id": row[2],
            "level": row[3], "challenger_score": row[4], "opponent_score": row[5],
            "challenger_done": row[6], "opponent_done": row[7],
            "question_index_ch": row[8], "questions": json.loads(row[9]), "status": row[10]
        }
    return None

# ─────────────────────────────────────────
# ХЕНДЛЕРЫ
# ─────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    get_user(user.id, user.username or user.first_name)
    keyboard = [
        [InlineKeyboardButton("⚔️ Квиз", callback_data="choose_level"),
         InlineKeyboardButton("🤺 Дуэль", callback_data="duel_menu")],
        [InlineKeyboardButton("🛒 Магазин карточек", callback_data="shop")],
        [InlineKeyboardButton("🎴 Моя коллекция", callback_data="collection"),
         InlineKeyboardButton("🏆 Топ", callback_data="leaderboard")],
        [InlineKeyboardButton("👤 Профиль", callback_data="profile")],
    ]
    await update.message.reply_text(
        f"Привет, {user.first_name}! ⚔️\n\n"
        "*The Force Quiz* — квиз по Звёздным войнам!\n\n"
        "За правильные ответы получай 🪙 монеты и трать их в магазине на карточки персонажей!\n\n"
        "Да пребудет с тобой Сила! ✨",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = query.from_user

    if data == "choose_level":
        keyboard = [
            [InlineKeyboardButton("🟢 Падаван (10 монет/вопрос, 10 вопросов)", callback_data="quiz_padawan")],
            [InlineKeyboardButton("🔵 Рыцарь джедай (20 монет, 10 вопросов)", callback_data="quiz_jedi")],
            [InlineKeyboardButton("🔴 Мастер джедай (40 монет, 10 вопросов)", callback_data="quiz_master")],
            [InlineKeyboardButton("◀️ Меню", callback_data="menu")],
        ]
        await query.edit_message_text("Выбери уровень сложности:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("quiz_"):
        level = data.replace("quiz_", "")
        questions = random.sample(QUESTIONS[level], 10)
        save_session(user.id, level, 0, 0, questions)
        await query.edit_message_text(
            f"Начинаем! {LEVEL_NAMES[level]}\n10 вопросов подряд. Удачи! 🚀"
        )
        await send_question(context, query.message.chat_id, user.id,
                           {"level": level, "index": 0, "score": 0, "questions": questions})

    elif data == "shop":
        user_data = get_user(user.id)
        coins = user_data[2]  # coins column
        owned = get_user_cards(user.id)
        text = f"🛒 *Магазин карточек*\n\n💰 У тебя: *{coins} монет*\n\n"
        keyboard = []
        for card_id, card in CARDS.items():
            if card_id in owned:
                keyboard.append([InlineKeyboardButton(f"✅ {card['emoji']} {card['name']} (есть)", callback_data=f"card_view_{card_id}")])
            else:
                keyboard.append([InlineKeyboardButton(f"{card['emoji']} {card['name']} — {card['price']}🪙", callback_data=f"buy_{card_id}")])
        keyboard.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("buy_"):
        card_id = data.replace("buy_", "")
        card = CARDS[card_id]
        owned = get_user_cards(user.id)
        if card_id in owned:
            await query.answer("У тебя уже есть эта карточка!", show_alert=True)
            return
        success = spend_coins(user.id, card["price"])
        if success:
            add_card(user.id, card_id)
            await query.answer(f"✅ Куплено! Карточка {card['name']} добавлена в коллекцию!", show_alert=True)
            # Обновить магазин
            user_data = get_user(user.id)
            coins = user_data[2]
            owned = get_user_cards(user.id)
            keyboard = []
            for cid, c in CARDS.items():
                if cid in owned:
                    keyboard.append([InlineKeyboardButton(f"✅ {c['emoji']} {c['name']} (есть)", callback_data=f"card_view_{cid}")])
                else:
                    keyboard.append([InlineKeyboardButton(f"{c['emoji']} {c['name']} — {c['price']}🪙", callback_data=f"buy_{cid}")])
            keyboard.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
            await query.edit_message_text(
                f"🛒 *Магазин карточек*\n\n💰 У тебя: *{coins} монет*\n\n",
                reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
            )
        else:
            await query.answer("❌ Недостаточно монет!", show_alert=True)

    elif data.startswith("card_view_"):
        card_id = data.replace("card_view_", "")
        card = CARDS[card_id]
        await query.edit_message_text(
            f"{card['emoji']} *{card['name']}*\n\n"
            f"🌌 Сторона: {card['side']}\n"
            f"💬 _«{card['quote']}»_",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="collection")]]),
            parse_mode="Markdown"
        )

    elif data == "collection":
        owned = get_user_cards(user.id)
        if not owned:
            await query.edit_message_text(
                "🎴 *Моя коллекция*\n\nУ тебя пока нет карточек.\nЗарабатывай монеты в квизе и покупай в магазине!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛒 В магазин", callback_data="shop")],
                                                   [InlineKeyboardButton("◀️ Меню", callback_data="menu")]]),
                parse_mode="Markdown"
            )
        else:
            keyboard = [[InlineKeyboardButton(f"{CARDS[cid]['emoji']} {CARDS[cid]['name']}", callback_data=f"card_view_{cid}")] for cid in owned]
            keyboard.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
            await query.edit_message_text(
                f"🎴 *Моя коллекция* ({len(owned)}/{len(CARDS)})\n\nНажми на карточку чтобы посмотреть:",
                reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
            )

    elif data == "duel_menu":
        keyboard = [
            [InlineKeyboardButton("⚔️ Создать дуэль", callback_data="duel_create")],
            [InlineKeyboardButton("🔗 Присоединиться", callback_data="duel_join")],
            [InlineKeyboardButton("◀️ Меню", callback_data="menu")],
        ]
        await query.edit_message_text(
            "🤺 *Дуэль с другом*\n\n"
            "Создай дуэль и отправь другу код — кто ответит правильнее на 5 вопросов, тот победит!\n"
            "Победитель получает *двойные монеты* 🪙",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )

    elif data == "duel_create":
        keyboard = [
            [InlineKeyboardButton("🟢 Падаван", callback_data="duel_level_padawan")],
            [InlineKeyboardButton("🔵 Рыцарь джедай", callback_data="duel_level_jedi")],
            [InlineKeyboardButton("🔴 Мастер джедай", callback_data="duel_level_master")],
        ]
        await query.edit_message_text("Выбери уровень дуэли:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("duel_level_"):
        level = data.replace("duel_level_", "")
        duel_id = create_duel(user.id, level)
        bot_username = (await context.bot.get_me()).username
        link = f"https://t.me/{bot_username}?start=duel_{duel_id}"
        await query.edit_message_text(
            f"⚔️ *Дуэль создана!*\n\n"
            f"Уровень: {LEVEL_NAMES[level]}\n"
            f"Код дуэли: `{duel_id}`\n\n"
            f"Отправь другу эту ссылку:\n{link}\n\n"
            f"Или пусть напишет боту: `/join {duel_id}`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Меню", callback_data="menu")]])
        )

    elif data == "duel_join":
        await query.edit_message_text(
            "Введи код дуэли командой:\n`/join КОД_ДУЭЛИ`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="duel_menu")]])
        )

    elif data == "leaderboard":
        rows = get_leaderboard()
        medals = ["🥇","🥈","🥉"] + ["▫️"]*7
        text = "🏆 *Таблица лидеров*\n\n"
        for i, (username, score, correct, total) in enumerate(rows):
            acc = f"{round(correct/total*100)}%" if total > 0 else "—"
            text += f"{medals[i]} {username} — *{score}* 🪙 ({acc})\n"
        if not rows:
            text += "Пока никого нет. Будь первым! 🚀"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Меню", callback_data="menu")]]), parse_mode="Markdown")

    elif data == "profile":
        row = get_user(user.id)
        _, username, score, coins, streak, last_play, total, correct = row
        acc = f"{round(correct/total*100)}%" if total > 0 else "—"
        rank = get_rank(score)
        owned = get_user_cards(user.id)
        await query.edit_message_text(
            f"👤 *{username}*\n\n"
            f"🎖 Звание: {rank}\n"
            f"⭐ Очки: {score}\n"
            f"🪙 Монеты: {coins}\n"
            f"📊 Точность: {acc} ({correct}/{total})\n"
            f"🔥 Стрик: {streak} дн.\n"
            f"🎴 Карточки: {len(owned)}/{len(CARDS)}\n",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⚔️ Играть", callback_data="choose_level")],
                [InlineKeyboardButton("🛒 Магазин", callback_data="shop")],
                [InlineKeyboardButton("◀️ Меню", callback_data="menu")],
            ]),
            parse_mode="Markdown"
        )

    elif data == "menu":
        keyboard = [
            [InlineKeyboardButton("⚔️ Квиз", callback_data="choose_level"),
             InlineKeyboardButton("🤺 Дуэль", callback_data="duel_menu")],
            [InlineKeyboardButton("🛒 Магазин карточек", callback_data="shop")],
            [InlineKeyboardButton("🎴 Моя коллекция", callback_data="collection"),
             InlineKeyboardButton("🏆 Топ", callback_data="leaderboard")],
            [InlineKeyboardButton("👤 Профиль", callback_data="profile")],
        ]
        await query.edit_message_text(
            "⚔️ Главное меню\nДа пребудет с тобой Сила! ✨",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def join_duel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    get_user(user.id, user.username or user.first_name)

    # Проверка на start=duel_XXX
    args = context.args
    if not args:
        await update.message.reply_text("Укажи код: `/join КОД`", parse_mode="Markdown")
        return

    duel_id = args[0].replace("duel_", "")
    duel = get_duel(duel_id)

    if not duel:
        await update.message.reply_text("❌ Дуэль не найдена.")
        return
    if duel["status"] != "waiting":
        await update.message.reply_text("❌ Дуэль уже началась или завершена.")
        return
    if duel["challenger_id"] == user.id:
        await update.message.reply_text("❌ Нельзя присоединиться к своей дуэли.")
        return

    conn = sqlite3.connect("quiz.db")
    c = conn.cursor()
    c.execute("UPDATE duels SET opponent_id=?, status='active' WHERE duel_id=?", (user.id, duel_id))
    conn.commit()
    conn.close()

    level = duel["level"]
    questions = duel["questions"]

    # Сохраняем сессии для обоих
    save_session(duel["challenger_id"], level, 0, 0, questions)
    save_session(user.id, level, 0, 0, questions)

    # Уведомляем challenger
    challenger_name = (await context.bot.get_chat(duel["challenger_id"])).first_name
    opponent_name = user.first_name

    await context.bot.send_message(
        duel["challenger_id"],
        f"⚔️ *{opponent_name}* принял твой вызов!\n\nДуэль начинается! {LEVEL_NAMES[level]}\n5 вопросов. Удачи!",
        parse_mode="Markdown"
    )
    await update.message.reply_text(
        f"⚔️ Ты принял вызов от *{challenger_name}*!\n\nДуэль начинается! {LEVEL_NAMES[level]}\n5 вопросов. Удачи!",
        parse_mode="Markdown"
    )

    # Отправляем вопросы обоим
    await send_question(context, duel["challenger_id"], duel["challenger_id"],
                       {"level": level, "index": 0, "score": 0, "questions": questions})
    await send_question(context, update.effective_chat.id, user.id,
                       {"level": level, "index": 0, "score": 0, "questions": questions})

async def start_with_args(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args and context.args[0].startswith("duel_"):
        await join_duel(update, context)
    else:
        await start(update, context)

async def poll_answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer = update.poll_answer
    poll_id = answer.poll_id
    user_id = answer.user.id
    chosen = answer.option_ids[0] if answer.option_ids else -1

    conn = sqlite3.connect("quiz.db")
    c = conn.cursor()
    c.execute("SELECT correct_id, points, level FROM active_polls WHERE poll_id=?", (poll_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return

    correct_id, points, level = row
    is_correct = chosen == correct_id

    session = get_session(user_id)
    if not session:
        return

    new_score = session["score"] + (points if is_correct else 0)
    new_index = session["index"] + 1

    if is_correct:
        add_coins(user_id, points, correct=True)
        try:
            await context.bot.send_message(user_id, f"✅ Верно! +{points} монет 🪙")
        except:
            pass
    else:
        add_coins(user_id, 0, correct=False)
        try:
            await context.bot.send_message(user_id, "❌ Неверно. Не сдавайся!")
        except:
            pass

    updated_session = {
        "level": session["level"],
        "index": new_index,
        "score": new_score,
        "questions": session["questions"]
    }
    save_session(user_id, session["level"], new_index, new_score, session["questions"])

    # Следующий вопрос автоматически
    chat_id = answer.user.id
    await send_question(context, chat_id, user_id, updated_session)

def main():
    init_db()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start_with_args))
    app.add_handler(CommandHandler("join", join_duel))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(PollAnswerHandler(poll_answer_handler))
    print("✅ TheForceQuizBot запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()