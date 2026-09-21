import base64
import json
import re
import threading
import time
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import websocket


CDP_URL = "http://127.0.0.1:9222"
HOST = "127.0.0.1"
PORT = 8080

browser_lock = threading.Lock()


def command_counter():
    value = 0
    while True:
        value += 1
        yield value


def cdp_connect():
    with urllib.request.urlopen(CDP_URL + "/json/list", timeout=5) as r:
        targets = json.loads(r.read().decode("utf-8"))

    target = None
    for item in targets:
        url = item.get("url", "")
        if "chat.deepseek.com" in url and item.get("type") == "page":
            target = item
            break

    if not target:
        raise RuntimeError(
            "Не найден открытый DeepSeek в Chrome. "
            "Запусти Chrome с --remote-debugging-port=9222 "
            "и открой https://chat.deepseek.com/"
        )

    ws_url = target.get("webSocketDebuggerUrl")
    if not ws_url:
        raise RuntimeError("У DeepSeek target отсутствует webSocketDebuggerUrl")

    ws = websocket.create_connection(
        ws_url,
        timeout=5,
        origin="http://127.0.0.1:9222",
    )
    print("CDP connected:", target.get("url", ""))
    return ws


def cdp_send(ws, counter, method, params=None):
    command_id = next(counter)
    message = {"id": command_id, "method": method}
    if params is not None:
        message["params"] = params
    ws.send(json.dumps(message, ensure_ascii=False))
    return command_id


def cdp_wait_response(ws, command_id, timeout=10):
    deadline = time.time() + timeout

    while time.time() < deadline:
        remaining = max(0.1, deadline - time.time())
        ws.settimeout(min(1.0, remaining))

        try:
            raw = ws.recv()
        except websocket.WebSocketTimeoutException:
            continue

        if not raw:
            continue

        try:
            msg = json.loads(raw)
        except Exception:
            continue

        if msg.get("id") != command_id:
            continue

        if "error" in msg:
            raise RuntimeError(
                "CDP error for %s: %s" % (command_id, msg["error"])
            )

        return msg

    raise RuntimeError(
        "CDP command timeout: response id=%s" % command_id
    )


def cdp_result(response):
    result = response.get("result", {})
    return result if isinstance(result, dict) else {}


def get_dom_root(ws, counter):
    command_id = cdp_send(
        ws,
        counter,
        "DOM.getDocument",
        {"depth": -1, "pierce": True},
    )
    response = cdp_wait_response(ws, command_id)
    root = cdp_result(response).get("root", {})

    if not isinstance(root, dict):
        root = {}

    node_id = root.get("nodeId")
    if not node_id:
        raise RuntimeError("DOM root не найден")

    return node_id


def query_all(ws, counter, root_node_id, selector):
    command_id = cdp_send(
        ws,
        counter,
        "DOM.querySelectorAll",
        {"nodeId": root_node_id, "selector": selector},
    )
    response = cdp_wait_response(ws, command_id)
    node_ids = cdp_result(response).get("nodeIds", [])

    return node_ids if isinstance(node_ids, list) else []


def find_textarea(ws, counter):
    root_node_id = get_dom_root(ws, counter)

    selectors = [
        "textarea",
        'textarea[placeholder*="Message"]',
        'textarea[placeholder*="消息"]',
    ]

    for selector in selectors:
        node_ids = query_all(ws, counter, root_node_id, selector)
        if node_ids:
            print("Textarea node:", node_ids[0])
            return node_ids[0]

    raise RuntimeError("Textarea DeepSeek не найден")


def resolve_object(ws, counter, node_id):
    command_id = cdp_send(
        ws,
        counter,
        "DOM.resolveNode",
        {"nodeId": node_id},
    )
    response = cdp_wait_response(ws, command_id)
    obj = cdp_result(response).get("object", {})

    if not isinstance(obj, dict):
        obj = {}

    object_id = obj.get("objectId")
    if not object_id:
        raise RuntimeError(
            "Не удалось получить JS object для nodeId=%s" % node_id
        )

    return object_id


