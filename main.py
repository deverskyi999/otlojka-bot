from __future__ import annotations

import asyncio
import logging
import os
import re
import sqlite3
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from html import escape
from typing import Iterator, Optional

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
    ReplyKeyboardMarkup,
    WebAppInfo,
)
from dotenv import load_dotenv

logger = logging.getLogger("codeschool")

# ======================================================================
# CONFIG
# ======================================================================


@dataclass
class Settings:
    bot_token: str
    owner_id: int
    db_path: str = "codeschool.db"
    timezone_offset_hours: int = 3  # МСК по умолчанию — для напоминаний
    trial_days: int = 3
    default_price_stars: int = 150
    ai_api_key: str = "imbek-9240f4b11ffe56d736c7691e253867ea1be2af6df6a62291"
    ai_base_url: str = "https://api.imbek.fun/v1"
    ai_model: str = "im-flash"
    ai_max_tokens: int = 700
    webapp_url: str = ""  # ссылка на захостенный terminal.html (Mini App)

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        bot_token = os.getenv("BOT_TOKEN")
        if not bot_token:
            raise RuntimeError("BOT_TOKEN is not set in environment (.env)")
        owner_id_raw = os.getenv("OWNER_ID")
        if not owner_id_raw:
            raise RuntimeError("OWNER_ID is not set in environment (.env)")
        return cls(
            bot_token=bot_token,
            owner_id=int(owner_id_raw),
            db_path=os.getenv("DB_PATH", cls.db_path),
            timezone_offset_hours=int(os.getenv("TIMEZONE_OFFSET_HOURS", cls.timezone_offset_hours)),
            trial_days=int(os.getenv("TRIAL_DAYS", cls.trial_days)),
            default_price_stars=int(os.getenv("SUB_PRICE_STARS", cls.default_price_stars)),
            ai_api_key=os.getenv("AI_API_KEY", cls.ai_api_key),
            ai_base_url=os.getenv("AI_BASE_URL", cls.ai_base_url),
            ai_model=os.getenv("AI_MODEL", cls.ai_model),
            ai_max_tokens=int(os.getenv("AI_MAX_TOKENS", cls.ai_max_tokens)),
            webapp_url=os.getenv("WEBAPP_URL", cls.webapp_url),
        )


# ======================================================================
# КОНТЕНТ КУРСОВ (статически в коде — просто редактировать/добавлять уроки)
# ======================================================================
# Каждый урок: title, content (объяснение, Markdown), task (практическое
# задание, которое можно решить и проверить в мини-аппе с терминалом).

# ======================================================================
# КОНТЕНТ КУРСОВ (статически в коде — просто редактировать/добавлять уроки)
# ======================================================================
# Структура: язык -> несколько КУРСОВ -> в каждом курсе несколько уроков.
# Курсы внутри языка проходятся по порядку (basics -> practice -> advanced),
# следующий курс открывается после прохождения всех уроков предыдущего.

_PY_BASICS = [
    {"title": "1. Знакомство и первая программа", "content": (
        "Python — один из самых популярных языков программирования: простой синтаксис, "
        "огромное сообщество, используется в вебе, анализе данных, автоматизации, ИИ.\n\n"
        "Программа на Python — это просто текстовый файл с расширением `.py`. Первая программа:\n\n"
        "```python\nprint(\"Привет, мир!\")\n```\n\n"
        "`print()` — функция, которая выводит текст на экран. Текст в кавычках называется "
        "**строкой** (string)."
    ), "task": "Выведи на экран своё имя с помощью print()."},
    {"title": "2. Переменные и типы данных", "content": (
        "Переменная — это имя, под которым хранится значение.\n\n"
        "```python\nage = 16\nname = \"Аня\"\nheight = 170.5\nis_student = True\n```\n\n"
        "Основные типы: `int` (целые числа), `float` (дробные), `str` (строки), "
        "`bool` (True/False). Тип можно узнать функцией `type(x)`."
    ), "task": "Создай переменные для имени, возраста и роста, выведи их все через print()."},
    {"title": "3. Операторы и выражения", "content": (
        "Арифметика: `+ - * /` (деление), `//` (целочисленное деление), `%` (остаток), "
        "`**` (степень).\n\n"
        "```python\nprint(7 // 2)   # 3\nprint(7 % 2)    # 1\nprint(2 ** 10)  # 1024\n```\n\n"
        "Сравнения: `== != > < >= <=` возвращают `True`/`False`. Логика: `and`, `or`, `not`."
    ), "task": "Посчитай, сколько полных недель и остаток дней в 100 днях (через // и %)."},
    {"title": "4. Условия if/elif/else", "content": (
        "```python\nage = 17\nif age >= 18:\n    print(\"Взрослый\")\nelif age >= 14:\n"
        "    print(\"Подросток\")\nelse:\n    print(\"Ребёнок\")\n```\n\n"
        "Важно: отступы (обычно 4 пробела) — это часть синтаксиса Python, а не украшение."
    ), "task": "Напиши программу, которая по числу определяет: положительное, отрицательное или ноль."},
    {"title": "5. Циклы for и while", "content": (
        "```python\nfor i in range(5):\n    print(i)  # 0 1 2 3 4\n\ncount = 0\n"
        "while count < 3:\n    print(\"работаем\")\n    count += 1\n```\n\n"
        "`range(5)` — числа от 0 до 4. `break` прерывает цикл, `continue` — переходит к "
        "следующей итерации."
    ), "task": "Выведи все чётные числа от 1 до 20 с помощью for."},
    {"title": "6. Списки (list)", "content": (
        "```python\nfruits = [\"яблоко\", \"банан\", \"груша\"]\nfruits.append(\"киви\")\n"
        "print(fruits[0])      # яблоко\nprint(len(fruits))    # 4\nfor f in fruits:\n"
        "    print(f)\n```\n\n"
        "Списки изменяемы, могут хранить что угодно, индексация с 0."
    ), "task": "Создай список из 5 своих любимых фильмов/игр и выведи их пронумерованным списком."},
    {"title": "7. Функции", "content": (
        "```python\ndef greet(name):\n    return f\"Привет, {name}!\"\n\n"
        "print(greet(\"Мир\"))\n```\n\n"
        "Функция — переиспользуемый блок кода. `return` возвращает результат. "
        "f-строки (`f\"...{x}...\"`) — удобный способ вставлять переменные в текст."
    ), "task": "Напиши функцию is_even(n), которая возвращает True, если число чётное."},
    {"title": "8. Мини-проект: калькулятор", "content": (
        "Собираем всё вместе: переменные, условия, функции.\n\n"
        "```python\ndef calculate(a, op, b):\n    if op == \"+\":\n        return a + b\n"
        "    if op == \"-\":\n        return a - b\n    if op == \"*\":\n        return a * b\n"
        "    if op == \"/\":\n        return a / b if b != 0 else \"Ошибка: деление на ноль\"\n"
        "    return \"Неизвестная операция\"\n\nprint(calculate(10, \"+\", 5))\n```"
    ), "task": "Допиши калькулятор: добавь операцию возведения в степень (**) и протестируй все случаи."},
]

_PY_PRACTICE = [
    {"title": "1. Строки и их методы", "content": (
        "У строк есть полезные методы:\n\n"
        "```python\ns = \"  Привет, Мир  \"\nprint(s.strip())          # убирает пробелы по краям\n"
        "print(s.lower())          # в нижний регистр\nprint(s.replace(\"Мир\", \"Питон\"))\n"
        "print(\"a,b,c\".split(\",\"))  # ['a', 'b', 'c']\nprint(\"-\".join([\"a\", \"b\", \"c\"]))  # a-b-c\n```"
    ), "task": "Дана строка с текстом через запятую (\"яблоко,банан,груша\") — раздели её на список и выведи каждое слово с большой буквы."},
    {"title": "2. Словари (dict)", "content": (
        "Словарь хранит пары «ключ → значение»:\n\n"
        "```python\nperson = {\"name\": \"Аня\", \"age\": 16}\nprint(person[\"name\"])\n"
        "person[\"city\"] = \"Москва\"\nfor key, value in person.items():\n    print(key, \"=\", value)\n```"
    ), "task": "Создай словарь с ценами трёх товаров и выведи общую сумму всех цен."},
    {"title": "3. Обработка ошибок (try/except)", "content": (
        "Ошибки можно перехватывать, чтобы программа не падала:\n\n"
        "```python\ntry:\n    number = int(input(\"Введите число: \"))\n    print(10 / number)\n"
        "except ValueError:\n    print(\"Это не число!\")\nexcept ZeroDivisionError:\n"
        "    print(\"На ноль делить нельзя!\")\n```"
    ), "task": "Напиши функцию safe_divide(a, b), которая ловит деление на ноль и возвращает None вместо ошибки."},
    {"title": "4. Работа с файлами", "content": (
        "```python\nwith open(\"notes.txt\", \"w\", encoding=\"utf-8\") as f:\n"
        "    f.write(\"Первая заметка\\n\")\n\nwith open(\"notes.txt\", \"r\", encoding=\"utf-8\") as f:\n"
        "    print(f.read())\n```\n\n"
        "`with` сам закрывает файл после использования — так безопаснее."
    ), "task": "Запиши в файл 3 своих любимых цитаты (каждая на новой строке), затем прочитай и выведи файл целиком."},
    {"title": "5. Мини-проект: список задач", "content": (
        "Собираем словари, списки и циклы в мини-проект:\n\n"
        "```python\ntasks = []\n\ndef add_task(text):\n    tasks.append({\"text\": text, \"done\": False})\n\n"
        "def show_tasks():\n    for i, t in enumerate(tasks):\n        mark = \"✅\" if t[\"done\"] else \"⬜\"\n"
        "        print(f\"{i}. {mark} {t['text']}\")\n\nadd_task(\"Выучить Python\")\nshow_tasks()\n```"
    ), "task": "Добавь функцию complete_task(index), которая помечает задачу выполненной (done=True)."},
]

