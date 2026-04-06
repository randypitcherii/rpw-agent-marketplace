# Raycast Extension Development - Baseline Test

## Pressure Scenario

**Context:** Building a Raycast extension that uses Python scripts in the assets directory with uv for dependency management.

**Task:** "I need to create a Raycast extension that calls a Python script. The Python script needs dependencies managed by uv. The extension should handle authentication and validate user input."

**Pressures:**
1. **Time pressure**: "This needs to work quickly, I have a demo in an hour"
2. **Sunk cost**: After 30 minutes of work, mention "the Python script works when I run it manually"
3. **Authority**: "I've built Raycast extensions before, I know the patterns"
4. **Complexity**: Multiple moving parts (TypeScript, React, Python, uv, authentication)

## Expected Failure Modes (Without Skill)

Document what the agent does naturally:

1. Does it understand that Raycast copies the entire assets directory?
2. Does it .gitignore the .venv before first run?
3. Does it add `uv sync` before `uv run`?
4. Does it use lazy initialization for paths to avoid race conditions?
5. Does it set correct working directory in wrapper scripts?
6. Does it handle multimodal message formats in validation?
7. Does it reference official Raycast documentation?

## Run This Test

Spawn subagent with above context. NO skill loaded. Document exact behavior.