def type_into_deepseek(ws, counter, text):
    node_id = find_textarea(ws, counter)
    object_id = resolve_object(ws, counter, node_id)

    js = """
    function(value) {
        const textarea = this;
        const prototype = Object.getPrototypeOf(textarea);
        const descriptor = Object.getOwnPropertyDescriptor(
            prototype,
            "value"
        );

        if (descriptor && descriptor.set) {
            descriptor.set.call(textarea, value);
        } else {
            textarea.value = value;
        }

        textarea.dispatchEvent(new Event("input", {
            bubbles: true,
            composed: true
        }));

        textarea.dispatchEvent(new Event("change", {
            bubbles: true,
            composed: true
        }));

        textarea.focus();
        return textarea.value;
    }
    """

    command_id = cdp_send(
        ws,
        counter,
        "Runtime.callFunctionOn",
        {
            "objectId": object_id,
            "functionDeclaration": js,
            "arguments": [{"value": text}],
            "returnByValue": True,
        },
    )

    response = cdp_wait_response(ws, command_id)
    result = cdp_result(response)

    if "exceptionDetails" in result:
        raise RuntimeError(
            "Ошибка JavaScript при вводе текста: %s"
            % result["exceptionDetails"]
        )

    remote_result = result.get("result", {})
    if not isinstance(remote_result, dict):
        remote_result = {}

    value = remote_result.get("value")
    if not isinstance(value, str):
        raise RuntimeError("DeepSeek textarea не принял текст")

    print("Textarea injection result:", {"length": len(value)})


def find_send_button(ws, counter):
    root_node_id = get_dom_root(ws, counter)

    selectors = [
        (
            'div[role="button"].'
            'ds-button--primary.'
            'ds-button--filled.'
            'ds-button--circle'
        ),
        'div[role="button"].ds-button--primary',
        'button.ds-button--primary',
        'div[role="button"][aria-label*="Send"]',
        'div[role="button"][aria-label*="发送"]',
    ]

    for selector in selectors:
        node_ids = query_all(ws, counter, root_node_id, selector)
        if node_ids:
            node_id = node_ids[-1]
            print("Using send button node:", node_id)
            print("Send selector:", selector)
            return node_id

    raise RuntimeError("Кнопка Send DeepSeek не найдена")


def click_send(ws, counter):
    node_id = find_send_button(ws, counter)
    object_id = resolve_object(ws, counter, node_id)

    js = """
    function() {
        this.click();
        return true;
    }
    """

    command_id = cdp_send(
        ws,
        counter,
        "Runtime.callFunctionOn",
        {
            "objectId": object_id,
            "functionDeclaration": js,
            "returnByValue": True,
        },
    )

    print("Send click command:", command_id)


def parse_sse(body):
    answer = []

    for raw_line in body.splitlines():
        line = raw_line.strip()

        if not line.startswith("data:"):
            continue

        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue

        try:
            obj = json.loads(data)
        except Exception:
            continue

        if not isinstance(obj, dict):
            continue

        v = obj.get("v")

        if isinstance(v, str):
            answer.append(v)
            continue

        if isinstance(v, dict):
            response = v.get("response")
            if isinstance(response, dict):
                direct = response.get("content")
                if isinstance(direct, str):
                    answer.append(direct)

                fragments = response.get("fragments", [])

                if isinstance(fragments, list):
                    for fragment in fragments:
                        if not isinstance(fragment, dict):
                            continue

                        content = fragment.get("content")
                        if isinstance(content, str):
                            answer.append(content)

    return "".join(answer)


