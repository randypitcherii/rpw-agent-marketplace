---
name: oss-contribution-closeout
description: Close out public-repo issues and PRs after an upstream maintainer merges a canonical solution. Use when a contributor's issue or PR was solved or superseded elsewhere and the user wants bidirectional GitHub links, duplicate closure, and a clean review trail. Not for deciding whether an unmerged competing PR should win.
---

# Close out superseded OSS contributions

Parallel OSS work often lands through a maintainer's PR while the contributor's original issue or PR remains open. Closing the duplicate without linking from the shipped solution loses attribution and makes the project history look unresolved.

**Start at the merged PR that actually shipped. Link outward from that canonical object first; close contributor objects only after those references exist.**

## Preconditions

This workflow changes public GitHub state. Run it only when the user has authorized linking and closing the specified contributions.

For each candidate issue or PR:

1. Confirm the canonical PR is merged, not merely closed.
2. Compare the problem, acceptance criteria, implementation, and user-visible result. Similar titles are not enough.
3. Classify the relationship:
   - **Completed** — the merged PR fully satisfies the issue. The issue may close.
   - **Superseded** — the merged PR delivers the same intended outcome as another PR. The duplicate PR may close.
   - **Advances** — only part of the requested outcome shipped. Link it, but leave the original open.
   - **Related only** — overlap is incidental. Do not call it completed or superseded.

If the relationship is uncertain or the remaining gap is material, stop and ask rather than closing useful work.

## Canonical-first linking

Post one consolidated comment on the merged PR. Mention every original object using a fully qualified reference (`owner/repo#123`), even when it is in the same repository; this remains unambiguous if the text is copied elsewhere.

```text
Follow-up linkage: this merged PR completed owner/repo#123 and superseded owner/repo#456. This PR is the canonical shipped implementation.
```

GitHub turns those mentions into timeline backlinks on the referenced issues and PRs. That automatic backlink is sufficient reciprocal linkage; do not add duplicate “see merged PR” comments merely for symmetry.

After posting, verify the comment exists on the canonical PR. If automatic linking is unavailable or the objects are on a tracker that does not create backlinks, add one concise comment to each original object linking the merged PR.

Do not rewrite a merged PR body solely to add retrospective links. A follow-up comment preserves the immutable review record and is visible in its timeline.

## Close only what the merged PR resolved

After canonical-first linkage:

- Close a fully completed issue with a short reason if it is still open.
- Close a superseded PR; leave its branch and discussion intact so reviewers can inspect it later.
- Leave partial issues open and state the remaining acceptance criteria.
- Never delete branches, issues, PRs, comments, or contributor evidence as part of this workflow.

Use the target repository's conventions and permissions. On an external repo, do not add labels, milestones, assignees, or closing keywords the maintainers did not request.

Example commands:

```bash
gh pr comment <merged-pr> --repo owner/repo --body \
  'Follow-up linkage: this merged PR completed owner/repo#123 and superseded owner/repo#456. This PR is the canonical shipped implementation.'
gh issue close 123 --repo owner/repo --comment 'Completed by owner/repo#789.'
gh pr close 456 --repo owner/repo --comment 'Superseded by owner/repo#789.'
```

Omit the close-side comment when the canonical mention already produced a clear backlink and no additional explanation is needed.

## Verification and report

Re-read the final states rather than trusting command success:

```bash
gh pr view <merged-pr> --repo owner/repo --json state,mergedAt,comments,url
gh issue view <issue> --repo owner/repo --json state,url
gh pr view <duplicate-pr> --repo owner/repo --json state,url
```

Report the canonical merged PR first, followed by each completed issue, superseded PR, and anything deliberately left open. Keep the report short and name why each object was closed or retained.

## Boundaries

- Preparing, reviewing, or merging the canonical PR belongs to `code-review-and-pr` or the repository's normal merge workflow.
- Migrating an entire repository and forwarding its tracker belongs to `archive-migrated-repo`.
- Creating a replacement issue belongs to `issue-creation`.
- This skill closes attribution and traceability gaps after the solution has already merged; it does not choose between live competing implementations.
