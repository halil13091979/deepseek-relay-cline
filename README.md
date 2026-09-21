# deepseek-relay-cline

Локальный OpenAI-совместимый релей, который позволяет
[Cline](https://github.com/cline/cline) в VS Code использовать
**DeepSeek Web Chat** как backend для кодинг-агента через
**Chrome DevTools Protocol** (CDP).

Cline думает, что общается с обычным OpenAI-совместимым API, и работает
в **Act mode**: читает файлы, запускает команды, редактирует код, ищет
по проекту. А на другом конце — веб-версия DeepSeek, которая не даёт
API-доступ напрямую.

---

## Содержание

- [Зачем это нужно](#зачем-это-нужно)
- [Как это работает](#как-это-работает)
- [Возможности](#возможности)
- [Требования](#требования)
- [Установка](#установка)
- [Первый запуск](#первый-запуск)
- [Ежедневный запуск](#ежедневный-запуск)
- [Настройка Cline](#настройка-cline)
- [Использование](#использование)
- [Проверка работоспособности](#проверка-работоспособности)
- [Где смотреть логи](#где-смотреть-логи)
- [Полезные команды](#полезные-команды)
- [Частые проблемы](#частые-проблемы)
- [Как обновлять релей](#как-обновлять-релей)
- [Структура проекта](#структура-проекта)
- [Ограничения](#ограничения)
- [Отказ от ответственности](#отказ-от-ответственности)
- [Лицензия](#лицензия)
- [Благодарности](#благодарности)

---

## Зачем это нужно

DeepSeek Web Chat хорош как модель, но у него нет публичного API для
использования в качестве backend'а для кодинг-агентов. При этом Cline
умеет работать с любым OpenAI-совместимым endpoint'ом.

Этот релей закрывает разрыв:

- принимает `/v1/chat/completions` от Cline,
- прокидывает сообщения и список инструментов в DeepSeek Web Chat через CDP,
- вытаскивает ответ (стриминг SSE, парсинг),
- если DeepSeek вернул вызов инструмента — отдаёт его Cline в формате
  OpenAI `tool_calls` с `finish_reason: "tool_calls"`,
- иначе — стримит обычный текст,
- получает результат выполнения инструмента от Cline и отправляет обратно
  в DeepSeek для следующего шага.

Получается полноценный agent loop:

> **DeepSeek планирует → Cline выполняет → результат возвращается → DeepSeek планирует следующий шаг.**

---

## Как это работает

```
┌─────────────────┐    HTTP/SSE    ┌──────────────────┐   WebSocket   ┌──────────────────┐
│  Cline (VS Code)│ ─────────────► │  deepseek-relay  │ ────────────► │  Chrome + CDP    │
│  Act mode       │ ◄───────────── │  127.0.0.1:8080  │ ◄──────────── │  chat.deepseek   │
└─────────────────┘   tool_calls   └──────────────────┘   SSE + DOM   └──────────────────┘
                            │                                                  ▲
                            ▼                                                  │
                    ┌──────────────────┐                                       │
                    │  Файлы, команды, │                                       │
                    │  редактор, поиск │ ──────────────────────────────────────┘
                    └──────────────────┘   (через Cline, не через релей)
```

**Пошагово:**

1. Cline отправляет HTTP POST на `http://127.0.0.1:8080/v1/chat/completions`
   с сообщениями и списком инструментов в формате OpenAI.
2. Релей собирает из этого текстовый промпт и вставляет его в `<textarea>`
   на странице `chat.deepseek.com` через CDP.
3. Релей нажимает кнопку Send.
4. DeepSeek обрабатывает запрос и возвращает ответ через SSE.
5. Релей слушает Network events, ловит запрос `POST /api/v0/chat/completion`
   и забирает его response body.
6. Парсит SSE, собирает текст.
7. Если в тексте есть `{"tool_call": ...}` или `{"tool_calls": [...]}` —
   превращает в OpenAI-совместимый ответ и отправляет Cline.
8. Cline выполняет инструмент, шлёт результат обратно на релей.
9. Релей добавляет результат в промпт и отправляет в DeepSeek снова.
10. Цикл повторяется, пока DeepSeek не вернёт обычный текст без tool_call.

Релей **не выполняет** инструменты сам — этим занимается Cline. Релей только
переводит сообщения между форматом OpenAI и текстовым протоколом DeepSeek Web.

---

## Возможности

- OpenAI-совместимый endpoint `/v1/chat/completions`
- Endpoint'ы `/v1/models` и `/health`
- CORS и OPTIONS для работы из VS Code
- Стриминг (SSE) ответов обратно в Cline
- Поддержка вызовов инструментов в формате OpenAI
- Параллельные вызовы инструментов (несколько в одном ответе)
- Fallback по именам инструментов (если модель «выдумала» имя)
- Чанк usage (оценка токенов), если клиент просит
- Устойчивость к обрывам соединения со стороны клиента
- Логирование всего цикла: запрос Cline → промпт → ответ DeepSeek → вызов инструмента

---

## Требования

| Компонент        | Версия / примечание                              |
|------------------|--------------------------------------------------|
| ОС               | Windows 10 / 11                                  |
| Python           | 3.10 или новее                                   |
| Google Chrome    | Любая свежая версия                              |
| VS Code          | Любая свежая версия                              |
| Cline            | Расширение для VS Code                           |
| websocket-client | Python-пакет, ставится через pip                 |
| Аккаунт DeepSeek | Зарегистрированный на chat.deepseek.com          |

---

## Установка

### Шаг 1. Проверь Python

Открой **PowerShell** (Win+R → `powershell` → Enter) и выполни:

```powershell
python --version
```

Должно вывести что-то вроде `Python 3.11.5`.

**Если пишет «python не является внутренней или внешней командой»:**

- Python не установлен, или не прописан в PATH.
- Скачай с https://www.python.org/downloads/ и при установке **обязательно**
  отметь галочку **"Add python.exe to PATH"**.
- После установки закрой и открой PowerShell заново.
- Проверь ещё раз.

### Шаг 2. Установи websocket-client

```powershell
python -m pip install websocket-client
```

Проверь:

```powershell
python -c "import websocket; print('ok')"
```

Должно вывести `ok`.

### Шаг 3. Клонируй репозиторий

```powershell
cd C:\Projects
git clone https://github.com/halil13091979/deepseek-relay-cline.git
cd deepseek-relay-cline
```

Если Git не установлен — качай с https://git-scm.com/download/win
и при установке выбери **"Git from the command line and also from 3rd-party software"**.

Если не хочешь клонировать — просто скачай ZIP с GitHub и распакуй в
`C:\Projects\deepseek-relay`.

### Шаг 4. Создай `start-chrome.bat`

В папке проекта создай файл `start-chrome.bat` (через Notepad или VS Code):

```bat
@echo off
set PROFILE=%~dp0chrome-profile
set CHROME="C:\Program Files\Google\Chrome\Application\chrome.exe"

if not exist %CHROME% (
    set CHROME="C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
)

start "" %CHROME% ^
    --remote-debugging-port=9222 ^
    --user-data-dir="%PROFILE%" ^
    --no-first-run ^
    --no-default-browser-check ^
    https://chat.deepseek.com/
```

**Если Chrome установлен в другом месте** — проверь путь:

```powershell
Test-Path "C:\Program Files\Google\Chrome\Application\chrome.exe"
Test-Path "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
```

Тот, что вернёт `True` — тот и есть. Если оба `False` — найди Chrome:

```powershell
Get-Command chrome.exe -ErrorAction SilentlyContinue
```

Или запусти Chrome, открой `chrome://version` — там будет `Path` к exe.

### Шаг 5. Создай `start-relay.bat`

```bat
@echo off
cd /d %~dp0
python deepseek-relay.py
pause
```

`pause` в конце — чтобы окно не закрылось, если релей упадёт с ошибкой.

---

## Первый запуск

Порядок важен: сначала Chrome, потом релей, потом Cline.

### 1. Запусти Chrome

Двойной клик по `start-chrome.bat`.

Откроется окно Chrome с **отдельным профилем** (папка `chrome-profile` в
проекте) и страницей https://chat.deepseek.com/.

**Залогинься в DeepSeek.** Введи логин/пароль, пройди капчу если есть.
После успешного входа профиль запомнит сессию — дальше логиниться не надо.

> **Важно:** это **отдельный** профиль Chrome, не твой обычный. Там нет
> твоих закладок, расширений и истории. Это нормально — так надо, чтобы
> CDP-режим не мешал обычному Chrome.

### 2. Проверь, что CDP работает

В том же Chrome открой новую вкладку и перейди по адресу:

```
http://127.0.0.1:9222/json/list
```

Должен вернуться JSON со списком вкладок. Найди там блок с
`"url": "https://chat.deepseek.com/"` — значит всё в порядке.

Если страница не открывается или пишет «Не удаётся получить доступ к сайту» —
значит Chrome запущен **без** флага `--remote-debugging-port=9222`.
Полностью закрой все окна Chrome и запусти снова через `start-chrome.bat`.

### 3. Запусти релей

Двойной клик по `start-relay.bat`.

Должно появиться:

```
======================================================================
DeepSeek Windows Relay
======================================================================
Listening: http://127.0.0.1:8080
Health:    http://127.0.0.1:8080/health
Models:    http://127.0.0.1:8080/v1/models
Chrome CDP: http://127.0.0.1:9222
======================================================================
```

**Окно не закрывай.** Свернуть можно. Закрыть = остановить релей.

### 4. Проверь, что релей отвечает

Открой **второй** PowerShell (первый занят релеем) и выполни:

```powershell
Invoke-RestMethod http://127.0.0.1:8080/health
```

Должно вывести:

```
ok     service
--     -------
True   deepseek-windows-relay
```

Или открой в браузере:

```
http://127.0.0.1:8080/health
```

Должно вернуть:

```json
{"ok": true, "service": "deepseek-windows-relay"}
```

---

## Ежедневный запуск

После первой настройки каждый раз делаешь одно и то же:

```
1. Двойной клик: start-chrome.bat         → Chrome + DeepSeek
2. Двойной клик: start-relay.bat          → релей на 8080
3. VS Code → Cline → Act mode
4. Пишешь задачу
5. Смотришь в окно релея — там весь лог
```

Остановка:

```
1. В окне релея — Ctrl+C
2. Chrome с CDP-профилем можно закрывать
```

Порядок **важен**: если запустить релей **раньше** Chrome, он упадёт с ошибкой
`Не найден открытый DeepSeek в Chrome`. В этом случае просто запусти Chrome
и перезапусти релей.

---

## Настройка Cline

Один раз (потом настройки сохраняются).

### 1. Открой настройки Cline

1. Открой VS Code.
2. Открой панель Cline (иконка на левой панели, или `Ctrl+Shift+P` → `Cline: Open`).
3. Нажми иконку **шестерёнки** (⚙) в верхней части панели Cline.

### 2. Заполни поля

| Поле          | Значение                     |
|---------------|------------------------------|
| API Provider  | OpenAI Compatible            |
| Base URL      | `http://127.0.0.1:8080`      |
| API Key       | `sk-local` (любой непустой)  |
| Model ID      | `deepseek-chat`              |
| Mode          | **Act**                      |

### 3. Включи Act mode

В верхней части панели Cline есть переключатель **Plan / Act**.
Нажми **Act**. Должно стать:

```
Act
```

---

## Использование

Переключись в **Act mode** и давай задачи как обычно — на русском или
английском, неважно.

### Простые задачи

```
Покажи список файлов в корне проекта
```

```
Прочитай package.json и README.md, расскажи что за проект
```

```
Сколько строк в deepseek-relay.py?
```

### Средние задачи

```
Создай файл src/hello.ts с функцией приветствия
```

```
Найди все места, где используется переменная CDP_URL, и покажи их
```

```
Добавь в README.md раздел "Примеры использования"
```

### Сложные задачи

```
Прочитай package.json, найди все зависимости, сгруппируй их по типу
(prod/dev) и сохрани отчёт в dependencies.md
```

```
Прогони npm test, покажи ошибки, если есть — предложи исправления
```

Cline будет вызывать инструменты, релей — прокидывать их в DeepSeek, и
цикл будет повторяться, пока задача не завершится.

---

## Проверка работоспособности

### Быстрая проверка (30 секунд)

Открой в браузере два адреса:

1. **Релей жив?**

   ```
   http://127.0.0.1:8080/health
   ```

   Ожидается:

   ```json
   {"ok": true, "service": "deepseek-windows-relay"}
   ```

2. **Chrome CDP жив?**

   ```
   http://127.0.0.1:9222/json/list
   ```

   Ожидается JSON со списком вкладок. Найди там `"url": "https://chat.deepseek.com/"`.

Если оба работают — запускай Cline и работай.

### Полная проверка (через PowerShell)

```powershell
# 1. Проверь health
Invoke-RestMethod http://127.0.0.1:8080/health

# 2. Проверь models
Invoke-RestMethod http://127.0.0.1:8080/v1/models

# 3. Проверь, что Chrome с CDP отвечает
Invoke-RestMethod http://127.0.0.1:9222/json/list | Select-Object -First 3

# 4. Проверь, что Python видит websocket-client
python -c "import websocket; print('websocket ok')"

# 5. Проверь синтаксис релея
python -m py_compile deepseek-relay.py
```

Если всё зелёное — релей готов к работе.

### Проверка через Cline (финальная)

1. Переключись в Cline на **Act mode**.
2. Дай задачу:

   ```
   Покажи список файлов в корне проекта
   ```

3. Смотри в окно релея. Должно побежать:

   ```
   CDP connected: https://chat.deepseek.com/...
   Textarea node: 123
   Textarea injection result: {'length': 22xxx}
   Using send button node: 456
   Send click command: 9
   Waiting for DeepSeek completion...
   Completion request: 13208.xxx
   Completion finished: 13208.xxx
   Completion body received: 2348 bytes
   ANSWER: '{"tool_call": {...}}'
   TOOL CALLS: [...]
   [HTTP] "POST /v1/chat/completions HTTP/1.1" 200 -
   ```

4. В Cline должен появиться результат — список файлов.

---

## Где смотреть логи

### Логи релея

Всё пишется **в окно `start-relay.bat`**. Открой его — там весь цикл:

```
FULL CLINE REQUEST       ← что прислал Cline
PROMPT TO DEEPSEEK       ← что ушло в DeepSeek
ANSWER: '...'            ← что ответил DeepSeek
TOOL CALLS: [...]        ← распознанный вызов инструмента
[HTTP] streamed answer   ← что ушло обратно в Cline
```

Если хочешь логировать в файл — в `start-relay.bat` замени:

```bat
python deepseek-relay.py
```

на:

```bat
python deepseek-relay.py >> relay.log 2>&1
```

Тогда лог будет и в окне, и в файле `relay.log` рядом с релеем.

### Логи Cline

В панели Cline нажми иконку **"..."** в правом верхнем углу → **"Open Logs"**.
Или в VS Code: `Ctrl+Shift+P` → `Cline: Open Logs`.

### Логи Chrome (если нужно)

В Chrome с CDP-профилем открой:

```
chrome://version
chrome://inspect
```

`chrome://inspect` покажет открытые CDP-таргеты.

---

## Полезные команды

### Git

```powershell
# Перейти в папку проекта
cd C:\Projects\deepseek-relay

# Посмотреть статус (что изменилось)
git status

# Посмотреть, что именно изменилось в файлах
git diff

# Добавить все изменения
git add .

# Добавить конкретный файл
git add README.md

# Закоммитить
git commit -m "Описание что сделал"

# Отправить на GitHub
git push

# Скачать изменения с GitHub
git pull

# Посмотреть историю коммитов
git log --oneline

# Отменить изменения в файле (до последнего коммита)
git checkout -- имя_файла

# Посмотреть, какие remote привязаны
git remote -v
```

### Python

```powershell
# Проверить версию
python --version

# Проверить, что websocket-client установлен
python -c "import websocket; print('ok')"

# Проверить синтаксис релея
python -m py_compile deepseek-relay.py

# Запустить релей (вручную, без .bat)
python deepseek-relay.py

# Обновить websocket-client
python -m pip install --upgrade websocket-client

# Посмотреть, что установлено
python -m pip list
```

### Сеть

```powershell
# Проверить, что релей отвечает
Invoke-RestMethod http://127.0.0.1:8080/health

# Проверить, что Chrome CDP отвечает
Invoke-RestMethod http://127.0.0.1:9222/json/list

# Проверить, что порт 8080 занят (кто-то слушает)
netstat -ano | findstr :8080

# Проверить, что порт 9222 занят (Chrome CDP)
netstat -ano | findstr :9222

# Убить процесс на порту 8080 (взять PID из netstat выше)
taskkill /F /PID ЗДЕСЬ_PID
```

### Процессы

```powershell
# Посмотреть все Python-процессы
Get-Process python

# Убить все Python-процессы (закроет релей)
taskkill /F /IM python.exe

# Посмотреть все процессы Chrome
Get-Process chrome

# Найти окно релея (если потерял)
Get-Process | Where-Object { $_.MainWindowTitle -like "*DeepSeek*" }
```

### Chrome

```powershell
# Запустить Chrome с CDP вручную (если .bat не работает)
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
    --remote-debugging-port=9222 `
    --user-data-dir="C:\Projects\deepseek-relay\chrome-profile" `
    --no-first-run `
    --no-default-browser-check `
    https://chat.deepseek.com/

# Проверить, где установлен Chrome
Get-Command chrome.exe -ErrorAction SilentlyContinue
Test-Path "C:\Program Files\Google\Chrome\Application\chrome.exe"
Test-Path "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
```

### Обновление релея

```powershell
# Остановить релей (Ctrl+C в его окне)
# Заменить deepseek-relay.py на новую версию
# Проверить синтаксис
python -m py_compile deepseek-relay.py
# Запустить
.\start-relay.bat
```

---

## Частые проблемы

### Python

**`python не является внутренней или внешней командой`**

Python не установлен или не прописан в PATH.

- Переустанови Python с https://www.python.org/downloads/
- При установке отметь **"Add python.exe to PATH"**
- Закрой и открой PowerShell заново

**`ModuleNotFoundError: No module named 'websocket'`**

```powershell
python -m pip install websocket-client
```

**`SyntaxError: invalid syntax` при `py_compile`**

Файл `deepseek-relay.py` повреждён или сохранён с ошибкой. Скачай заново с
GitHub, либо скинь ошибку — разберём.

### Chrome / CDP

**`Не найден открытый DeepSeek в Chrome`**

Причины и решения:

1. Chrome запущен **без** `--remote-debugging-port=9222`.
   - Полностью закрой **все** окна Chrome (проверь в трее).
   - Запусти снова `start-chrome.bat`.
2. Вкладка `chat.deepseek.com` не открыта.
   - Открой её вручную.
3. Ты залогинен в **другом** Chrome (обычном), а CDP-профиль пустой.
   - В CDP-профиле залогинься заново.

**`http://127.0.0.1:9222/json/list` не открывается**

То же самое — Chrome без флага `--remote-debugging-port`. Полностью закрой
Chrome, запусти через `start-chrome.bat`.

**Chrome не запускается через `start-chrome.bat`**

Проверь путь к Chrome:

```powershell
Test-Path "C:\Program Files\Google\Chrome\Application\chrome.exe"
```

Если `False` — найди Chrome и поправь путь в `start-chrome.bat`.

**`CDP websocket error` в логах релея**

Chrome с CDP закрылся или завис. Закрой Chrome, запусти `start-chrome.bat`,
перезапусти релей.

### Релей

**`Address already in use` / `порт 8080 занят`**

Старый релей не убит. Закрой все окна `start-relay.bat` или:

```powershell
taskkill /F /IM python.exe
```

⚠️ Убьёт **все** Python-процессы.

**`Connection refused` в Cline**

Релей не запущен или упал. Проверь окно `start-relay.bat`. Если закрылось —
открой заново.

**Релей выдаёт 500 / ошибку**

Смотри лог — там будет `[ERROR] ...` с конкретной причиной. Скинь эту
строку.

**Релей запустился, но `http://127.0.0.1:8080/health` не открывается**

Проверь, что порт занят:

```powershell
netstat -ano | findstr :8080
```

Если ничего не выводит — релей не слушает. Перезапусти.

### Cline / DeepSeek

**DeepSeek отвечает текстом вместо вызова инструмента**

Бывает на длинном контексте — модель «забывает» формат.

Решения:

1. Начни новый чат в DeepSeek — закрой и открой вкладку `chat.deepseek.com`.
2. Переформулируй задачу проще.
3. Перезапусти релей.

В логе релея это видно как `TOOL CALLS: []` или
`Ignoring unknown tool call: ...`.

**`TOOL CALLS` есть, но Cline не выполняет команду**

Смотри, приходит ли в Cline ответ с `finish_reason: "tool_calls"`. Если Cline
показывает JSON как текст — возможно, версия Cline не принимает наш формат.
Скинь лог релея — разберём.

**Cline зависает на «Thinking…»**

- DeepSeek ещё обрабатывает запрос (может занять 10–60 секунд).
- Если больше минуты — смотри лог релея. Возможно, `Completion timeout`.
- Попробуй задачу попроще.

**Cline показывает «Connection refused» или «Failed to connect»**

Релей не запущен. Открой `start-relay.bat`.

**Cline работает, но медленно**

Нормально — каждый шаг это один round-trip до DeepSeek через CDP:
10–30 секунд на шаг. На больших задачах может быть 5–10 минут.

---

## Как обновлять релей

Если у тебя локально есть папка проекта с git:

```powershell
cd C:\Projects\deepseek-relay
git pull
python -m py_compile deepseek-relay.py
```

Если файл обновился — останови релей (Ctrl+C в его окне) и запусти заново:

```powershell
.\start-relay.bat
```

Chrome можно не перезапускать.

Если git нет — скачай `deepseek-relay.py` с GitHub вручную, замени файл,
проверь синтаксис, перезапусти релей.

---

## Структура проекта

```
deepseek-relay/
├── deepseek-relay.py        основной код релея (~1500 строк)
├── start-chrome.bat         запуск Chrome с CDP-профилем
├── start-relay.bat          запуск релея
├── README.md                этот файл
├── .gitignore               что не заливать в git
└── chrome-profile/          отдельный профиль Chrome (не в git!)
    └── ...                  cookie, сессия DeepSeek
```

**Что где:**

- `deepseek-relay.py` — вся логика: HTTP-сервер, CDP-клиент, парсинг SSE,
  преобразование tool_calls.
- `start-chrome.bat` — запускает Chrome с флагами
  `--remote-debugging-port=9222` и `--user-data-dir=chrome-profile`.
- `start-relay.bat` — запускает Python-релей.
- `.gitignore` — исключает `chrome-profile/`, `__pycache__/`, `.venv/` и т.д.
- `chrome-profile/` — **не коммитить**. Там cookie сессии DeepSeek.

---

## Ограничения

- Релей однопоточный на уровне CDP: параллельные запросы к DeepSeek
  становятся в очередь (`browser_lock`).
- Стриминг текста эмулируется (ответ дробится на порции), а не идёт
  в реальном времени из DeepSeek.
- DeepSeek Web не гарантирует стабильность формата ответа — при апдейтах
  веб-интерфейса парсеры (`parse_sse`, `extract_tool_calls`) могут потребовать
  правки.
- Работает только на Windows (пути, PowerShell, `.bat`).
- Chrome должен быть запущен в фоне всё время работы.
- Требуется активная сессия DeepSeek в Chrome (залогинен).
- На длинных задачах DeepSeek может терять формат tool_call.

---

## Отказ от ответственности

Проект использует **веб-интерфейс DeepSeek через браузер**, а не официальный
API. Это может нарушать условия использования DeepSeek. Используй на свой
страх и риск, для личных экспериментов. Не выкладывай токены и сессии
в публичный доступ.

---

## Лицензия

MIT

---

## Благодарности

- [Cline](https://github.com/cline/cline) — расширение-агент для VS Code
- [DeepSeek](https://chat.deepseek.com) — модель и веб-чат
- [websocket-client](https://github.com/websocket-client/websocket-client) —
  Python-клиент для WebSocket, используется для CDP
