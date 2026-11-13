# Report shape

The bucket depends on **what removal needs**. Within a bucket, sort by payoff × confidence.

| Bucket | Goes here when | Deliverable |
|---|---|---|
| **Delete now** | Verified dead, no decision record governs it, nothing at runtime breaks | A PR could land today. Give the exact `git rm` |
| **Needs a decision** | A decision record froze it, an open issue may still want it, or there is a live but questionable consumer | A one-line yes/no question |
| **Simplify** | Live and wanted, but oversized, duplicated or misplaced | Split, merge, move, or generate one copy from the other |

## Template

```markdown
**~N verified lines reclaimable; the biggest single win is <X> (~M lines).**

### Delete now
| Path | Action | Evidence | Lines | Conf |

### Needs a decision
| Path | Question (yes/no) | Evidence | Lines |

### Simplify
| Path | Change | Evidence | Payoff |

### Refuted (looked dead, isn't)
- <path>: <the live reference that saved it>

**Next action (<2 min):** `<exact command>`
```

Keep refuted rows in the report. They stop the next run from proposing them again, and they show the audit checked.

If the user asked for issues, file one per accepted row (or one grouped issue for a batch of small rows of the same kind), each linking back to this report. Never open a deletion PR straight from the audit.
