#!/usr/bin/env node
// Call the Slack Web API from INSIDE a signed-in Slack tab of the agent Chrome
// (`rpw browser`), over CDP. The page already holds the xoxc token
// (localStorage.localConfig_v2) and the `d` cookie, so neither ever leaves the
// browser, reaches disk, or lands in the transcript. No dependencies (Node >= 22).
//
//   node slack_browser.mjs [--team T..|E..] [--channel C..] <command> [key=value ...]
//
//   whoami                                     auth.test (is the session live?)
//   history [limit=50] [oldest=<ts|YYYY-MM-DD>] [latest=...]   compact log, oldest first
//   thread ts=<ts>                             one thread's replies
//   search query="..."                         search.messages, scoped to --channel if set
//   <api.method> [key=value ...]               any Web API method, raw JSON out
//
// --team / --channel default to $SLACK_BROWSER_TEAM / $SLACK_BROWSER_CHANNEL.
// Enterprise Grid: the tab URL shows the enterprise id (E..); --team takes either the
// workspace T.. or the E.., and the tab is matched on both (tab_match.mjs, #2717).
// Read-only: write methods are refused unless --allow-write is passed.
// Exit: 0 ok · 1 Slack returned ok:false · 2 usage / write refused · 3 not signed in.
import { execFileSync } from "node:child_process";
import { TEAM_ID, clientId, selectTab } from "./tab_match.mjs";

const WRITE =
  /^(chat\.|reactions\.(add|remove)|conversations\.(join|leave|mark|invite|kick|archive|unarchive|rename|create|close|open|set)|files\.(upload|delete|complete|getUpload)|pins\.|stars\.|bookmarks\.(add|edit|remove)|reminders\.(add|delete|complete)|users\.(profile\.set|setPresence)|dnd\.)/;
const USAGE =
  "usage: slack_browser.mjs [--team T..|E..] [--channel C..] [--allow-write] <whoami|history|thread|search|api.method> [key=value ...]";

const die = (code, msg) => { console.error(msg); process.exit(code); };

// ---------------------------------------------------------------- args
const opts = { team: process.env.SLACK_BROWSER_TEAM || "", channel: process.env.SLACK_BROWSER_CHANNEL || "", allowWrite: false };
const positional = [];
const argv = process.argv.slice(2);
for (let i = 0; i < argv.length; i++) {
  const a = argv[i];
  if (a === "--allow-write") opts.allowWrite = true;
  else if (a === "--team" || a === "--channel") opts[a.slice(2)] = argv[++i] || "";
  else if (a.startsWith("--team=") || a.startsWith("--channel=")) { const [k, v] = a.slice(2).split("="); opts[k] = v; }
  else if (a === "-h" || a === "--help") die(0, USAGE);
  else positional.push(a);
}
const [cmd, ...kv] = positional;
if (!cmd) die(2, USAGE);
const params = {};
for (const p of kv) {
  const i = p.indexOf("=");
  if (i < 1) die(2, `bad argument ${JSON.stringify(p)}: expected key=value\n${USAGE}`);
  params[p.slice(0, i)] = p.slice(i + 1);
}
if (!TEAM_ID.test(opts.team)) die(2, `--team (or $SLACK_BROWSER_TEAM) must be a Slack team id like T02ABCDEF (or a grid enterprise id like E02ABCDEF)\n${USAGE}`);
if (opts.channel && !/^[CGD][A-Z0-9]+$/.test(opts.channel)) die(2, `--channel must be a channel id like C0ABCDEF`);
if (WRITE.test(cmd) && !opts.allowWrite) die(2, `Refusing write method ${cmd} without --allow-write.`);
const needsChannel = { history: 1, thread: 1 };
if (needsChannel[cmd] && !opts.channel) die(2, `${cmd} needs --channel (or $SLACK_BROWSER_CHANNEL)`);
if (cmd === "thread" && !params.ts) die(2, "thread needs ts=<message ts>");
if (cmd === "search" && !params.query) die(2, 'search needs query="..."');

