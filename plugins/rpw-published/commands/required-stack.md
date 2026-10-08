---
name: required-stack
description: Install and verify the public companion plugins used by rpw-published
---

# /required-stack - Verify the Public Plugin Stack

Check the public marketplace installation without assuming access to the private source repository. Use one onboarding mode only: the public plugin is required and browser support is an optional companion. Do not offer persona-based variants.

## Required

- `rpw-published@rpw-agent-marketplace`

## Optional browser companion

- `chrome-devtools-mcp@claude-plugins-official`

## Execution

1. Run `claude plugin marketplace list` and `claude plugin list`.
2. Confirm `rpw-published@rpw-agent-marketplace` is enabled. If it is missing, show this command but ask before installing:

   ```bash
   claude plugin install rpw-published@rpw-agent-marketplace
   ```

3. If the user needs browser automation, confirm the official marketplace and plugin are present. Ask before running either command:

   ```bash
   claude plugin marketplace add anthropics/claude-plugins-official
   claude plugin install chrome-devtools-mcp@claude-plugins-official
   ```

4. Run `claude plugin validate --strict "${CLAUDE_PLUGIN_ROOT}"` and report the exact result.

## Safety

- Do not modify project files or repository settings.
- Do not install or enable a plugin without explicit confirmation.
- Do not claim that private plugins or source-repository scripts are available.