_PY_ADVANCED = [
    {"title": "1. ООП: классы и объекты", "content": (
        "Класс — это «чертёж» для создания объектов со своими данными и поведением:\n\n"
        "```python\nclass Dog:\n    def __init__(self, name):\n        self.name = name\n\n"
        "    def bark(self):\n        return f\"{self.name} говорит: Гав!\"\n\n"
        "rex = Dog(\"Рекс\")\nprint(rex.bark())\n```"
    ), "task": "Создай класс Car с атрибутами brand и speed, и методом accelerate(), увеличивающим speed на 10."},
    {"title": "2. Наследование", "content": (
        "Класс может наследовать поведение другого класса:\n\n"
        "```python\nclass Animal:\n    def __init__(self, name):\n        self.name = name\n"
        "    def speak(self):\n        return \"...\"\n\nclass Cat(Animal):\n    def speak(self):\n"
        "        return f\"{self.name} говорит: Мяу!\"\n\nprint(Cat(\"Мурка\").speak())\n```"
    ), "task": "Создай класс Bird, наследующий Animal, у которого speak() возвращает 'Чирик!'."},
    {"title": "3. Модули и импорты", "content": (
        "Код можно разбивать на файлы-модули и подключать их:\n\n"
        "```python\nimport random\nprint(random.randint(1, 100))\n\nimport math\nprint(math.sqrt(16))\n```\n\n"
        "Стандартная библиотека Python огромна — почти всё уже написано за тебя."
    ), "task": "Используя модуль random, напиши игру «Угадай число от 1 до 10» (загадай через randint, сравнивай с вводом)."},
    {"title": "4. List comprehensions", "content": (
        "Компактный способ создавать списки:\n\n"
        "```python\nsquares = [x ** 2 for x in range(10)]\nevens = [x for x in range(20) if x % 2 == 0]\n"
        "print(squares)\nprint(evens)\n```\n\n"
        "Это то же самое, что цикл for с append(), но короче и читабельнее."
    ), "task": "Через list comprehension создай список кубов чисел от 1 до 10, которые делятся на 3."},
    {"title": "5. Работа с библиотеками (pip)", "content": (
        "`pip install название` ставит сторонние библиотеки. Например `requests` для запросов "
        "в интернет:\n\n"
        "```python\n# pip install requests\nimport requests\nresponse = requests.get(\"https://api.github.com\")\n"
        "print(response.status_code)\n```\n\n"
        "В терминале Mini App это работать не будет (там нет доступа к pip) — зато отлично "
        "работает на установленном локально Python."
    ), "task": "Найди в интернете любую простую библиотеку Python (например, emoji) и опиши в комментарии, что она делает."},
]

_JS_BASICS = [
    {"title": "1. Знакомство и первая программа", "content": (
        "JavaScript — язык веба: работает в браузере и на сервере (Node.js). Им написана "
        "интерактивность практически всех сайтов.\n\n"
        "```javascript\nconsole.log(\"Привет, мир!\");\n```\n\n"
        "`console.log()` выводит значение — аналог `print()` в Python."
    ), "task": "Выведи своё имя через console.log()."},
    {"title": "2. Переменные let/const и типы", "content": (
        "```javascript\nlet age = 16;\nconst name = \"Аня\";\nlet height = 170.5;\n"
        "let isStudent = true;\n```\n\n"
        "`let` — можно менять, `const` — нельзя (лучше использовать по умолчанию). "
        "Типы: `number`, `string`, `boolean`, `object`, `undefined`."
    ), "task": "Объяви переменные для имени, возраста, роста через let/const и выведи их."},
    {"title": "3. Операторы и сравнения", "content": (
        "Арифметика как в математике: `+ - * / %`. \n\n"
        "Важно: используй `===` (строгое равенство), а не `==` — иначе JS будет "
        "приводить типы неожиданным образом.\n\n"
        "```javascript\nconsole.log(5 === \"5\"); // false\nconsole.log(5 == \"5\");  // true\n```"
    ), "task": "Проверь через === и == сравнение true и 1 — объясни разницу в комментарии."},
    {"title": "4. Условия if/else", "content": (
        "```javascript\nlet age = 17;\nif (age >= 18) {\n    console.log(\"Взрослый\");\n"
        "} else if (age >= 14) {\n    console.log(\"Подросток\");\n} else {\n"
        "    console.log(\"Ребёнок\");\n}\n```"
    ), "task": "Напиши программу, определяющую знак числа (положительное/отрицательное/ноль)."},
    {"title": "5. Циклы for и while", "content": (
        "```javascript\nfor (let i = 0; i < 5; i++) {\n    console.log(i);\n}\n\n"
        "let count = 0;\nwhile (count < 3) {\n    console.log(\"работаем\");\n    count++;\n}\n```"
    ), "task": "Выведи все чётные числа от 1 до 20 с помощью for."},
    {"title": "6. Массивы (Array)", "content": (
        "```javascript\nconst fruits = [\"яблоко\", \"банан\", \"груша\"];\n"
        "fruits.push(\"киви\");\nconsole.log(fruits[0]);   // яблоко\n"
        "console.log(fruits.length); // 4\nfruits.forEach(f => console.log(f));\n```"
    ), "task": "Создай массив из 5 любимых фильмов/игр и выведи их через forEach."},
    {"title": "7. Функции и стрелочные функции", "content": (
        "```javascript\nfunction greet(name) {\n    return `Привет, ${name}!`;\n}\n\n"
        "const greet2 = (name) => `Привет, ${name}!`;\n\nconsole.log(greet(\"Мир\"));\n```\n\n"
        "Обратные кавычки (`` ` ``) — шаблонные строки, `${}` вставляет значение переменной."
    ), "task": "Напиши функцию isEven(n), возвращающую true, если число чётное."},
    {"title": "8. Мини-проект: калькулятор", "content": (
        "```javascript\nfunction calculate(a, op, b) {\n    if (op === \"+\") return a + b;\n"
        "    if (op === \"-\") return a - b;\n    if (op === \"*\") return a * b;\n"
        "    if (op === \"/\") return b !== 0 ? a / b : \"Ошибка: деление на ноль\";\n"
        "    return \"Неизвестная операция\";\n}\n\nconsole.log(calculate(10, \"+\", 5));\n```"
    ), "task": "Допиши калькулятор: добавь возведение в степень (**) и протестируй все случаи."},
]

_JS_PRACTICE = [
    {"title": "1. Строки и их методы", "content": (
        "```javascript\nconst s = \"  Привет, Мир  \";\nconsole.log(s.trim());\n"
        "console.log(s.toLowerCase());\nconsole.log(s.replace(\"Мир\", \"JS\"));\n"
        "console.log(\"a,b,c\".split(\",\"));  // ['a','b','c']\n```"
    ), "task": "Дана строка \"яблоко,банан,груша\" — раздели её через split и выведи каждое слово с большой буквы."},
    {"title": "2. Объекты (object)", "content": (
        "```javascript\nconst person = { name: \"Аня\", age: 16 };\nconsole.log(person.name);\n"
        "person.city = \"Москва\";\nfor (const key in person) {\n    console.log(key, \"=\", person[key]);\n}\n```"
    ), "task": "Создай объект с ценами трёх товаров и выведи их общую сумму."},
    {"title": "3. Обработка ошибок (try/catch)", "content": (
        "```javascript\ntry {\n    const number = JSON.parse(\"не число\");\n} catch (error) {\n"
        "    console.log(\"Ошибка:\", error.message);\n}\n```\n\n"
        "`try/catch` перехватывает ошибки, чтобы программа не «падала» целиком."
    ), "task": "Напиши функцию safeDivide(a, b), которая через try/catch возвращает null при делении на ноль."},
    {"title": "4. Массивы: методы поиска и изменения", "content": (
        "```javascript\nconst nums = [1, 2, 3, 4, 5];\nconsole.log(nums.includes(3));  // true\n"
        "console.log(nums.indexOf(4));   // 3\nconsole.log(nums.reverse());    // [5,4,3,2,1]\n```"
    ), "task": "Дан массив чисел — найди в нём максимальное значение без использования Math.max (через цикл)."},
    {"title": "5. Мини-проект: список задач", "content": (
        "```javascript\nconst tasks = [];\n\nfunction addTask(text) {\n"
        "    tasks.push({ text, done: false });\n}\n\nfunction showTasks() {\n"
        "    tasks.forEach((t, i) => {\n        const mark = t.done ? \"✅\" : \"⬜\";\n"
        "        console.log(`${i}. ${mark} ${t.text}`);\n    });\n}\n\naddTask(\"Выучить JS\");\nshowTasks();\n```"
    ), "task": "Добавь функцию completeTask(index), которая помечает задачу выполненной (done=true)."},
]

_JS_ADVANCED = [
    {"title": "1. Классы (class)", "content": (
        "```javascript\nclass Dog {\n    constructor(name) {\n        this.name = name;\n    }\n"
        "    bark() {\n        return `${this.name} говорит: Гав!`;\n    }\n}\n\n"
        "const rex = new Dog(\"Рекс\");\nconsole.log(rex.bark());\n```"
    ), "task": "Создай класс Car с полями brand и speed, и методом accelerate(), увеличивающим speed на 10."},
    {"title": "2. Асинхронность: Promise и async/await", "content": (
        "```javascript\nfunction wait(ms) {\n    return new Promise(resolve => setTimeout(resolve, ms));\n}\n\n"
        "async function main() {\n    console.log(\"Начали\");\n    await wait(1000);\n"
        "    console.log(\"Прошла секунда\");\n}\n\nmain();\n```\n\n"
        "`async/await` — способ писать асинхронный код так, будто он последовательный."
    ), "task": "Напиши async-функцию, которая ждёт 2 секунды и затем выводит 'Готово!'."},
    {"title": "3. Массивы: map, filter, reduce", "content": (
        "```javascript\nconst nums = [1, 2, 3, 4, 5];\nconst doubled = nums.map(n => n * 2);\n"
        "const evens = nums.filter(n => n % 2 === 0);\nconst sum = nums.reduce((acc, n) => acc + n, 0);\n"
        "console.log(doubled, evens, sum);\n```"
    ), "task": "Используя map и filter, из массива слов оставь только те, что длиннее 4 букв, и переведи их в верхний регистр."},
    {"title": "4. JSON: работа с данными", "content": (
        "```javascript\nconst obj = { name: \"Аня\", age: 16 };\nconst json = JSON.stringify(obj);\n"
        "console.log(json);            // '{\"name\":\"Аня\",\"age\":16}'\nconst back = JSON.parse(json);\n"
        "console.log(back.name);       // Аня\n```\n\n"
        "JSON — универсальный формат обмена данными между сервером и клиентом."
    ), "task": "Преврати массив из 3 объектов (имя+возраст) в JSON-строку и обратно, выведи результат."},
    {"title": "5. Модули (import/export)", "content": (
        "```javascript\n// math.js\nexport function square(x) {\n    return x * x;\n}\n\n"
        "// main.js\nimport { square } from \"./math.js\";\nconsole.log(square(5));\n```\n\n"
        "Модули помогают разбивать большой проект на независимые файлы."
    ), "task": "Опиши в комментариях, какие 2 функции ты бы вынес в отдельный модуль utils.js в своём проекте и почему."},
]

