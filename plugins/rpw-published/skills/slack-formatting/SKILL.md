---
name: slack-formatting
description: Formatting rules for composing Slack messages so they render correctly (mrkdwn, not Markdown). Trigger on "post this to Slack", "format this for Slack", "send a Slack message", "reply in the thread", or before any slack_chat_post_message call. Covers mrkdwn vs Markdown, code blocks, link `<url|label>` and mention `<@Uxxx>`/`<#Cxxx>` syntax, no-Markdown-tables, and thread-vs-channel etiquette. NOT for email or Google Docs (use doc-styling); NOT for choosing which channel/thread to target.
---

# Slack Message Formatting

Slack does **not** render standard Markdown. Its `chat.postMessage` `text` field uses
**mrkdwn** — a similar-looking but distinct syntax. Text that looks right in a Markdown
preview often renders wrong in Slack (literal `**`, broken links, raw table pipes). Apply
these rules before posting via `slack_chat_post_message`.

## mrkdwn vs Markdown — the differences that bite

| Intent        | Markdown            | Slack mrkdwn            |
|---------------|---------------------|-------------------------|
| Bold          | `**bold**`          | `*bold*` (single stars) |
| Italic        | `*italic*` / `_x_`  | `_italic_`              |
| Strikethrough | `~~strike~~`        | `~strike~` (single)     |
| Inline code   | `` `code` ``        | `` `code` `` (same)     |
| Code block    | ```` ```lang ````   | ```` ``` ```` (no lang) |
| Bulleted list | `- item`            | `• item` (literal bullet)|

Key traps:

- **Bold is one asterisk, not two.** `**text**` renders in Slack as literal
  `*text*` wrapped in stray asterisks. Use `*text*`.
- **No language hint on fences.** ```` ```python ```` shows the word `python` as
  the first line. Use a bare ```` ``` ````.
- **No heading syntax.** `#`, `##` do nothing — they render literally. Emphasize a
  section with a bold lead line (`*Summary*`) instead.
- **Lists aren't auto-formatted.** `- ` and `1. ` are not list markers. Start lines
  with a literal `•`, `-`, or a number you type yourself, and add your own newlines.
- **Blockquote** is `> ` at the start of a line (same as Markdown) — this one works.

## Links and mentions — Slack's angle-bracket syntax

- **Link:** `<https://example.com|click here>` → *click here*. A bare URL
  auto-links. Never use Markdown `[label](url)` — it renders literally.
- **User mention:** `<@U012ABCDEF>` (the user **ID**, not `@name`). Resolve a name/email
  to an ID with `slack_users_lookup_by_email` first. Typing `@randy` does **not** notify.
- **Channel link:** `<#C012ABCDEF>` renders as *#channel-name* and links.
- **Group/here:** `<!here>`, `<!channel>`, `<!subteam^S012|@team>`. Use sparingly —
  `<!channel>` pings everyone in the channel.
- **Emoji:** `:tada:` shortcodes render as emoji. Unicode emoji also work.

## No tables

Slack has **no table support**. Markdown pipe tables render as a wall of raw `|`
characters and are unreadable. Instead:

- Use a bulleted list with bold labels: `• *Status:* green`.
- For tabular data, use a code block (```` ``` ````) with space-padded columns — the
  monospace font keeps columns aligned. Keep it narrow (mobile clients wrap).
- For anything genuinely tabular and large, link out to a doc/sheet rather than
  jamming it into a message.

## Structure and length

- **Lead with the point.** Slack messages are skimmed. First line = the takeaway.
- Keep paragraphs short; use blank lines between them (a single `\n` inside `text`).
- Break long updates into a short parent message + details in the thread, rather than
  one giant message.
- `text` has a ~40k-character hard cap, but anything over a screen or two belongs in a
  thread, a snippet, or a linked doc.

## Thread vs channel etiquette

- **Reply in-thread** by passing `thread_ts` (the parent message's `ts`) to
  `slack_chat_post_message`. This keeps the channel readable.
- **Start a new top-level message** (omit `thread_ts`) only for a genuinely new topic.
- **Don't split one thought across multiple messages** — it spams the channel and
  fragments notifications. Compose the whole message, then send once.
- When replying to a specific person in a busy thread, `@`-mention them
  (`<@Uxxx>`) so they're notified — thread replies don't always notify.
- Match the channel's register: `#incidents` is terse and factual; a team channel
  can carry more context and an emoji or two.

## Quick pre-send checklist

1. Bold is `*single*`, not `**double**`.
2. Links are `<url|label>`, mentions are `<@ID>` / `<#ID>` — no Markdown `[]()`.
3. No `#` headings, no ```` ```lang ```` fences, no pipe tables.
4. Lists use literal `•`/`-` and your own newlines.
5. Replying to a thread? `thread_ts` is set. New topic? It's omitted.
6. First line states the point.

## Related

- Rendering Google Docs / customer prose (real Markdown + headings): use the
  `doc-styling` skill instead — its rules are the opposite of these.
- Choosing the target channel/user or opening a group DM is out of scope here; that's
  the Slack MCP tools' job (`slack_conversations_open`, `slack_users_lookup_by_email`).
