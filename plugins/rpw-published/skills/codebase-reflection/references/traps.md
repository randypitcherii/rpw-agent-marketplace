# False-positive traps

Each trap below produced a wrong finding, or a wrong rejection, in a real run. Check every high-payoff row against all of them before reporting it.

| Trap | What it looks like | How to check |
|---|---|---|
| **Human-facing caller** | Zero code callers, but a doc or skill tells a person to run it. | Grep docs and skill bodies too, not just code and CI. A documented manual command is live. |
| **Truncated grep** | `git grep … \| head -5` showed no live hit, because the hit was line 6. | Re-run without truncation. Count first (`git grep -c`), then read. |
| **Name collision** | "X is imported by project P", when P has its *own* module named X. | Open the import line. Check that the module path is the shared one. |
| **Data coupling, not import** | No importer, but another component reads its output file or table. | Grep for the artifact (file path, table name, schema), not only the module. |
| **Textual path in fixtures** | An eval dataset, test fixture or snapshot names the path as a string or asserts it exists. | Grep fixtures and datasets. Decide whether the fixture runs against today's tree or a pinned base before you call it breaking. |
| **Governed removal** | Dead, but a decision record says "no deletion without a later decision". | The row goes in *Needs a decision*, not *Delete now*. |
| **Open issue wants it** | An unused prototype that an open issue plans to wire up. | Search open issues for the path or the feature name. Put it in *Needs a decision*. |
| **Deliberate copy** | Byte-identical files that a sync script or test keeps identical. | Find the sync or check. If it exists, the copy is a design decision. Ask whether the reason behind it still holds. |
| **Installed outside the repo** | A service definition no build target references, but the machine runs it. | Check the generic installer and the live service manager before calling it unused. |
| **Required by a live workflow** | Its own data source is dead, but a heavily used skill makes a step that opens it *required*. In a real run, a "UI over a dead telemetry store" turned out to be every wave's required dashboard. | Grep skill bodies for the path or the project name and read the step that mentions it. Judge it by what the live workflow uses, not by the subsystem it was built for. |
| **Ungated is not unused** | A sub-project that is excluded from CI on purpose ("red by design until #N"). | It is a real finding, but only the human can decide whether to fund the fix or delete it. |

## Harness notes

- A child session can finish with an empty inbox payload ("produced no output") even though it wrote its full report. Read its history before you treat it as failed.
- Lenses that disagree point to a trap. Lenses that independently agree on a live consumer are your strongest *rejection* evidence.
- **Approval is not verification.** The human approves a report. Before each deletion, re-run this whole table against that row at implementation time, and bring back anything that fails rather than deleting it.