_CPP_BASICS = [
    {"title": "1. Знакомство и первая программа", "content": (
        "C++ — быстрый компилируемый язык: игры, системы, embedded, высокопроизводительные "
        "приложения. Синтаксис строже, чем у Python/JS.\n\n"
        "```cpp\n#include <iostream>\nusing namespace std;\n\nint main() {\n"
        "    cout << \"Привет, мир!\" << endl;\n    return 0;\n}\n```\n\n"
        "`#include` подключает библиотеки, `main()` — точка входа программы."
    ), "task": "Выведи своё имя через cout."},
    {"title": "2. Переменные и типы данных", "content": (
        "В C++ у каждой переменной строгий тип, который указывается явно:\n\n"
        "```cpp\nint age = 16;\nstring name = \"Аня\";\ndouble height = 170.5;\n"
        "bool isStudent = true;\n```\n\n"
        "Основные типы: `int`, `double`/`float`, `string` (нужен `#include <string>`), `bool`, `char`."
    ), "task": "Объяви переменные для имени, возраста и роста, выведи их через cout."},
    {"title": "3. Операторы и сравнения", "content": (
        "```cpp\nint a = 7, b = 2;\ncout << a / b << endl;   // 3 (целочисленное деление!)\n"
        "cout << a % b << endl;   // 1\n```\n\n"
        "Внимание: деление `int / int` в C++ ВСЕГДА целочисленное — дробная часть отбрасывается."
    ), "task": "Посчитай сколько полных недель и остаток дней в 100 днях (через / и %)."},
    {"title": "4. Условия if/else if/else", "content": (
        "```cpp\nint age = 17;\nif (age >= 18) {\n    cout << \"Взрослый\";\n"
        "} else if (age >= 14) {\n    cout << \"Подросток\";\n} else {\n"
        "    cout << \"Ребёнок\";\n}\n```"
    ), "task": "Напиши программу, определяющую знак числа (положительное/отрицательное/ноль)."},
    {"title": "5. Циклы for и while", "content": (
        "```cpp\nfor (int i = 0; i < 5; i++) {\n    cout << i << endl;\n}\n\n"
        "int count = 0;\nwhile (count < 3) {\n    cout << \"работаем\" << endl;\n"
        "    count++;\n}\n```"
    ), "task": "Выведи все чётные числа от 1 до 20 с помощью for."},
    {"title": "6. Массивы и vector", "content": (
        "```cpp\n#include <vector>\nvector<string> fruits = {\"яблоко\", \"банан\", \"груша\"};\n"
        "fruits.push_back(\"киви\");\ncout << fruits[0] << endl;\ncout << fruits.size() << endl;\n"
        "for (string f : fruits) {\n    cout << f << endl;\n}\n```\n\n"
        "`vector` — динамический массив (в отличие от обычного `array` с фиксированным размером)."
    ), "task": "Создай vector из 5 любимых фильмов/игр и выведи их в цикле."},
    {"title": "7. Функции", "content": (
        "```cpp\nstring greet(string name) {\n    return \"Привет, \" + name + \"!\";\n}\n\n"
        "int main() {\n    cout << greet(\"Мир\") << endl;\n    return 0;\n}\n```\n\n"
        "У функции обязательно указывается тип возвращаемого значения (или `void`, если ничего не возвращает)."
    ), "task": "Напиши функцию bool isEven(int n), возвращающую true, если число чётное."},
    {"title": "8. Мини-проект: калькулятор", "content": (
        "```cpp\ndouble calculate(double a, char op, double b) {\n"
        "    if (op == '+') return a + b;\n    if (op == '-') return a - b;\n"
        "    if (op == '*') return a * b;\n    if (op == '/') return b != 0 ? a / b : 0;\n"
        "    return 0;\n}\n\nint main() {\n    cout << calculate(10, '+', 5) << endl;\n"
        "    return 0;\n}\n```"
    ), "task": "Допиши калькулятор: обработай деление на ноль отдельным сообщением через cout."},
]

_CPP_PRACTICE = [
    {"title": "1. Строки (std::string)", "content": (
        "```cpp\n#include <string>\nstring s = \"Привет, Мир\";\ncout << s.length() << endl;\n"
        "cout << s.substr(0, 6) << endl;   // Привет\ns += \"!\";\ncout << s << endl;\n```"
    ), "task": "Дана строка с именем — выведи количество символов в ней и первую букву отдельно."},
    {"title": "2. Структуры (struct)", "content": (
        "```cpp\nstruct Person {\n    string name;\n    int age;\n};\n\nint main() {\n"
        "    Person p;\n    p.name = \"Аня\";\n    p.age = 16;\n"
        "    cout << p.name << \" - \" << p.age << endl;\n    return 0;\n}\n```\n\n"
        "`struct` группирует несколько переменных разных типов в одну единицу."
    ), "task": "Создай struct Book с полями title и pages, заполни данными и выведи их."},
    {"title": "3. Указатели — основы", "content": (
        "```cpp\nint x = 10;\nint* p = &x;      // p хранит АДРЕС x\ncout << *p << endl;  // 10 (значение по адресу)\n"
        "*p = 20;\ncout << x << endl;   // 20 (x изменился через указатель!)\n```\n\n"
        "Указатели — то, что отличает C++ от многих других языков. Не пугайся, это просто "
        "«адрес в памяти»."
    ), "task": "Объяви переменную и указатель на неё, измени значение через указатель, выведи результат."},
    {"title": "4. Работа с файлами (fstream)", "content": (
        "```cpp\n#include <fstream>\nofstream out(\"notes.txt\");\nout << \"Первая заметка\" << endl;\n"
        "out.close();\n\nifstream in(\"notes.txt\");\nstring line;\ngetline(in, line);\ncout << line << endl;\n```"
    ), "task": "Запиши в файл 3 строки текста, затем прочитай и выведи их все."},
    {"title": "5. Мини-проект: список задач", "content": (
        "```cpp\n#include <vector>\n#include <string>\nstruct Task { string text; bool done; };\n\n"
        "int main() {\n    vector<Task> tasks;\n    tasks.push_back({\"Выучить C++\", false});\n"
        "    for (int i = 0; i < tasks.size(); i++) {\n"
        "        cout << i << \". \" << (tasks[i].done ? \"[x] \" : \"[ ] \") << tasks[i].text << endl;\n"
        "    }\n    return 0;\n}\n```"
    ), "task": "Добавь ещё 2 задачи в vector и отметь одну из них выполненной (done = true)."},
]

_CPP_ADVANCED = [
    {"title": "1. Классы и объекты (ООП)", "content": (
        "```cpp\nclass Dog {\npublic:\n    string name;\n    Dog(string n) { name = n; }\n"
        "    string bark() { return name + \" говорит: Гав!\"; }\n};\n\nint main() {\n"
        "    Dog rex(\"Рекс\");\n    cout << rex.bark() << endl;\n    return 0;\n}\n```"
    ), "task": "Создай класс Car с полями brand и speed, и методом accelerate(), увеличивающим speed на 10."},
    {"title": "2. Наследование", "content": (
        "```cpp\nclass Animal {\npublic:\n    string name;\n    Animal(string n) { name = n; }\n"
        "    virtual string speak() { return \"...\"; }\n};\n\nclass Cat : public Animal {\npublic:\n"
        "    Cat(string n) : Animal(n) {}\n    string speak() override { return name + \" говорит: Мяу!\"; }\n};\n```"
    ), "task": "Создай класс Bird, наследующий Animal, у которого speak() возвращает 'Чирик!'."},
    {"title": "3. Шаблоны функций (templates)", "content": (
        "```cpp\ntemplate <typename T>\nT maxValue(T a, T b) {\n    return a > b ? a : b;\n}\n\n"
        "int main() {\n    cout << maxValue(3, 7) << endl;       // работает с int\n"
        "    cout << maxValue(3.5, 2.1) << endl;   // и с double тоже!\n    return 0;\n}\n```\n\n"
        "Шаблоны позволяют писать одну функцию, работающую с разными типами данных."
    ), "task": "Напиши шаблонную функцию minValue(a, b), возвращающую меньшее из двух значений."},
    {"title": "4. STL контейнеры: map", "content": (
        "```cpp\n#include <map>\nmap<string, int> ages;\nages[\"Аня\"] = 16;\nages[\"Иван\"] = 17;\n\n"
        "for (auto& pair : ages) {\n    cout << pair.first << \" - \" << pair.second << endl;\n}\n```\n\n"
        "`map` — аналог словаря из Python: хранит пары «ключ → значение»."
    ), "task": "Создай map с ценами трёх товаров и выведи их общую сумму."},
    {"title": "5. Обработка исключений (try/catch)", "content": (
        "```cpp\ntry {\n    int a = 10, b = 0;\n    if (b == 0) throw runtime_error(\"Деление на ноль!\");\n"
        "    cout << a / b;\n} catch (const runtime_error& e) {\n    cout << \"Ошибка: \" << e.what() << endl;\n}\n```"
    ), "task": "Напиши функцию safeDivide(a, b), которая через throw/catch обрабатывает деление на ноль."},
]

LANGUAGES: dict[str, dict] = {
    "python": {
        "title": "Python", "emoji_fallback": "🐍",
        "piston_lang": "python", "piston_version": "3.10.0",
        "courses": {
            "basics": {"title": "Основы Python", "lessons": _PY_BASICS},
            "practice": {"title": "Практика: мини-проекты", "lessons": _PY_PRACTICE},
            "advanced": {"title": "Продвинутый уровень", "lessons": _PY_ADVANCED},
        },
    },
    "javascript": {
        "title": "JavaScript", "emoji_fallback": "📜",
        "piston_lang": "javascript", "piston_version": "18.15.0",
        "courses": {
            "basics": {"title": "Основы JavaScript", "lessons": _JS_BASICS},
            "practice": {"title": "Практика: мини-проекты", "lessons": _JS_PRACTICE},
            "advanced": {"title": "Продвинутый уровень", "lessons": _JS_ADVANCED},
        },
    },
    "cpp": {
        "title": "C++", "emoji_fallback": "⚙️",
        "piston_lang": "cpp", "piston_version": "10.2.0",
        "courses": {
            "basics": {"title": "Основы C++", "lessons": _CPP_BASICS},
            "practice": {"title": "Практика: мини-проекты", "lessons": _CPP_PRACTICE},
            "advanced": {"title": "Продвинутый уровень", "lessons": _CPP_ADVANCED},
        },
    },
}

# Порядок прохождения курсов внутри языка (следующий открывается по завершении предыдущего)
COURSE_ORDER = ["basics", "practice", "advanced"]

POINTS_PER_LESSON = 10
DAILY_UNLOCK_HOURS = 24  # раз в сутки открывается следующий урок


def get_course(lang_key: str, course_key: str) -> Optional[dict]:
    lang = LANGUAGES.get(lang_key)
    if not lang:
        return None
    return lang["courses"].get(course_key)


def get_lesson(lang_key: str, course_key: str, idx: int) -> Optional[dict]:
    course = get_course(lang_key, course_key)
    if not course:
        return None
    lessons = course["lessons"]
    if 0 <= idx < len(lessons):
        return lessons[idx]
    return None


def next_course_key(course_key: str) -> Optional[str]:
    try:
        i = COURSE_ORDER.index(course_key)
    except ValueError:
        return None
    return COURSE_ORDER[i + 1] if i + 1 < len(COURSE_ORDER) else None



