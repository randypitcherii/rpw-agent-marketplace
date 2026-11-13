// Pure tab-matching logic for slack_browser.mjs (#2717), split out so it is unit-testable
// without a browser. No I/O here.
//
// Enterprise Grid: the client URL carries the enterprise id, not the team id. Opening
// app.slack.com/client/T0AAAAAAA/... redirects to app.slack.com/client/E0BBBBBBB/..., while
// localStorage.localConfig_v2.teams still keys the workspace by T… (with enterprise_id: "E…").

export const TEAM_ID = /^[TE][A-Z0-9]+$/;
const CLIENT = "https://app.slack.com/client/";

/** True when `url` is a Slack client tab for exactly one of `ids` (no prefix collisions). */
// True when the URL's host is slack.com or a subdomain. Parsed, never a substring test.
export function isSlackUrl(url) {
  try {
    const host = new URL(url).hostname;
    return host === "slack.com" || host.endsWith(".slack.com");
  } catch {
    return false;
  }
}

export function urlMatches(url, ids) {
  const seg = clientId(url);
  return Boolean(seg) && ids.filter(Boolean).includes(seg);
}

/** The id segment of a Slack client URL, or "" when `url` is not one. */
export function clientId(url) {
  return url?.startsWith(CLIENT) ? url.slice(CLIENT.length).split(/[/?#]/, 1)[0] : "";
}

/**
 * Resolve `--team` against a localConfig_v2.teams summary ({id: {enterprise_id?, hasToken}}).
 * Returns {team, enterprise} for the workspace the API calls run as, or {error} / null.
 *   T…  → itself, plus its enterprise_id when it sits in a grid.
 *   E…  → the one grid workspace (T…) under it; the enterprise entry itself if none is listed.
 */
export function resolveTeam(teams, id) {
  if (!teams || !id) return null;
  if (id.startsWith("T")) {
    const cfg = teams[id];
    return cfg?.hasToken ? { team: id, enterprise: cfg.enterprise_id || "" } : null;
  }
  const members = Object.entries(teams)
    .filter(([k, v]) => k.startsWith("T") && v?.enterprise_id === id && v.hasToken)
    .map(([k]) => k);
  if (members.length === 1) return { team: members[0], enterprise: id };
  if (members.length > 1) return { error: `ambiguous_enterprise`, members };
  return teams[id]?.hasToken ? { team: id, enterprise: id } : null;
}

/**
 * Pick the tab to run API calls in.
 *   tabs    CDP page targets ({id, url, ...})
 *   team    the --team value (T… or E…)
 *   teamsOf {tabId: teams summary} for client tabs whose localStorage was read; may be partial
 * Returns {tab, team} (team is the resolved T… to send the token for), {error, members}, or null.
 */
export function selectTab(tabs, team, teamsOf = {}) {
  const clients = tabs.filter((t) => clientId(t.url));
  // Non-grid fast path: the URL already names the team, nothing to resolve.
  if (team.startsWith("T")) {
    const direct = clients.find((t) => urlMatches(t.url, [team]));
    if (direct) return { tab: direct, team };
  }
  for (const tab of clients) {
    const r = resolveTeam(teamsOf[tab.id], team);
    if (r?.error) return r;
    if (r && urlMatches(tab.url, [r.team, r.enterprise])) return { tab, team: r.team };
  }
  return null;
}
