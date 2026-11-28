/* The pitch graph measured against its kana (POLISH-321): where each point of the graph sits across its mora, and
   the room between the graph and the big word above it — positions, read from the page's own layout. */
window.__pitch = () => {
  const kana = document.querySelector('[data-r="reading"] .kana');
  const svg = kana && kana.querySelector("svg.pitch");
  if (!svg) return null;
  const word = document.querySelector(".wrow .w").getBoundingClientRect();
  const s = svg.getBoundingClientRect(), vb = svg.viewBox.baseVal, sx = s.width / vb.width, sy = s.height / vb.height;
  const pts = svg.querySelector("polyline").getAttribute("points").trim().split(/\s+/)
    .map((p) => p.split(",").map(Number)).map(([x, y]) => [s.left + x * sx, s.top + y * sy]);
  // each mora's box: its slot (the page draws one per mora), else its characters as they fell in the text
  const slots = [...kana.querySelectorAll(".mo")];
  const morae = slots.length ? slots.map((el) => { const b = el.getBoundingClientRect(), r = document.createRange();
    r.selectNodeContents(el); const g = r.getBoundingClientRect();
    return { ch: el.textContent, left: b.left, right: b.right, top: g.top, bottom: g.bottom, inkL: g.left, inkR: g.right }; }) : [];
  const node = [...kana.childNodes].find((n) => n.nodeType === 3 && n.textContent.trim());
  let at = 0;
  for (const c of slots.length || !node ? "" : node.textContent) {
    const r = document.createRange(); r.setStart(node, at); r.setEnd(node, at + c.length); at += c.length;
    const b = r.getBoundingClientRect();
    if (/[ゃゅょぁぃぅぇぉゎャュョァィゥェォヮ]/.test(c) && morae.length) {
      const m = morae[morae.length - 1]; m.right = m.inkR = b.right; m.ch += c;
    } else morae.push({ ch: c, left: b.left, right: b.right, top: b.top, bottom: b.bottom, inkL: b.left, inkR: b.right });
  }
  const text = morae.map((m) => m.ch).join("");
  return { text, morae, pts, svg: { left: s.left, top: s.top, bottom: s.bottom, right: s.right }, word: { bottom: word.bottom, top: word.top } };
};