def get_deepseek_answer(ws, counter, timeout=120):
    completion_request_id = None
    deadline = time.time() + timeout

    print("Waiting for DeepSeek completion...")

    while time.time() < deadline:
        remaining = max(0.1, deadline - time.time())
        ws.settimeout(min(2.0, remaining))

        try:
            raw = ws.recv()
        except websocket.WebSocketTimeoutException:
            continue
        except Exception as e:
            raise RuntimeError("CDP websocket error: %r" % e)

        if not raw:
            continue

        try:
            msg = json.loads(raw)
        except Exception:
            continue

        method = msg.get("method")
        params = msg.get("params", {})

        if method == "Network.requestWillBeSent":
            request = params.get("request", {})
            url = request.get("url", "")
            http_method = request.get("method")

            if (
                http_method == "POST"
                and "/api/v0/chat/completion" in url
            ):
                completion_request_id = params.get("requestId")
                print("Completion request:", completion_request_id)
                continue

        if method != "Network.loadingFinished":
            continue

        request_id = params.get("requestId")

        if not (
            completion_request_id
            and request_id == completion_request_id
        ):
            continue

        print("Completion finished:", request_id)

        body_command_id = cdp_send(
            ws,
            counter,
            "Network.getResponseBody",
            {"requestId": request_id},
        )

        body_deadline = time.time() + 15
        completion_body = None

        while time.time() < body_deadline:
            ws.settimeout(1.0)

            try:
                body_raw = ws.recv()
            except websocket.WebSocketTimeoutException:
                continue

            if not body_raw:
                continue

            try:
                body_msg = json.loads(body_raw)
            except Exception:
                continue

            if body_msg.get("id") != body_command_id:
                continue

            if "error" in body_msg:
                raise RuntimeError(
                    "Network.getResponseBody error: %s"
                    % body_msg["error"]
                )

            result = body_msg.get("result", {})
            completion_body = result.get("body", "")

            if result.get("base64Encoded"):
                completion_body = base64.b64decode(
                    completion_body
                ).decode("utf-8", errors="replace")

            break

        if completion_body is None:
            raise RuntimeError(
                "Не удалось получить DeepSeek response body"
            )

        print(
            "Completion body received:",
            len(completion_body),
            "bytes",
        )

        answer = parse_sse(completion_body)

        if not answer:
            raise RuntimeError(
                "DeepSeek completion пришёл, но текст ответа не найден"
            )

        # DeepSeek Web иногда приклеивает служебные маркеры к тексту ответа.
        answer = answer.rstrip()

        for marker in ("FINISHED", "FINISH", "[DONE]", "STOP"):
            if answer.endswith(marker):
                answer = answer[: -len(marker)].rstrip()

        print("ANSWER:", repr(answer[:1000]))
        return answer

    raise RuntimeError("DeepSeek completion timeout")


def ask_deepseek(prompt):
    with browser_lock:
        ws = None

        try:
            ws = cdp_connect()
            counter = command_counter()

            enable_cmd = cdp_send(
                ws,
                counter,
                "Network.enable",
                {},
            )
            cdp_wait_response(ws, enable_cmd, timeout=10)

            type_into_deepseek(ws, counter, prompt)
            time.sleep(0.3)
            click_send(ws, counter)

            return get_deepseek_answer(
                ws,
                counter,
                timeout=120,
            )

        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass


def normalize_content(content):
    if isinstance(content, list):
        pieces = []

        for item in content:
            if not isinstance(item, dict):
                continue

            text = item.get("text")
            if isinstance(text, str):
                pieces.append(text)

        return "\n".join(pieces)

    if isinstance(content, str):
        return content

    if content is None:
        return ""

    return str(content)


def tool_summary(tools):
    if not isinstance(tools, list):
        return []

    result = []

    for item in tools:
        if not isinstance(item, dict):
            continue

        function = item.get("function", {})
        if not isinstance(function, dict):
            continue

        name = function.get("name")
        description = function.get("description", "")
        parameters = function.get("parameters", {})

        if not isinstance(name, str):
            continue

        result.append(
            {
                "name": name,
                "description": description,
                "parameters": parameters,
            }
        )

    return result


