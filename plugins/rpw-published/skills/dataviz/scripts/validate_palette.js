#!/usr/bin/env node
/** Dependency-free gate for categorical chart colors. */

const HEX = /^#[0-9a-f]{6}$/i;

function rgb(hex) {
  return [1, 3, 5].map((start) => Number.parseInt(hex.slice(start, start + 2), 16) / 255);
}

function linear(channel) {
  return channel <= 0.04045
    ? channel / 12.92
    : Math.pow((channel + 0.055) / 1.055, 2.4);
}

function luminance(hex) {
  const [red, green, blue] = rgb(hex).map(linear);
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}

export function contrast(first, second) {
  const values = [luminance(first), luminance(second)].sort((a, b) => b - a);
  return (values[0] + 0.05) / (values[1] + 0.05);
}

// Published OKLab conversion matrices: https://bottosson.github.io/posts/oklab/
function oklab(hex) {
  const [red, green, blue] = rgb(hex).map(linear);
  const l = Math.cbrt(0.4122214708 * red + 0.5363325363 * green + 0.0514459929 * blue);
  const m = Math.cbrt(0.2119034982 * red + 0.6806995451 * green + 0.1073969566 * blue);
  const s = Math.cbrt(0.0883024619 * red + 0.2817188376 * green + 0.6299787005 * blue);
  return {
    lightness: 0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
    a: 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
    b: 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s,
  };
}

function distance(first, second) {
  const left = oklab(first);
  const right = oklab(second);
  return 100 * Math.hypot(
    left.lightness - right.lightness,
    left.a - right.a,
    left.b - right.b,
  );
}

export function validatePalette(colors, { surface = "#ffffff" } = {}) {
  const failures = [];
  if (!HEX.test(surface)) failures.push(`invalid surface: ${surface}`);
  if (colors.length < 2) failures.push("provide at least two colors");
  const invalid = colors.filter((color) => !HEX.test(color));
  if (invalid.length) failures.push(`invalid colors: ${invalid.join(", ")}`);
  if (failures.length) return { ok: false, failures, measurements: [] };

  const measurements = [];
  for (const color of colors) {
    const ratio = contrast(color, surface);
    measurements.push(`${color} contrast ${ratio.toFixed(2)}:1`);
    if (ratio < 3) failures.push(`${color} has less than 3:1 contrast against ${surface}`);
  }
  for (let left = 0; left < colors.length; left += 1) {
    for (let right = left + 1; right < colors.length; right += 1) {
      const delta = distance(colors[left], colors[right]);
      measurements.push(`${colors[left]} ↔ ${colors[right]} OKLab ΔE ${delta.toFixed(1)}`);
      if (delta < 12) {
        failures.push(`${colors[left]} and ${colors[right]} are too similar (OKLab ΔE ${delta.toFixed(1)} < 12)`);
      }
    }
  }
  return { ok: failures.length === 0, failures, measurements };
}

function parse(argv) {
  let surface = "#ffffff";
  let raw = null;
  for (let index = 0; index < argv.length; index += 1) {
    if (argv[index] === "--surface") {
      surface = argv[index + 1] || "";
      index += 1;
    } else if (raw === null) {
      raw = argv[index];
    } else {
      return { error: `unknown argument: ${argv[index]}` };
    }
  }
  if (!raw) return { error: 'usage: validate_palette.js "#hex,#hex" [--surface "#hex"]' };
  return { colors: raw.split(",").map((value) => value.trim()).filter(Boolean), surface };
}

if (process.argv[1]?.endsWith("validate_palette.js")) {
  const input = parse(process.argv.slice(2));
  if (input.error) {
    console.error(input.error);
    process.exitCode = 2;
  } else {
    const result = validatePalette(input.colors, { surface: input.surface });
    for (const measurement of result.measurements) console.log(measurement);
    for (const failure of result.failures) console.error(`FAIL: ${failure}`);
    console.log(result.ok ? "PASS: palette checks passed" : "FAIL: revise the palette");
    process.exitCode = result.ok ? 0 : 1;
  }
}
