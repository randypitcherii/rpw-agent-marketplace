# Upstream contribution — mechanical recipes

The judgment lives in [SKILL.md](SKILL.md). These are the commands behind it. Placeholders:
`<upstream>` = `owner/repo` you contribute to, `<you>` = your GitHub login, `<dir>` = the new
worktree, `<branch>` = the branch you are cutting.

## 1. Remotes and the base ref

Resolve remotes by URL, not by name. Clones disagree on naming: a fork clone usually has
`origin` = fork and `upstream` = parent, but a clone of the upstream with the fork added later
has them the other way round.

```bash
git remote -v
gh repo view --json isFork,parent -q '{fork: .isFork, parent: .parent.nameWithOwner}'
```

`plugins/rpw-published/scripts/git-base-branch.sh` (#1164) is the one recipe for "which ref
do I branch from". It is repo-agnostic — it reads the current checkout, never a hardcoded
branch name:

| Situation | What it picks |
|---|---|
| `origin` is a fork (per `gh`) and an `upstream` remote exists | `upstream/<parent default>` |
| No `gh`, but a distinct `upstream` remote exists | `upstream/<its default>` |
| `origin` is itself the upstream (not a fork) | `origin/<default>` |
| A fork with no remote for its parent | exit 3 + the exact `git remote add upstream …` to run |

```bash
S="$CLAUDE_PLUGIN_ROOT/scripts/git-base-branch.sh"
"$S" ref                       # fetch, then print <remote>/<branch>
"$S" worktree <dir> <branch>   # fetch, then `git worktree add <dir> -b <branch> <ref>`
cd <dir> && git log --oneline "$("$S" ref --no-fetch)"..HEAD   # empty before you write code
```

Inside this monorepo the same helper is `make base-ref` / `make base-worktree PATH_=… BRANCH=…`.

By hand (no helper available):

```bash
BASE=$(gh repo view <upstream> --json defaultBranchRef -q .defaultBranchRef.name)   # never assume main
git fetch upstream "$BASE"
git worktree add <dir> -b <branch> "upstream/$BASE"
```

**Re-assert before every push.** A rebase, an amend or a long-lived branch drifts:

```bash
git fetch upstream "$BASE"
git log --oneline "upstream/$BASE"..HEAD     # only your commits
git rebase "upstream/$BASE"                  # if upstream moved and the PR is not yet open
```

## 2. Issue discovery

```bash
gh issue list --repo <upstream> --state all --search "<the user's words>"   --limit 30
gh issue list --repo <upstream> --state all --search "<the codebase's words>" --limit 30
gh pr list    --repo <upstream> --state all --search "<same keywords>"       --limit 30
gh api repos/<upstream>/contents/.github/ISSUE_TEMPLATE -q '.[].name'
gh api repos/<upstream>/contents/.github/ISSUE_TEMPLATE/config.yml -q .content | base64 -d   # blank_issues_enabled?
gh label list --repo <upstream> --limit 200
```

Then read the code at `upstream/<default>` — the issue history says what people *asked for*;
only the source says what *shipped*. Cross-reference a prior issue with a comment
(`gh issue comment <n> --repo <upstream> --body "Related: <link> …"`), after consent.

## 3. DCO and commit hygiene

```bash
git commit -s -m "<their message convention>"
git log -1 --format='%(trailers:key=Signed-off-by,valueonly)'   # read the name, don't grep for presence
git config user.name; git config user.email                      # what the trailer will carry
```

Stage explicit paths, never `git add -A`: local tooling (registry mirrors, formatters, lockfile
rewrites) leaves churn that does not belong in their tree.

```bash
git add <paths you changed>
git diff --cached --stat     # nothing you did not name; no lockfile churn
```

A missing sign-off is only fixable by rewriting and force-pushing the PR branch — catch it
before the first push.

## 4. Their pre-commit in a fresh worktree

A fresh worktree has no virtualenv and no `node_modules`. Hooks then fail on missing tooling,
which reads exactly like a real failure.

```bash
cd <dir>
# Python side — either build fresh, or reuse the primary checkout's env (same lockfile, same interpreter):
uv sync                                  # or: ln -s <primary-checkout>/.venv .venv
# JS side — always install fresh. Never symlink the primary checkout's node_modules: it drifts
# from upstream's lockfile and produces bogus unresolvable-import errors.
pnpm install --frozen-lockfile           # or npm ci / yarn --immutable, per their lockfile
# Then THEIR entry point, whatever CONTRIBUTING names:
pre-commit run --files $(git diff --name-only "upstream/$BASE"...HEAD)   # or `just check`, `make lint`, …
```

Prefer their task runner (`just`, `make`, `pnpm run`) over invoking tools yourself — it pins the
versions and flags their CI uses.

## 5. Baseline failure or mine?

Before reporting any red result, reproduce it without your change:

```bash
git worktree add ../<repo>-pristine "upstream/$BASE"
cd ../<repo>-pristine && <same install steps> && <exact same test command, same file>
```

- Fails the same way there → **baseline**. Note it in the PR ("N pre-existing failures in this
  environment, identical on `upstream/<default>`: `<one representative message>`"). Do not patch
  their config to make your environment pass.
- Passes there → **yours**. Fix it.
- Quick variant for an uncommitted change: `git stash -u`, re-run, `git stash pop`.

Worked example: omnigent's Vitest suite showed 853 failures, every one
`localStorage is not available for opaque origins` (a jsdom/vitest interaction). Identical on
a pristine checkout → baseline, reported, not "fixed" in the PR.

## 6. Sandboxed demo capture

A screenshot of your real instance leaks real data (session titles, names, paths) into a public
PR. Point the app at throwaway state, seed fixtures through its own API, then capture.

```bash
SANDBOX="$(mktemp -d)"
# omnigent: both config and data dirs are relocatable
OMNIGENT_CONFIG_HOME="$SANDBOX/config" OMNIGENT_DATA_DIR="$SANDBOX/data" <their dev-server command>
# seed plausible fixture data via the app's HTTP API, never by copying real state
```

Drive and record per the `demo-capture` skill (Playwright or chrome-devtools; GIF + stills).
Stop the server and delete `$SANDBOX` afterwards. Look at every frame before it leaves the
machine.

## 7. Images into the PR body from the CLI

`gh` has no attachment upload. Host the PNGs on a ref of **your fork** (not the PR branch, so
they stay out of the diff) through the API — no checkout needed. Pushing to a public fork is
itself outward-facing: same consent as the PR.

```bash
FORK=<you>/<repo>; REF=demo-assets-<issue>
SHA=$(gh api repos/$FORK/git/ref/heads/$(gh api repos/$FORK -q .default_branch) -q .object.sha)
gh api repos/$FORK/git/refs -f ref="refs/heads/$REF" -f sha="$SHA"
for f in demo/*.png demo/*.gif; do
  gh api -X PUT "repos/$FORK/contents/demo/$(basename "$f")" \
    -f message="demo assets for <upstream>#<issue>" -f branch="$REF" \
    -f content="$(base64 < "$f" | tr -d '\n')"
done
# Over ~500 KB a file overflows argv: build the JSON body with jq and pass `--input -` instead.
curl -sIL "https://raw.githubusercontent.com/$FORK/$REF/demo/<file>.png" | grep -i -E '^(HTTP|content-type)'
```

Embed `![<what it shows>](https://raw.githubusercontent.com/<you>/<repo>/demo-assets-<issue>/demo/<file>.png)`.
Keep the ref until the PR merges — deleting it 404s every image. `demo-capture` describes the
same hosting with a local commit instead of the contents API.

## 8. Opening the PR

```bash
gh api repos/<upstream>/contents/.github/pull_request_template.md -q .content | base64 -d   # fill every section
git push -u <fork-remote> <branch>
gh pr create --repo <upstream> --base "$BASE" --head <you>:<branch> \
  --title "<their title convention>" --body-file <filled-template>.md
```

Before `gh pr create`, the destination check (from this marketplace): it refuses a public
upstream until the **human** names it.

```bash
uv run --no-project python "$CLAUDE_PLUGIN_ROOT/scripts/destination_preflight.py" <upstream> --base "$BASE"
# outcome=refused → stop and ask. The human, not the agent, sets RPW_DESTINATION_OPT_IN=<upstream>.
```

After it merges — or a maintainer ships an equivalent fix — close out with the
`oss-contribution-closeout` skill.
