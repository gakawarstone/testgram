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

Directory runs isolate every scenario with a fresh testgram server, bot process,
and chat id, starting at `--chat-id`. This also gives in-process FSM storage and
bot-owned database connections a fresh lifecycle. Parallel runs execute these
isolated runtimes concurrently; when multiple scenarios run in parallel,
`--port` must remain `0` so each server can bind its own automatic port.

In a bot project, add `testgram.yaml` next to the bot command so scenarios do
not duplicate setup:

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

`send` and `click` wait for the injected update to be consumed before the next
step starts. Consumption follows Telegram's acknowledgement rule: the bot must
make a subsequent `getUpdates` request with an offset greater than the injected
update id. This makes consecutive actions deterministic. Set
`wait_consumed: false` on an action only when deliberately testing overlapping
updates; its `timeout` defaults to the scenario timeout.
Control clients can query or long-poll the same state at
`GET /testgram/updates/{update_id}/consumed?timeout=5`.

Assert that a matching reply does not occur during a complete observation
window with `expect_none` (it never succeeds immediately):

```yaml
steps:
  - send: {text: /quiet}
  - expect_none:
      text_contains: Error
      duration: 1
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

When callback data contains generated IDs, select the button with a regular
expression or its visible text. The matched button's actual callback data is
sent to the bot:

```yaml
steps:
  - send: {text: /create}
  - expect: {text_contains: Created}
  - click:
      callback_data_regex: '^record:\d+:open$'
  - expect: {text: Record details}

  # Or select by the visible label:
  - click:
      button_text: Delete
```

`click` requires exactly one of `callback_data`, `callback_data_regex`, or
`button_text`. It searches the newest matching bot message first. When several
messages contain the same button, restrict the search with the same message
fields accepted by `expect`:

```yaml
- click:
    button_text: Open
    message:
      text_contains: Record created
```

`message_id` can still restrict the search when the ID is known.

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
    forbidden_bot_messages:
      - {filename: traceback.txt}
    no_errors: true
```

`no_errors` checks server errors and unsuccessful Bot API responses. Use
`forbidden_bot_messages` for application-specific failure messages. The matcher
checks every chat, so it can catch diagnostics sent to an administrator.

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

Run the E2E test:

```bash
testgram run scenarios/start.yaml
```

Testgram starts the fake API and your bot, injects the scenario updates, checks
the responses, then stops both processes. Use `testgram chat` for interactive
testing or `testgram run scenarios/ --parallel 4` to run a suite concurrently.

Callbacks can also be injected directly with `POST /testgram/callbacks`; its
JSON body requires `data`, `chat_id`, and the complete source `message`.
Inline queries use `POST /testgram/inline-queries`, and arbitrary Telegram
update fields use `POST /testgram/updates`.

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

Reset state:

```bash
curl -X POST http://127.0.0.1:8081/testgram/reset
```

## Notes

This is intentionally not a full Telegram implementation. Unknown Bot API
methods are logged and answered with a Telegram-style HTTP 404 response:
`{"ok": false, "error_code": 404, "description": "Not Found"}`. This makes
missing fake implementations fail visibly instead of appearing successful.