def build_alias_map(tools):
    """Строит словарь синонимов -> реальные имена инструментов Cline."""
    names = {
        item.get("name")
        for item in tool_summary(tools)
        if isinstance(item, dict)
    }

    aliases = {}

    for real in names:
        low = real.lower()

        if "run_command" in low or low in ("execute_command", "shell", "bash"):
            for alias in (
                "run_commands",
                "run_command",
                "execute_command",
                "execute",
                "shell",
                "terminal",
                "bash",
                "cmd",
                "powershell",
            ):
                aliases.setdefault(alias, real)

        elif "read_file" in low or low in ("read", "cat", "view"):
            for alias in (
                "read_files",
                "read_file",
                "read",
                "cat",
                "view",
                "open_file",
                "get_file",
            ):
                aliases.setdefault(alias, real)

        elif low in ("editor", "edit_file", "write_to_file", "replace_in_file"):
            for alias in (
                "editor",
                "edit",
                "edit_file",
                "write_file",
                "write_to_file",
                "replace_in_file",
                "create_file",
                "apply_diff",
            ):
                aliases.setdefault(alias, real)

        elif "search" in low:
            for alias in (
                "search_codebase",
                "search_files",
                "search",
                "grep",
                "find",
                "ripgrep",
            ):
                aliases.setdefault(alias, real)

        elif "fetch" in low or "browse" in low:
            for alias in (
                "fetch_web_content",
                "fetch",
                "web_fetch",
                "browse",
                "web_browse",
            ):
                aliases.setdefault(alias, real)

        elif "ask" in low or "question" in low:
            for alias in (
                "ask_question",
                "ask_followup_question",
                "ask_user",
                "question",
            ):
                aliases.setdefault(alias, real)

    return aliases


def build_tool_instruction(tools):
    available = tool_summary(tools)

    if not available:
        return ""

    return """
IMPORTANT TOOL PROTOCOL.

You are connected to an external coding agent. The agent has tools.
When the user request requires a tool, DO NOT pretend that you executed
the tool and DO NOT write a normal-language description of an execution.

Return EXACTLY one JSON object and nothing else.

Single tool:

{
  "tool_call": {
    "name": "EXACT_TOOL_NAME",
    "arguments": {
      "argument_name": "value"
    }
  }
}

Multiple independent tools (use this when you need several tools at once,
and their results do not depend on each other):

{
  "tool_calls": [
    {
      "name": "TOOL_NAME_1",
      "arguments": { }
    },
    {
      "name": "TOOL_NAME_2",
      "arguments": { }
    }
  ]
}

CRITICAL RULES:
- The "name" field MUST be copied EXACTLY from the "Available tools"
  list below. Do NOT invent, translate, rename, or paraphrase names.
  If a name is not in that list, it does not exist.
- "arguments" must be valid JSON matching that tool's parameters schema.
- Do not add explanations, comments, or Markdown fences around the JSON.
- Do not append any marker, suffix, or trailing word after the JSON.
  The answer must END immediately after the closing brace.
- Prefer batching multiple independent tool calls into one "tool_calls"
  array rather than returning them one by one.

If no tool is needed, answer normally in plain text.

Available tools:
""" + json.dumps(
        available,
        ensure_ascii=False,
        indent=2,
    )


def build_prompt(messages, tools):
    parts = []

    for message in messages:
        if not isinstance(message, dict):
            continue

        role = message.get("role", "user")
        content = normalize_content(message.get("content", ""))

        # Preserve tool calls/results from the previous Cline turn.
        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            content += "\nTOOL_CALLS:\n" + json.dumps(
                tool_calls,
                ensure_ascii=False,
                indent=2,
            )

        tool_call_id = message.get("tool_call_id")
        if tool_call_id:
            content = (
                "TOOL_CALL_ID: %s\n%s" % (tool_call_id, content)
            )

        name = message.get("name")
        if name:
            content = "TOOL NAME: %s\n%s" % (name, content)

        parts.append(
            "%s:\n%s" % (str(role).upper(), content)
        )

    base = "\n\n".join(parts)
    instruction = build_tool_instruction(tools)

    if instruction:
        return (
            "You are DeepSeek acting as the reasoning model for a coding "
            "agent. Follow the tool protocol below.\n\n"
            + instruction
            + "\n\n"
            + "CONVERSATION:\n"
            + base
        )

    return base


