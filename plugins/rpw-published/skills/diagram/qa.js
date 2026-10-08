/* Browser-side deterministic checks for qa.sh.
 *
 * qa.sh evaluates this async function in a Chrome DevTools isolated world and
 * receives its return value over the DevTools pipe. Authored HTML therefore
 * cannot block the checker with CSP or forge its receipt. Semantic truth and
 * editorial quality remain human review; these checks cover only geometry and
 * artifact properties the browser can establish.
 */
async (meta) => {
  "use strict";

  const checkIds = [
    "html-contract",
    "external-resources",
    "clipped-content",
    "text-overlap",
    "connector-outside-gutter",
    "connector-crosses-text",
    "connector-crossing",
    "connector-label-length",
    "legible-text",
    "png-dimensions",
    "non-blank",
  ];
  const findings = [];
  const failed = new Set();
  const tolerance = 1;

  function selector(element) {
    if (!element || element.nodeType !== Node.ELEMENT_NODE) return "unknown";
    if (element === document.body) return "body";
    if (element.id) return `#${element.id}`;
    const parts = [];
    for (let node = element; node && node !== document.body; node = node.parentElement) {
      let part = node.tagName.toLowerCase();
      if (node.classList.length) part += `.${[...node.classList].slice(0, 2).join(".")}`;
      parts.unshift(part);
    }
    return `body > ${parts.join(" > ")}`;
  }

  function fail(check, element, message, evidence, supportedFixes) {
    failed.add(check);
    findings.push({
      check,
      subject: selector(element),
      message,
      evidence,
      supportedFixes,
    });
  }

  function intersection(a, b) {
    const left = Math.max(a.left, b.left);
    const right = Math.min(a.right, b.right);
    const top = Math.max(a.top, b.top);
    const bottom = Math.min(a.bottom, b.bottom);
    return right - left > tolerance && bottom - top > tolerance;
  }

  function segmentIntersection(a, b, c, d) {
    const denominator = (a.x - b.x) * (c.y - d.y) - (a.y - b.y) * (c.x - d.x);
    if (Math.abs(denominator) <= tolerance / 10) return null;
    const t = ((a.x - c.x) * (c.y - d.y) - (a.y - c.y) * (c.x - d.x)) / denominator;
    const u = -((a.x - b.x) * (a.y - c.y) - (a.y - b.y) * (a.x - c.x)) / denominator;
    if (t < 0 || t > 1 || u < 0 || u > 1) return null;
    return { x: a.x + t * (b.x - a.x), y: a.y + t * (b.y - a.y) };
  }

  function nearConnectorEndpoint(point, connector) {
    const endpoints = [connector.points[0], connector.points[connector.points.length - 1]];
    return endpoints.some(
      (endpoint) => Math.hypot(point.x - endpoint.x, point.y - endpoint.y) <= tolerance * 2,
    );
  }

  function roundedRect(rect) {
    return {
      left: Math.round(rect.left * 10) / 10,
      top: Math.round(rect.top * 10) / 10,
      right: Math.round(rect.right * 10) / 10,
      bottom: Math.round(rect.bottom * 10) / 10,
    };
  }

  // A pixel counts as ink when any channel is at or below this, so the theme's
  // darkest flat fill (--muted #F2F2F2 = 242) counts and near-white
  // antialiasing does not. The check is a floor, not a density policy, so the
  // exact cutoff only has to separate "drew something" from "drew nothing".
  const inkChannelMax = 246;

  async function nonWhitePixelShare(base64) {
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) {
      bytes[index] = binary.charCodeAt(index);
    }
    const bitmap = await createImageBitmap(new Blob([bytes], { type: "image/png" }));
    // Read the dimensions now: close() zeroes them, and dividing by a post-close
    // 0 area yields Infinity, which JSON.stringify renders as a null share.
    const width = bitmap.width;
    const height = bitmap.height;
    const canvas = new OffscreenCanvas(width, height);
    const context = canvas.getContext("2d", { willReadFrequently: true });
    // Flatten onto white FIRST. Page.captureScreenshot can return RGBA whose
    // background is transparent; reading that unflattened counts every
    // transparent pixel as black and reports ~100% non-white — the opposite
    // false result, which passes a blank PNG just as happily.
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, width, height);
    context.drawImage(bitmap, 0, 0);
    const pixels = context.getImageData(0, 0, width, height).data;
    let ink = 0;
    for (let index = 0; index < pixels.length; index += 4) {
      if (
        pixels[index] <= inkChannelMax ||
        pixels[index + 1] <= inkChannelMax ||
        pixels[index + 2] <= inkChannelMax
      ) {
        ink += 1;
      }
    }
    bitmap.close();
    return ink / (width * height);
  }

  function textFragments() {
    const fragments = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let text = walker.nextNode(); text; text = walker.nextNode()) {
      if (!text.textContent.trim()) continue;
      const element = text.parentElement;
      const style = getComputedStyle(element);
      if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) === 0) {
        continue;
      }
      const range = document.createRange();
      range.selectNodeContents(text);
      for (const rect of range.getClientRects()) {
        if (rect.width > tolerance && rect.height > tolerance) {
          fragments.push({ element, rect, text: text.textContent.trim() });
        }
      }
    }
    return fragments;
  }

  const title = document.querySelectorAll("h1");
  const subtitle = document.querySelector(".hd > p");
  if (title.length !== 1) {
    fail("html-contract", document.body, "Expected exactly one h1.", { count: title.length }, [
      "Keep one answer-first title in .hd.",
    ]);
  }
  if (!subtitle) {
    fail("html-contract", document.body, "Missing the .hd > p reading instruction.", {}, [
      "Add one subtitle sentence beside the title.",
    ]);
  } else {
    const range = document.createRange();
    range.selectNodeContents(subtitle);
    if (range.getClientRects().length !== 1) {
      fail("html-contract", subtitle, "Subtitle wraps beyond one line.", {
        lines: range.getClientRects().length,
      }, ["Shorten the reading instruction or reduce the title width."]);
    }
  }
  if (document.body.getBoundingClientRect().width > 1600 + tolerance) {
    fail("html-contract", document.body, "Canvas exceeds the 1600 CSS px width limit.", {
      width: document.body.getBoundingClientRect().width,
    }, ["Set --canvas-w to 1600px or less."]);
  }

  const resourceAttributes = ["src", "href", "srcset", "poster", "action", "formaction"];
  for (const element of document.querySelectorAll(
    "[src], [href], [srcset], [poster], [action], [formaction], object[data]",
  )) {
    const attributes = [
      ...resourceAttributes.filter((name) => element.hasAttribute(name)),
      ...(element.matches("object[data]") ? ["data"] : []),
    ];
    for (const attribute of attributes) {
      const raw = element.getAttribute(attribute) || "";
      if (raw && !raw.startsWith("#") && !raw.startsWith("data:")) {
        fail("external-resources", element, "Diagram references a non-inline resource.", {
          attribute,
          value: raw,
        }, ["Inline the asset as data or inline SVG."]);
      }
    }
  }
  const cssUrlPattern = /url\(\s*(['"]?)([^'")]+)\1\s*\)/gi;
  for (const element of document.querySelectorAll("style, [style]")) {
    const css = element.tagName === "STYLE" ? element.textContent : element.getAttribute("style") || "";
    for (const match of css.matchAll(cssUrlPattern)) {
      const raw = match[2].trim();
      if (raw && !raw.startsWith("#") && !raw.startsWith("data:")) {
        fail("external-resources", element, "CSS references a non-inline resource.", { value: raw }, [
          "Inline the asset as data or inline SVG.",
        ]);
      }
    }
    if (/@import\s+(?:url\()?['"]?(?!data:|#)/i.test(css)) {
      fail("external-resources", element, "CSS imports a non-inline stylesheet.", {}, [
        "Inline stylesheet rules in the diagram HTML.",
      ]);
    }
  }
  for (const entry of performance.getEntriesByType("resource")) {
    if (/^https?:/i.test(entry.name)) {
      fail("external-resources", document.body, "Rendering made a network request.", {
        url: entry.name,
      }, ["Remove remote fonts, stylesheets, scripts, and images."]);
    }
  }
  if (Number(meta.externalNetworkCount) > 0) {
    fail("external-resources", document.body, "Chrome observed an external network attempt.", {
      requests: Number(meta.externalNetworkCount),
    }, ["Remove HTTP, WebSocket, WebTransport, and other remote dependencies."]);
  }

  const fragments = textFragments();
  const bodyRect = document.body.getBoundingClientRect();
  for (const fragment of fragments) {
    const rect = fragment.rect;
    if (
      rect.left < bodyRect.left - tolerance ||
      rect.top < bodyRect.top - tolerance ||
      rect.right > bodyRect.right + tolerance ||
      rect.bottom > bodyRect.bottom + tolerance
    ) {
      fail("clipped-content", fragment.element, "Text extends beyond the canvas.", {
        text: fragment.text.slice(0, 80),
        textRect: roundedRect(rect),
        canvasRect: roundedRect(bodyRect),
      }, ["Let the body grow or reduce the content width."]);
    }
    for (let ancestor = fragment.element.parentElement; ancestor; ancestor = ancestor.parentElement) {
      const style = getComputedStyle(ancestor);
      if (!/(hidden|clip)/.test(`${style.overflow} ${style.overflowX} ${style.overflowY}`)) continue;
      const clip = ancestor.getBoundingClientRect();
      if (
        rect.left < clip.left - tolerance ||
        rect.top < clip.top - tolerance ||
        rect.right > clip.right + tolerance ||
        rect.bottom > clip.bottom + tolerance
      ) {
        fail("clipped-content", ancestor, "An overflow boundary clips text.", {
          text: fragment.text.slice(0, 80),
          textRect: roundedRect(rect),
          clipRect: roundedRect(clip),
        }, ["Remove fixed height/width and let the card or group size to content."]);
        break;
      }
    }
  }
  for (const element of document.querySelectorAll("body *")) {
    const style = getComputedStyle(element);
    if (
      /(hidden|clip)/.test(`${style.overflow} ${style.overflowX} ${style.overflowY}`) &&
      (element.scrollWidth > element.clientWidth + tolerance ||
        element.scrollHeight > element.clientHeight + tolerance)
    ) {
      fail("clipped-content", element, "An overflow boundary hides laid-out content.", {
        client: [element.clientWidth, element.clientHeight],
        scroll: [element.scrollWidth, element.scrollHeight],
      }, ["Remove fixed dimensions and let the container grow."]);
    }
  }

  for (let i = 0; i < fragments.length; i += 1) {
    for (let j = i + 1; j < fragments.length; j += 1) {
      const a = fragments[i];
      const b = fragments[j];
      if (a.element === b.element || !intersection(a.rect, b.rect)) continue;
      fail("text-overlap", a.element, "Two text fragments overlap.", {
        other: selector(b.element),
        firstText: a.text.slice(0, 60),
        secondText: b.text.slice(0, 60),
      }, ["Increase the grid track or gap; shorten one label."]);
    }
  }

  const connectorGeometries = [];
  for (const geometry of document.querySelectorAll(".conn svg > path, .conn svg > line")) {
    const gutter = geometry.closest(".conn");
    const gutterRect = gutter.getBoundingClientRect();
    const length = geometry.getTotalLength();
    const matrix = geometry.getScreenCTM();
    const points = [];
    let outside = null;
    let crossed = null;
    for (let distance = 0; distance <= length; distance += Math.max(1, length / 100)) {
      const local = geometry.getPointAtLength(distance);
      const point = new DOMPoint(local.x, local.y).matrixTransform(matrix);
      points.push({ x: point.x, y: point.y });
      if (
        point.x < gutterRect.left - tolerance ||
        point.x > gutterRect.right + tolerance ||
        point.y < gutterRect.top - tolerance ||
        point.y > gutterRect.bottom + tolerance
      ) {
        outside = { x: Math.round(point.x), y: Math.round(point.y) };
      }
      const hit = fragments.find((item) => {
        const rect = item.rect;
        return (
          point.x >= rect.left - tolerance &&
          point.x <= rect.right + tolerance &&
          point.y >= rect.top - tolerance &&
          point.y <= rect.bottom + tolerance
        );
      });
      if (hit) crossed = hit;
    }
    if (outside) {
      fail("connector-outside-gutter", geometry, "Connector leaves its .conn gutter.", {
        point: outside,
        gutterRect: roundedRect(gutterRect),
      }, ["End the connector near x=90 and aim at the group boundary."]);
    }
    if (crossed) {
      fail("connector-crosses-text", geometry, "Connector crosses visible text.", {
        text: crossed.text.slice(0, 80),
        textSubject: selector(crossed.element),
      }, ["Move the label off the path or shorten/delete the connector."]);
    }
    connectorGeometries.push({ element: geometry, points });
  }

  for (let i = 0; i < connectorGeometries.length; i += 1) {
    for (let j = i + 1; j < connectorGeometries.length; j += 1) {
      const first = connectorGeometries[i];
      const second = connectorGeometries[j];
      let crossing = false;
      for (let a = 1; a < first.points.length && !crossing; a += 1) {
        for (let b = 1; b < second.points.length; b += 1) {
          const point = segmentIntersection(
            first.points[a - 1],
            first.points[a],
            second.points[b - 1],
            second.points[b],
          );
          if (point && !nearConnectorEndpoint(point, first) && !nearConnectorEndpoint(point, second)) {
            crossing = true;
            break;
          }
        }
      }
      if (crossing) {
        fail("connector-crossing", first.element, "Two connectors cross.", {
          other: selector(second.element),
        }, ["Route connectors in separate gutters or replace a return edge with prose."]);
      }
    }
  }

  for (const label of document.querySelectorAll(".elabel")) {
    const words = label.textContent.trim().split(/\s+/).filter(Boolean);
    if (words.length > 3) {
      fail("connector-label-length", label, "Connector label exceeds three words.", {
        words: words.length,
        text: label.textContent.trim(),
      }, ["Cut the label to 1–3 words or move the verb into a heading badge."]);
    }
  }

  for (const fragment of fragments) {
    const fontSize = Number.parseFloat(getComputedStyle(fragment.element).fontSize);
    if (fontSize < 10) {
      fail("legible-text", fragment.element, "Text is smaller than 10 CSS px.", {
        fontSize,
        text: fragment.text.slice(0, 80),
      }, ["Use at least 10 CSS px for the smallest label."]);
    }
  }

  const expectedWidth = Math.ceil(bodyRect.width) * Number(meta.scale || 2);
  const expectedHeight = Math.ceil(bodyRect.height) * Number(meta.scale || 2);
  if (meta.pngWidth !== expectedWidth || meta.pngHeight !== expectedHeight) {
    fail("png-dimensions", document.body, "PNG dimensions do not match the CSS canvas and scale.", {
      expected: [expectedWidth, expectedHeight],
      actual: [meta.pngWidth, meta.pngHeight],
      scale: Number(meta.scale || 2),
    }, ["Render the PNG again with render.sh at the same RPW_SCALE."]);
  }

  // Every other check measures a relationship between boxes that exist, so an
  // empty page violates none of them and png-dimensions is satisfied because
  // the pipeline is self-consistent even when it renders nothing (#1944). This
  // one reads the artifact itself: a floor on inked pixels, not a density
  // policy. The 18 committed diagrams measure 3.0%–47.8% ink, so a 1% floor
  // clears the thinnest of them 3x over while a blank page reads 0.00%.
  const nonWhiteFloor = 0.01;
  let nonWhiteShare = null;
  try {
    const measured = await nonWhitePixelShare(String(meta.pngData || ""));
    if (!Number.isFinite(measured) || measured < 0 || measured > 1) {
      throw new Error(`pixel read produced ${measured}`);
    }
    nonWhiteShare = Math.round(measured * 100000) / 100000;
  } catch (error) {
    // Fail closed: a pixel read that cannot run must not report a pass.
    fail("non-blank", document.body, "Could not read the PNG's pixels.", {
      error: String((error && error.message) || error),
    }, ["Re-render with render.sh and re-run qa.sh on the produced PNG."]);
  }
  if (nonWhiteShare !== null && nonWhiteShare < nonWhiteFloor) {
    fail("non-blank", document.body, "PNG is blank or near-blank.", {
      nonWhiteShare,
      floor: nonWhiteFloor,
      percent: `${(nonWhiteShare * 100).toFixed(2)}% non-white`,
    }, [
      "Open the PNG: the page rendered nothing.",
      "Check the <style> block survived authoring, then re-render.",
    ]);
  }

  const receipt = {
    schemaVersion: 1,
    ok: findings.length === 0,
    artifact: {
      html: meta.html,
      png: meta.png,
      cssPixels: [Math.ceil(bodyRect.width), Math.ceil(bodyRect.height)],
      pngPixels: [meta.pngWidth, meta.pngHeight],
      scale: Number(meta.scale || 2),
      // Recorded on pass as well as fail, so the receipt is evidence of what
      // was actually inked and not just of which assertions held.
      nonWhiteShare,
    },
    checks: checkIds.map((id) => ({ id, status: failed.has(id) ? "fail" : "pass" })),
    findings,
  };

  const validReceipt =
    receipt.schemaVersion === 1 &&
    typeof receipt.ok === "boolean" &&
    receipt.artifact &&
    typeof receipt.artifact.html === "string" &&
    typeof receipt.artifact.png === "string" &&
    Array.isArray(receipt.artifact.cssPixels) &&
    receipt.artifact.cssPixels.length === 2 &&
    receipt.artifact.cssPixels.every((value) => Number.isInteger(value) && value >= 0) &&
    Array.isArray(receipt.artifact.pngPixels) &&
    receipt.artifact.pngPixels.length === 2 &&
    receipt.artifact.pngPixels.every((value) => Number.isInteger(value) && value >= 0) &&
    Number.isInteger(receipt.artifact.scale) &&
    receipt.artifact.scale > 0 &&
    ((typeof receipt.artifact.nonWhiteShare === "number" &&
      receipt.artifact.nonWhiteShare >= 0 &&
      receipt.artifact.nonWhiteShare <= 1) ||
      (receipt.artifact.nonWhiteShare === null && failed.has("non-blank"))) &&
    Array.isArray(receipt.checks) &&
    receipt.checks.length === checkIds.length &&
    receipt.checks.every(
      (check, index) =>
        check.id === checkIds[index] && (check.status === "pass" || check.status === "fail"),
    ) &&
    Array.isArray(receipt.findings) &&
    receipt.findings.every(
      (finding) =>
        checkIds.includes(finding.check) &&
        typeof finding.subject === "string" &&
        typeof finding.message === "string" &&
        finding.evidence &&
        typeof finding.evidence === "object" &&
        !Array.isArray(finding.evidence) &&
        Array.isArray(finding.supportedFixes) &&
        finding.supportedFixes.every((fix) => typeof fix === "string"),
    ) &&
    receipt.ok === receipt.checks.every((check) => check.status === "pass") &&
    receipt.ok === (receipt.findings.length === 0);
  if (!validReceipt) {
    throw new Error("qa.js produced an invalid receipt");
  }
  return receipt;
}
