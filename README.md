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

- Windows 10 / 11
- Python 3.10+
- Google Chrome
- VS Code с расширением [Cline](https://github.com/cline/cline)
- Python-пакет `websocket-client`

---

## Установка

### 1. Клонируй репозиторий

```cmd
git clone https://github.com/halil13091979/deepseek-relay-cline.git
cd deepseek-relay-cline
```

### 2. Установи Python-зависимость

```cmd
python -m pip install websocket-client
```

### 3. Создай `start-chrome.bat`

Содержимое:

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

### 4. Создай `start-relay.bat`

Содержимое:

```bat
@echo off
cd /d %~dp0
python deepseek-relay.py
pause
```

### 5. Первый запуск Chrome и логин

Двойной клик по `start-chrome.bat`. Откроется Chrome с отдельным профилем
и страницей `chat.deepseek.com`. **Залогинься в DeepSeek** — профиль
запомнит сессию, дальше логиниться не придётся.

---

## Запуск

Каждый раз в таком порядке:

```
1. start-chrome.bat      → Chrome с DeepSeek, залогинен
2. start-relay.bat       → релей на http://127.0.0.1:8080
3. VS Code → Cline → Act mode
4. Пишешь задачу
```

---

## Настройка Cline

Один раз в настройках Cline (шестерёнка → **API Configuration**):

| Поле          | Значение                     |
|---------------|------------------------------|
| API Provider  | OpenAI Compatible            |
| Base URL      | `http://127.0.0.1:8080`      |
| API Key       | `sk-local` (любой непустой)  |
| Model ID      | `deepseek-chat`              |
| Mode          | **Act**                      |

---

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

Cline будет вызывать инструменты, релей — прокидывать их в DeepSeek,
и цикл будет повторяться, пока задача не завершится.

---

## Диагностика

В окне `start-relay.bat` идёт полный лог:

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

**Проверить, что релей жив:**

```
http://127.0.0.1:8080/health
→ {"ok": true, "service": "deepseek-windows-relay"}
```

**Проверить, что Chrome CDP жив:**

```
http://127.0.0.1:9222/json/list
→ JSON со списком вкладок
```

---

## Частые проблемы

### `Не найден открытый DeepSeek в Chrome`

- Chrome запущен без `--remote-debugging-port=9222`.
  Полностью закрой Chrome, запусти через `start-chrome.bat`.
- Вкладка `chat.deepseek.com` не открыта. Открой.
- Ты залогинен в другом Chrome, а CDP-профиль пустой.
  Залогинься в CDP-профиле.

### `Address already in use`

Старый релей не убит. Закрой окно `start-relay.bat` или:

```cmd
taskkill /F /IM python.exe
```

⚠️ Убьёт **все** Python-процессы.

### `ModuleNotFoundError: No module named 'websocket'`

```cmd
python -m pip install websocket-client
```

### DeepSeek отвечает текстом вместо вызова инструмента

Бывает на длинном контексте. Начни новый чат в DeepSeek — закрой и открой
вкладку `chat.deepseek.com`. Контекст очистится, формат вернётся.

### `Connection refused` в Cline

Релей не запущен. Проверь окно `start-relay.bat`.

### Релей падает с `[ERROR] CDP websocket error`

Chrome с CDP закрылся или завис. Закрой Chrome, запусти `start-chrome.bat`,
перезапусти `start-relay.bat`.

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
