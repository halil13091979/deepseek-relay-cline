# deepseek-relay-cline

[English](#english) · [Русский](#русский)

---

<a name="english"></a>

# English

Local OpenAI-compatible relay that lets [Cline](https://github.com/cline/cline)
in VS Code use **DeepSeek Web Chat** as a coding-agent backend through
**Chrome DevTools Protocol** (CDP).

Cline thinks it's talking to a normal OpenAI-compatible API and works in
**Act mode**: reads files, runs commands, edits code, searches the project.
On the other end is the DeepSeek web UI, which doesn't expose a public API.

## Table of Contents

- [Why](#why)
- [How it works](#how-it-works)
- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [First run](#first-run)
- [Daily run](#daily-run)
- [Cline setup](#cline-setup)
- [Usage](#usage)
- [Health checks](#health-checks)
- [Where to find logs](#where-to-find-logs)
- [Useful commands](#useful-commands)
- [Troubleshooting](#troubleshooting)
- [Updating the relay](#updating-the-relay)
- [Project structure](#project-structure)
- [Limitations](#limitations)
- [Disclaimer](#disclaimer)
- [License](#license)
- [Credits](#credits)

## Why

DeepSeek Web Chat is a great model, but it doesn't provide a public API for
use as a coding-agent backend. Cline, on the other hand, can work with any
OpenAI-compatible endpoint.

This relay bridges the gap:

- accepts `/v1/chat/completions` from Cline,
- forwards messages and the tool list to DeepSeek Web Chat via CDP,
- extracts the response (streaming SSE, parsing),
- if DeepSeek returns a tool call, converts it to OpenAI-compatible
  `tool_calls` with `finish_reason: "tool_calls"`,
- otherwise streams plain text,
- receives tool results from Cline and sends them back to DeepSeek for
  the next step.

The result is a full agent loop:

> **DeepSeek plans → Cline executes → result returns → DeepSeek plans the next step.**

## How it works

```
┌─────────────────┐    HTTP/SSE    ┌──────────────────┐   WebSocket   ┌──────────────────┐
│  Cline (VS Code)│ ─────────────► │  deepseek-relay  │ ────────────► │  Chrome + CDP    │
│  Act mode       │ ◄───────────── │  127.0.0.1:8080  │ ◄──────────── │  chat.deepseek   │
└─────────────────┘   tool_calls   └──────────────────┘   SSE + DOM   └──────────────────┘
                            │                                                  ▲
                            ▼                                                  │
                    ┌──────────────────┐                                       │
                    │  Files, commands │                                       │
                    │  editor, search  │ ──────────────────────────────────────┘
                    └──────────────────┘   (through Cline, not the relay)
```

Step by step:

1. Cline sends an HTTP POST to `http://127.0.0.1:8080/v1/chat/completions`
   with messages and the tool list in OpenAI format.
2. The relay builds a text prompt and injects it into the `<textarea>` on
   `chat.deepseek.com` via CDP.
3. The relay clicks Send.
4. DeepSeek processes the request and returns the answer via SSE.
5. The relay listens to Network events, catches
   `POST /api/v0/chat/completion`, and reads its response body.
6. Parses SSE and assembles the text.
7. If the text contains `{"tool_call": ...}` or `{"tool_calls": [...]}`,
   converts it to an OpenAI-compatible response and sends it to Cline.
8. Cline executes the tool and posts the result back to the relay.
9. The relay appends the result to the prompt and sends it to DeepSeek again.
10. The loop repeats until DeepSeek returns plain text without a tool call.

The relay **does not execute** tools itself — Cline does. The relay only
translates between OpenAI format and the DeepSeek Web text protocol.

## Features

- OpenAI-compatible endpoint `/v1/chat/completions`
- `/v1/models` and `/health` endpoints
- CORS and OPTIONS for VS Code
- SSE streaming of responses back to Cline
- OpenAI-format tool call support
- Parallel tool calls (multiple in one response)
- Tool name fallback (if the model "invented" a name)
- Usage chunk (token estimate) when the client asks
- Resilience to client disconnects
- Full-cycle logging: Cline request → prompt → DeepSeek answer → tool call

## Requirements

| Component         | Version / note                          |
|-------------------|-----------------------------------------|
| OS                | Windows 10 / 11                         |
| Python            | 3.10 or newer                           |
| Google Chrome     | Any recent version                      |
| VS Code           | Any recent version                      |
| Cline             | VS Code extension                       |
| websocket-client  | Python package, install via pip         |
| DeepSeek account  | Registered at chat.deepseek.com         |

## Installation

### 1. Check Python

Open **PowerShell** and run:

```powershell
python --version
```

If you see `python is not recognized` — install Python from
https://www.python.org/downloads/ and **tick the "Add python.exe to PATH"
checkbox** during installation. Reopen PowerShell afterwards.

### 2. Install websocket-client

```powershell
python -m pip install websocket-client
```

Verify:

```powershell
python -c "import websocket; print('ok')"
```

### 3. Clone the repo

```powershell
cd C:\Projects
git clone https://github.com/halil13091979/deepseek-relay-cline.git
cd deepseek-relay-cline
```

### 4. Create `start-chrome.bat`

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

### 5. Create `start-relay.bat`

```bat
@echo off
cd /d %~dp0
python deepseek-relay.py
pause
```

## First run

Order matters: Chrome first, then relay, then Cline.

### 1. Start Chrome

Double-click `start-chrome.bat`.

Chrome opens with a **separate profile** (folder `chrome-profile`) and the
page `chat.deepseek.com`.

**Log in to DeepSeek.** The profile will remember your session.

### 2. Verify CDP works

Open this URL in that same Chrome:

```
http://127.0.0.1:9222/json/list
```

You should see a JSON list of tabs. Look for `"url": "https://chat.deepseek.com/"`.

### 3. Start the relay

Double-click `start-relay.bat`. You should see:

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

**Do not close this window.**

### 4. Verify the relay

Open in a browser:

```
http://127.0.0.1:8080/health
```

Expected:

```json
{"ok": true, "service": "deepseek-windows-relay"}
```

## Daily run

```
1. Double-click: start-chrome.bat     → Chrome + DeepSeek
2. Double-click: start-relay.bat      → relay on 8080
3. VS Code → Cline → Act mode
4. Type your task
5. Watch the relay window for logs
```

To stop: `Ctrl+C` in the relay window.

## Cline setup

One-time (settings persist).

In Cline settings (gear icon → **API Configuration**):

| Field         | Value                        |
|---------------|------------------------------|
| API Provider  | OpenAI Compatible            |
| Base URL      | `http://127.0.0.1:8080`      |
| API Key       | `sk-local` (any non-empty)   |
| Model ID      | `deepseek-chat`              |
| Mode          | **Act**                      |

## Usage

Switch to **Act mode** and give tasks as usual:

```
List files in the project root
```

```
Read package.json and README.md, summarize the project
```

```
Create src/hello.ts with a greeting function
```

## Health checks

### Fast check

```
http://127.0.0.1:8080/health     → {"ok": true, ...}
http://127.0.0.1:9222/json/list  → JSON list of tabs
```

### Full check (PowerShell)

```powershell
Invoke-RestMethod http://127.0.0.1:8080/health
Invoke-RestMethod http://127.0.0.1:8080/v1/models
Invoke-RestMethod http://127.0.0.1:9222/json/list | Select-Object -First 3
python -c "import websocket; print('websocket ok')"
python -m py_compile deepseek-relay.py
```

## Where to find logs

**Relay logs:** in the `start-relay.bat` window. Everything is there:
`FULL CLINE REQUEST`, `PROMPT TO DEEPSEEK`, `ANSWER: '...'`, `TOOL CALLS`,
`[HTTP] streamed answer`.

To also write to a file, change `start-relay.bat` to:

```bat
python deepseek-relay.py >> relay.log 2>&1
```

**Cline logs:** in the Cline panel, click **"..."** → **"Open Logs"**.

## Useful commands

### Git

```powershell
cd C:\Projects\deepseek-relay
git status                          # what changed
git diff                            # exact diff
git add .                           # stage all
git commit -m "message"             # commit
git push                            # upload
git pull                            # download
git log --oneline                   # commit history
git remote -v                       # remotes
git checkout -- file.txt            # discard local changes to a file
```

### Python

```powershell
python --version
python -c "import websocket; print('ok')"
python -m py_compile deepseek-relay.py
python deepseek-relay.py            # run manually
python -m pip install --upgrade websocket-client
python -m pip list
```

### Network / ports

```powershell
Invoke-RestMethod http://127.0.0.1:8080/health
Invoke-RestMethod http://127.0.0.1:9222/json/list
netstat -ano | findstr :8080
netstat -ano | findstr :9222
taskkill /F /PID <pid>
```

### Processes

```powershell
Get-Process python
taskkill /F /IM python.exe          # kill all python processes
Get-Process chrome
```

### Chrome

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
    --remote-debugging-port=9222 `
    --user-data-dir="C:\Projects\deepseek-relay\chrome-profile" `
    --no-first-run `
    --no-default-browser-check `
    https://chat.deepseek.com/

Get-Command chrome.exe -ErrorAction SilentlyContinue
Test-Path "C:\Program Files\Google\Chrome\Application\chrome.exe"
```

## Troubleshooting

### Python

**`python is not recognized`** — install Python with the PATH checkbox ticked,
reopen PowerShell.

**`ModuleNotFoundError: No module named 'websocket'`** —
`python -m pip install websocket-client`

**`SyntaxError: invalid syntax` in `py_compile`** — file damaged, re-download
or paste it again.

### Chrome / CDP

**`Не найден открытый DeepSeek в Chrome`** — Chrome wasn't started with
`--remote-debugging-port=9222`, or the DeepSeek tab isn't open, or the CDP
profile isn't logged in. Fully close Chrome, run `start-chrome.bat`, log in.

**`http://127.0.0.1:9222/json/list` doesn't open** — same reason.

**`CDP websocket error`** — Chrome crashed or hung. Restart Chrome and relay.

### Relay

**`Address already in use`** — old relay still running. Close its window or
`taskkill /F /IM python.exe`.

**`Connection refused` in Cline** — relay not running. Start `start-relay.bat`.

**500 / error** — check relay log; there will be an `[ERROR] ...` line.

### Cline / DeepSeek

**DeepSeek replies with plain text instead of a tool call** — happens on long
context. Start a new chat in DeepSeek (close and reopen the tab).

**`TOOL CALLS` present but Cline doesn't execute** — check the relay log.
Possibly the Cline version doesn't accept our format.

**Cline stuck on "Thinking…"** — DeepSeek still processing (10–60 s).
If longer — check relay log for `Completion timeout`.

## Updating the relay

```powershell
cd C:\Projects\deepseek-relay
git pull
python -m py_compile deepseek-relay.py
```

Stop the relay (`Ctrl+C`), start it again. Chrome doesn't need a restart.

## Project structure

```
deepseek-relay/
├── deepseek-relay.py        main relay code (~1500 lines)
├── start-chrome.bat         launch Chrome with CDP profile
├── start-relay.bat          launch the relay
├── README.md                this file
├── .gitignore               what not to push
└── chrome-profile/          separate Chrome profile (not in git!)
    └── ...                  cookies, DeepSeek session
```

## Limitations

- The relay is single-threaded at the CDP level: parallel requests to
  DeepSeek are queued (`browser_lock`).
- Text streaming is emulated (the answer is chunked), not real-time from
  DeepSeek.
- DeepSeek Web doesn't guarantee a stable response format — after UI updates
  the parsers (`parse_sse`, `extract_tool_calls`) may need fixes.
- Windows only (paths, PowerShell, `.bat`).
- Chrome must be running in the background.
- A live DeepSeek session in Chrome is required.

## Disclaimer

This project uses the **DeepSeek web UI through a browser**, not the official
API. This may violate DeepSeek's terms of use. Use at your own risk, for
personal experiments. Do not expose tokens or sessions publicly.

## License

MIT

## Credits

- [Cline](https://github.com/cline/cline) — VS Code coding agent extension
- [DeepSeek](https://chat.deepseek.com) — model and web chat
- [websocket-client](https://github.com/websocket-client/websocket-client) —
  Python WebSocket client used for CDP

---

<a name="русский"></a>

# Русский

Локальный OpenAI-совместимый релей, который позволяет
[Cline](https://github.com/cline/cline) в VS Code использовать
**DeepSeek Web Chat** как backend для кодинг-агента через
**Chrome DevTools Protocol** (CDP).

Cline думает, что общается с обычным OpenAI-совместимым API, и работает
в **Act mode**: читает файлы, запускает команды, редактирует код, ищет
по проекту. А на другом конце — веб-версия DeepSeek, которая не даёт
API-доступ напрямую.

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

Пошагово:

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

## Установка

### Шаг 1. Проверь Python

Открой **PowerShell** и выполни:

```powershell
python --version
```

**Если пишет «python не является внутренней или внешней командой»** —
скачай с https://www.python.org/downloads/ и при установке отметь
**"Add python.exe to PATH"**. После установки закрой и открой PowerShell
заново.

### Шаг 2. Установи websocket-client

```powershell
python -m pip install websocket-client
```

Проверь:

```powershell
python -c "import websocket; print('ok')"
```

### Шаг 3. Клонируй репозиторий

```powershell
cd C:\Projects
git clone https://github.com/halil13091979/deepseek-relay-cline.git
cd deepseek-relay-cline
```

### Шаг 4. Создай `start-chrome.bat`

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

### Шаг 5. Создай `start-relay.bat`

```bat
@echo off
cd /d %~dp0
python deepseek-relay.py
pause
```

## Первый запуск

Порядок важен: сначала Chrome, потом релей, потом Cline.

### 1. Запусти Chrome

Двойной клик по `start-chrome.bat`. Откроется Chrome с **отдельным
профилем** (папка `chrome-profile`) и страницей `chat.deepseek.com`.

**Залогинься в DeepSeek.** Профиль запомнит сессию.

### 2. Проверь, что CDP работает

Открой в том же Chrome:

```
http://127.0.0.1:9222/json/list
```

Должен вернуться JSON со списком вкладок. Найди
`"url": "https://chat.deepseek.com/"`.

### 3. Запусти релей

Двойной клик по `start-relay.bat`. Должно появиться:

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

**Окно не закрывай.**

### 4. Проверь релей

Открой в браузере:

```
http://127.0.0.1:8080/health
```

Ожидается:

```json
{"ok": true, "service": "deepseek-windows-relay"}
```

## Ежедневный запуск

```
1. Двойной клик: start-chrome.bat     → Chrome + DeepSeek
2. Двойной клик: start-relay.bat      → релей на 8080
3. VS Code → Cline → Act mode
4. Пишешь задачу
5. Смотришь в окно релея — там весь лог
```

Остановка: `Ctrl+C` в окне релея.

## Настройка Cline

Один раз в настройках Cline (шестерёнка → **API Configuration**):

| Поле          | Значение                     |
|---------------|------------------------------|
| API Provider  | OpenAI Compatible            |
| Base URL      | `http://127.0.0.1:8080`      |
| API Key       | `sk-local` (любой непустой)  |
| Model ID      | `deepseek-chat`              |
| Mode          | **Act**                      |

## Использование

Переключись в **Act mode** и давай задачи как обычно:

```
Покажи список файлов в корне проекта
```

```
Прочитай package.json и README.md, расскажи что за проект
```

```
Создай файл src/hello.ts с функцией приветствия
```

## Проверка работоспособности

### Быстрая проверка

```
http://127.0.0.1:8080/health     → {"ok": true, ...}
http://127.0.0.1:9222/json/list  → JSON со списком вкладок
```

### Полная проверка (PowerShell)

```powershell
Invoke-RestMethod http://127.0.0.1:8080/health
Invoke-RestMethod http://127.0.0.1:8080/v1/models
Invoke-RestMethod http://127.0.0.1:9222/json/list | Select-Object -First 3
python -c "import websocket; print('websocket ok')"
python -m py_compile deepseek-relay.py
```

## Где смотреть логи

**Логи релея:** в окне `start-relay.bat`. Там всё: `FULL CLINE REQUEST`,
`PROMPT TO DEEPSEEK`, `ANSWER: '...'`, `TOOL CALLS`, `[HTTP] streamed answer`.

Чтобы писать ещё и в файл, замени в `start-relay.bat`:

```bat
python deepseek-relay.py >> relay.log 2>&1
```

**Логи Cline:** в панели Cline нажми **"..."** → **"Open Logs"**.

## Полезные команды

### Git

```powershell
cd C:\Projects\deepseek-relay
git status                          # что изменилось
git diff                            # точный дифф
git add .                           # добавить все
git commit -m "сообщение"           # коммит
git push                            # отправить
git pull                            # скачать
git log --oneline                   # история коммитов
git remote -v                       # remote'ы
git checkout -- file.txt            # отменить локальные правки
```

### Python

```powershell
python --version
python -c "import websocket; print('ok')"
python -m py_compile deepseek-relay.py
python deepseek-relay.py            # запустить вручную
python -m pip install --upgrade websocket-client
python -m pip list
```

### Сеть и порты

```powershell
Invoke-RestMethod http://127.0.0.1:8080/health
Invoke-RestMethod http://127.0.0.1:9222/json/list
netstat -ano | findstr :8080
netstat -ano | findstr :9222
taskkill /F /PID <pid>
```

### Процессы

```powershell
Get-Process python
taskkill /F /IM python.exe          # убить все Python-процессы
Get-Process chrome
```

### Chrome

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
    --remote-debugging-port=9222 `
    --user-data-dir="C:\Projects\deepseek-relay\chrome-profile" `
    --no-first-run `
    --no-default-browser-check `
    https://chat.deepseek.com/

Get-Command chrome.exe -ErrorAction SilentlyContinue
Test-Path "C:\Program Files\Google\Chrome\Application\chrome.exe"
```

## Частые проблемы

### Python

**`python не является внутренней или внешней командой`** — установи Python
с галочкой PATH, перезапусти PowerShell.

**`ModuleNotFoundError: No module named 'websocket'`** —
`python -m pip install websocket-client`

**`SyntaxError: invalid syntax` при `py_compile`** — файл повреждён,
скачай заново.

### Chrome / CDP

**`Не найден открытый DeepSeek в Chrome`** — Chrome без
`--remote-debugging-port=9222`, вкладка не открыта, или CDP-профиль
не залогинен. Полностью закрой Chrome, запусти `start-chrome.bat`, залогинься.

**`http://127.0.0.1:9222/json/list` не открывается** — та же причина.

**`CDP websocket error`** — Chrome упал или завис. Перезапусти Chrome и релей.

### Релей

**`Address already in use`** — старый релей не убит. Закрой окно или
`taskkill /F /IM python.exe`.

**`Connection refused` в Cline** — релей не запущен. Запусти `start-relay.bat`.

**500 / ошибка** — смотри лог релея, там будет `[ERROR] ...`.

### Cline / DeepSeek

**DeepSeek отвечает текстом вместо tool call** — бывает на длинном контексте.
Начни новый чат в DeepSeek (закрой и открой вкладку).

**`TOOL CALLS` есть, но Cline не выполняет** — проверь лог релея. Возможно,
версия Cline не принимает наш формат.

**Cline зависает на «Thinking…»** — DeepSeek ещё обрабатывает (10–60 сек).
Если дольше — смотри лог на `Completion timeout`.

## Как обновлять релей

```powershell
cd C:\Projects\deepseek-relay
git pull
python -m py_compile deepseek-relay.py
```

Останови релей (`Ctrl+C`), запусти заново. Chrome перезапускать не нужно.

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

## Отказ от ответственности

Проект использует **веб-интерфейс DeepSeek через браузер**, а не официальный
API. Это может нарушать условия использования DeepSeek. Используй на свой
страх и риск, для личных экспериментов. Не выкладывай токены и сессии
в публичный доступ.

## Лицензия

MIT

## Благодарности

- [Cline](https://github.com/cline/cline) — расширение-агент для VS Code
- [DeepSeek](https://chat.deepseek.com) — модель и веб-чат
- [websocket-client](https://github.com/websocket-client/websocket-client) —
  Python-клиент для WebSocket, используется для CDP
