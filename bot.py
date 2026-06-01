import logging
import random
import sqlite3
from datetime import date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Poll
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, PollAnswerHandler
)

TOKEN = "8905147513:AAEfEXBjIvC-BJrkyp4Bm1LO57xGentsyjg"  # вставьте новый токен из BotFather

logging.basicConfig(level=logging.INFO)

# ─────────────────────────────────────────
# БАЗА ДАННЫХ
# ─────────────────────────────────────────
def init_db():
    conn = sqlite3.connect("quiz.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id    INTEGER PRIMARY KEY,
            username   TEXT,
            score      INTEGER DEFAULT 0,
            streak     INTEGER DEFAULT 0,
            last_play  TEXT,
            total_games INTEGER DEFAULT 0,
            correct    INTEGER DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS active_polls (
            poll_id    TEXT PRIMARY KEY,
            user_id    INTEGER,
            correct_id INTEGER,
            points     INTEGER
        )
    """)
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
    return row  # id, username, score, streak, last_play, total_games, correct

def update_score(user_id, points, correct: bool):
    conn = sqlite3.connect("quiz.db")
    c = conn.cursor()
    today = str(date.today())
    c.execute("SELECT streak, last_play FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    streak = row[0] if row else 0
    last_play = row[1] if row else None
    new_streak = streak + 1 if last_play == str(date.today()) or last_play is None else 1
    if correct:
        c.execute("""
            UPDATE users SET score=score+?, streak=?, last_play=?,
            total_games=total_games+1, correct=correct+1
            WHERE user_id=?
        """, (points, new_streak, today, user_id))
    else:
        c.execute("""
            UPDATE users SET total_games=total_games+1, streak=1, last_play=?
            WHERE user_id=?
        """, (today, user_id))
    conn.commit()
    conn.close()

def get_leaderboard():
    conn = sqlite3.connect("quiz.db")
    c = conn.cursor()
    c.execute("SELECT username, score, correct, total_games FROM users ORDER BY score DESC LIMIT 10")
    rows = c.fetchall()
    conn.close()
    return rows

# ─────────────────────────────────────────
# ВОПРОСЫ
# ─────────────────────────────────────────
QUESTIONS = {
    "padawan": [
        {
            "q": "Какого цвета световой меч у Йоды?",
            "options": ["Зелёный", "Синий", "Красный", "Фиолетовый"],
            "answer": 0, "points": 10
        },
        {
            "q": "Кто сказал фразу 'Я — твой отец'?",
            "options": ["Палпатин", "Дарт Мол", "Дарт Вейдер", "Граф Дуку"],
            "answer": 2, "points": 10
        },
        {
            "q": "На какой планете вырос Люк Скайуокер?",
            "options": ["Корусант", "Татуин", "Набу", "Эндор"],
            "answer": 1, "points": 10
        },
        {
            "q": "Как называется организация рыцарей Силы на светлой стороне?",
            "options": ["Ситхи", "Мандалорцы", "Орден джедаев", "Новая Республика"],
            "answer": 2, "points": 10
        },
        {
            "q": "Кто является пилотом Сокола Тысячелетия?",
            "options": ["Люк Скайуокер", "Лэндо Калриссиан", "Хан Соло", "Чубакка"],
            "answer": 2, "points": 10
        },
    ],
    "jedi": [
        {
            "q": "Что такое мидихлорианы?",
            "options": [
                "Оружие ситхов", "Микроорганизмы, связанные с Силой",
                "Вид инопланетян", "Единица измерения мощности двигателя"
            ],
            "answer": 1, "points": 20
        },
        {
            "q": "Кто обучал Оби-Вана Кеноби?",
            "options": ["Йода", "Квай-Гон Джинн", "Мейс Винду", "Кит Фисто"],
            "answer": 1, "points": 20
        },
        {
            "q": "На какой планете находится Академия джедаев (Храм джедаев)?",
            "options": ["Набу", "Дагоба", "Корусант", "Илум"],
            "answer": 2, "points": 20
        },
        {
            "q": "Какой орден Палпатин отдал, чтобы начать уничтожение джедаев?",
            "options": ["Приказ 65", "Приказ 66", "Приказ 99", "Приказ 77"],
            "answer": 1, "points": 20
        },
        {
            "q": "Какова настоящая раса Йоды?",
            "options": ["Квермийцы", "Тогрутане", "Не раскрыта", "Миральцы"],
            "answer": 2, "points": 20
        },
    ],
    "master": [
        {
            "q": "Как звали мать Энакина Скайуокера?",
            "options": ["Падме", "Шми", "Бару", "Лира"],
            "answer": 1, "points": 40
        },
        {
            "q": "В каком году (BBY) произошла Битва при Явине?",
            "options": ["0 BBY", "4 BBY", "19 BBY", "32 BBY"],
            "answer": 0, "points": 40
        },
        {
            "q": "Какой ситх разрушил правило двух?",
            "options": ["Дарт Бейн", "Дарт Плэгас", "Дарт Тенебрус", "Дарт Сидиус"],
            "answer": 0, "points": 40
        },
        {
            "q": "Как называется мандалорский кодекс чести?",
            "options": ["Дин Джарин", "Резол'наре", "Бесκар", "Ковата"],
            "answer": 1, "points": 40
        },
        {
            "q": "Кто создал армию клонов для Республики?",
            "options": ["Дарт Тиранус", "Джанго Фетт", "Сайфо-Диас", "Камино"],
            "answer": 2, "points": 40
        },
    ]
}

LEVEL_NAMES = {
    "padawan": "🟢 Падаван",
    "jedi": "🔵 Рыцарь джедай",
    "master": "🔴 Мастер джедай"
}

def get_rank(score):
    if score < 50:   return "🌱 Новичок"
    if score < 150:  return "⚔️ Падаван"
    if score < 350:  return "🔵 Рыцарь джедай"
    if score < 700:  return "🟣 Мастер джедай"
    return "⭐ Великий магистр"

# ─────────────────────────────────────────
# HANDLERS
# ─────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    get_user(user.id, user.username or user.first_name)
    keyboard = [
        [InlineKeyboardButton("⚔️ Начать квиз", callback_data="choose_level")],
        [InlineKeyboardButton("🏆 Таблица лидеров", callback_data="leaderboard")],
        [InlineKeyboardButton("👤 Мой профиль", callback_data="profile")],
    ]
    await update.message.reply_text(
        f"Привет, {user.first_name}! 🌌\n\n"
        "Добро пожаловать в *The Force Quiz* — проверь свои знания вселенной Звёздных войн!\n\n"
        "Три уровня сложности:\n"
        "🟢 Падаван — 10 очков за вопрос\n"
        "🔵 Рыцарь джедай — 20 очков\n"
        "🔴 Мастер джедай — 40 очков\n\n"
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
            [InlineKeyboardButton("🟢 Падаван (10 очков)", callback_data="quiz_padawan")],
            [InlineKeyboardButton("🔵 Рыцарь джедай (20 очков)", callback_data="quiz_jedi")],
            [InlineKeyboardButton("🔴 Мастер джедай (40 очков)", callback_data="quiz_master")],
            [InlineKeyboardButton("◀️ Назад", callback_data="menu")],
        ]
        await query.edit_message_text(
            "Выбери уровень сложности:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data.startswith("quiz_"):
        level = data.replace("quiz_", "")
        q = random.choice(QUESTIONS[level])
        msg = await query.message.reply_poll(
            question=f"[{LEVEL_NAMES[level]}] {q['q']}",
            options=q["options"],
            type=Poll.QUIZ,
            correct_option_id=q["answer"],
            explanation=f"За правильный ответ: +{q['points']} очков",
            is_anonymous=False,
        )
        conn = sqlite3.connect("quiz.db")
        c = conn.cursor()
        c.execute(
            "INSERT OR REPLACE INTO active_polls VALUES (?, ?, ?, ?)",
            (msg.poll.id, user.id, q["answer"], q["points"])
        )
        conn.commit()
        conn.close()
        await query.edit_message_text(
            f"Вопрос отправлен! Уровень: {LEVEL_NAMES[level]}\n"
            "После ответа нажми кнопку ещё раз для следующего вопроса.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➡️ Ещё вопрос", callback_data="choose_level")],
                [InlineKeyboardButton("🏆 Таблица лидеров", callback_data="leaderboard")],
            ])
        )

    elif data == "leaderboard":
        rows = get_leaderboard()
        medals = ["🥇", "🥈", "🥉"] + ["▫️"] * 7
        text = "🏆 *Таблица лидеров*\n\n"
        for i, (username, score, correct, total) in enumerate(rows):
            acc = f"{round(correct/total*100)}%" if total > 0 else "—"
            text += f"{medals[i]} {username} — *{score} очков* ({acc} верных)\n"
        if not rows:
            text += "Пока никого нет. Будь первым! 🚀"
        keyboard = [[InlineKeyboardButton("◀️ Меню", callback_data="menu")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "profile":
        row = get_user(user.id, user.username or user.first_name)
        _, username, score, streak, last_play, total, correct = row
        acc = f"{round(correct/total*100)}%" if total > 0 else "—"
        rank = get_rank(score)
        text = (
            f"👤 *{username}*\n\n"
            f"🎖 Звание: {rank}\n"
            f"⭐ Очки: {score}\n"
            f"📊 Точность: {acc} ({correct}/{total})\n"
            f"🔥 Стрик: {streak} дн.\n"
        )
        keyboard = [
            [InlineKeyboardButton("⚔️ Играть", callback_data="choose_level")],
            [InlineKeyboardButton("◀️ Меню", callback_data="menu")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "menu":
        keyboard = [
            [InlineKeyboardButton("⚔️ Начать квиз", callback_data="choose_level")],
            [InlineKeyboardButton("🏆 Таблица лидеров", callback_data="leaderboard")],
            [InlineKeyboardButton("👤 Мой профиль", callback_data="profile")],
        ]
        await query.edit_message_text(
            "Главное меню ⚔️\nДа пребудет с тобой Сила! ✨",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def poll_answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer = update.poll_answer
    poll_id = answer.poll_id
    user_id = answer.user.id
    chosen = answer.option_ids[0] if answer.option_ids else -1

    conn = sqlite3.connect("quiz.db")
    c = conn.cursor()
    c.execute("SELECT correct_id, points FROM active_polls WHERE poll_id=?", (poll_id,))
    row = c.fetchone()
    conn.close()

    if not row:
        return

    correct_id, points = row
    is_correct = chosen == correct_id
    update_score(user_id, points if is_correct else 0, is_correct)

    try:
        if is_correct:
            await context.bot.send_message(
                user_id,
                f"✅ Верно! +{points} очков\n\nВернись в бот и продолжай! 🚀"
            )
        else:
            await context.bot.send_message(
                user_id,
                "❌ Неверно. Не сдавайся — Сила в тебе! 💪"
            )
    except Exception:
        pass

# ─────────────────────────────────────────
# ЗАПУСК
# ─────────────────────────────────────────
def main():
    init_db()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(PollAnswerHandler(poll_answer_handler))
    print("✅ TheForceQuizBot запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()