def _normalize_tool_name(name, allowed, aliases):
    if name in allowed:
        return name

    mapped = aliases.get(name)
    if mapped and mapped in allowed:
        print("Mapping tool name %r -> %r" % (name, mapped))
        return mapped

    print(
        "Ignoring unknown tool call: %r. Available: %s"
        % (name, sorted(allowed))
    )
    return None


def _parse_json_object(text):
    """Пытается распарсить JSON, при неудаче — вытащить объект regexp'ом."""
    if not isinstance(text, str):
        return None

    stripped = text.strip()

    # Remove optional markdown fences if DeepSeek adds them.
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()

        if len(lines) >= 3:
            stripped = "\n".join(lines[1:-1]).strip()

    try:
        obj = json.loads(stripped)
    except Exception:
        obj = None

    if isinstance(obj, dict):
        return obj

    # Fallback: вытащить JSON-объект с "tool_call"/"tool_calls".
    match = re.search(
        r'\{.*?"tool_calls?".*\}',
        stripped,
        re.DOTALL,
    )

    if match:
        try:
            candidate = json.loads(match.group(0))
        except Exception:
            candidate = None

        if isinstance(candidate, dict):
            return candidate

    return None


def extract_tool_calls(answer, tools):
    """Возвращает список OpenAI-совместимых tool_call или []."""
    obj = _parse_json_object(answer)

    if not isinstance(obj, dict):
        return []

    raw_list = []

    single = obj.get("tool_call")
    if isinstance(single, dict):
        raw_list.append(single)

    many = obj.get("tool_calls")
    if isinstance(many, list):
        for item in many:
            if isinstance(item, dict):
                raw_list.append(item)

    if not raw_list:
        return []

    allowed = {
        item.get("name")
        for item in tool_summary(tools)
        if isinstance(item, dict)
    }
    aliases = build_alias_map(tools)

    result = []

    for raw in raw_list:
        name = raw.get("name")
        arguments = raw.get("arguments", {})

        if not isinstance(name, str) or not name:
            continue

        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except Exception:
                continue

        if not isinstance(arguments, dict):
            continue

        real_name = _normalize_tool_name(name, allowed, aliases)
        if not real_name:
            continue

        result.append(
            {
                "id": "call_" + uuid.uuid4().hex[:24],
                "type": "function",
                "function": {
                    "name": real_name,
                    "arguments": json.dumps(
                        arguments,
                        ensure_ascii=False,
                    ),
                },
            }
        )

    return result


