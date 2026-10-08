# Data visualization reference

## Choose the form

| Reader's task | Prefer | Avoid |
|---|---|---|
| Compare magnitudes | sorted bar, dot plot | area or angle |
| Show change over time | line, small multiples | unordered bars |
| Show a distribution | histogram, box/violin plus points | only an average |
| Show relationship | scatterplot, faceted scatterplot | connecting unordered points |
| Show composition | stacked bar for a few parts | many pie slices |
| Find a value | table | decorative chart |
| Show one important value | headline number with context | gauge |
| Show geography | map only when location explains the pattern | map used as decoration |

Small multiples are safer than a second axis. A table is better when exact lookup is
the main task.

## Encoding order

Prefer channels people compare accurately:

1. position on a shared scale;
2. position on aligned scales;
3. length;
4. angle or area;
5. color lightness or saturation.

Use shape, labels, or texture with color when series must remain distinguishable in
print, forced-colors mode, or common color-vision deficiencies.

## Color roles

- **Categorical:** a short, ordered list of distinct colors. Keep one entity mapped to
  one color across every view.
- **Sequential:** one hue from light to dark. State whether light or dark means more.
- **Diverging:** two ordered ramps around a meaningful neutral value such as zero.
- **Status:** pair the status color with text or an icon. Do not reuse status colors as
  arbitrary series colors.

The validator checks WCAG contrast against the supplied surface and OKLab distance
between every color pair. It cannot prove semantic consistency, label quality, or
color-vision accessibility; inspect those separately.

## Marks and labels

- Give axes names and units. Format values consistently.
- Sort categories in the order that answers the question, not alphabetically by habit.
- Keep grid lines quieter than data marks.
- Make selected and hovered states visible without shrinking the mark.
- Reserve annotation for decisions, events, and outliers. Do not narrate every point.
- Put source, date range, filters, and important exclusions next to the chart.

## Interaction

- A pointer target can be larger than its visible mark.
- Every pointer action needs a keyboard path and visible focus.
- Tooltips repeat the series/category, exact value, unit, and relevant time.
- Filters preserve stable color assignments and expose the active state in text.
- Motion respects `prefers-reduced-motion`; never animate merely to delay reading.
- Loading, empty, error, and partial-data states say what happened and what remains.

## Final review

1. Can a reader state the main comparison in five seconds?
2. Does the chart remain understandable without color?
3. Are units, time range, source, and filters visible?
4. Does the equivalent table contain the same values?
5. Does the rendered output work at narrow width, 200% zoom, and in dark mode?
