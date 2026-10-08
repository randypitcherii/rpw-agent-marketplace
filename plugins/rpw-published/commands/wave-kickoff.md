---
name: wave-kickoff
description: Launch an unbounded wave supervisor as a durable omnigent session over a fresh worktree — brief-file spawn, mandatory liveness probe, structured session title, then hands off.
allowed-tools: Bash, Skill, Read, Write
user-invocable: true
---

# /wave-kickoff — launch a wave supervisor as a durable session

A fresh wave request is supervised in the **current session** by default. Use
this command only when the user explicitly requests a separate, durable
supervisor session (or invokes `/wave-kickoff` by name).

Run the **`wave-kickoff`** skill and follow its pipeline:

1. **Orient** — `gh issue list` for the open backlog; collect the in-flight-claim skip-list.
2. **Create** a fresh supervisor worktree (`make base-worktree`, branch `wave-supervisor/<date>-<slug>`) — the base is the **fetched upstream default branch** resolved by `make base-ref`, never a hardcoded name and never the fork's default when the repo has a parent (#1164).
3. **Write `WAVE-BRIEF.md`** into the worktree from the skill's canonical template — never a long prompt, and always with the mandatory Step 0 relocation block (#795).
4. **Launch** the supervisor with a title beginning `⏳ 🌊 repo::branch::date::wave_supervisor — <wave-summary>`; the shared state emoji comes first and `🌊` marks this as a wave (convention: `docs/process/agent-session-titles.md`). Use the default REST bind-mode flow, file the session in the unique matching existing Omnigent project before waking it, and never create a project. If REST is unavailable, the `sys_session_create` fallback cannot set project membership; report that and continue.
5. **Liveness gate** — mandatory; `status` alone is not proof, the session history must show real tool calls. Relaunch once on a dead spawn, stop and report if twice-dead — and flip the state emoji (❌ dead, ‼️ parked on a decision) while preserving `🌊`, so the rail stops claiming it is working.
6. **Surface** the session by `conversation_id` + title (there is no terminal to focus).
7. **Report** worktree/branches/brief/liveness evidence + cleanup commands, then get out of the way.

Anything after `/wave-kickoff` is scope input: explicit seed issues and ordering, stop caps, or a slug. With no argument, the wave is **unbounded** — the supervisor works the whole eligible backlog by judgment. An explicit invocation opts into a fresh session; do not dispatch a single issue this way (that's `dispatch-launch`).