def make_tool_response(
    completion_id,
    model,
    now,
    tool_calls,
    stream,
):
    if stream:
        chunks = []

        role_chunk = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": now,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant"},
                    "finish_reason": None,
                }
            ],
        }
        chunks.append(role_chunk)

        delta_calls = []

        for idx, tool_call in enumerate(tool_calls):
            call = tool_call["function"]
            delta_calls.append(
                {
                    "index": idx,
                    "id": tool_call["id"],
                    "type": "function",
                    "function": {
                        "name": call["name"],
                        "arguments": call["arguments"],
                    },
                }
            )

        tool_chunk = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": now,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {"tool_calls": delta_calls},
                    "finish_reason": None,
                }
            ],
        }
        chunks.append(tool_chunk)

        finish_chunk = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": now,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {},
                    "finish_reason": "tool_calls",
                }
            ],
        }
        chunks.append(finish_chunk)

        return chunks

    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": now,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": tool_calls,
                },
                "finish_reason": "tool_calls",
            }
        ],
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        print("[HTTP]", fmt % args)

    def send_json(self, status, obj):
        body = json.dumps(
            obj,
            ensure_ascii=False,
        ).encode("utf-8")

        self.send_response(status)
        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8",
        )
        self.send_header(
            "Content-Length",
            str(len(body)),
        )
        self.send_header(
            "Connection",
            "close",
        )
        self.send_header(
            "Access-Control-Allow-Origin",
            "*",
        )
        self.end_headers()

        self.wfile.write(body)
        self.wfile.flush()
        self.close_connection = True

    def _write_sse(self, chunk):
        try:
            self.wfile.write(
                (
                    "data: "
                    + json.dumps(
                        chunk,
                        ensure_ascii=False,
                    )
                    + "\n\n"
                ).encode("utf-8")
            )
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError):
            print("[HTTP] client disconnected mid-stream")
            return False

    def send_stream(self, chunks):
        self.send_response(200)
        self.send_header(
            "Content-Type",
            "text/event-stream; charset=utf-8",
        )
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        self.close_connection = True

        for chunk in chunks:
            if not self._write_sse(chunk):
                return

        try:
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            print("[HTTP] client disconnected before [DONE]")

    def send_stream_text_chunked(
        self,
        completion_id,
        model,
        now,
        answer,
        prompt_len,
        include_usage,
    ):
        """Эмулирует стриминг: отдаёт текст порциями по ~40 символов."""
        self.send_response(200)
        self.send_header(
            "Content-Type",
            "text/event-stream; charset=utf-8",
        )
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        self.close_connection = True

        role_chunk = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": now,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant"},
                    "finish_reason": None,
                }
            ],
        }

        if not self._write_sse(role_chunk):
            return

        step = 40

        for i in range(0, len(answer), step):
            piece = answer[i : i + step]

            content_chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": now,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": piece},
                        "finish_reason": None,
                    }
                ],
            }

            if not self._write_sse(content_chunk):
                return

            time.sleep(0.02)

        finish_chunk = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": now,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {},
                    "finish_reason": "stop",
                }
            ],
        }

        if not self._write_sse(finish_chunk):
            return

        if include_usage:
            usage_chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": now,
                "model": model,
                "choices": [],
                "usage": {
                    "prompt_tokens": max(1, prompt_len // 4),
                    "completion_tokens": max(1, len(answer) // 4),
                    "total_tokens": max(1, (prompt_len + len(answer)) // 4),
                },
            }

            if not self._write_sse(usage_chunk):
                return

        try:
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            print("[HTTP] client disconnected before [DONE]")

    def send_stream_tool_calls_with_usage(
        self,
        chunks,
        completion_id,
        model,
        now,
        prompt_len,
        answer_len,
        include_usage,
    ):
        self.send_response(200)
        self.send_header(
            "Content-Type",
            "text/event-stream; charset=utf-8",
        )
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        self.close_connection = True

        for chunk in chunks:
            if not self._write_sse(chunk):
                return

        if include_usage:
            usage_chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": now,
                "model": model,
                "choices": [],
                "usage": {
                    "prompt_tokens": max(1, prompt_len // 4),
                    "completion_tokens": max(1, answer_len // 4),
                    "total_tokens": max(1, (prompt_len + answer_len) // 4),
                },
            }

            if not self._write_sse(usage_chunk):
                return

        try:
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            print("[HTTP] client disconnected before [DONE]")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header(
            "Access-Control-Allow-Origin",
            "*",
        )
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, Authorization",
        )
        self.send_header(
            "Access-Control-Allow-Methods",
            "GET, POST, OPTIONS",
        )
        self.end_headers()

    def do_GET(self):
        if self.path == "/v1/models":
            self.send_json(
                200,
                {
                    "object": "list",
                    "data": [
                        {
                            "id": "deepseek-chat",
                            "object": "model",
                            "owned_by": "local-deepseek-web",
                        }
                    ],
                },
            )
            return

        if self.path == "/health":
            self.send_json(
                200,
                {
                    "ok": True,
                    "service": "deepseek-windows-relay",
                },
            )
            return

        self.send_json(
            404,
            {"error": "not_found"},
        )

    def do_POST(self):
        if not self.path.startswith("/v1/chat/completions"):
            self.send_json(
                404,
                {"error": "not_found"},
            )
            return

        try:
            length = int(
                self.headers.get(
                    "Content-Length",
                    "0",
                )
            )

            raw = self.rfile.read(length)
            request = json.loads(
                raw.decode("utf-8-sig")
            )

            print()
            print("=" * 70)
            print("FULL CLINE REQUEST")
            print("=" * 70)
            print(
                json.dumps(
                    request,
                    ensure_ascii=False,
                    indent=2,
                )
            )
            print("=" * 70)

            messages = request.get("messages", [])
            tools = request.get("tools", [])
            tool_choice = request.get("tool_choice")
            stream = bool(request.get("stream", False))

            stream_options = request.get("stream_options") or {}
            include_usage = bool(
                stream_options.get("include_usage")
            )

            print("TOOLS:", len(tools) if isinstance(tools, list) else 0)
            print(
                "tool_choice:",
                json.dumps(
                    tool_choice,
                    ensure_ascii=False,
                ),
            )
            print("stream:", stream)
            print("include_usage:", include_usage)

            prompt = build_prompt(
                messages,
                tools,
            )

            print()
            print("=" * 70)
            print("PROMPT TO DEEPSEEK")
            print("=" * 70)
            print("PROMPT LENGTH:", len(prompt))
            print("--- HEAD ---")
            print(prompt[:2000])
            print("--- TAIL ---")
            print(prompt[-12000:])
            print("=" * 70)

            answer = ask_deepseek(prompt)

            if tool_choice == "none":
                tool_calls = []
            else:
                tool_calls = extract_tool_calls(answer, tools)

            if tool_choice == "required" and not tool_calls:
                print(
                    "WARNING: tool_choice=required, "
                    "но DeepSeek не выдал tool_call"
                )

            now = int(time.time())
            completion_id = "chatcmpl-" + uuid.uuid4().hex
            model = request.get(
                "model",
                "deepseek-chat",
            )

            if tool_calls:
                print(
                    "TOOL CALLS:",
                    json.dumps(
                        tool_calls,
                        ensure_ascii=False,
                        indent=2,
                    ),
                )

                if stream:
                    chunks = make_tool_response(
                        completion_id,
                        model,
                        now,
                        tool_calls,
                        True,
                    )
                    self.send_stream_tool_calls_with_usage(
                        chunks,
                        completion_id,
                        model,
                        now,
                        len(prompt),
                        len(answer),
                        include_usage,
                    )
                else:
                    response = make_tool_response(
                        completion_id,
                        model,
                        now,
                        tool_calls,
                        False,
                    )
                    self.send_json(200, response)

                return

            if stream:
                self.send_stream_text_chunked(
                    completion_id,
                    model,
                    now,
                    answer,
                    len(prompt),
                    include_usage,
                )

                print(
                    "[HTTP] streamed answer:",
                    len(answer),
                    "chars",
                )
                return

            response = {
                "id": completion_id,
                "object": "chat.completion",
                "created": now,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": answer,
                        },
                        "finish_reason": "stop",
                    }
                ],
            }

            if include_usage:
                response["usage"] = {
                    "prompt_tokens": max(1, len(prompt) // 4),
                    "completion_tokens": max(1, len(answer) // 4),
                    "total_tokens": max(1, (len(prompt) + len(answer)) // 4),
                }

            self.send_json(200, response)

        except Exception as e:
            print("[ERROR]", repr(e))

            try:
                self.send_json(
                    500,
                    {
                        "error": {
                            "message": str(e),
                            "type": "server_error",
                        }
                    },
                )
            except Exception:
                pass


def main():
    print("=" * 70)
    print("DeepSeek Windows Relay")
    print("=" * 70)
    print("Listening: http://127.0.0.1:%d" % PORT)
    print("Health:    http://127.0.0.1:%d/health" % PORT)
    print("Models:    http://127.0.0.1:%d/v1/models" % PORT)
    print("Chrome CDP:", CDP_URL)
    print("=" * 70)

    server = ThreadingHTTPServer(
        (HOST, PORT),
        Handler,
    )

    server.daemon_threads = True

    try:
        server.serve_forever()

    except KeyboardInterrupt:
        print("\nStopping...")

    finally:
        server.server_close()


if __name__ == "__main__":
    main()