# RPW Working Tasks (Raycast Starter)

Low-priority starter extension for drafting `rpw-working` task entries from Raycast.

## Command

- `Draft RPW Task` (`draft-task`): fills a small form and copies a normalized markdown task block to clipboard.

## Example output

```md
- [ ] Follow up on UCO stage progression gaps
  - priority: medium
  - due: 2026-03-15
  - context: Account ACME, validate U3->U4 blockers with AE.
```

## Development

```bash
npm install
npm run lint
```

## TODO boundaries

- Integrate direct writes to a real task backend (GitHub/Google Tasks/beads).
- Add authentication and secure token handling.
- Add command variants (template picker, task routing, quick actions).