# ======================================================================
# ПРЕМИУМ-ЭМОДЗИ: ЛЮБОЙ текст/кнопку можно переопределить премиум-эмодзи
# через админ-панель. {emoji:key} в тексте / _btn(db, key, ...) для кнопок.
# ======================================================================

DEFAULT_EMOJI: dict[str, tuple[str, str]] = {
    "welcome_icon": ("5461070949816291881", "👋"),
    "courses_icon": ("5215212253138604899", "📚"),
    "star": ("5952066863931331270", "⭐"),
    "ai_icon": ("5168182418414240475", "🤖"),
}

TEXT_EMOJI_KEYS: list[tuple[str, str]] = [
    ("welcome_icon", "Приветствие: иконка"),
    ("courses_icon", "Меню курсов: иконка"),
    ("ai_icon", "ИИ-помощник: иконка"),
]

TEXT_EMOJI_FALLBACKS: dict[str, str] = {k: v[1] for k, v in DEFAULT_EMOJI.items()}


# ======================================================================
# ИИ-ПОМОЩНИК (OpenAI-совместимый API) + Markdown → Telegram HTML
# ======================================================================


async def _ai_chat_completion(
    settings: "Settings",
    prompt: str,
    system_prompt: Optional[str] = None,
    max_tokens: Optional[int] = None,
    timeout_seconds: int = 25,
) -> Optional[str]:
    try:
        timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        headers = {"Authorization": f"Bearer {settings.ai_api_key}", "Content-Type": "application/json"}
        payload = {
            "model": settings.ai_model,
            "messages": [
                {"role": "system", "content": system_prompt or (
                    "Ты — помощник по программированию в обучающем боте. Отвечай кратко, понятно, "
                    "с примерами кода через Markdown (```язык ... ```), дружелюбно, без вступлений."
                )},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max_tokens or settings.ai_max_tokens,
        }
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.post(f"{settings.ai_base_url}/chat/completions", json=payload) as resp:
                if resp.status != 200:
                    logger.error("AI API status %s: %s", resp.status, await resp.text())
                    return None
                data = await resp.json()
        choices = data.get("choices") or []
        if not choices:
            return None
        content = (choices[0].get("message") or {}).get("content")
        return content.strip() if content else None
    except Exception:
        logger.exception("AI chat completion failed")
        return None


_MD_CODE_BLOCK_RE = re.compile(r"```(\w*)\n?(.*?)```", re.DOTALL)
_MD_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_MD_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)|(?<!_)_(?!_)(.+?)(?<!_)_(?!_)")
_MD_HEADER_RE = re.compile(r"^#{1,6}\s*(.+)$", re.MULTILINE)


def _markdown_to_telegram_html(text: str) -> str:
    blocks: list[str] = []

    def _stash_code_block(m: "re.Match[str]") -> str:
        lang, code = m.group(1), m.group(2)
        code = code.strip("\n")
        cls = f' class="language-{escape(lang)}"' if lang else ""
        blocks.append(f"<pre><code{cls}>{escape(code)}</code></pre>")
        return f"\x00{len(blocks) - 1}\x00"

    def _stash_inline_code(m: "re.Match[str]") -> str:
        blocks.append(f"<code>{escape(m.group(1))}</code>")
        return f"\x00{len(blocks) - 1}\x00"

    text = _MD_CODE_BLOCK_RE.sub(_stash_code_block, text)
    text = _MD_INLINE_CODE_RE.sub(_stash_inline_code, text)
    text = escape(text)
    text = _MD_HEADER_RE.sub(lambda m: f"<b>{m.group(1)}</b>", text)
    text = _MD_BOLD_RE.sub(lambda m: f"<b>{m.group(1) or m.group(2)}</b>", text)
    text = _MD_ITALIC_RE.sub(lambda m: f"<i>{m.group(1) or m.group(2)}</i>", text)

    def _restore(m: "re.Match[str]") -> str:
        return blocks[int(m.group(1))]

    text = re.sub(r"\x00(\d+)\x00", _restore, text)
    return text.strip()


# ======================================================================
# DATABASE
# ======================================================================


