\# deepseek-relay-cline



Локальный OpenAI-совместимый релей для Cline в VS Code,

работающий через DeepSeek Web Chat и Chrome DevTools Protocol.



\## Что делает



\- Принимает запросы `/v1/chat/completions` от Cline.

\- Проксирует их в DeepSeek Web Chat через CDP.

\- Возвращает ответы Cline в формате OpenAI (включая tool\_calls).

\- Позволяет Cline работать в Act mode: читать файлы, запускать команды, править код.



\## Запуск



1\. `start-chrome.bat` — Chrome с DeepSeek (залогинься один раз).

2\. `start-relay.bat` — релей на http://127.0.0.1:8080.

3\. VS Code → Cline → Act mode.