const clientUrl = `https://app.slack.com/client/${opts.team}${opts.channel ? `/${opts.channel}` : ""}`;
const signInHelp =
  `No signed-in Slack tab for ${opts.team} in the agent Chrome. Sign in once (headed, a human does SSO/2FA):\n` +
  `  rpw browser status || rpw browser start\n  rpw browser open '${clientUrl}'`;

// ---------------------------------------------------------------- CDP
let endpoint;
try { endpoint = execFileSync("rpw", ["browser", "endpoint"], { encoding: "utf8" }).trim(); }
catch { die(3, `The agent Chrome is not running.\n${signInHelp}`); }

const listTabs = async () => (await (await fetch(`${endpoint}/json/list`)).json()).filter((t) => t.type === "page");

// Ids only (never the token) from one client tab's localConfig_v2, for tab_match.selectTab.
const TEAMS_SUMMARY = `(() => { const t = JSON.parse(localStorage.localConfig_v2 || "{}").teams || {};
  return Object.fromEntries(Object.entries(t).map(([k, v]) => [k, { enterprise_id: v?.enterprise_id || "", hasToken: !!v?.token }])); })()`;

async function find(tabs) {
  let hit = selectTab(tabs, opts.team);
  if (hit) return hit;
  // Grid (or --team E..): the URL shows the enterprise id, so read each client tab's team map.
  const teamsOf = {};
  for (const t of tabs.filter((t) => clientId(t.url) && t.webSocketDebuggerUrl)) {
    try { teamsOf[t.id] = await evaluate(t, TEAMS_SUMMARY); } catch { /* tab mid-load: skip */ }
  }
  hit = selectTab(tabs, opts.team, teamsOf);
  if (hit?.error) die(2, `--team ${opts.team} is an Enterprise Grid with several workspaces; pass one: ${hit.members.join(", ")}`);
  return hit;
}

async function slackTab() {
  let tabs = await listTabs();
  let hit = await find(tabs);
  // Open one tab only when no Slack tab exists at all, so retries never pile up sign-in tabs.
  if (!hit && !tabs.some((t) => t.url.includes("slack.com"))) {
    execFileSync("rpw", ["browser", "open", clientUrl]);
    for (let i = 0; i < 20 && !hit; i++) { await new Promise((r) => setTimeout(r, 1000)); hit = await find(await listTabs()); }
  }
  if (!hit) die(3, signInHelp);
  opts.team = hit.team; // the workspace T.. whose token the page sends
  return hit.tab;
}

async function evaluate(tab, expression) {
  const ws = new WebSocket(tab.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
  const res = await new Promise((resolve) => {
    ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.id === 1) resolve(d); };
    ws.send(JSON.stringify({ id: 1, method: "Runtime.evaluate", params: { expression, awaitPromise: true, returnByValue: true } }));
  });
  ws.close();
  const ex = res.result?.exceptionDetails;
  if (ex) throw new Error(ex.exception?.description || ex.text);
  return res.result.result.value;
}

// Runs in the page: one evaluate per batch of calls, with 429 back-off.
const pageFn = async (team, calls) => {
  const cfg = JSON.parse(localStorage.localConfig_v2 || "{}").teams?.[team];
  if (!cfg?.token) return { error: "not_signed_in" };
  // Same-origin on purpose: from app.slack.com a POST to the workspace host (cfg.url) fails CORS.
  const base = `${location.origin}/`;
  const out = [];
  for (const [method, args] of calls) {
    for (let attempt = 0; ; attempt++) {
      const body = new FormData();
      body.append("token", cfg.token);
      for (const [k, v] of Object.entries(args)) body.append(k, v);
      const r = await fetch(`${base}api/${method}`, { method: "POST", body, credentials: "include" });
      if (r.status === 429 && attempt < 4) {
        await new Promise((s) => setTimeout(s, 1000 * (Number(r.headers.get("retry-after")) || 2)));
        continue;
      }
      out.push(r.ok ? await r.json() : { ok: false, error: `http_${r.status}` });
      break;
    }
  }
  return out;
};