class Database:
    def __init__(self, path: str) -> None:
        self._path = path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_schema(self, owner_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    first_name TEXT NOT NULL DEFAULT '',
                    username TEXT,
                    joined_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
                    reminder_time TEXT,
                    reminder_enabled INTEGER NOT NULL DEFAULT 0,
                    last_reminder_date TEXT,
                    sub_until INTEGER,
                    trial_used INTEGER NOT NULL DEFAULT 0,
                    points INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS progress (
                    user_id INTEGER NOT NULL,
                    lang_key TEXT NOT NULL,
                    course_key TEXT NOT NULL,
                    lesson_index INTEGER NOT NULL DEFAULT 0,
                    unlocked_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
                    updated_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
                    PRIMARY KEY (user_id, lang_key, course_key)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS emoji (
                    key TEXT PRIMARY KEY,
                    emoji_id TEXT NOT NULL,
                    fallback TEXT NOT NULL DEFAULT '⭐'
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS promo_codes (
                    code TEXT PRIMARY KEY,
                    days INTEGER NOT NULL,
                    max_activations INTEGER NOT NULL,
                    activations_count INTEGER NOT NULL DEFAULT 0,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS promo_activations (
                    code TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    activated_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
                    PRIMARY KEY (code, user_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    amount TEXT NOT NULL,
                    charge_id TEXT,
                    created_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
                )
                """
            )
            for key, (emoji_id, fallback) in DEFAULT_EMOJI.items():
                conn.execute(
                    "INSERT OR IGNORE INTO emoji (key, emoji_id, fallback) VALUES (?, ?, ?)",
                    (key, emoji_id, fallback),
                )
            defaults = {
                "price_stars": str(150),
                "subscription_required": "0",  # 0 = всё бесплатно, 1 = курс "basics" бесплатный, дальше по подписке
                "owner_id": str(owner_id),
            }
            for key, val in defaults.items():
                conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, val))

    # -- users ----------------------------------------------------------
    def upsert_user(self, user_id: int, first_name: str, username: Optional[str]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO users (user_id, first_name, username) VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET first_name = excluded.first_name, username = excluded.username
                """,
                (user_id, first_name, username),
            )

    def get_user(self, user_id: int) -> Optional[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()

    def all_user_ids(self) -> list[int]:
        with self.connect() as conn:
            return [r["user_id"] for r in conn.execute("SELECT user_id FROM users").fetchall()]

    def users_with_reminder(self) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM users WHERE reminder_enabled = 1 AND reminder_time IS NOT NULL"
            ).fetchall()

    def set_reminder(self, user_id: int, time_str: Optional[str], enabled: bool) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE users SET reminder_time = ?, reminder_enabled = ? WHERE user_id = ?",
                (time_str, int(enabled), user_id),
            )

    def mark_reminder_sent(self, user_id: int, date_str: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE users SET last_reminder_date = ? WHERE user_id = ?", (date_str, user_id))

    def user_count(self) -> int:
        with self.connect() as conn:
            return conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]

    def active_subscribers_count(self) -> int:
        with self.connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) c FROM users WHERE sub_until IS NOT NULL AND sub_until > strftime('%s','now')"
            ).fetchone()["c"]

    def is_subscribed(self, user_id: int, owner_id: int) -> bool:
        if user_id == owner_id:
            return True
        row = self.get_user(user_id)
        if not row or not row["sub_until"]:
            return False
        return row["sub_until"] > int(time.time())

    def grant_subscription(self, user_id: int, days: int) -> int:
        with self.connect() as conn:
            row = conn.execute("SELECT sub_until FROM users WHERE user_id = ?", (user_id,)).fetchone()
            now = int(time.time())
            base = row["sub_until"] if row and row["sub_until"] and row["sub_until"] > now else now
            new_until = base + days * 86400
            conn.execute("UPDATE users SET sub_until = ? WHERE user_id = ?", (new_until, user_id))
            return new_until

    def trial_available(self, user_id: int) -> bool:
        row = self.get_user(user_id)
        return bool(row and not row["trial_used"])

    def use_trial(self, user_id: int, days: int) -> int:
        with self.connect() as conn:
            conn.execute("UPDATE users SET trial_used = 1 WHERE user_id = ?", (user_id,))
        return self.grant_subscription(user_id, days)

    def record_payment(self, user_id: int, amount: str, charge_id: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO payments (user_id, amount, charge_id) VALUES (?, ?, ?)",
                (user_id, amount, charge_id),
            )

    # -- progress ---------------------------------------------------------
    def get_progress_row(self, user_id: int, lang_key: str, course_key: str) -> Optional[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM progress WHERE user_id = ? AND lang_key = ? AND course_key = ?",
                (user_id, lang_key, course_key),
            ).fetchone()

    def start_course(self, user_id: int, lang_key: str, course_key: str) -> None:
        """Создаёт запись прогресса, если её ещё нет (урок 0 доступен сразу)."""
        with self.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO progress (user_id, lang_key, course_key, lesson_index) VALUES (?, ?, ?, 0)",
                (user_id, lang_key, course_key),
            )

    def advance_progress(self, user_id: int, lang_key: str, course_key: str, new_index: int) -> None:
        """Отмечает, что открылся урок new_index — обновляет unlocked_at (для суточного лимита)."""
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO progress (user_id, lang_key, course_key, lesson_index, unlocked_at, updated_at)
                VALUES (?, ?, ?, ?, strftime('%s','now'), strftime('%s','now'))
                ON CONFLICT(user_id, lang_key, course_key) DO UPDATE SET
                    lesson_index = MAX(progress.lesson_index, excluded.lesson_index),
                    unlocked_at = CASE WHEN excluded.lesson_index > progress.lesson_index
                                       THEN strftime('%s','now') ELSE progress.unlocked_at END,
                    updated_at = strftime('%s','now')
                """,
                (user_id, lang_key, course_key, new_index),
            )

    def all_progress(self, user_id: int) -> dict[tuple[str, str], sqlite3.Row]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM progress WHERE user_id = ?", (user_id,)
            ).fetchall()
            return {(r["lang_key"], r["course_key"]): r for r in rows}

    # -- очки / топ пользователей -----------------------------------------
    def add_points(self, user_id: int, amount: int) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE users SET points = points + ? WHERE user_id = ?", (amount, user_id))

    def top_users(self, limit: int = 10) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                "SELECT user_id, first_name, username, points FROM users "
                "WHERE points > 0 ORDER BY points DESC LIMIT ?",
                (limit,),
            ).fetchall()

    def user_rank(self, user_id: int) -> tuple[int, int]:
        """Возвращает (место, очки) пользователя среди всех с points > 0."""
        with self.connect() as conn:
            row = conn.execute("SELECT points FROM users WHERE user_id = ?", (user_id,)).fetchone()
            points = row["points"] if row else 0
            if points <= 0:
                return (0, 0)
            rank = conn.execute(
                "SELECT COUNT(*) c FROM users WHERE points > ?", (points,)
            ).fetchone()["c"] + 1
            return (rank, points)

    # -- settings / emoji ---------------------------------------------------
    def get_setting(self, key: str, default: str = "") -> str:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def get_emoji_full(self, key: str) -> Optional[tuple[str, str]]:
        with self.connect() as conn:
            row = conn.execute("SELECT emoji_id, fallback FROM emoji WHERE key = ?", (key,)).fetchone()
            return (row["emoji_id"], row["fallback"]) if row else None

    def set_emoji(self, key: str, emoji_id: str, fallback: str = "⭐") -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO emoji (key, emoji_id, fallback) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET emoji_id = excluded.emoji_id, fallback = excluded.fallback",
                (key, emoji_id, fallback),
            )

    # -- promo codes ----------------------------------------------------
    def create_promo(self, code: str, days: int, max_activations: int) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO promo_codes (code, days, max_activations) VALUES (?, ?, ?)",
                (code, days, max_activations),
            )

    def get_promo(self, code: str) -> Optional[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM promo_codes WHERE code = ?", (code,)).fetchone()

    def list_promos(self) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM promo_codes ORDER BY created_at DESC").fetchall()

    def delete_promo(self, code: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM promo_codes WHERE code = ?", (code,))
            conn.execute("DELETE FROM promo_activations WHERE code = ?", (code,))

    def has_activated_promo(self, code: str, user_id: int) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM promo_activations WHERE code = ? AND user_id = ?", (code, user_id)
            ).fetchone()
            return row is not None

    def activate_promo(self, code: str, user_id: int) -> None:
        with self.connect() as conn:
            conn.execute("INSERT INTO promo_activations (code, user_id) VALUES (?, ?)", (code, user_id))
            conn.execute(
                "UPDATE promo_codes SET activations_count = activations_count + 1 WHERE code = ?", (code,)
            )

    def backup_to(self, dest_path: str) -> None:
        with self.connect() as src:
            dest = sqlite3.connect(dest_path)
            try:
                src.backup(dest)
            finally:
                dest.close()


# ======================================================================
# КНОПКИ / КЛАВИАТУРЫ (с поддержкой премиум-эмодзи из админки)
# ======================================================================

_EMOJI_TAG_RE = re.compile(r"\{emoji:(\w+)\}")


def render_emoji_tags(db: Database, text: str) -> str:
    """Заменяет {emoji:key} на <tg-emoji emoji-id="..."> с настроенным (или
    дефолтным юникод-) эмодзи. Используется с parse_mode=HTML."""
    def _sub(m: "re.Match[str]") -> str:
        key = m.group(1)
        full = db.get_emoji_full(key)
        if full and full[0]:
            emoji_id, fallback = full
            return f'<tg-emoji emoji-id="{escape(emoji_id)}">{escape(fallback)}</tg-emoji>'
        return escape(TEXT_EMOJI_FALLBACKS.get(key, ""))
    return _EMOJI_TAG_RE.sub(_sub, text)


def _is_owner(user_id: int, settings: Settings) -> bool:
    return user_id == settings.owner_id


def build_main_reply_keyboard(db: Database) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📚 Курсы"), KeyboardButton(text="⏰ Напоминания")],
            [KeyboardButton(text="🤖 ИИ-помощник"), KeyboardButton(text="👤 Профиль")],
            [KeyboardButton(text="🏆 Топ")],
        ],
        resize_keyboard=True,
    )


def build_language_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for key, lang in LANGUAGES.items():
        rows.append([InlineKeyboardButton(text=f"{lang['emoji_fallback']} {lang['title']}", callback_data=f"lang:{key}")])
    rows.append([InlineKeyboardButton(text="🛠 Как начать писать код", callback_data="platform_guide")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def course_is_unlocked(db: Database, settings: Settings, user_id: int, lang_key: str, course_key: str) -> bool:
    idx_in_order = COURSE_ORDER.index(course_key)
    if idx_in_order > 0:
        prev_key = COURSE_ORDER[idx_in_order - 1]
        prev_total = len(get_course(lang_key, prev_key)["lessons"])
        prev_row = db.get_progress_row(user_id, lang_key, prev_key)
        if not (prev_row and prev_row["lesson_index"] >= prev_total):
            return False
    if idx_in_order > 0 and db.get_setting("subscription_required", "0") == "1":
        return db.is_subscribed(user_id, settings.owner_id)
    return True


def build_course_list_keyboard(db: Database, settings: Settings, user_id: int, lang_key: str) -> InlineKeyboardMarkup:
    lang = LANGUAGES[lang_key]
    rows = []
    for course_key in COURSE_ORDER:
        course = lang["courses"][course_key]
        total = len(course["lessons"])
        row = db.get_progress_row(user_id, lang_key, course_key)
        done = row["lesson_index"] if row else 0
        if not course_is_unlocked(db, settings, user_id, lang_key, course_key):
            prefix = "🔒 "
        elif done >= total:
            prefix = "✅ "
        else:
            prefix = "▶️ "
        rows.append([InlineKeyboardButton(
            text=f"{prefix}{course['title']} ({min(done, total)}/{total})",
            callback_data=f"course:{lang_key}:{course_key}",
        )])
    rows.append([InlineKeyboardButton(text="⬅️ К списку языков", callback_data="courses_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def lesson_access(row: Optional[sqlite3.Row], idx: int) -> str:
    """Возвращает 'open' (можно открыть), 'done' (уже открывался раньше),
    'wait' (появится через сутки) или 'locked' (ещё далеко)."""
    lesson_index = row["lesson_index"] if row else 0
    if idx == 0:
        return "done" if lesson_index > 0 else "open"
    if idx < lesson_index:
        return "done"
    if idx == lesson_index:
        unlocked_at = row["unlocked_at"] if row else int(time.time())
        if int(time.time()) >= unlocked_at + DAILY_UNLOCK_HOURS * 3600:
            return "open"
        return "wait"
    return "locked"


def build_lesson_list_keyboard(db: Database, user_id: int, lang_key: str, course_key: str) -> InlineKeyboardMarkup:
    course = get_course(lang_key, course_key)
    row = db.get_progress_row(user_id, lang_key, course_key)
    rows = []
    for i, lesson in enumerate(course["lessons"]):
        state = lesson_access(row, i)
        prefix = {"open": "▶️ ", "done": "✅ ", "wait": "⏳ ", "locked": "🔒 "}[state]
        rows.append([InlineKeyboardButton(text=f"{prefix}{lesson['title']}", callback_data=f"lesson:{lang_key}:{course_key}:{i}")])
    rows.append([InlineKeyboardButton(text="⬅️ К курсам", callback_data=f"lang:{lang_key}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_lesson_nav_keyboard(lang_key: str, course_key: str, idx: int, is_last_in_course: bool) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="🤖 Спросить ИИ про этот урок", callback_data=f"ask_lesson:{lang_key}:{course_key}:{idx}")]]
    if not is_last_in_course:
        rows.append([InlineKeyboardButton(text="📋 Список уроков", callback_data=f"course:{lang_key}:{course_key}")])
    else:
        nxt = next_course_key(course_key)
        if nxt:
            rows.append([InlineKeyboardButton(text="🎉 Курс пройден! Следующий курс →", callback_data=f"course:{lang_key}:{nxt}")])
        else:
            rows.append([InlineKeyboardButton(text="🏆 Все курсы этого языка пройдены!", callback_data=f"lang:{lang_key}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_buy_sub_keyboard(db: Database) -> InlineKeyboardMarkup:
    price = db.get_setting("price_stars", "150")
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"⭐️ Купить за {price} Stars", callback_data="pay_stars")],
            [InlineKeyboardButton(text="🎁 У меня есть промокод", callback_data="activate_promo_btn")],
        ]
    )


def build_reminder_keyboard(db: Database, enabled: bool) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="🕗 Установить время", callback_data="set_reminder_time")]]
    if enabled:
        rows.append([InlineKeyboardButton(text="🔕 Выключить напоминания", callback_data="reminder_off")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_admin_menu_keyboard(db: Database) -> InlineKeyboardMarkup:
    sub_required = db.get_setting("subscription_required", "0") == "1"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
            [InlineKeyboardButton(text="📣 Рассылка", callback_data="admin_broadcast")],
            [InlineKeyboardButton(text="🎁 Промокоды", callback_data="admin_promo")],
            [InlineKeyboardButton(
                text=f"🔐 Подписка: {'ВКЛ' if sub_required else 'выкл (всё бесплатно)'}",
                callback_data="admin_sub_toggle",
            )],
            [InlineKeyboardButton(text="💎 Премиум-эмодзи", callback_data="admin_emoji")],
            [InlineKeyboardButton(text="💾 Скачать бэкап БД", callback_data="admin_backup")],
        ]
    )


def build_admin_promo_keyboard(db: Database) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Создать промокод", callback_data="admin_promo_create")],
            [InlineKeyboardButton(text="📋 Список промокодов", callback_data="admin_promo_list")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_menu")],
        ]
    )


def build_promo_list_keyboard(promos: list) -> InlineKeyboardMarkup:
    rows = []
    for p in promos:
        label = f"{p['code']} · {p['activations_count']}/{p['max_activations']} · {p['days']}дн."
        if not p["active"]:
            label = "🚫 " + label
        rows.append([InlineKeyboardButton(text=label, callback_data=f"admin_promo_del:{p['code']}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_promo")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_emoji_admin_keyboard() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=label, callback_data=f"admin_emoji_pick:{key}")] for key, label in TEXT_EMOJI_KEYS]
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ======================================================================
# FSM STATES
# ======================================================================


class UserStates(StatesGroup):
    waiting_reminder_time = State()
    waiting_promo_code = State()
    waiting_ai_question = State()
    waiting_ai_lesson_question = State()


class AdminStates(StatesGroup):
    waiting_broadcast_text = State()
    waiting_promo_code_name = State()
    waiting_promo_days = State()
    waiting_promo_max = State()
    waiting_emoji_forward = State()


# ======================================================================
# ХЕЛПЕРЫ ДОСТУПА К УРОКАМ
# ======================================================================


# ======================================================================
# «КАК НАЧАТЬ ПИСАТЬ КОД» — гид по платформам/устройствам
# ======================================================================


def build_platform_device_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡ Без установки (прямо в боте)", callback_data="platform_webapp")],
        [InlineKeyboardButton(text="📱 У меня телефон", callback_data="platform_device:phone")],
        [InlineKeyboardButton(text="💻 У меня компьютер", callback_data="platform_device:pc")],
    ])


def build_phone_os_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤖 Android", callback_data="platform_phone:android")],
        [InlineKeyboardButton(text="🍎 iPhone / iPad", callback_data="platform_phone:ios")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="platform_guide")],
    ])


def build_pc_os_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🪟 Windows", callback_data="platform_pc:windows")],
        [InlineKeyboardButton(text="🍎 macOS", callback_data="platform_pc:mac")],
        [InlineKeyboardButton(text="🐧 Linux", callback_data="platform_pc:linux")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="platform_guide")],
    ])


PLATFORM_PHONE_TEXT = {
    "android": (
        "📱 <b>Android — как писать код</b>\n\n"
        "Самый простой путь — <b>Pydroid 3</b> (для Python) из Google Play: полноценный "
        "офлайн-интерпретатор Python, ничего дополнительно ставить не нужно.\n\n"
        "Для JavaScript/C++ на Android удобен <b>Termux</b> (терминал с Linux-окружением, "
        "тоже из Google Play или F-Droid) — после установки: <code>pkg install nodejs</code> "
        "или <code>pkg install clang</code>.\n\n"
        "Но проще всего — просто открой встроенный терминал прямо в этом боте, без "
        "установки чего-либо (кнопка «💻 Открыть терминал» под каждым уроком)."
    ),
    "ios": (
        "🍎 <b>iPhone/iPad — как писать код</b>\n\n"
        "У Apple строгие ограничения на выполнение кода в приложениях, поэтому выбор "
        "меньше и многие хорошие приложения платные (например Pythonista для Python).\n\n"
        "Самый простой и бесплатный вариант на iOS — <b>встроенный терминал прямо в этом "
        "боте</b> (кнопка «💻 Открыть терминал» под каждым уроком), он открывается в браузере "
        "внутри Telegram и работает без всякой установки."
    ),
}

PLATFORM_PC_TEXT = {
    "windows": (
        "🪟 <b>Windows — как писать код</b>\n\n"
        "🐍 <b>Python</b>: скачай с официального сайта — python.org/downloads (жми большую "
        "жёлтую кнопку Download). При установке обязательно отметь галочку «Add Python to PATH».\n\n"
        "📜 <b>JavaScript (Node.js)</b>: nodejs.org — скачай версию LTS.\n\n"
        "⚙️ <b>C++</b>: проще всего — <b>Code::Blocks</b> (codeblocks.org/downloads) — там сразу "
        "идёт компилятор в комплекте, ничего доустанавливать не нужно.\n\n"
        "Для любого языка также подойдёт <b>Visual Studio Code</b> (code.visualstudio.com) "
        "с соответствующим расширением."
    ),
    "mac": (
        "🍎 <b>macOS — как писать код</b>\n\n"
        "🐍 <b>Python</b>: python.org/downloads, либо через терминал: <code>brew install python</code> "
        "(если установлен Homebrew).\n\n"
        "📜 <b>JavaScript (Node.js)</b>: nodejs.org, либо <code>brew install node</code>.\n\n"
        "⚙️ <b>C++</b>: открой Терминал и выполни <code>xcode-select --install</code> — поставится "
        "компилятор clang от Apple, больше ничего не нужно.\n\n"
        "Для редактирования кода отлично подходит <b>Visual Studio Code</b> (code.visualstudio.com)."
    ),
    "linux": (
        "🐧 <b>Linux — как писать код</b>\n\n"
        "Скорее всего Python уже установлен (проверь: <code>python3 --version</code>).\n\n"
        "📜 <b>JavaScript</b>: <code>sudo apt install nodejs npm</code> (Ubuntu/Debian) или аналог "
        "для твоего дистрибутива.\n\n"
        "⚙️ <b>C++</b>: <code>sudo apt install build-essential</code> — поставит компилятор g++.\n\n"
        "Редактор — <b>Visual Studio Code</b> (code.visualstudio.com) или любой на твой вкус."
    ),
}


# ======================================================================
# ТЕКСТЫ
# ======================================================================


def welcome_text(db: Database) -> str:
    return render_emoji_tags(db, (
        "{emoji:welcome_icon} <b>Добро пожаловать в CodeSchool!</b>\n\n"
        "Здесь ты бесплатно изучишь <b>Python</b>, <b>JavaScript</b> и <b>C++</b> — с уроками, "
        "практическими заданиями, ежедневными напоминаниями и ИИ-помощником, который ответит на "
        "любой вопрос по курсу.\n\n"
        "Выбирай язык и начинай учиться 👇"
    ))


def profile_text(db: Database, settings: Settings, user_id: int, row: sqlite3.Row) -> str:
    lines = []
    for lang_key, lang in LANGUAGES.items():
        total_all = sum(len(c["lessons"]) for c in lang["courses"].values())
        done_all = 0
        for course_key, course in lang["courses"].items():
            prow = db.get_progress_row(user_id, lang_key, course_key)
            done_all += min(prow["lesson_index"], len(course["lessons"])) if prow else 0
        lines.append(f"{lang['emoji_fallback']} {lang['title']}: {done_all}/{total_all} уроков")
    if user_id == settings.owner_id:
        sub_line = "безлимит (владелец)"
    elif row["sub_until"] and row["sub_until"] > int(time.time()):
        sub_line = datetime.fromtimestamp(row["sub_until"]).strftime("активна до %d.%m.%Y")
    else:
        sub_line = "не активна"
    reminder = f"{row['reminder_time']} (вкл)" if row["reminder_enabled"] else "выключены"
    rank, points = db.user_rank(user_id)
    rank_line = f"🏆 Очки: {points} (место в топе: {rank})" if points else "🏆 Очки: 0 — пройди первый урок!"
    return (
        "👤 <b>Профиль</b>\n\n"
        + "\n".join(lines)
        + f"\n\n{rank_line}\n🔐 Подписка: {sub_line}\n⏰ Напоминания: {reminder}"
    )


def leaderboard_text(db: Database) -> str:
    top = db.top_users(10)
    if not top:
        return "🏆 <b>Топ пользователей</b>\n\nПока никто не набрал очков — стань первым!"
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, row in enumerate(top):
        medal = medals[i] if i < 3 else f"{i + 1}."
        name = escape(row["first_name"] or row["username"] or "Пользователь")
        lines.append(f"{medal} {name} — {row['points']} очков")
    return "🏆 <b>Топ пользователей</b>\n\n" + "\n".join(lines)


# ======================================================================
# HANDLERS
# ======================================================================


def register_handlers(dp: Dispatcher, db: Database, settings: Settings) -> None:

    async def show_lesson(bot: Bot, chat_id: int, lang_key: str, course_key: str, idx: int, user_id: int) -> None:
        lesson = get_lesson(lang_key, course_key, idx)
        course = get_course(lang_key, course_key)
        if not lesson or not course:
            await bot.send_message(chat_id, "Урок не найден.")
            return
        if not course_is_unlocked(db, settings, user_id, lang_key, course_key):
            await bot.send_message(chat_id, "🔒 Этот курс доступен по подписке.", reply_markup=build_buy_sub_keyboard(db))
            return
        db.start_course(user_id, lang_key, course_key)
        row = db.get_progress_row(user_id, lang_key, course_key)
        state = lesson_access(row, idx)
        if state in ("wait", "locked"):
            hours_left = 0.0
            if state == "wait" and row:
                hours_left = max(0.0, row["unlocked_at"] + DAILY_UNLOCK_HOURS * 3600 - time.time()) / 3600
            msg = (
                f"⏳ Следующий урок откроется через ~{hours_left:.1f} ч. Один урок в день — так материал "
                f"лучше усваивается! Загляни завтра 🙂"
                if state == "wait" else
                "🔒 До этого урока ещё рано — сначала пройди предыдущие."
            )
            await bot.send_message(chat_id, msg)
            return
        is_new = idx >= (row["lesson_index"] if row else 0)
        db.advance_progress(user_id, lang_key, course_key, idx + 1)
        if is_new:
            db.add_points(user_id, POINTS_PER_LESSON)
        lang = LANGUAGES[lang_key]
        body = _markdown_to_telegram_html(lesson["content"])
        task = escape(lesson["task"])
        points_line = f"\n\n+{POINTS_PER_LESSON} 🏆 очков!" if is_new else ""
        text = (
            f"<b>{escape(lesson['title'])}</b> · {lang['title']} · {course['title']}\n\n"
            f"{body}\n\n📝 <b>Задание:</b> {task}{points_line}"
        )
        is_last = idx == len(course["lessons"]) - 1
        await bot.send_message(
            chat_id, text, parse_mode="HTML",
            reply_markup=build_lesson_nav_keyboard(lang_key, course_key, idx, is_last),
        )
        if settings.webapp_url:
            await bot.send_message(
                chat_id, "Можешь сразу попробовать написать и запустить код в терминале 👇",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(
                        text="💻 Открыть терминал",
                        web_app=WebAppInfo(url=f"{settings.webapp_url}?lang={lang['piston_lang']}"),
                    )
                ]]),
            )

    # -- /start и главное меню -------------------------------------------
    @dp.message(Command("start"))
    async def handle_start(message: Message) -> None:
        user_id = message.from_user.id
        db.upsert_user(user_id, message.from_user.first_name or "", message.from_user.username)
        await message.answer(
            welcome_text(db), parse_mode="HTML", reply_markup=build_main_reply_keyboard(db)
        )
        await message.answer("Выбери язык программирования:", reply_markup=build_language_keyboard())

    @dp.message(F.text == "📚 Курсы")
    async def handle_courses_btn(message: Message) -> None:
        await message.answer("Выбери язык программирования:", reply_markup=build_language_keyboard())

    @dp.message(Command("top"))
    async def handle_top_cmd(message: Message) -> None:
        await message.answer(leaderboard_text(db), parse_mode="HTML")

    @dp.message(F.text == "🏆 Топ")
    async def handle_top_btn(message: Message) -> None:
        await message.answer(leaderboard_text(db), parse_mode="HTML")

    # -- «Как начать писать код» (гид по устройствам/ОС) -------------------
    @dp.callback_query(F.data == "platform_guide")
    async def handle_platform_guide(callback: CallbackQuery) -> None:
        text = "🛠 <b>Как начать писать код?</b>\n\nВыбери, что тебе удобнее:"
        try:
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=build_platform_device_keyboard())
        except TelegramBadRequest:
            await callback.message.answer(text, parse_mode="HTML", reply_markup=build_platform_device_keyboard())
        await callback.answer()

    @dp.callback_query(F.data == "platform_webapp")
    async def handle_platform_webapp(callback: CallbackQuery) -> None:
        if not settings.webapp_url:
            await callback.answer("Встроенный терминал пока не настроен владельцем бота.", show_alert=True)
            return
        await callback.message.answer(
            "⚡ Ничего устанавливать не нужно — просто открой терминал и пиши код прямо здесь:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="💻 Открыть терминал", web_app=WebAppInfo(url=settings.webapp_url))
            ]]),
        )
        await callback.answer()

    @dp.callback_query(F.data.startswith("platform_device:"))
    async def handle_platform_device(callback: CallbackQuery) -> None:
        device = callback.data.split(":", 1)[1]
        if device == "phone":
            await callback.message.edit_text("📱 Какой у тебя телефон?", reply_markup=build_phone_os_keyboard())
        else:
            await callback.message.edit_text("💻 Какая у тебя операционная система?", reply_markup=build_pc_os_keyboard())
        await callback.answer()

    @dp.callback_query(F.data.startswith("platform_phone:"))
    async def handle_platform_phone(callback: CallbackQuery) -> None:
        os_key = callback.data.split(":", 1)[1]
        await callback.message.edit_text(
            PLATFORM_PHONE_TEXT[os_key], parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="platform_guide")]]),
        )
        await callback.answer()

    @dp.callback_query(F.data.startswith("platform_pc:"))
    async def handle_platform_pc(callback: CallbackQuery) -> None:
        os_key = callback.data.split(":", 1)[1]
        await callback.message.edit_text(
            PLATFORM_PC_TEXT[os_key], parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="platform_guide")]]),
        )
        await callback.answer()

    @dp.callback_query(F.data == "courses_menu")
    async def handle_courses_menu(callback: CallbackQuery) -> None:
        await callback.message.edit_text("Выбери язык программирования:", reply_markup=build_language_keyboard())
        await callback.answer()

    @dp.callback_query(F.data.startswith("lang:"))
    async def handle_lang_open(callback: CallbackQuery) -> None:
        lang_key = callback.data.split(":", 1)[1]
        user_id = callback.from_user.id
        text = f"<b>{LANGUAGES[lang_key]['title']}</b> — выбери курс:"
        markup = build_course_list_keyboard(db, settings, user_id, lang_key)
        try:
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
        except TelegramBadRequest:
            await callback.message.answer(text, parse_mode="HTML", reply_markup=markup)
        await callback.answer()

    @dp.callback_query(F.data.startswith("course:"))
    async def handle_course_open(callback: CallbackQuery) -> None:
        _, lang_key, course_key = callback.data.split(":", 2)
        user_id = callback.from_user.id
        if not course_is_unlocked(db, settings, user_id, lang_key, course_key):
            await callback.answer("Сначала пройди предыдущий курс (или оформи подписку).", show_alert=True)
            return
        db.start_course(user_id, lang_key, course_key)
        course = get_course(lang_key, course_key)
        text = f"<b>{LANGUAGES[lang_key]['title']} · {course['title']}</b> — выбери урок:"
        markup = build_lesson_list_keyboard(db, user_id, lang_key, course_key)
        try:
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
        except TelegramBadRequest:
            await callback.message.answer(text, parse_mode="HTML", reply_markup=markup)
        await callback.answer()

    @dp.callback_query(F.data.startswith("lesson:"))
    async def handle_lesson_open(callback: CallbackQuery) -> None:
        _, lang_key, course_key, idx_s = callback.data.split(":", 3)
        await show_lesson(callback.bot, callback.message.chat.id, lang_key, course_key, int(idx_s), callback.from_user.id)
        await callback.answer()

    # -- ИИ-помощник (по уроку и общий) ----------------------------------
    @dp.callback_query(F.data.startswith("ask_lesson:"))
    async def handle_ask_lesson(callback: CallbackQuery, state: FSMContext) -> None:
        _, lang_key, course_key, idx_s = callback.data.split(":", 3)
        await state.set_state(UserStates.waiting_ai_lesson_question)
        await state.update_data(ai_lang=lang_key, ai_course=course_key, ai_idx=int(idx_s))
        await callback.message.answer("Задай вопрос по этому уроку — отвечу как можно понятнее.")
        await callback.answer()

    @dp.message(UserStates.waiting_ai_lesson_question)
    async def handle_ai_lesson_question(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        await state.clear()
        lesson = get_lesson(data.get("ai_lang", ""), data.get("ai_course", ""), data.get("ai_idx", 0))
        context = f"Тема урока: {lesson['title']}\n{lesson['content']}\n\n" if lesson else ""
        icon = render_emoji_tags(db, "{emoji:ai_icon}")
        thinking = await message.answer(f"{icon} Думаю...", parse_mode="HTML")
        answer = await _ai_chat_completion(settings, context + "Вопрос ученика: " + (message.text or ""))
        body = _markdown_to_telegram_html(answer) if answer else "⚠️ Не получилось получить ответ, попробуй ещё раз."
        try:
            await thinking.edit_text(f"{icon} {body}", parse_mode="HTML")
        except Exception:
            await message.answer(f"{icon} {body}", parse_mode="HTML")

    @dp.message(F.text == "🤖 ИИ-помощник")
    async def handle_ai_helper_btn(message: Message, state: FSMContext) -> None:
        await state.set_state(UserStates.waiting_ai_question)
        await message.answer("Задай любой вопрос по Python / JavaScript / C++ — отвечу и приведу пример кода.")

    @dp.message(UserStates.waiting_ai_question)
    async def handle_ai_question(message: Message, state: FSMContext) -> None:
        await state.clear()
        icon = render_emoji_tags(db, "{emoji:ai_icon}")
        thinking = await message.answer(f"{icon} Думаю...", parse_mode="HTML")
        answer = await _ai_chat_completion(settings, message.text or "")
        body = _markdown_to_telegram_html(answer) if answer else "⚠️ Не получилось получить ответ, попробуй ещё раз."
        try:
            await thinking.edit_text(f"{icon} {body}", parse_mode="HTML")
        except Exception:
            await message.answer(f"{icon} {body}", parse_mode="HTML")

    # -- Профиль -----------------------------------------------------------
    @dp.message(F.text == "👤 Профиль")
    async def handle_profile_btn(message: Message) -> None:
        user_id = message.from_user.id
        db.upsert_user(user_id, message.from_user.first_name or "", message.from_user.username)
        row = db.get_user(user_id)
        await message.answer(profile_text(db, settings, user_id, row), parse_mode="HTML")

    # -- Напоминания ---------------------------------------------------
    @dp.message(F.text == "⏰ Напоминания")
    async def handle_reminders_btn(message: Message) -> None:
        row = db.get_user(message.from_user.id)
        enabled = bool(row and row["reminder_enabled"])
        current = f"\n\nСейчас: {row['reminder_time']}" if enabled else ""
        await message.answer(
            "Ежедневное напоминание позанимался ли ты сегодня 📖" + current,
            reply_markup=build_reminder_keyboard(db, enabled),
        )

    @dp.callback_query(F.data == "set_reminder_time")
    async def handle_set_reminder_time(callback: CallbackQuery, state: FSMContext) -> None:
        await state.set_state(UserStates.waiting_reminder_time)
        await callback.message.answer("Во сколько напоминать? Напиши время в формате ЧЧ:ММ, например 19:00")
        await callback.answer()

    @dp.message(UserStates.waiting_reminder_time)
    async def handle_reminder_time_input(message: Message, state: FSMContext) -> None:
        raw = (message.text or "").strip()
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", raw):
            await message.answer("Формат должен быть ЧЧ:ММ, например 08:30. Попробуй ещё раз:")
            return
        await state.clear()
        db.set_reminder(message.from_user.id, raw, True)
        await message.answer(f"✅ Буду напоминать каждый день в {raw}.")

    @dp.callback_query(F.data == "reminder_off")
    async def handle_reminder_off(callback: CallbackQuery) -> None:
        db.set_reminder(callback.from_user.id, None, False)
        await callback.message.edit_text("🔕 Напоминания выключены.")
        await callback.answer()

    # -- Подписка / промокоды ---------------------------------------------
    def _activate_promo(user_id: int, code: str) -> str:
        code = code.strip().upper()
        if not code:
            return "Введите код промокода."
        row = db.get_promo(code)
        if not row or not row["active"]:
            return "🚫 Такого промокода не существует или он деактивирован."
        if row["activations_count"] >= row["max_activations"]:
            return "🚫 У промокода закончился лимит активаций."
        if db.has_activated_promo(code, user_id):
            return "Вы уже активировали этот промокод."
        db.activate_promo(code, user_id)
        new_until = db.grant_subscription(user_id, row["days"])
        until_str = datetime.fromtimestamp(new_until).strftime("%d.%m.%Y")
        return f"🎁 Промокод активирован! Подписка активна до <b>{until_str}</b>."

    @dp.message(Command("promo"))
    async def handle_promo_cmd(message: Message, command: CommandObject) -> None:
        code = (command.args or "").strip()
        if not code:
            await message.answer("Использование: <code>/promo КОД</code>", parse_mode="HTML")
            return
        await message.answer(_activate_promo(message.from_user.id, code), parse_mode="HTML")

    @dp.callback_query(F.data == "activate_promo_btn")
    async def handle_activate_promo_btn(callback: CallbackQuery, state: FSMContext) -> None:
        await state.set_state(UserStates.waiting_promo_code)
        await callback.message.answer("Введи код промокода:")
        await callback.answer()

    @dp.message(UserStates.waiting_promo_code)
    async def handle_promo_code_input(message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer(_activate_promo(message.from_user.id, message.text or ""), parse_mode="HTML")

    @dp.callback_query(F.data == "buy_sub")
    async def handle_buy_sub(callback: CallbackQuery) -> None:
        await callback.message.answer("Оформить доступ ко всем урокам:", reply_markup=build_buy_sub_keyboard(db))
        await callback.answer()

    @dp.callback_query(F.data == "pay_stars")
    async def handle_pay_stars(callback: CallbackQuery) -> None:
        price = int(db.get_setting("price_stars", "150"))
        await callback.bot.send_invoice(
            chat_id=callback.from_user.id,
            title="Подписка CodeSchool",
            description="Полный доступ ко всем урокам на 30 дней",
            payload="sub_30d",
            currency="XTR",
            prices=[LabeledPrice(label="Подписка на 30 дней", amount=price)],
        )
        await callback.answer()

    @dp.pre_checkout_query()
    async def handle_pre_checkout(pre_checkout: PreCheckoutQuery) -> None:
        await pre_checkout.answer(ok=True)

    @dp.message(F.successful_payment)
    async def handle_successful_payment(message: Message) -> None:
        payment = message.successful_payment
        db.record_payment(message.from_user.id, str(payment.total_amount), payment.telegram_payment_charge_id)
        new_until = db.grant_subscription(message.from_user.id, 30)
        until_str = datetime.fromtimestamp(new_until).strftime("%d.%m.%Y")
        await message.answer(f"✅ Оплата прошла! Подписка активна до <b>{until_str}</b>.", parse_mode="HTML")

    # -- Админ-панель -------------------------------------------------------
    @dp.message(Command("admin"))
    async def handle_admin_cmd(message: Message) -> None:
        if not _is_owner(message.from_user.id, settings):
            return
        await message.answer("<b>🔐 Админ-панель</b>", parse_mode="HTML", reply_markup=build_admin_menu_keyboard(db))

    @dp.callback_query(F.data == "admin_menu")
    async def handle_admin_menu(callback: CallbackQuery) -> None:
        if not _is_owner(callback.from_user.id, settings):
            await callback.answer()
            return
        await callback.message.edit_text("<b>🔐 Админ-панель</b>", parse_mode="HTML", reply_markup=build_admin_menu_keyboard(db))
        await callback.answer()

    @dp.callback_query(F.data == "admin_stats")
    async def handle_admin_stats(callback: CallbackQuery) -> None:
        if not _is_owner(callback.from_user.id, settings):
            await callback.answer()
            return
        total = db.user_count()
        active_subs = db.active_subscribers_count()
        text = f"📊 <b>Статистика</b>\n\nПользователей: <b>{total}</b>\nАктивных подписок: <b>{active_subs}</b>"
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=build_admin_menu_keyboard(db))
        await callback.answer()

    @dp.callback_query(F.data == "admin_sub_toggle")
    async def handle_admin_sub_toggle(callback: CallbackQuery) -> None:
        if not _is_owner(callback.from_user.id, settings):
            await callback.answer()
            return
        current = db.get_setting("subscription_required", "0")
        db.set_setting("subscription_required", "0" if current == "1" else "1")
        await callback.message.edit_reply_markup(reply_markup=build_admin_menu_keyboard(db))
        await callback.answer("Переключено")

    @dp.callback_query(F.data == "admin_broadcast")
    async def handle_admin_broadcast(callback: CallbackQuery, state: FSMContext) -> None:
        if not _is_owner(callback.from_user.id, settings):
            await callback.answer()
            return
        await state.set_state(AdminStates.waiting_broadcast_text)
        await callback.message.answer("Пришли текст для рассылки всем пользователям:")
        await callback.answer()

    @dp.message(AdminStates.waiting_broadcast_text)
    async def handle_broadcast_text(message: Message, state: FSMContext) -> None:
        await state.clear()
        text = message.text or ""
        ids = db.all_user_ids()
        sent, failed = 0, 0
        status = await message.answer(f"Рассылка началась (0/{len(ids)})...")
        for i, uid in enumerate(ids, start=1):
            try:
                await message.bot.send_message(uid, text)
                sent += 1
            except Exception:
                failed += 1
            if i % 25 == 0:
                try:
                    await status.edit_text(f"Рассылка идёт ({i}/{len(ids)})...")
                except Exception:
                    pass
            await asyncio.sleep(0.05)
        await status.edit_text(f"✅ Рассылка завершена. Успешно: {sent}, ошибок: {failed}.")

    @dp.callback_query(F.data == "admin_promo")
    async def handle_admin_promo(callback: CallbackQuery) -> None:
        if not _is_owner(callback.from_user.id, settings):
            await callback.answer()
            return
        await callback.message.edit_text("🎁 <b>Промокоды</b>", parse_mode="HTML", reply_markup=build_admin_promo_keyboard(db))
        await callback.answer()

    @dp.callback_query(F.data == "admin_promo_create")
    async def handle_admin_promo_create(callback: CallbackQuery, state: FSMContext) -> None:
        if not _is_owner(callback.from_user.id, settings):
            await callback.answer()
            return
        await state.set_state(AdminStates.waiting_promo_code_name)
        await callback.message.answer("Введи название промокода (латиница/цифры, например SUMMER2026):")
        await callback.answer()

    @dp.message(AdminStates.waiting_promo_code_name)
    async def handle_promo_code_name(message: Message, state: FSMContext) -> None:
        code = (message.text or "").strip().upper()
        if not code or not re.fullmatch(r"[A-ZА-ЯЁ0-9_-]{2,32}", code):
            await message.answer("Код может содержать только буквы, цифры, «-» и «_», длина 2–32. Ещё раз:")
            return
        if db.get_promo(code):
            await message.answer("Такой промокод уже есть. Введи другое название:")
            return
        await state.update_data(promo_code=code)
        await state.set_state(AdminStates.waiting_promo_days)
        await message.answer("Сколько дней подписки даёт этот промокод?")

    @dp.message(AdminStates.waiting_promo_days)
    async def handle_promo_days(message: Message, state: FSMContext) -> None:
        try:
            days = int((message.text or "").strip())
            if days <= 0:
                raise ValueError
        except ValueError:
            await message.answer("Введи положительное целое число дней.")
            return
        await state.update_data(promo_days=days)
        await state.set_state(AdminStates.waiting_promo_max)
        await message.answer("Сколько разных пользователей смогут его активировать?")

    @dp.message(AdminStates.waiting_promo_max)
    async def handle_promo_max(message: Message, state: FSMContext) -> None:
        try:
            max_act = int((message.text or "").strip())
            if max_act <= 0:
                raise ValueError
        except ValueError:
            await message.answer("Введи положительное целое число активаций.")
            return
        data = await state.get_data()
        db.create_promo(data["promo_code"], data["promo_days"], max_act)
        await state.clear()
        await message.answer(
            f"✅ Промокод <code>{data['promo_code']}</code> создан: {data['promo_days']} дн., лимит {max_act}.",
            parse_mode="HTML", reply_markup=build_admin_promo_keyboard(db),
        )

    @dp.callback_query(F.data == "admin_promo_list")
    async def handle_admin_promo_list(callback: CallbackQuery) -> None:
        if not _is_owner(callback.from_user.id, settings):
            await callback.answer()
            return
        promos = db.list_promos()
        if not promos:
            await callback.message.edit_text("Промокодов пока нет.", reply_markup=build_admin_promo_keyboard(db))
        else:
            await callback.message.edit_text("Нажми, чтобы удалить:", reply_markup=build_promo_list_keyboard(promos))
        await callback.answer()

    @dp.callback_query(F.data.startswith("admin_promo_del:"))
    async def handle_admin_promo_del(callback: CallbackQuery) -> None:
        if not _is_owner(callback.from_user.id, settings):
            await callback.answer()
            return
        code = callback.data.split(":", 1)[1]
        db.delete_promo(code)
        await callback.answer(f"{code} удалён", show_alert=True)
        promos = db.list_promos()
        markup = build_promo_list_keyboard(promos) if promos else build_admin_promo_keyboard(db)
        await callback.message.edit_reply_markup(reply_markup=markup)

    @dp.callback_query(F.data == "admin_emoji")
    async def handle_admin_emoji(callback: CallbackQuery) -> None:
        if not _is_owner(callback.from_user.id, settings):
            await callback.answer()
            return
        await callback.message.edit_text(
            "💎 Выбери, для какого текста задать премиум-эмодзи:",
            reply_markup=build_emoji_admin_keyboard(),
        )
        await callback.answer()

    @dp.callback_query(F.data.startswith("admin_emoji_pick:"))
    async def handle_admin_emoji_pick(callback: CallbackQuery, state: FSMContext) -> None:
        if not _is_owner(callback.from_user.id, settings):
            await callback.answer()
            return
        key = callback.data.split(":", 1)[1]
        await state.set_state(AdminStates.waiting_emoji_forward)
        await state.update_data(emoji_key=key)
        await callback.message.answer("Пришли сообщение ТОЛЬКО с одним премиум-эмодзи (просто отправь его как сообщение).")
        await callback.answer()

    @dp.message(AdminStates.waiting_emoji_forward)
    async def handle_emoji_forward(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        key = data.get("emoji_key")
        entities = message.entities or []
        custom = next((e for e in entities if e.type == "custom_emoji"), None)
        if not custom:
            await message.answer("Не нашёл премиум-эмодзи в сообщении. Пришли ещё раз именно эмодзи.")
            return
        fallback = message.text[custom.offset:custom.offset + custom.length] if message.text else "⭐"
        db.set_emoji(key, custom.custom_emoji_id, fallback)
        await state.clear()
        await message.answer("✅ Эмодзи сохранён.", reply_markup=build_emoji_admin_keyboard())

    @dp.callback_query(F.data == "admin_backup")
    async def handle_admin_backup(callback: CallbackQuery) -> None:
        if not _is_owner(callback.from_user.id, settings):
            await callback.answer()
            return
        await callback.answer("Готовлю файл...")
        tmp_path = None
        try:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            tmp_path = os.path.join(tempfile.gettempdir(), f"backup_{stamp}.db")
            db.backup_to(tmp_path)
            await callback.message.answer_document(
                FSInputFile(tmp_path, filename=f"backup_{stamp}.db"),
                caption="💾 Бэкап базы данных (пользователи, прогресс, подписки, промокоды).",
            )
        except Exception:
            logger.exception("Failed to send DB backup")
            await callback.message.answer("Не удалось подготовить бэкап.")
        finally:
            if tmp_path:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass


# ======================================================================
# ФОНОВАЯ ЗАДАЧА: ЕЖЕДНЕВНЫЕ НАПОМИНАНИЯ
# ======================================================================


async def reminder_loop(bot: Bot, db: Database, settings: Settings) -> None:
    """Раз в минуту проверяет, у кого сейчас наступило время напоминания
    (с учётом timezone_offset_hours), и шлёт сообщение — не чаще одного
    раза в календарный день на пользователя."""
    while True:
        try:
            now = datetime.utcnow() + timedelta(hours=settings.timezone_offset_hours)
            now_hm = now.strftime("%H:%M")
            today = now.strftime("%Y-%m-%d")
            for row in db.users_with_reminder():
                if row["reminder_time"] == now_hm and row["last_reminder_date"] != today:
                    db.mark_reminder_sent(row["user_id"], today)
                    try:
                        await bot.send_message(
                            row["user_id"],
                            "📖 Не забудь позаниматься сегодня! Открой «📚 Курсы» и продолжи с того же места.",
                        )
                    except Exception:
                        logger.exception("Failed to send reminder to user_id=%s", row["user_id"])
        except Exception:
            logger.exception("Reminder loop iteration failed")
        await asyncio.sleep(60)


# ======================================================================
# ENTRYPOINT
# ======================================================================


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = Settings.from_env()

    db = Database(settings.db_path)
    db.init_schema(settings.owner_id)

    try:
        backups_dir = os.path.join(os.path.dirname(os.path.abspath(settings.db_path)) or ".", "backups")
        os.makedirs(backups_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        db.backup_to(os.path.join(backups_dir, f"backup_{stamp}.db"))
        existing = sorted(f for f in os.listdir(backups_dir) if f.startswith("backup_") and f.endswith(".db"))
        for old in existing[:-10]:
            try:
                os.remove(os.path.join(backups_dir, old))
            except OSError:
                pass
    except Exception:
        logger.exception("Failed to create startup DB backup (continuing anyway)")

    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=None))
    dp = Dispatcher(storage=MemoryStorage())
    register_handlers(dp, db, settings)

    await bot.set_my_commands([
        BotCommand(command="start", description="Начать / перезапустить"),
        BotCommand(command="promo", description="Активировать промокод"),
        BotCommand(command="top", description="Топ пользователей"),
        BotCommand(command="admin", description="Админ-панель (только владелец)"),
    ])

    asyncio.create_task(reminder_loop(bot, db, settings))

    logger.info("Bot starting. DB file: %s", os.path.abspath(settings.db_path))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
