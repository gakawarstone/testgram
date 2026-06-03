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
uv run testgram serve --host 127.0.0.1 --port 8081
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
uv run testgram chat
```

It behaves like:

```text
me: /list
bot: Привет вот список команд которые есть в боте:
...
```

Run a scenario with a hidden testgram server:

```bash
uv run testgram run scenarios/list.yaml
```

Run every scenario file in a directory:

```bash
uv run testgram run scenarios/
```

Run multiple scenarios from a directory concurrently:

```bash
uv run testgram run scenarios/ --parallel 4
```

Parallel runs use separate chat ids for each scenario, starting at `--chat-id`.
When reset is enabled, testgram resets once before the parallel batch instead of
between scenarios.

In a bot project, add `testgram.yaml` next to the bot command so scenarios do
not duplicate setup:

```yaml
bot:
  command: uv run python bot/main.py
  env:
    BOT_TOKEN: 123456:test
    ADMIN_IDS: "999999"
```

`testgram run` discovers `testgram.yaml`, starts testgram on an automatic local
port, starts the bot with `API_SERVER_URL` pointing at that server, runs the
scenario, and then stops both processes. `testgram chat` also starts a hidden
local testgram server when `--url` is not already running, discovers
`testgram.yaml`, and starts the configured bot with `API_SERVER_URL` pointing at
the chat server; pass `--no-bot` to chat without starting the bot.

If the configured bot command is already running from the same project
directory, `testgram run` and `testgram chat` will not start another copy or
stop the existing one.

Check that `/feed` gives the normal user a visible response:

```bash
uv run testgram run scenarios/feed_responds.yaml
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
