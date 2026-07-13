# PPTX — `python-pptx`

Create, read, and edit PowerPoint decks. License: MIT.

```bash
uv run --with python-pptx python <script.py>
```

## Read

```python
from pptx import Presentation
prs = Presentation("deck.pptx")
for i, slide in enumerate(prs.slides, 1):
    for shape in slide.shapes:
        if shape.has_text_frame:
            print(i, "|", shape.text_frame.text)
        if shape.has_table:
            for row in shape.table.rows:
                print([c.text for c in row.cells])
```

## Create a deck

```python
from pptx import Presentation
from pptx.util import Inches, Pt
prs = Presentation()                       # default 4:3; or Presentation("template.pptx")

# Title slide — layout 0 is "Title Slide", 1 is "Title and Content"
title = prs.slides.add_slide(prs.slide_layouts[0])
title.shapes.title.text = "Quarterly Review"
title.placeholders[1].text = "Q2 2026"

# Bullets slide
body = prs.slides.add_slide(prs.slide_layouts[1])
body.shapes.title.text = "Highlights"
tf = body.placeholders[1].text_frame
tf.text = "Revenue up 12%"                  # first bullet
for line in ("Costs flat", "Two new logos"):
    p = tf.add_paragraph()
    p.text = line
    p.level = 1                             # indent level

# Free-form text box
blank = prs.slides.add_slide(prs.slide_layouts[6])  # layout 6 is blank
box = blank.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(1))
box.text_frame.text = "Thank you"
box.text_frame.paragraphs[0].font.size = Pt(40)

prs.save("review.pptx")
```

## Common extras

- **Images**: `slide.shapes.add_picture("img.png", Inches(1), Inches(1), width=Inches(4))`.
- **Tables**: `slide.shapes.add_table(rows, cols, left, top, width, height).table` then set
  `.cell(r, c).text`.
- **Charts**: `from pptx.chart.data import CategoryChartData` +
  `slide.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, ...)`.
- **Templates**: open an existing branded `.pptx` and add slides using its layouts to inherit
  theme/fonts.

## Verify after writing

Re-open with `Presentation(path)` and assert the expected slide count and title text.
