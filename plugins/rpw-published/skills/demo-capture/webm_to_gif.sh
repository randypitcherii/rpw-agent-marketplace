#!/usr/bin/env bash
# Convert a Playwright .webm recording to a compact, crisp GIF.
# No system ffmpeg needed: imageio-ffmpeg's static binary is fetched via uv.
#
# Usage: ./webm_to_gif.sh input.webm output.gif [fps] [width]
#   fps    default 12 — UI flows read fine at 12 fps; drop to 10 if oversized
#   width  default 1080 — pixels; drop to 900 if the GIF exceeds ~5 MB
set -euo pipefail

IN="${1:?usage: webm_to_gif.sh input.webm output.gif [fps] [width]}"
OUT="${2:?usage: webm_to_gif.sh input.webm output.gif [fps] [width]}"
FPS="${3:-12}"
WIDTH="${4:-1080}"

FFMPEG="$(uv run --with imageio-ffmpeg python -c \
  'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())' 2>/dev/null | tail -1)"

# Two-pass palette: generate an optimal per-file palette, then dither with it.
# This is what keeps a 1440x900 UI recording crisp at ~1 MB instead of mushy at ~8 MB.
"$FFMPEG" -y -i "$IN" \
  -vf "fps=${FPS},scale=${WIDTH}:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=128[p];[s1][p]paletteuse=dither=bayer" \
  -loop 0 "$OUT"

SIZE=$(stat -f%z "$OUT" 2>/dev/null || stat -c%s "$OUT")
echo "$OUT — $((SIZE / 1024)) KiB"
if [ "$SIZE" -gt 5242880 ]; then
  echo "warning: >5 MiB; rerun with lower fps/width, e.g. ./webm_to_gif.sh $IN $OUT 10 900" >&2
fi
