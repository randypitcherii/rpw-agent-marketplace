# Paused experiments: the "resume here" header

Reference for the **Paused experiments** section of `SKILL.md`.

An experiment often finishes a pass with real findings but is **not done**: some
rows stay ❓ because a capability is not yet switched on in the environment it runs
against, and the work resumes once that changes. Without a convention, that state
lives in a PR description that scrolls away, a "Not done" paragraph under the
matrix, or the operator's memory. Two readers lose:

- **A human** skimming the README cannot tell "never tried" ❓ from "waiting on an
  unblock" ❓.
- **A future agent** has no machine-followable statement of what to check, what to
  re-run, and which rows to update, so it re-derives the blocker or treats a paused
  experiment as finished.

❓ already means "could not be isolated, here's why." This header is the orthogonal
axis: **is anyone expected to come back?** A permanently-❓ row (needs infrastructure
nobody will build) and a ❓-this-week row (a setting is being enabled) otherwise read
identically.

## Template

Place it **directly under the experiment title, above the matrix**:

```markdown
> **⏸️ Paused — further work expected.**
> **Waiting on:** <capability, in public-docs terms> on the environment this experiment runs against.
> **Blocks:** rows N–M — <one line on what stays unproven>.
> **To resume:** run `<preflight command>`; if the gate is open, re-run `<command>` and update rows N–M plus `results/matrix_results.json`.
> **Last checked:** YYYY-MM-DD
```

## Requirements

- **Placement is fixed.** Top of the README, under the title, above the matrix: the
  first thing both readers see.
- **`To resume` is executable, not prose.** A named preflight script or make target
  beats "check if it's enabled." An experiment with an enablement probe points at it.
- **`Blocks` names matrix rows**, so the ❓ cells and the header cross-check. Every
  row it names is ❓ (or ◑) in the matrix, and every ❓ awaiting this unblock is named.
- **`Last checked` is a date** (`YYYY-MM-DD`), so staleness is visible without git
  archaeology. Bump it each time the preflight is re-run, even if still blocked.
- **Remove the header when the block clears.** It is a live claim, not a changelog
  entry. Re-run the blocked rows, update the matrix and `results/matrix_results.json`,
  delete the header, and move the resolved blocker into **Key Findings** as history.

## Sanitization — capability and environment shape only

The shareables repo is public, and a blocker header is unusually prone to leaks: the
natural phrasing of a blocker is a person, a date and an internal roadmap item. Shapes
to refuse:

- "waiting on <person> to enable this on account `<id>`"
- "<internal feature name> ships end of week per <contact>"
- "blocked until <customer> approves"

Write the **capability**, described the way public docs describe it, and the
**environment shape**, not its coordinates:

> Blocked until foundation-model Unity Catalog permissions are enabled on the
> workspace this experiment runs against.

The header must never contain:

- person names (no owner, no contact, no approver);
- customer names, or anything that identifies one;
- account, workspace, metastore or other environment ids or hostnames;
- internal feature names or codenames;
- internal timelines, roadmap dates or product plans ("ships next week", "GA in Q3").

`Last checked` is the only date allowed: when *you* looked, never when someone else
plans to act.

## Exemplar

The coding-agent inference through Unity AI Gateway experiment (first entry in the
skill's **Exemplars** list) is the motivating case: rows that await foundation-model
permissions on its workspace, with an enablement probe to point `To resume` at.
