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
        total INTEGER DEFAULT 0, correct INTEGER DEFAULT 0,
        last_daily INTEGER DEFAULT 0, last_meditate INTEGER DEFAULT 0
    )""")
    for col, default in [("coins","0"),("total","0"),("correct","0"),("streak","0"),("last_daily","0"),("last_meditate","0")]:
        try: c.execute(f"ALTER TABLE users ADD COLUMN {col} INTEGER DEFAULT {default}")
        except: pass
    c.execute("""CREATE TABLE IF NOT EXISTS sessions (
        user_id INTEGER PRIMARY KEY, level TEXT,
        index_ INTEGER DEFAULT 0, coins INTEGER DEFAULT 0, questions TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS active_polls (
        poll_id TEXT PRIMARY KEY, user_id INTEGER,
        correct_id INTEGER, points INTEGER,
        session_type TEXT DEFAULT 'quiz', duel_id TEXT DEFAULT NULL
    )""")
    for col in ["session_type TEXT DEFAULT 'quiz'", "duel_id TEXT DEFAULT NULL"]:
        try: c.execute(f"ALTER TABLE active_polls ADD COLUMN {col}")
        except: pass
    c.execute("""CREATE TABLE IF NOT EXISTS user_cards (
        user_id INTEGER, card_id TEXT, PRIMARY KEY (user_id, card_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS duels (
        duel_id TEXT PRIMARY KEY,
        p1_id INTEGER, p2_id INTEGER, level TEXT,
        p1_score INTEGER DEFAULT 0, p2_score INTEGER DEFAULT 0,
        p1_index INTEGER DEFAULT 0, p2_index INTEGER DEFAULT 0,
        p1_done INTEGER DEFAULT 0, p2_done INTEGER DEFAULT 0,
        questions TEXT, status TEXT DEFAULT 'waiting',
        chat_id INTEGER DEFAULT NULL, current_q_msg_id INTEGER DEFAULT NULL,
        current_q_index INTEGER DEFAULT 0, p1_answered INTEGER DEFAULT 0, p2_answered INTEGER DEFAULT 0
    )""")
    for col_def in ["chat_id INTEGER DEFAULT NULL","current_q_msg_id INTEGER DEFAULT NULL","current_q_index INTEGER DEFAULT 0","p1_answered INTEGER DEFAULT 0","p2_answered INTEGER DEFAULT 0"]:
        try: c.execute(f"ALTER TABLE duels ADD COLUMN {col_def}")
        except: pass
    conn.commit()
    conn.close()

def get_user(user_id, username=""):
    conn = sqlite3.connect("quiz.db")
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?,?)", (user_id, username))
    c.execute("SELECT user_id, username, score, coins, streak, last_play, total, correct, last_daily, last_meditate FROM users WHERE user_id=?", (user_id,))
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
        c.execute("UPDATE users SET coins=coins+?, score=score+?, streak=?, last_play=?, total=total+1, correct=correct+1 WHERE user_id=?", (coins, coins, streak, today, user_id))
    else:
        c.execute("UPDATE users SET total=total+1, streak=0, last_play=? WHERE user_id=?", (today, user_id))
    conn.commit()
    conn.close()

def spend_coins(user_id, amount):
    conn = sqlite3.connect("quiz.db")
    c = conn.cursor()
    c.execute("SELECT coins FROM users WHERE user_id=?", (user_id,))
    r = c.fetchone()
    if not r or r[0] < amount: conn.close(); return False
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

def update_time(user_id, column, value):
    conn = sqlite3.connect("quiz.db")
    c = conn.cursor()
    c.execute(f"UPDATE users SET {column}=? WHERE user_id=?", (value, user_id))
    conn.commit()
    conn.close()

def save_session(user_id, level, index, coins, questions):
    conn = sqlite3.connect("quiz.db")
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO sessions VALUES (?,?,?,?,?)", (user_id, level, index, coins, json.dumps(questions)))
    conn.commit()
    conn.close()

def get_session(user_id):
    conn = sqlite3.connect("quiz.db")
    c = conn.cursor()
    c.execute("SELECT * FROM sessions WHERE user_id=?", (user_id,))
    r = c.fetchone()
    conn.close()
    if r: return {"level":r[1],"index":r[2],"coins":r[3],"questions":json.loads(r[4])}
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
    c.execute("INSERT OR REPLACE INTO active_polls VALUES (?,?,?,?,?,?)", (poll_id, user_id, correct_id, points, session_type, duel_id))
    conn.commit()
    conn.close()

def get_poll(poll_id):
    conn = sqlite3.connect("quiz.db")
    c = conn.cursor()
    c.execute("SELECT * FROM active_polls WHERE poll_id=?", (poll_id,))
    r = c.fetchone()
    conn.close()
    if r: return {"poll_id":r[0],"user_id":r[1],"correct_id":r[2],"points":r[3],"type":r[4],"duel_id":r[5]}
    return None

def get_duel(duel_id):
    conn = sqlite3.connect("quiz.db")
    c = conn.cursor()
    c.execute("SELECT * FROM duels WHERE duel_id=?", (duel_id,))
    r = c.fetchone()
    conn.close()
    if not r: return None
    return {"duel_id":r[0],"p1":r[1],"p2":r[2],"level":r[3],"p1s":r[4],"p2s":r[5],"p1i":r[6],"p2i":r[7],"p1d":r[8],"p2d":r[9],"questions":json.loads(r[10]),"status":r[11],"chat_id":r[12],"cur_msg":r[13],"cur_qi":r[14],"p1a":r[15],"p2a":r[16]}

def update_duel(duel_id, **kwargs):
    col_map = {"p2_id":"p2_id","p1s":"p1_score","p2s":"p2_score","p1i":"p1_index","p2i":"p2_index","p1d":"p1_done","p2d":"p2_done","status":"status","chat_id":"chat_id","cur_msg":"current_q_msg_id","cur_qi":"current_q_index","p1a":"p1_answered","p2a":"p2_answered"}
    conn = sqlite3.connect("quiz.db")
    c = conn.cursor()
    mapped = {col_map.get(k,k): v for k,v in kwargs.items()}
    sets = ", ".join(f"{k}=?" for k in mapped)
    c.execute(f"UPDATE duels SET {sets} WHERE duel_id=?", list(mapped.values())+[duel_id])
    conn.commit()
    conn.close()

# ─────────────────────────────────────────
# ДАННЫЕ (ЭКОНОМИКА СНИЖЕНА: теперь квиз дает мало монет)
# ─────────────────────────────────────────
QUESTIONS = {
    "padawan": [
        {"q":"Какого цвета световой меч у Йоды?","o":["Зелёный","Синий","Красный","Фиолетовый"],"a":0,"p":3,"d":1},
        {"q":"Кто сказал 'Я — твой отец'?","o":["Палпатин","Дарт Мол","Дарт Вейдер","Граф Дуку"],"a":2,"p":3,"d":1},
        {"q":"На какой планете вырос Люк?","o":["Корусант","Татуин","Набу","Эндор"],"a":1,"p":3,"d":1},
        {"q":"Кто пилотировал Миллениум Фэлкон?","o":["Люк","Лэндо","Хан Соло","Чубакка"],"a":2,"p":3,"d":1},
        {"q":"Какое оружие используют джедаи?","o":["Бластер","Световой меч","Вибромеч","Винтовка"],"a":1,"p":3,"d":1},
        {"q":"Кто такой Чубакка?","o":["Дроид","Вуки","Мандалорец","Тогрута"],"a":1,"p":3,"d":1},
        {"q":"Как называется орден Светлой стороны?","o":["Ситхи","Мандалорцы","Джедаи","Республиканцы"],"a":2,"p":3,"d":1},
        {"q":"Цвет меча Дарта Вейдера?","o":["Синий","Зелёный","Красный","Фиолетовый"],"a":2,"p":3,"d":1},
        {"q":"Какая планета полностью покрыта городом?","o":["Татуин","Набу","Корусант","Камино"],"a":2,"p":3,"d":1},
        {"q":"Кто правил Галактикой как Император?","o":["Дарт Вейдер","Граф Дуку","Палпатин","Таркин"],"a":2,"p":3,"d":1},
        {"q":"Кто такой R2-D2?","o":["Протокол-дроид","Астромех дроид","Боевой дроид","Охотник"],"a":1,"p":3,"d":1},
        {"q":"Как зовут мастера-джедая, похожего на черепаху?","o":["Йода","Пло Кун","Мейс Винду","Оби-Ван"],"a":0,"p":3,"d":1},
        
        {"q":"Кто убил Дарта Мола?","o":["Йода","Оби-Ван","Квай-Гон","Палпатин"],"a":1,"p":4,"d":2},
        {"q":"Из чего состоит армия Республики?","o":["Дроидов","Клонов","Мандалорцев","Волонтёров"],"a":1,"p":4,"d":2},
        {"q":"Какая организация управляла Галактикой до Империи?","o":["Сепаратисты","Республика","Орден Джедаев","Торговая Федерация"],"a":1,"p":4,"d":2},
        {"q":"Кто такая Падме Амидала?","o":["Джедай","Сенатор Набу","Охотница","Ситх"],"a":1,"p":4,"d":2},
        {"q":"Какой корабль разрушает Альдераан?","o":["Звезда Смерти","Исполнительный","ТИЕ-Истребитель","Разрушитель"],"a":0,"p":4,"d":2},
        {"q":"Кто такой Боба Фетт?","o":["Клон","Джедай","Ситх","Дроид"],"a":0,"p":4,"d":2},
        {"q":"На какой планете ледяная база в Эп. 5?","o":["Хот","Дагоба","Татуин","Эндор"],"a":0,"p":4,"d":2},
        {"q":"Кто спас Хана Соло из карбонита?","o":["Люк","Лэндо","Лея","Чубакка"],"a":1,"p":4,"d":2},
        {"q":"Кто тренировал Оби-Вана?","o":["Йода","Квай-Гон","Мейс Винду","Кит Фисто"],"a":1,"p":4,"d":2},
        {"q":"Какая раса у Джар-Джара Бинкса?","o":["Дроид","Гунган","Твилек","Человек"],"a":1,"p":4,"d":2},
        {"q":"Кто такой Лэндо Калриссиан?","o":["Джедай","Бармен","Админ Облачного Города","Солдат"],"a":2,"p":4,"d":2},

        {"q":"Какой приказ уничтожил джедаев?","o":["Приказ 65","Приказ 66","Приказ 99","Приказ 77"],"a":1,"p":5,"d":3},
        {"q":"Кто тайно заказал создание армии клонов?","o":["Палпатин","Сифо-Диас","Дарт Тиранус","Сифо-Диас и Тиранус"],"a":3,"p":5,"d":3},
        {"q":"Какое реальное имя Дарта Сидиуса?","o":["Шив Палпатин","Дарт Плэгас","Финис Валорум","Хас Визла"],"a":0,"p":5,"d":3},
        {"q":"Какой расы был Дарт Мол?","o":["Забрак","Тогрута","Миралука","Человек"],"a":0,"p":5,"d":3},
        {"q":"Кто вырастил Анакина как раба?","o":["Ватто","Гарджа","Шоу","Квай-Гон"],"a":0,"p":5,"d":3},
        {"q":"Сколько лет длилась Война Клонов?","o":["1 год","3 года","5 лет","10 лет"],"a":1,"p":5,"d":3},
        {"q":"Кто убил Джанго Фетта?","o":["Оби-Ван","Мейс Винду","Йода","Боба Фетт"],"a":1,"p":5,"d":3},
        {"q":"На какой планете первый бой с Дуку?","o":["Дженона","Корусант","Геонозис","Мустафар"],"a":2,"p":5,"d":3},
        {"q":"Какое животное оседлал Анакин на Набу?","o":["Воркон","Фаба","Таунтаун","Дрого"],"a":0,"p":5,"d":3},
        {"q":"Кто такой Нут Ганрей?","o":["Ситх","Вице-король Торг. Федерации","Джедай","Сенатор"],"a":1,"p":5,"d":3},
        {"q":"Какой дроид-ассасин пытался убить Падме?","o":["IG-88","Боба Фетт","ЗAM-Веселл","R2-D2"],"a":2,"p":5,"d":3},
        {"q":"Как называется родная планета Чубакки?","o":["Эндор","Кашyyк","Татуин","Хот"],"a":1,"p":5,"d":3},
    ],
    "jedi": [
        {"q":"Где находится Храм джедаев?","o":["Набу","Дагоба","Корусант","Илум"],"a":2,"p":5,"d":1},
        {"q":"Цвет меча Мейса Винду?","o":["Синий","Зелёный","Фиолетовый","Красный"],"a":2,"p":5,"d":1},
        {"q":"Кто такая Асока Тано?","o":["Ситх","Падаван Энакина","Сенатор","Наёмник"],"a":1,"p":5,"d":1},
        {"q":"Что такое Голокрон?","o":["Корабль","Хранилище знаний","Оружие","Планета"],"a":1,"p":5,"d":1},
        {"q":"Какая раса у Асоки Тано?","o":["Твилек","Тогрута","Миралука","Забрак"],"a":1,"p":5,"d":1},
        {"q":"Кто такой Капитан Рекс?","o":["Дроид","Клон-командир","Штурмовик","Мандалорец"],"a":1,"p":5,"d":1},
        {"q":"Какой меч был у Дарта Мола?","o":["Один красный","Двойной красный","Синий и красный","Черный"],"a":1,"p":5,"d":1},
        {"q":"Кто предал Орден в Эпизоде 2?","o":["Анакин","Дуку","Сифо-Диас","Пло Кун"],"a":1,"p":5,"d":1},
        {"q":"Планета-болото Йоды?","o":["Дагоба","Фелуция","Камино","Мустафар"],"a":0,"p":5,"d":1},
        {"q":"Кто такой Канан Джаррус?","o":["Мастер","Выживший после Приказа 66","Ситх","Клон"],"a":1,"p":5,"d":1},
        {"q":"Как зовут сына Хана и Леи?","o":["Кайло Рен","Бен Соло","Энакин","Хан мл."],"a":1,"p":5,"d":1},
        {"q":"Кто такая Асадж Вентресс?","o":["Джедай","Ученица Дуку","Ситх","Сенатор"],"a":1,"p":5,"d":1},
        
        {"q":"Что такое мидихлорианы?","o":["Оружие","Микроорганизмы Силы","Инопланетяне","Двигатель"],"a":1,"p":7,"d":2},
        {"q":"Кто такая Сатин Крайз?","o":["Джедай","Ситх","Мандалорка-пацифист","Клон"],"a":2,"p":7,"d":2},
        {"q":"Какой расы был Сев Тарс?","o":["Человек","Твилек","Миралука","Тогрута"],"a":1,"p":7,"d":2},
        {"q":"Кто такие 'Ночные Совы'?","o":["Элитные клоны","Темные джедаи","Культ","Дроиды"],"a":0,"p":7,"d":2},
        {"q":"Где добывают кристаллы для мечей?","o":["Корусант","Мустафар","Илум","Татуин"],"a":2,"p":7,"d":2},
        {"q":"Кто такой Саваж Опресс?","o":["Брат Мола","Клон","Джедай","Хатт"],"a":0,"p":7,"d":2},
        {"q":"Что произошло с Асокой в финале 5 сезона?","o":["Погибла","Ушла из Ордена","Стала ситхом","Попала в плен"],"a":1,"p":7,"d":2},
        {"q":"Кто такой генерал Гривус?","o":["Киборг-главнокомандующий","Ситх","Клон","Хатт"],"a":0,"p":7,"d":2},
        {"q":"В каком братстве была Вентресс?","o":["Орден Ситхов","Сестры Ночи","Мандалорцы","Инквизиторы"],"a":1,"p":7,"d":2},
        {"q":"Кто убийца Сифо-Диаса?","o":["Дарт Мол","Дарт Сидиус","Дарт Плегас","Дарт Тиранус"],"a":1,"p":7,"d":2},
        {"q":"Как называется корабль Энакина и Асоки?","o":["Наблюдатель","Тень","Гостеприимный","Сокол"],"a":0,"p":7,"d":2},

        {"q":"Раса Йоды (по канону)?","o":["Квермийцы","Тогрутане","Не раскрыта","Миральцы"],"a":2,"p":10,"d":3},
        {"q":"Сколько членов Совета Джедаев?","o":["10","12","15","5"],"a":1,"p":10,"d":3},
        {"q":"Какое преступление совершил Энакин после смерти Шми?","o":["Убил Ватто","Убил тускенов","Сжег ферму","Убил Шоу"],"a":1,"p":10,"d":3},
        {"q":"Кто такой Дарт Плэгас Мудрый?","o":["Учитель Сидиуса","Первый ситх","Ученик Мола","Джедай"],"a":0,"p":10,"d":3},
        {"q":"Кто создал правило 'Только двое'?","o":["Дарт Бейн","Сидиус","Нихилус","Реван"],"a":0,"p":10,"d":3},
        {"q":"Как называется мир Авторов Силы?","o":["Дагоба","Мортис","Коррибан","Мустафар"],"a":1,"p":10,"d":3},
        {"q":"Кто первым применил молнию Силы (легенды)?","o":["Йода","Мейс Винду","Пло Кун","Сайлер"],"a":1,"p":10,"d":3},
        {"q":"Какая форма боя у Мола?","o":["Шиен","Джар'Кай","Джуйсо","Сорцу"],"a":1,"p":10,"d":3},
        {"q":"Кто такая Талзин (Мать)?","o":["Ситх","Джедай","Лидер сестер ночи","Охотница"],"a":2,"p":10,"d":3},
        {"q":"Что случилось с Зейном после Приказа 66?","o":["Погиб","Потерял память","Остался верен Империи","Стал Инквизитором"],"a":1,"p":10,"d":3},
        {"q":"Какой планетой управлял Кад Бейн?","o":["Татуин","Конкорд Даун","Датомер","Ондерон"],"a":1,"p":10,"d":3},
        {"q":"Кто такой Реван (до падения)?","o":["Ситх","Джедай-Мастер","Клон","Мандалорец"],"a":1,"p":10,"d":3},
    ],
    "master": [
        {"q":"Мать Энакина Скайуокера?","o":["Падме","Шми","Бару","Лира"],"a":1,"p":8,"d":1},
        {"q":"Кто озвучил Вейдера в оригинале?","o":["Марк Хэмилл","Джеймс Эрл Джонс","Харрисон Форд","Прауз"],"a":1,"p":8,"d":1},
        {"q":"Что такое Дарксейбер?","o":["Красный меч","Черный меч Мандалора","Меч Бейна","Артефакт Йоды"],"a":1,"p":8,"d":1},
        {"q":"Кто такая Бо-Катан Крайз?","o":["Джедай","Ситх","Мандалорка","Сенатор"],"a":2,"p":8,"d":1},
        {"q":"Кто создал правило двух ситхов?","o":["Дарт Бейн","Плэгас","Тенебрус","Сидиус"],"a":0,"p":8,"d":1},
        {"q":"Из чего делают мандалорскую броню?","o":["Дюраниум","Бескар","Титан","Кортозис"],"a":1,"p":8,"d":1},
        {"q":"Кто такой Гранд Мофф Таркин?","o":["Ситх","Джедай","Командующий Звезды Смерти","Охотник"],"a":2,"p":8,"d":1},
        {"q":"Кто тренировал Дарта Мола (канон)?","o":["Сидиус","Плегас","Тиранус","Снока"],"a":0,"p":8,"d":1},
        {"q":"Кто такой Эзра Бриджер?","o":["Джедай Республики","Падаван из Rebels","Мандалорец","Клон"],"a":1,"p":8,"d":1},
        {"q":"Кто такой Гоган (Grogu)?","o":["Злодей","Детеныш расы Йоды","Дроид","Клон"],"a":1,"p":8,"d":1},
        {"q":"Какая группа охотников есть в Мандалорце?","o":["Боба Фетт","Клан Крайт","Инквизиторы","Гильдия"],"a":1,"p":8,"d":1},
        {"q":"Кто такой Роук?","o":["Дроид","Джедай-падаван","Мандалорец","Штурмовик"],"a":1,"p":8,"d":1},

        {"q":"Мандалорский кодекс чести?","o":["Дин Джарин","Резол-наре","Бескар","Ковата"],"a":1,"p":12,"d":2},
        {"q":"Кто такой Палпатин ДО канцлера?","o":["Сенатор Набу","Сенатор Корусанта","Губернатор","Джедай"],"a":0,"p":12,"d":2},
        {"q":"Как называется судно спасения Палпатина?","o":["Звезда Смерти","Затмение","Исполнительный","Нексус"],"a":1,"p":12,"d":2},
        {"q":"Какая форма боя у Оби-Вана?","o":["Атару","Сорцу","Соору","Макаси"],"a":2,"p":12,"d":2},
        {"q":"Кто такой Дарт Нихилус?","o":["Человек","Тень, пожирающий миры","Дроид","Инквизитор"],"a":1,"p":12,"d":2},
        {"q":"Какая планета разрушена для Звезды Смерти?","o":["Альдераан","Джедха","Илум","Кореллия"],"a":1,"p":12,"d":2},
        {"q":"Кто такая Сноук?","o":["Ситх","Претензия Палпатина","Джедай","Клон Вейдера"],"a":1,"p":12,"d":2},
        {"q":"Как называется орден убийц Империи?","o":["Штурмовики","Инквизиторы","Дарк Труперы","Гварда"],"a":1,"p":12,"d":2},
        {"q":"Кто убийца Шми Скайуокер?","o":["Дарт Мол","Племя тускенов","Вейдер","Боба Фетт"],"a":1,"p":12,"d":2},
        {"q":"Кто такая Миттра Сурик?","o":["Ситх","Джедай-Генерал","Мандалорка","Дроид"],"a":1,"p":12,"d":2},
        {"q":"Где древний храм ситхов?","o":["Корусант","Академия Бейна","Морабанд","Затмение"],"a":2,"p":12,"d":2},

        {"q":"Кто обучал Дарта Плагиаса?","o":["Дарт Тенебрус","Бейн","Сидиус","Нихилус"],"a":0,"p":15,"d":3},
        {"q":"Кто граф Дуку как ситх?","o":["Дарт Мол","Дарт Тиранус","Сидиус","Вейдер"],"a":1,"p":15,"d":3},
        {"q":"Что произошло с Энакином на Мустафаре?","o":["Потерял руку","Потерял ноги","Попал в лаву","Утонул"],"a":2,"p":15,"d":3},
        {"q":"Древняя раса, создавших гипердрайв?","o":["Люди","Раката","Чисс","Келл-Дроиды"],"a":1,"p":15,"d":3},
        {"q":"Кто такой Дарт Реван до падения?","o":["Мандалорец","Джедай-Мастер","Сенатор","Клон"],"a":1,"p":15,"d":3},
        {"q":"Кто такой Небула Сноук (канон)?","o":["Клон Палпатина","ИИ","Ученик Люка","Сын Леи"],"a":0,"p":15,"d":3},
        {"q":"Кто спас Вейдера с Мустафара?","o":["Оби-Ван","Палпатин","Таркин","Моли"],"a":1,"p":15,"d":3},
        {"q":"Родная планета мандалорцев?","o":["Конкорд Даун","Мандалор","Корусант","Мандо'аир"],"a":1,"p":15,"d":3},
        {"q":"Кто такая Бастила Шан?","o":["Ситх","Джедай-тень","Мандалорка","Дроид"],"a":1,"p":15,"d":3},
        {"q":"Какая Долина - источник Силы (Legends)?","o":["Долина Джедаев","Долина Силы","Долина Смерти","Долина Тьмы"],"a":0,"p":15,"d":3},
        {"q":"Кто убил Сидиуса в Эпизоде 9?","o":["Рей","Кайло Рен","Люк","Финн"],"a":0,"p":15,"d":3},
    ]
}

LEVEL_NAMES = {"padawan":"🟢 Падаван","jedi":"🔵 Рыцарь джедай","master":"🔴 Мастер джедай"}

# ─────────────────────────────────────────
# КАРТОЧКИ (Расширенная база и шансы для Паков)
# ─────────────────────────────────────────
CARDS = {
    # ⚪ ОБЫЧНЫЕ
    "clone":{"name":"Клон-солдат","side":"Республика","rarity":"common","emoji":"⚪","img":"https://i.pinimg.com/1200x/aa/ea/59/aaea593fff212eca1fab094c3cedb25b.jpg","quote":"За Республику!"},
    "bb8":{"name":"BB-8","side":"Светлая","rarity":"common","emoji":"⚪","img":"https://i.pinimg.com/1200x/48/11/41/481141b646a94a2ef84fed47b3c345ca.jpg","quote":"Бип-буп!"},
    "scout":{"name":"Штурмовик-разведчик","side":"Империя","rarity":"common","emoji":"⚪","img":"https://i.pinimg.com/736x/52/79/a0/5279a05bd89ffa13572889b489fe06a3.jpg","quote":"Цель найдена."},
    "ewok":{"name":"Вуки","side":"Повстанцы","rarity":"common","emoji":"⚪","img":"https://i.pinimg.com/736x/ewok_placeholder.jpg","quote":"Юбуб!"}, # Замени ссылку
    "jawa":{"name":"Джава","side":"Нейтральная","rarity":"common","emoji":"⚪","img":"https://i.pinimg.com/736x/jawa_placeholder.jpg","quote":"Утини!"}, # Замени ссылку
    
    # 🔹 РЕДКИЕ
    "maul":{"name":"Дарт Мол","side":"Тёмная","rarity":"rare","emoji":"🔹","img":"https://i.pinimg.com/736x/39/42/ce/3942ced609109fb6c4c41835d4a82c27.jpg","quote":"Страдания — пища ситха."},
    "asoka":{"name":"Асока Тано","side":"Светлая","rarity":"rare","emoji":"🔹","img":"https://i.pinimg.com/736x/asoka_placeholder.jpg","quote":"Я никому не подчиняюсь!"},
    "mando":{"name":"Мандалорец","side":"Нейтральная","rarity":"rare","emoji":"🔹","img":"https://i.pinimg.com/736x/mando_placeholder.jpg","quote":"Таков путь."},
    "kylo":{"name":"Кайло Рен","side":"Тёмная","rarity":"rare","emoji":"🔹","img":"https://i.pinimg.com/736x/kylo_placeholder.jpg","quote":"Пусть прошлое умрет!"},
    "dooku":{"name":"Граф Дуку","side":"Тёмная","rarity":"rare","emoji":"🔹","img":"https://i.pinimg.com/736x/dooku_placeholder.jpg","quote":"Я большой фанат драмы."},
    
    # 🟣 ЭПИЧЕСКИЕ
    "yoda":{"name":"Йода","side":"Светлая","rarity":"epic","emoji":"🟣","img":"https://i.pinimg.com/736x/yoda_placeholder.jpg","quote":"Делай или не делай."},
    "obi":{"name":"Оби-Ван Кеноби","side":"Светлая","rarity":"epic","emoji":"🟣","img":"https://i.pinimg.com/736x/obi_placeholder.jpg","quote":"Да прибудет с тобой Сила."},
    "luke":{"name":"Люк Скайуокер","side":"Светлая","rarity":"epic","emoji":"🟣","img":"https://i.pinimg.com/736x/luke_placeholder.jpg","quote":"Я джедай."},
    "anakin":{"name":"Энакин Скайуокер","side":"Светлая","rarity":"epic","emoji":"🟣","img":"https://i.pinimg.com/736x/anakin_placeholder.jpg","quote":"Я самый сильный джедай!"},
    
    # 🟡 ЛЕГЕНДАРНЫЕ
    "vader":{"name":"Дарт Вейдер","side":"Тёмная","rarity":"legendary","emoji":"🟡","img":"https://i.pinimg.com/736x/a6/0d/bf/a60dbf9ad0db8b8e0d2b3d935f5b7ae4.jpg","quote":"Я — твой отец."},
    "palp":{"name":"Палпатин","side":"Тёмная","rarity":"legendary","emoji":"🟡","img":"https://i.pinimg.com/736x/palp_placeholder.jpg","quote":"Неограниченная власть!"},
    "revan":{"name":"Дарт Реван","side":"Тёмная","rarity":"legendary","emoji":"🟡","img":"https://i.pinimg.com/736x/revan_placeholder.jpg","quote":"Свет... Тьма... Я и то, и другое."},
    "boba":{"name":"Боба Фетт","side":"Нейтральная","rarity":"legendary","emoji":"🟡","img":"https://i.pinimg.com/736x/boba_placeholder.jpg","quote":"Он ничего мне не должен."},
}

# Шансы для МАГАЗИНА (Пак за 100 монет)
PACK_CHANCES = {"common": 50, "rare": 30, "epic": 15, "legendary": 5}
# Шансы для ЕЖЕДНЕВНОГО НАГРАЖДЕНИЯ (Больше легких)
DAILY_CHANCES = {"common": 65, "rare": 25, "epic": 8, "legendary": 2}
# Шансы для МЕДИТАЦИИ (Шанс на эпик/легу выше!)
MEDITATE_CHANCES = {"common": 0, "rare": 50, "epic": 35, "legendary": 15}

def get_rank(score):
    if score < 50: return "🌱 Новичок"
    if score < 150: return "⚔️ Падаван"
    if score < 350: return "🔵 Рыцарь"
    if score < 700: return "🟣 Мастер"
    return "⭐ Великий магистр"

# Вспомогательная функция выдачи карточки
async def give_random_card(user_id, context, chat_id, chances_dict, source_text):
    roll = random.randint(1, 100)
    current_chance, chosen_rarity = 0, "common"
    for rarity, chance in chances_dict.items():
        current_chance += chance
        if roll <= current_chance: chosen_rarity = rarity; break

    possible_cards = [cid for cid, c in CARDS.items() if c["rarity"] == chosen_rarity]
    if not possible_cards: possible_cards = [cid for cid, c in CARDS.items() if c["rarity"] == "common"]
    
    won_card_id = random.choice(possible_cards)
    card = CARDS[won_card_id]
    is_new = won_card_id not in get_cards(user_id)
    add_card(user_id, won_card_id)

    rarity_names = {"common": "Обычная", "rare": "Редкая", "epic": "Эпическая", "legendary": "Легендарная"}
    text = f"🎁 {source_text}\n\n🎉 Выпала карточка!\n{card['emoji']} {card['name']}\nРедкость: {rarity_names[card['rarity']]}\n«{card['quote']}»"
    if not is_new: text += "\n\n⚡ Дубль! Карточка уже в коллекции."

    kb = [[InlineKeyboardButton("🏠 Меню", callback_data="menu")]]
    try:
        await context.bot.send_photo(chat_id=chat_id, photo=card["img"], caption=text, reply_markup=InlineKeyboardMarkup(kb))
    except:
        await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=InlineKeyboardMarkup(kb))


# ─────────────────────────────────────────
# ОТПРАВКА ОПРОСОВ И ДУЭЛЕЙ
# ─────────────────────────────────────────
async def send_poll(context, chat_id, user_id, question, index, total, level, session_type="quiz", duel_id=None):
    q = question
    msg = await context.bot.send_poll(chat_id=chat_id, question=f"[{LEVEL_NAMES[level]}] Вопрос {index+1}/{total}\n{q['q']}", options=q["o"], type=Poll.QUIZ, correct_option_id=q["a"], is_anonymous=False, explanation=f"+{q['p']} монет")
    save_poll(msg.poll.id, user_id, q["a"], q["p"], session_type, duel_id)

async def send_duel_question(context, chat_id, duel_id, q_index, duel):
    q = duel["questions"][q_index]
    total = len(duel["questions"])
    try: p1_name, p2_name = (await context.bot.get_chat(duel["p1"])).first_name, (await context.bot.get_chat(duel["p2"])).first_name
    except: p1_name, p2_name = "Игрок 1", "Игрок 2"
    text = f"⚔️ Дуэль: {p1_name} {duel['p1s']} — {duel['p2s']} {p2_name}\n[{LEVEL_NAMES[duel['level']]}] Вопрос {q_index+1}/{total}\n\n❓ {q['q']}"
    kb = [[InlineKeyboardButton(opt, callback_data=f"da_{duel_id}_{q_index}_{i}")] for i, opt in enumerate(q["o"])]
    msg = await context.bot.send_message(chat_id, text, reply_markup=InlineKeyboardMarkup(kb))
    update_duel(duel_id, cur_msg=msg.message_id, cur_qi=q_index, p1a=0, p2a=0)
    return msg

# ─────────────────────────────────────────
# ХЕНДЛЕРЫ
# ─────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    get_user(user.id, user.username or user.first_name)
    
    kb = [
        [InlineKeyboardButton("⚔️ Квиз", callback_data="choose_level"), InlineKeyboardButton("🤺 Дуэль", callback_data="duel_menu")],
        [InlineKeyboardButton("🛒 Магазин", callback_data="shop"), InlineKeyboardButton("🎴 Коллекция", callback_data="collection")],
        [InlineKeyboardButton("🎁 Ежедневное", callback_data="daily"), InlineKeyboardButton("🧘 Медитация", callback_data="meditate")],
        [InlineKeyboardButton("🏆 Топ", callback_data="leaderboard"), InlineKeyboardButton("👤 Профиль", callback_data="profile")],
    ]
    await update.message.reply_text("⚔️ Главное меню\nДа прибудет с тобой Сила! ✨", reply_markup=InlineKeyboardMarkup(kb))

async def btn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = q.data
    user = q.from_user
    row = get_user(user.id, user.username)
    uid, name, score, coins, streak, lp, total, correct, last_daily, last_meditate = row
    now = int(time.time())
    last_daily = last_daily or 0
    last_meditate = last_meditate or 0

    if d.startswith("da_"):
        parts = d.split("_")
        duel_id, q_index, chosen = parts[1], int(parts[2]), int(parts[3])
        duel = get_duel(duel_id)
        if not duel or duel["status"] != "active": return await q.answer("Дуэль не найдена.", show_alert=True)
        if user.id not in [duel["p1"], duel["p2"]]: return await q.answer("Ты не участник!", show_alert=True)
        if q_index != duel["cur_qi"]: return await q.answer("Вопрос закрыт.", show_alert=True)
        is_p1 = user.id == duel["p1"]
        if (is_p1 and duel["p1a"]) or (not is_p1 and duel["p2a"]): return await q.answer("Ты уже ответил!", show_alert=True)
        question = duel["questions"][q_index]
        is_correct = chosen == question["a"]
        points = question["p"] if is_correct else 0
        add_result(user.id, points, is_correct)
        if is_p1: update_duel(duel_id, p1s=duel["p1s"]+points, p1a=1)
        else: update_duel(duel_id, p2s=duel["p2s"]+points, p2a=1)
        await q.answer(f"✅ Верно! +{points}" if is_correct else "❌ Неверно", show_alert=True)
        duel = get_duel(duel_id)
        if duel["p1a"] and duel["p2a"]:
            next_index = q_index + 1
            try: await context.bot.edit_message_reply_markup(chat_id=duel["chat_id"], message_id=duel["cur_msg"], reply_markup=None)
            except: pass
            if next_index < len(duel["questions"]):
                update_duel(duel_id, p1i=next_index, p2i=next_index)
                await send_duel_question(context, duel["chat_id"], duel_id, next_index, get_duel(duel_id))
            else:
                update_duel(duel_id, p1d=1, p2d=1, status="finished")
                d_final = get_duel(duel_id)
                try: p1_name, p2_name = (await context.bot.get_chat(d_final["p1"])).first_name, (await context.bot.get_chat(d_final["p2"])).first_name
                except: p1_name, p2_name = "Игрок 1", "Игрок 2"
                res = f"🤝 Ничья!\n{p1_name}: {d_final['p1s']} — {d_final['p2s']} {p2_name}"
                if d_final["p1s"] > d_final["p2s"]: res = f"🏆 Победил {p1_name}!\n{p1_name}: {d_final['p1s']} — {d_final['p2s']} {p2_name}"; add_result(d_final["p1"], 20, True)
                elif d_final["p2s"] > d_final["p1s"]: res = f"🏆 Победил {p2_name}!\n{p1_name}: {d_final['p1s']} — {d_final['p2s']} {p2_name}"; add_result(d_final["p2"], 20, True)
                await context.bot.send_message(d_final["chat_id"], f"⚔️ Дуэль завершена!\n\n{res}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Меню", callback_data="menu")]]))

    elif d == "menu":
        kb = [
            [InlineKeyboardButton("⚔️ Квиз", callback_data="choose_level"), InlineKeyboardButton("🤺 Дуэль", callback_data="duel_menu")],
            [InlineKeyboardButton("🛒 Магазин", callback_data="shop"), InlineKeyboardButton("🎴 Коллекция", callback_data="collection")],
            [InlineKeyboardButton("🎁 Ежедневное", callback_data="daily"), InlineKeyboardButton("🧘 Медитация", callback_data="meditate")],
            [InlineKeyboardButton("🏆 Топ", callback_data="leaderboard"), InlineKeyboardButton("👤 Профиль", callback_data="profile")],
        ]
        await q.edit_message_text("⚔️ Главное меню\nДа прибудет с тобой Сила! ✨", reply_markup=InlineKeyboardMarkup(kb))

    elif d == "choose_level":
        kb = [
                [InlineKeyboardButton("🟢 Падаван — легкие", callback_data="quiz_padawan")],
                [InlineKeyboardButton("🔵 Рыцарь — средние", callback_data="quiz_jedi")],
                [InlineKeyboardButton("🔴 Мастер — хардкор", callback_data="quiz_master")],
        ]
        await q.edit_message_text("Выбери уровень — 10 вопросов:", reply_markup=InlineKeyboardMarkup(kb))

    elif d.startswith("quiz_"):
        level = d.replace("quiz_", "")
        easy_qs = [q for q in QUESTIONS[level] if q.get("d") == 1]
        med_qs = [q for q in QUESTIONS[level] if q.get("d") == 2]
        hard_qs = [q for q in QUESTIONS[level] if q.get("d") == 3]
        questions = random.sample(easy_qs, 3) + random.sample(med_qs, 4) + random.sample(hard_qs, 3)
        save_session(user.id, level, 0, 0, questions)
        await q.edit_message_text(f"Начинаем! {LEVEL_NAMES[level]}\nСложность будет расти! 🚀")
        await send_poll(context, q.message.chat_id, user.id, questions[0], 0, 10, level)

    elif d == "duel_menu":
        kb = [[InlineKeyboardButton("⚔️ Создать дуэль", callback_data="duel_create")],[InlineKeyboardButton("🔗 Ввести код", callback_data="duel_code")],[InlineKeyboardButton("◀️ Назад", callback_data="menu")]]
        await q.edit_message_text("🤺 Дуэль с другом\n\nСоздай дуэль и отправь другу код!", reply_markup=InlineKeyboardMarkup(kb))

        elif d == "duel_create":
        kb = [[InlineKeyboardButton("🟢 Падаван", callback_data="duel_lvl_padawan")],[InlineKeyboardButton("🔵 Рыцарь", callback_data="duel_lvl_jedi")],[InlineKeyboardButton("🔴 Мастер", callback_data="duel_lvl_master")]]
        await q.edit_message_text("Выбери уровень дуэли:", reply_markup=InlineKeyboardMarkup(kb))

    elif d.startswith("duel_lvl_"):
        level = d.replace("duel_lvl_", "")
        duel_id = str(uuid.uuid4())[:8].upper()
        questions = random.sample(QUESTIONS[level], 5)
        conn = sqlite3.connect("quiz.db")
        c = conn.cursor()
        c.execute("INSERT INTO duels (duel_id,p1_id,p2_id,level,p1_score,p2_score,p1_index,p2_index,p1_done,p2_done,questions,status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (duel_id, user.id, None, level, 0, 0, 0, 0, 0, 0, json.dumps(questions), "waiting"))
        conn.commit(); conn.close()
        await q.edit_message_text(f"⚔️ Дуэль создана!\n\nУровень: {LEVEL_NAMES[level]}\nКод: <code>{duel_id}</code>\n\n⚠️ Добавь бота в общую беседу и отправь другу команду:\n/join {duel_id}", parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Меню", callback_data="menu")]]))

    elif d == "duel_code":
        await q.edit_message_text("Введи команду:\n/join КОД", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="duel_menu")]]))

    elif d == "shop":
        kb = [[InlineKeyboardButton("📦 Открыть пак (100 монет)", callback_data="open_pack")],[InlineKeyboardButton("◀️ Меню", callback_data="menu")]]
        await q.edit_message_text(f"🛒 Магазин карточек\n\nУ тебя: {coins} монет 🪙\n\nПак стоит 100 монет.\n⚪ Обычные - 50%\n🔹 Редкие - 30%\n🟣 Эпические - 15%\n🟡 Легендарные - 5%", reply_markup=InlineKeyboardMarkup(kb))

    elif d == "open_pack":
        if not spend_coins(user.id, 100): return await q.answer("❌ Нужно 100 монет!", show_alert=True)
        try: await q.message.delete()
        except: pass
        await give_random_card(user.id, context, q.message.chat_id, PACK_CHANCES, "Пак открыт!")

    elif d == "daily":
        if now - last_daily < 86400:
            remain = 86400 - (now - last_daily)
            h, m = remain // 3600, (remain % 3600) // 60
            return await q.answer(f"⏰ Ежедневная награда будет через {h}ч. {m}мин.", show_alert=True)
        update_time(user.id, "last_daily", now)
        try: await q.message.delete()
        except: pass
        await give_random_card(user.id, context, q.message.chat_id, DAILY_CHANCES, "Ежедневная награда!")

    elif d == "meditate":
        if now - last_meditate < 10800: # 3 часа = 10800 секунд
            remain = 10800 - (now - last_meditate)
            h, m = remain // 3600, (remain % 3600) // 60
            return await q.answer(f"⏰ Медитация восстановится через {h}ч. {m}мин.", show_alert=True)
        
        update_time(user.id, "last_meditate", now)
        try: await q.message.delete()
        except: pass
        
        # Моя идея: 70% монеты, 30% крутая карточка
        if random.randint(1, 100) <= 30:
            await give_random_card(user.id, context, q.message.chat_id, MEDITATE_CHANCES, "🧘 Глубокая медитация...\n\nТы увидел вещее видение в Силе!")
        else:
            bonus_coins = random.randint(30, 60)
            add_result(user.id, bonus_coins, False)
            await context.bot.send_message(q.message.chat_id, f"🧘 Медитация...\n\nСила дала тебе покой.\nТы получил {bonus_coins} монет 🪙", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Меню", callback_data="menu")]]))

    elif d == "collection":
        owned = get_cards(user.id)
        if not owned:
            await q.edit_message_text("🎴 Коллекция пуста\n\nОткрывай паки и забирай ежедневные награды!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Меню", callback_data="menu")]]))
        else:
            kb = [[InlineKeyboardButton(f"{CARDS[cid]['emoji']} {CARDS[cid]['name']}", callback_data=f"card_{cid}")] for cid in owned]
            kb.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
            await q.edit_message_text(f"🎴 Моя коллекция ({len(owned)}/{len(CARDS)})", reply_markup=InlineKeyboardMarkup(kb))

    elif d.startswith("card_"):
        cid = d.replace("card_","")
        card = CARDS[cid]
        await q.edit_message_text(f"{card['emoji']} {card['name']}\n\nСторона: {card['side']}\n\n{card['quote']}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="collection")]]))

    elif d == "leaderboard":
        rows = get_leaderboard()
        medals = ["🥇","🥈","🥉"]+["▫️"]*7
        text = "🏆 Таблица лидеров\n\n"
        for i,(name,score,cor,tot) in enumerate(rows):
            acc = f"{round(cor/tot*100)}%" if tot>0 else "—"
            text += f"{medals[i]} {name} — {score} монет ({acc})\n"
        if not rows: text += "Пока никого нет!"
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Меню", callback_data="menu")]]))

    elif d == "profile":
        acc = f"{round(correct/total*100)}%" if total>0 else "—"
        owned = get_cards(user.id)
        await q.edit_message_text(f"👤 {name}\n\n🎖 {get_rank(score)}\n⭐ Очки: {score}\n🪙 Монеты: {coins}\n📊 Точность: {acc} ({correct}/{total})\n🔥 Стрик: {streak} дн.\n🎴 Карточки: {len(owned)}/{len(CARDS)}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚔️ Квиз", callback_data="choose_level")],[InlineKeyboardButton("◀️ Меню", callback_data="menu")]]))

# ─────────────────────────────────────────
# ОБРАБОТКА ОТВЕТОВ И ДУЭЛЕЙ
# ─────────────────────────────────────────
async def poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer = update.poll_answer
    poll_id, user_id = answer.poll_id, answer.user.id
    chosen = answer.option_ids[0] if answer.option_ids else -1
    poll = get_poll(poll_id)
    if not poll: return
    is_correct = chosen == poll["correct_id"]
    points = poll["points"] if is_correct else 0
    session = get_session(user_id)
    if not session: return

    add_result(user_id, points, is_correct)
    new_coins, new_index = session["coins"] + points, session["index"] + 1
    save_session(user_id, session["level"], new_index, new_coins, session["questions"])
    result_text = f"✅ Верно! +{points} монет 🪙" if is_correct else f"❌ Неверно. Правильный ответ: {session['questions'][session['index']]['o'][session['questions'][session['index']]['a']]}"

    if new_index < len(session["questions"]):
        try:
            await context.bot.send_message(user_id, result_text)
            await send_poll(context, user_id, user_id, session["questions"][new_index], new_index, len(session["questions"]), session["level"])
        except Exception as e:
            logging.error(f"Quiz error: {e}")
            del_session(user_id)
            await context.bot.send_message(user_id, "⚠️ Произошла ошибка, квиз прерван. Нажми /start")
    else:
        del_session(user_id)
        kb = [[InlineKeyboardButton("🔄 Ещё раз", callback_data="choose_level"), InlineKeyboardButton("🏠 Меню", callback_data="menu")]]
        try: await context.bot.send_message(user_id, f"{result_text}\n\n🏁 Квиз завершён!\nЗаработано: {new_coins} монет 🪙", reply_markup=InlineKeyboardMarkup(kb))
        except: pass

async def join_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return await update.message.reply_text("Укажи код: /join КОД")
    if update.effective_chat.type == 'private':
        return await update.message.reply_text("❌ Дуэли проходят только в общих чатах! Добавь меня в беседу и введи команду там.")
    await join_duel_handler(update, context, context.args[0].upper())

async def join_duel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    get_user(user.id, user.username or user.first_name)
    if update.effective_chat.type == 'private':
        return await update.message.reply_text("❌ Дуэль проходит в группе!")
        
    duel = get_duel(duel_id)
    if not duel: return await update.message.reply_text("❌ Дуэль не найдена. Проверь код.")
    if duel["status"] != "waiting": return await update.message.reply_text("❌ Дуэль уже началась или завершена.")
    if duel["p1"] == user.id: return await update.message.reply_text("❌ Нельзя присоединиться к своей дуэли!")

    chat_id = update.effective_chat.id
    update_duel(duel_id, p2_id=user.id, status="active", chat_id=chat_id)
    duel = get_duel(duel_id)
    
    try: p1_name = (await context.bot.get_chat(duel["p1"])).first_name
    except: p1_name = "Игрок 1"

    await update.message.reply_text(f"⚔️ {user.first_name} принял вызов {p1_name}!\n5 вопросов — удачи! ✨")
    await send_duel_question(context, chat_id, duel_id, 0, duel)

async def get_file_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        await update.message.reply_text(f"file_id:\n`{update.message.photo[-1].file_id}`", parse_mode="Markdown")
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