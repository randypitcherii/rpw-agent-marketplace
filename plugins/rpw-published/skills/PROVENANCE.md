# Published skill provenance

Most skills in this plugin are original house guidance. The two exceptions found by
the publish-artifact audit for issue #1657 are classified here.

| Skill content | Classification | Distribution strategy |
|---|---|---|
| `communication/references/adhd-reader.md` | Adapted: the always-on default and composition with `communication` and `simple-english` are local behavior changes. | Retain the local adaptation under the upstream MIT license, reviewed at [`58494af`](https://github.com/ayghri/i-have-adhd/commit/58494af57962b2d7a996b4d419474380a299af5e). The required notice and license text are in `../THIRD_PARTY_NOTICES.md`. A plugin dependency would not preserve these local semantics across harnesses. |
| `dataviz/` before issue #1657 | True duplicate plus a small local routing section: most files reproduced a Claude Code bundled skill. | The bundled skill has no separately installable canonical plugin in [Anthropic's public skill marketplace](https://github.com/anthropics/skills/tree/53048666b05b4799081517d00e09e0a2dd688678), and Claude plugin dependencies only compose whole marketplace plugins. The copied definition was removed. `dataviz/` is now an independently written, compact cross-harness implementation with its own validator, so clean installs retain the behavior without reproducing the bundled files. |

## Dependency decision

[Claude Code supports executable plugin composition](https://code.claude.com/docs/en/plugin-dependencies)
through the `dependencies` array in `plugin.json`; cross-marketplace dependencies also require
`allowCrossMarketplaceDependenciesOn` in the root marketplace manifest. This is the
supported mechanism used when a canonical upstream plugin exists. A URL in prose is
not a dependency, and filesystem links outside a marketplace are rejected or skipped.

Neither exception above is a valid dependency candidate: the public Anthropic skills
marketplace does not publish `dataviz`, while the communication reference intentionally
changes the upstream skill's activation and composition behavior. Keeping the minimum
licensed or independently authored local implementation is therefore the portable path.