let tab;
async function api(calls) {
  tab ||= await slackTab();
  const res = await evaluate(tab, `(${pageFn})(${JSON.stringify(opts.team)}, ${JSON.stringify(calls)})`);
  if (res?.error === "not_signed_in") die(3, signInHelp);
  return res;
}
const one = async (method, args) => {
  const [r] = await api([[method, args]]);
  if (!r.ok) die(1, JSON.stringify(r));
  return r;
};

// ---------------------------------------------------------------- render
const toTs = (v) => (/^\d{4}-\d{2}-\d{2}/.test(v) ? String(Date.parse(v) / 1000) : v);
const fmtTs = (ts) => new Date(Number(ts) * 1000).toISOString().slice(0, 16).replace("T", " ");

async function names(msgs) {
  const ids = [...new Set(msgs.flatMap((m) => [m.user, ...[...(m.text || "").matchAll(/<@([UW][A-Z0-9]+)>/g)].map((x) => x[1])]).filter(Boolean))];
  if (!ids.length) return {};
  const res = await api(ids.map((id) => ["users.info", { user: id }]));
  return Object.fromEntries(res.map((r, i) => {
    const p = r.user?.profile;
    return [ids[i], p?.display_name || p?.real_name || r.user?.name || ids[i]];
  }));
}
function render(msgs, who) {
  const text = (t = "") =>
    t.replace(/<@([A-Z0-9]+)>/g, (_, id) => `@${who[id] || id}`)
      .replace(/<#[A-Z0-9]+\|([^>]*)>/g, "#$1")
      .replace(/<!(channel|here|everyone)>/g, "@$1")
      .replace(/<(https?:[^|>]+)\|([^>]+)>/g, "$2 ($1)")
      .replace(/<(https?:[^>]+)>/g, "$1")
      .replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
  return msgs.map((m) => {
    const files = (m.files || []).map((f) => ` [file: ${f.name || f.title || f.id}]`).join("");
    const thread = m.reply_count ? `  (thread: ${m.reply_count} replies, ts=${m.ts})` : "";
    return `[${fmtTs(m.ts)}] ${who[m.user] || m.username || m.bot_id || "?"}: ${text(m.text)}${files}${thread}`;
  }).join("\n");
}

// ---------------------------------------------------------------- commands
if (cmd === "whoami") {
  console.log(JSON.stringify(await one("auth.test", {}), null, 2));
} else if (cmd === "history") {
  const limit = Number(params.limit || 50);
  const args = { channel: opts.channel, limit: String(Math.min(limit, 200)) };
  if (params.oldest) args.oldest = toTs(params.oldest);
  if (params.latest) args.latest = toTs(params.latest);
  const msgs = [];
  let cursor;
  do {
    const r = await one("conversations.history", cursor ? { ...args, cursor } : args);
    msgs.push(...r.messages);
    cursor = r.response_metadata?.next_cursor;
  } while (cursor && msgs.length < limit);
  const page = msgs.slice(0, limit).reverse();
  console.log(render(page, await names(page)));
} else if (cmd === "thread") {
  const msgs = [];
  let cursor;
  do {
    const r = await one("conversations.replies", { channel: opts.channel, ts: params.ts, limit: "200", ...(cursor ? { cursor } : {}) });
    msgs.push(...r.messages);
    cursor = r.response_metadata?.next_cursor;
  } while (cursor);
  console.log(render(msgs, await names(msgs)));
} else if (cmd === "search") {
  const query = opts.channel ? `${params.query} in:<#${opts.channel}>` : params.query;
  const r = await one("search.messages", { query, count: params.count || "20", sort: params.sort || "timestamp" });
  const msgs = r.messages.matches;
  console.log(render(msgs, await names(msgs)));
} else if (/^[a-z]+(\.[a-zA-Z]+)+$/.test(cmd)) {
  console.log(JSON.stringify((await api([[cmd, params]]))[0], null, 2));
} else {
  die(2, `unknown command ${cmd}\n${USAGE}`);
}
