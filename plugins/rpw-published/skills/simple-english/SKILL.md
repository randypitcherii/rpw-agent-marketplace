---
name: simple-english
description: Write or rewrite technical text with ASD-STE100 Simplified Technical English rules so it is clear, unambiguous, and free of AI slop. Use for documentation, READMEs, runbooks, error messages, release notes, incident reports, and API guides. Trigger on "STE", "Simplified Technical English", "ASD-STE100", "de-slop", "make this readable", or "write for non-native readers". Enforces 20/25-word sentence limits, one word one meaning, simple tenses, active voice, condition before command.
license: MIT
---

# Simple English: Write Like an Aerospace Manual

STE is the controlled language that aerospace manufacturers use for maintenance documentation. The rules exist so that a tired reader who is not a native English speaker cannot misread an instruction. As a side effect, they remove the signs of AI-generated text: long sentences, synonym rotation, hedges, and filler.

Write for that tired reader. Each sentence must survive one read.

Adapted from [AminBlg/SimpleEnglish](https://github.com/AminBlg/SimpleEnglish) (MIT license).

## Your Task

When asked to write or rewrite technical text:

1. **Select the mode** (pragmatic or strict, below).
2. **Classify each passage** as procedural or descriptive. Every other rule depends on this.
3. **Fix your vocabulary before drafting.** Pick ONE verb for the check/verify/confirm/validate concept and ONE noun for config/settings. Use no other word for these concepts in the whole document.
4. **Apply the core rules** below. In strict mode, also read `references/rule-catalog.md`.
5. **Run the self-check** before you deliver. This step is not optional.
6. **Never touch code**, identifiers, commands, or quoted errors (see Untouchables).

When asked to CHECK text instead of writing it, first read `references/rule-catalog.md`, then report each violation as: rule number, the offending text, a compliant rewrite. Cite only rule numbers that exist in that file. Do not cite rule numbers from memory — the numbering is unintuitive and models invent it.

## Two Modes

| Mode | When | What you apply |
|---|---|---|
| **Pragmatic** (default) | Docs, READMEs, error messages — the user wants clear text | All structural rules. Domain words stay ("idempotent", "webhook"). |
| **Strict** | The user names STE, ASD-STE100, or compliance | Structural rules + full vocabulary discipline. Tell the user that full compliance needs the official dictionary (asd-ste100.org). |

## Step 1: Classify the Text

| | Procedural (instructions) | Descriptive (explanations) |
|---|---|---|
| Purpose | Tell the reader what to do | Explain what a thing is or does |
| Verb form | Imperative: "Install the pump." | Simple present/past/future |
| Sentence limit | **20 words** (Rule 5.1) | **25 words** (Rule 6.3) |
| Unit rule | One instruction per sentence (5.2) | One topic per paragraph (6.5), max six sentences per paragraph (6.6) |

Do not mix the two in one passage. A "Getting started" section is procedural. An "Architecture" section is descriptive. So is a note inside a procedure.

## Core Rules

**Words (Section 1).** One item, one name — do not call it "config" here and "settings" there (1.11). Domain nouns and verbs are legal: "webhook", "deploy" (1.5, 1.12). Do not use nouns as verbs or verbs as nouns (1.7, 1.13). American spelling (1.14). Multi-word nouns get three words maximum — break longer chains with prepositions: "the timeout value for the connection pool" (2.1).

**Verbs (Section 3).** Use only: infinitive, imperative, simple present, simple past, simple future, past participle as adjective (3.2). No perfect tenses, no "is to be installed" (3.4). Use an "-ing" form only inside a technical noun ("logging") — never as a verb (3.5). Active voice; passive is legal only in descriptive text when the agent is unknown (3.6). Describe an action with a verb: "compress the file", not "perform compression of the file" (3.7).

**Approved modals: can, will, must. Banned: should, would, may, might, could.** Write "an explosion can occur", never "could occur". This matters double for agent instructions — models read "should" as optional.

| You wrote | STE writes |
|---|---|
| should (requirement) | must |
| should (recommendation) | Delete it, or state it as fact: "X is better because Y." |
| may / might / could (possibility) | can |
| may (permission) | can |
| would (hypothetical) | Restructure: "If X occurs, Y occurs." |

**Sentences (Section 4).** Short sentences with complete grammar, not telegraph style. Keep articles, keep "that", no contractions (4.2, 4.5). Wrong shortening: "Ensure file exists before running." STE: "Make sure that the file exists before you run the command."

**Procedures (Section 5).** Maximum 20 words per sentence (5.1). One instruction per sentence, unless two actions happen at the same time (5.2). Imperative: "Run the migration." (5.3). Put a required condition before the command, divided by a comma: "If the build fails, read the log." (5.4). Notes give information, never instructions (5.5).

**Descriptions (Section 6).** Maximum 25 words per sentence (6.3). One new fact per sentence (6.1). One topic per paragraph, maximum six sentences (6.5, 6.6). No imperative in descriptive text.

**Safety (Section 7).** Risk word first ("WARNING" = injury, "CAUTION" = damage), then the command or condition, then the possible result. Never bury the instruction after the explanation. The pattern transfers to destructive CLI flags and irreversible migrations:

> CAUTION: Do not use the `--force` flag against production. The flag deletes rows that do not match the source.

**Punctuation and word count (Section 8).** No semicolons — write two sentences (8.1). Numbers, numbers with units, abbreviations, identifiers, and quoted or backticked text each count as one word (8.6), so long identifiers do not blow the sentence budget.

**Practices (Section 9).** When a word-for-word replacement does not work, restructure the sentence (9.1). No phrasal verbs: "go down" → "decrease", "set up" → "install" or "configure" (9.3). Keep one consistent style and terminology through the whole document (9.4). "e.g." → "for example", "i.e." → "that is", and delete "etc." — name the items (GR-6).

## Slop-to-Simple Substitutions

This table maps the words AI-generated docs overuse to plain replacements. If the word carries no fact, delete it instead of replacing it.

| Slop | Write instead |
|---|---|
| leverage, utilize | use |
| in order to | to |
| prior to | before |
| ensure | make sure that |
| it is worth noting that, crucially | (delete — state the fact) |
| simply, just, easily, seamlessly | (delete) |
| robust, powerful, comprehensive | (delete, or give the measurable property) |
| enables you to, allows you to | you can |
| in the event that | if |
| due to the fact that | because |
| as needed, as necessary | (state the condition) |
| and/or | Pick one, or write "X, or Y, or both" |
| gracefully handles | (say what it does: "retries three times, then stops") |
| out of the box | by default |
| under the hood | internally |

## Consistency Pass

Collapse these common rotations to one term each (Rules 1.11, 9.4):

- check / verify / confirm / validate / ensure → pick one
- config / configuration / settings / options → pick one
- delete / remove / drop / destroy → one per meaning
- error / issue / problem / failure → "error" for errors, "failure" for failed operations
- run / execute / invoke / launch → pick one

## Untouchables

These are technical names (Rules 1.5, 8.6). Leave them exact, even when they break vocabulary rules:

- Code blocks, inline code, identifiers, CLI commands, flags, file paths
- Quoted error messages and log lines
- Product names, API endpoint names, config keys
- Numbers with units — each counts as one word in the sentence limit

## Beyond Documentation

Same rules, different targets. Full adaptations in `references/use-cases.md`:

- **Error messages**: what happened (simple past), the cause if known, then the fix as an imperative. No "Oops", no apology filler.
- **Runbooks and release notes**: imperative steps, conditions first, warnings before the step.
- **Incident reports**: simple past only, with times and numbers: "Between 14:02 and 14:31 UTC, 12% of requests failed."
- **Agent instructions (prompts, AGENTS.md)**: a system prompt is a procedure for a reader that cannot ask questions. One instruction per sentence, no "should", condition first.

## Self-Check Before You Deliver

This step is not optional. Run these checks on your draft:

1. Count words in your three longest sentences. Over the 20/25 limit → split them.
2. Search your draft for: `'ll`, `'re`, `'s` (contraction), `has been`, `have been`, `should`, `-ing` verbs after a comma, semicolons.
3. Search for every `if` and `when`. Each one stands at the START of its sentence, before the command. "Increase the timeout if the network is slow" → "If the network is slow, increase the timeout."
4. Search for the verbs you did NOT pick in Your Task step 3 (the check/verify/confirm set). Replace every hit with your chosen verb.

Fix what you find, then deliver. For a full audit, run `references/checklist.md`.

## Limits

STE is for technical facts and instructions. Do not apply it to marketing copy, blog voice, or brand writing — it deletes persuasion by design.

This skill is an unofficial aid. It is not affiliated with or endorsed by ASD or STEMG, and no tool can guarantee STE compliance. ASD-STE100 is a registered trademark of ASD. The official standard is a free download at asd-ste100.org.

## References

- `references/rule-catalog.md` — the full 53-rule catalog, vocabulary rulings, worked example
- `references/checklist.md` — verification pass with searchable patterns, for check mode and audits
- `references/use-cases.md` — adaptations: error messages, runbooks, incident reports, commits, UI copy, i18n
