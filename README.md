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
