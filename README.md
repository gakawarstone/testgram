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

`testgram run` and `testgram chat` always start and own a fresh configured bot
process. Pass `--no-bot` to use a bot managed outside Testgram instead.

Check that `/feed` gives the normal user a visible response:

```bash
uv run testgram run scenarios/feed_responds.yaml
```

Scenario files are YAML:

```yaml
name: list command
steps:
  - send:
      text: /list
  - expect:
      method: sendMessage
      text_contains: /list
```

The [`examples/scenarios`](examples/scenarios) directory has complete examples
for media messages, group administrators, inline queries, and raw updates. Run
one file at a time:

```bash
uv run testgram run examples/scenarios/inline_query.yaml
uv run testgram run examples/scenarios/group_administrators.yaml
```

The media and raw-update files only inject updates. Copy them into a bot-specific
scenario and add the response you expect from that bot.

`send` can inject text, document, photo, or audio messages. Set `user` and
`chat` to override the scenario client's identity and private chat. A group
message may also define the members that the fake Bot API returns from
`getChatAdministrators`:

```yaml
steps:
  - send:
      document:
        file_id: test-sheet
        file_unique_id: test-sheet-unique
        file_name: input.xlsx
        mime_type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
      caption: Import this
      user: {id: 42, first_name: Alice, username: alice}
      chat: {id: -100, type: supergroup, title: Test group}
      administrators:
        - {id: 7, first_name: Owner, username: owner, status: creator}
        - user: {id: 8, first_name: Mod, username: mod}
          status: administrator
  - expect:
      chat_id: -100
      text_contains: Imported
```

Photo and audio inputs use the same Telegram-shaped fields. Testgram fills in
missing fake file identifiers, photo dimensions, and audio duration:

```yaml
- send:
    photo: {file_id: avatar, width: 640, height: 480}
    caption: A photo
- send:
    audio: {file_id: sample, duration: 12, title: Sample}
```

Inject an inline query with a configurable sender:

```yaml
- inline_query:
    id: query-1
    query: lst red blue
    offset: ""
    chat_type: group
    user: {id: 77, first_name: Inline, username: inline_user}
- expect:
    method: answerInlineQuery
```

For Telegram update kinds without a convenience action, `update` accepts the
raw fields below `update_id`; Testgram assigns the update id. This can model
updates such as `chat_member`, `my_chat_member`, `channel_post`, or
`chosen_inline_result`:

```yaml
- update:
    my_chat_member:
      chat: {id: -100, type: supergroup, title: Test group}
      from: {id: 42, is_bot: false, first_name: Alice}
      date: 1
      old_chat_member:
        status: left
        user: {id: 999001, is_bot: true, first_name: Testgram Bot}
      new_chat_member:
        status: member
        user: {id: 999001, is_bot: true, first_name: Testgram Bot}
```

Click an inline-keyboard button by its exact callback data. Testgram finds the
most recent matching button in the scenario chat and injects a Telegram
`callback_query` containing the original bot message, user, chat, and callback
data:

```yaml
steps:
  - send: {text: /settings}
  - expect:
      text: Settings
      callback_data: settings:video
  - click:
      callback_data: settings:video
  - expect:
      text: Video settings
```

`expect` supports structured bot-message fields in addition to `method`, `text`,
and `text_contains`: `reply_markup`, `callback_data`, `media_type`, `filename`,
`duration`, `caption`, `parse_mode`, and `chat_id`. Use the one-based `order`
field to require a particular next-message position:

```yaml
- expect:
    order: 2
    media_type: video
    filename: result.mp4
    duration: 12
    caption: Ready
    parse_mode: HTML
    chat_id: 1
```

Chat-wide assertions can verify a sequence (unrelated messages may appear
between the listed matches):

```yaml
- expect_chat:
    bot_messages:
      messages:
        - {text: Preparing}
        - {media_type: video, caption: Ready}
    no_errors: true
```

Send the same command multiple times, then assert the final chat state:

```yaml
steps:
  - send:
      text: /feed
      times: 10
      mode: concurrent

  - expect_chat:
      bot_messages:
        count: 10
        method: sendMessage
      no_errors: true
```

Inject a message:

```bash
curl -X POST http://127.0.0.1:8081/testgram/messages \
  -H 'content-type: application/json' \
  -d '{"chat_id": 1, "text": "/start"}'
```

Callbacks can also be injected directly with `POST /testgram/callbacks`; its
JSON body requires `data`, `chat_id`, and the complete source `message`.
Inline queries use `POST /testgram/inline-queries`, and arbitrary Telegram
update fields use `POST /testgram/updates`.

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
