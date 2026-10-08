# Morning Prep Report skill

Portable copy of the Omnigent project skill at `projects/omnigent/skills/morning-prep-report/`. The HTML assets are byte-identical across both copies (enforced by `tests/test_morning_prep_report_skill.py`).

- `SKILL.md` — short procedure
- `references/report-contract.md` — evidence, action, comparison, and identity rules
- `assets/template.html` — blank standalone report template
- `assets/example-report.html` — fictional example with day-over-day chart and equivalent table
- `assets/icon/` — project icon set, built by `scripts/build_icons.py` from `assets/project-icons/morning-prep.png`; never hand-edit
- `scripts/inline_favicon.py` — re-embeds `assets/icon/favicon-32.png` as a data URI in both copies (`--check` to verify)

Rebuild the icon: `make icons SRC=assets/project-icons/morning-prep.png OUT=plugins/rpw-published/skills/morning-prep-report/assets/icon`, then `uv run --no-project python plugins/rpw-published/skills/morning-prep-report/scripts/inline_favicon.py`.

Tracking issue: #2185.
