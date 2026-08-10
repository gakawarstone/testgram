# Testgram

Testgram is a small end-to-end testing framework for Telegram bots. It runs a
local fake Telegram Bot API, sends user messages and callback queries, and
asserts the bot's responses from YAML scenarios—without contacting Telegram.

## Install

Requires Python 3.13+.

```bash
git clone https://github.com/gakawarstone/testgram.git
cd testgram
uv tool install .
```

Or run it directly from GitHub without cloning or installing:

```bash
uvx --from git+https://github.com/gakawarstone/testgram.git testgram run scenarios/start.yaml
```

## Use

Add `testgram.yaml` to your bot project:

```yaml
bot:
  command: python bot/main.py
  env:
    BOT_TOKEN: 123456:test
```

Create `scenarios/start.yaml`:

```yaml
name: start command
steps:
  - send: {text: /start}
  - expect:
      method: sendMessage
      text_contains: Welcome
```

Run the E2E test:

```bash
testgram run scenarios/start.yaml
```

Testgram starts the fake API and your bot, injects the scenario updates, checks
the responses, then stops both processes. Use `testgram chat` for interactive
testing or `testgram run scenarios/ --parallel 4` to run a suite concurrently.

## Interactive chat readiness

When `testgram chat` starts a configured bot, it waits for that process to begin
a new `getUpdates` long poll before showing the prompt and establishing the chat
event baseline. Messages sent during bot startup—such as an admin notification
that the bot started—are therefore treated as existing chat activity, not as the
response to the first command entered by the user.

Testgram tracks polling generations, so an earlier bot poll on a reused server
does not make the new process appear ready. Readiness uses the configured
`--timeout`. Passing `--no-bot` skips the readiness wait because Testgram does
not own the external bot's lifecycle.
