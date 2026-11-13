# Orient recipe

Run from the repo root. It works on any git repo; adjust the area list to the repo's top-level layout.

```bash
# Overall shape
git ls-files | wc -l
git log -1 --format=%cs                      # "today" for this repo: compare dates against it, not the wall clock

# Per area: files, lines, last touch, recent activity
for d in $(git ls-files | cut -d/ -f1-2 | sort -u); do
  [ -d "$d" ] || continue
  n=$(git ls-files "$d" | wc -l)
  l=$(git ls-files "$d" | xargs cat 2>/dev/null | wc -l)
  last=$(git log -1 --format=%cs -- "$d")
  c=$(git log --since=60.days --oneline -- "$d" | wc -l)
  printf "%-45s files=%-5s lines=%-7s last=%s commits60d=%s\n" "$d" "$n" "$l" "$last" "$c"
done | sort -t= -k3 -n -r | head -40

# Declared state: frozen, deprecated, superseded
git grep -n -i -E "frozen|superseded|deprecated|legacy|TODO.?remove|remove once" -- '*.md' | head -40
ls docs/decisions docs/adr adr 2>/dev/null       # decision records, if any

# Byte-identical files (duplication lens seed)
git ls-files -z | xargs -0 shasum 2>/dev/null | sort | awk '{print $1}' | uniq -d | head -20 \
  | while read h; do git ls-files -z | xargs -0 shasum | grep "^$h" | awk '{print $2}' | tr '\n' ' '; echo; done

# Biggest files (simplify lens seed)
git ls-files | xargs wc -l 2>/dev/null | sort -n -r | sed -n 2,21p
```

Read the output for **large and quiet**: high line counts, an old `last=` date, low `commits60d`. Those areas are the first ones to give a lens.
