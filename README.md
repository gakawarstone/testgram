# testgram

Small fake Telegram Bot API server for manual bot testing.

The first version supports echo/control mode:

- the bot points `API_SERVER_URL` at testgram;
- testgram serves a small Telegram Bot API subset;
- testgram logs bot API calls to stdout and optional JSONL;
- tester injects fake user messages through control endpoints.

## Run

From the testgram repository root:

```bash
uv run python main.py --host 127.0.0.1 --port 8081
```

Run gkbot with:

```bash
API_SERVER_URL=http://127.0.0.1:8081 \
BOT_TOKEN=123456:abcdefghijklmnopqrstuvwxyzABCDE \
ADMIN_IDS=999999 \
SQLDIALECT=sqlite \
DB_USER=x \
DB_PASSWORD=x \
DB_HOST=localhost \
DB_PORT=0 \
DB_NAME=/tmp/testgram-gkbot.sqlite \
uv run python bot/main.py
```

Open an interactive chat:

```bash
uv run python chat.py
```

It behaves like:

```text
me: /list
bot: Привет вот список команд которые есть в боте:
...
```

Run a scenario:

```bash
uv run python scenario.py scenarios/list.yaml
```

Check that `/feed` gives the normal user a visible response:

```bash
uv run python scenario.py scenarios/feed_responds.yaml
```

Scenario files are YAML:

```yaml
name: list command
steps:
  - message: /list
  - expect:
      method: sendMessage
      text_contains: /list
```

Inject a message:

```bash
curl -X POST http://127.0.0.1:8081/testgram/messages \
  -H 'content-type: application/json' \
  -d '{"chat_id": 1, "text": "/start"}'
```

Read events:

```bash
curl http://127.0.0.1:8081/testgram/events
```

Reset state:

```bash
curl -X POST http://127.0.0.1:8081/testgram/reset
```

## Notes

This is intentionally not a full Telegram implementation. Unknown Bot API
methods are logged and answered with `{"ok": true, "result": true}` so the
framework can reveal which methods need real behavior next.
