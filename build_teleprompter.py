#!/usr/bin/env python3
"""Build a self-contained teleprompter.html from presentation.zip."""

import base64
import io
import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path

ZIP_PATH = Path(__file__).parent / "presentation.zip"
OUT_PATH = Path(__file__).parent / "teleprompter.html"
WPM = 135
MAX_IMG_WIDTH = 300


def resize_image(data: bytes) -> bytes:
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        if img.width > MAX_IMG_WIDTH:
            ratio = MAX_IMG_WIDTH / img.width
            new_h = int(img.height * ratio)
            img = img.resize((MAX_IMG_WIDTH, new_h), Image.LANCZOS)
        buf = io.BytesIO()
        fmt = "JPEG" if img.mode in ("RGB", "L") else "PNG"
        if fmt == "JPEG":
            img = img.convert("RGB")
        img.save(buf, format=fmt, quality=82, optimize=True)
        return buf.getvalue(), fmt.lower()
    except ImportError:
        return data, "png"


def img_to_data_uri(zf: zipfile.ZipFile, src: str) -> str:
    try:
        data = zf.read(src)
        resized, fmt = resize_image(data)
        b64 = base64.b64encode(resized).decode()
        mime = "image/jpeg" if fmt == "jpeg" else "image/png"
        return f"data:{mime};base64,{b64}"
    except KeyError:
        return src


def extract_bold_classes(html: str) -> set[str]:
    """Return the set of CSS class names that apply font-weight:700."""
    style_match = re.search(r'<style[^>]*>(.*?)</style>', html, re.DOTALL)
    if not style_match:
        return set()
    style = style_match.group(1)
    names = re.findall(r'\.(c\d+)\{[^}]*font-weight\s*:\s*700[^}]*\}', style)
    return set(names)


class ContentExtractor(HTMLParser):
    """Parse Google Docs HTML into clean teleprompter content."""

    def __init__(self, zf: zipfile.ZipFile, bold_classes: set[str]):
        super().__init__(convert_charrefs=False)
        self.zf = zf
        self._bold_classes = bold_classes
        self.out: list[str] = []
        self._slides: list[str] = []
        self._slide_count = 0
        self._in_body = False
        self._span_stack: list[bool] = []  # tracks whether each open span is bold
        self._skip_depth = 0  # depth of tags we're ignoring
        self._skip_stack: list[str] = []
        self._para_open = False

    def handle_starttag(self, tag, attrs):
        if tag == "body":
            self._in_body = True
            return
        if not self._in_body:
            return

        attrs_dict = dict(attrs)
        classes = attrs_dict.get("class", "").split()

        if tag in ("style", "head", "script"):
            self._skip_depth += 1
            self._skip_stack.append(tag)
            return

        if self._skip_depth:
            return

        if tag in ("p", "h1", "h2", "h3"):
            if self._para_open:
                self.out.append("</p>")
            self.out.append("<p>")
            self._para_open = True

        elif tag == "hr":
            if self._para_open:
                self.out.append("</p>\n")
                self._para_open = False
            self.out.append("<hr>\n")

        elif tag in ("ul", "ol"):
            if self._para_open:
                self.out.append("</p>\n")
                self._para_open = False
            self.out.append(f"<{tag}>\n")

        elif tag == "li":
            self.out.append("<li>")

        elif tag == "sup":
            self.out.append("<sup>")

        elif tag == "a":
            pass  # keep link text, drop the anchor

        elif tag == "span":
            is_bold = bool(self._bold_classes & set(classes))
            self._span_stack.append(is_bold)
            if is_bold:
                self.out.append("<strong>")

        elif tag == "img":
            src = attrs_dict.get("src", "")
            if src.startswith("images/"):
                data_uri = img_to_data_uri(self.zf, src)
                # Preserve displayed width/height from style if present
                style = attrs_dict.get("style", "")
                w_match = re.search(r"width:\s*([\d.]+)px", style)
                h_match = re.search(r"height:\s*([\d.]+)px", style)
                w = float(w_match.group(1)) if w_match else MAX_IMG_WIDTH
                h = float(h_match.group(1)) if h_match else 0
                # Scale dimensions proportionally capped at MAX_IMG_WIDTH
                if w > MAX_IMG_WIDTH:
                    scale = MAX_IMG_WIDTH / w
                    w = MAX_IMG_WIDTH
                    h = h * scale
                dim = f'width="{int(w)}"' + (f' height="{int(h)}"' if h else "")
                sid = self._slide_count
                self._slides.append(f'<div class="slide-item" data-slide-id="{sid}"><img {dim} src="{data_uri}"></div>')
                self.out.append(f'<span class="slide-marker" data-slide-id="{sid}">&#9655;</span>')
                self._slide_count += 1

        elif tag == "br":
            self.out.append("<br>")

    def handle_endtag(self, tag):
        if not self._in_body:
            return

        if self._skip_stack and tag == self._skip_stack[-1]:
            self._skip_stack.pop()
            self._skip_depth -= 1
            return

        if self._skip_depth:
            return

        if tag in ("p", "h1", "h2", "h3"):
            if self._para_open:
                self.out.append("</p>\n")
                self._para_open = False

        elif tag in ("ul", "ol"):
            self.out.append(f"</{tag}>\n")

        elif tag == "li":
            self.out.append("</li>\n")

        elif tag == "sup":
            self.out.append("</sup>")

        elif tag == "a":
            pass

        elif tag == "span":
            if self._span_stack:
                was_bold = self._span_stack.pop()
                if was_bold:
                    self.out.append("</strong>")

        elif tag == "body":
            if self._para_open:
                self.out.append("</p>\n")
                self._para_open = False
            self._in_body = False

    def handle_data(self, data):
        if not self._in_body or self._skip_depth:
            return
        # Escape any stray < > that came through as raw characters
        self.out.append(data.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    def handle_entityref(self, name):
        if not self._in_body or self._skip_depth:
            return
        entities = {
            "rsquo": "’", "lsquo": "‘",
            "rdquo": "”", "ldquo": "“",
            "ndash": "–", "mdash": "—",
            "amp": "&amp;", "nbsp": " ",
            "lt": "&lt;", "gt": "&gt;",
        }
        self.out.append(entities.get(name, f"&{name};"))

    def handle_charref(self, name):
        if not self._in_body or self._skip_depth:
            return
        if name.startswith("x"):
            self.out.append(chr(int(name[1:], 16)))
        else:
            self.out.append(chr(int(name)))

    def get_html(self) -> tuple[str, str]:
        return "".join(self.out), "".join(self._slides)


def mark_stage_cues(html: str) -> str:
    """Wrap [stage cues] and <acting notes> in amber spans."""
    # Match [bracketed] cues — min 3 chars to exclude footnote refs like [a], [1]
    html = re.sub(
        r"(\[[^\[\]]{3,60}\])",
        r'<span class="cue">\1</span>',
        html,
    )
    # Match &lt;acting notes&gt; preserved as entities by the parser
    html = re.sub(
        r"(&lt;[^&<>]{1,40}&gt;)",
        r'<span class="cue">\1</span>',
        html,
    )
    return html


def count_words(html: str) -> int:
    text = re.sub(r"<[^>]+>", " ", html)
    return len(text.split())


def build_html(content_html: str, slides_html: str, word_count: int) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Teleprompter</title>
<style>
:root {{
  --bg: #fff;
  --fg: #111;
  --cue: #b45309;
  --bar-bg: #f3f4f6;
  --bar-border: #d1d5db;
  --btn-bg: #e5e7eb;
  --btn-fg: #111;
  --btn-hover: #d1d5db;
  --shadow: rgba(0,0,0,0.08);
}}
body.dark {{
  --bg: #111;
  --fg: #e8e8e0;
  --cue: #fbbf24;
  --bar-bg: #1e1e1e;
  --bar-border: #333;
  --btn-bg: #2a2a2a;
  --btn-fg: #e8e8e0;
  --btn-hover: #3a3a3a;
  --shadow: rgba(0,0,0,0.4);
}}
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
html {{ scroll-behavior: auto; }}
body {{
  background: var(--bg);
  color: var(--fg);
  font-family: Georgia, 'Times New Roman', serif;
  font-size: 2rem;
  line-height: 1.7;
  transition: background 0.2s, color 0.2s;
}}
#bar {{
  position: fixed;
  top: 0; left: 0; right: 0;
  z-index: 100;
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem 1.5rem;
  background: var(--bar-bg);
  border-bottom: 1px solid var(--bar-border);
  box-shadow: 0 2px 6px var(--shadow);
  font-family: system-ui, sans-serif;
  font-size: 2rem;
}}
#bar button {{
  background: var(--btn-bg);
  color: var(--btn-fg);
  border: 1px solid var(--bar-border);
  border-radius: 8px;
  padding: 0.4rem 1rem;
  cursor: pointer;
  font-size: 2rem;
  line-height: 1;
  transition: background 0.15s;
  white-space: nowrap;
}}
#bar button:hover {{ background: var(--btn-hover); }}
#bar button#btn-play {{ font-size: 2.6rem; padding: 0.2rem 0.8rem; }}
#speed-display {{
  font-variant-numeric: tabular-nums;
  min-width: 6ch;
  text-align: center;
  font-family: system-ui, sans-serif;
  font-size: 1.9rem;
  color: var(--fg);
}}
#time-remaining {{
  margin-left: auto;
  font-variant-numeric: tabular-nums;
  font-family: system-ui, sans-serif;
  font-size: 1.9rem;
  color: var(--fg);
  white-space: nowrap;
}}
#time-info {{
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 0.1rem;
}}
#time-elapsed, #time-clock {{
  font-variant-numeric: tabular-nums;
  font-family: system-ui, sans-serif;
  font-size: 1.4rem;
  color: var(--fg);
  opacity: 0.7;
  white-space: nowrap;
}}
.sep {{ width: 1px; height: 2.5rem; background: var(--bar-border); margin: 0 0.25rem; }}
#layout {{
  position: relative;
  max-width: 1400px;
  margin: 0 auto;
  display: flex;
}}
#content {{
  flex: 1;
  min-width: 0;
  padding: 50vh 2rem 50vh;
}}
#divider {{
  width: 6px;
  flex-shrink: 0;
  background: var(--bar-border);
  cursor: col-resize;
  transition: background 0.15s;
}}
#divider:hover, #divider.active {{
  background: var(--cue);
}}
#slide-rail {{
  position: relative;
  width: 300px;
  flex-shrink: 0;
}}
.slide-item {{
  position: absolute;
  width: 100%;
}}
.slide-item img {{
  display: block;
  width: 100%;
  height: auto;
  border-radius: 4px;
  box-shadow: 0 2px 8px var(--shadow);
  filter: brightness(0.7) saturate(0.5);
}}
.slide-marker {{
  color: var(--cue);
  font-family: system-ui, sans-serif;
  font-size: 0.75em;
  font-weight: 700;
  user-select: none;
  vertical-align: middle;
}}
#content p {{
  margin-bottom: 1.4em;
}}
#content strong {{
  font-weight: 700;
  text-decoration: underline;
  text-decoration-style: dotted;
  text-decoration-color: rgba(128,128,128,0.5);
  text-underline-offset: 3px;
}}
#content hr {{
  border: none;
  border-top: 2px solid var(--bar-border);
  margin: 2rem 0;
}}
#content ul, #content ol {{
  margin: 0.5em 0 1.2em 2em;
}}
#content li {{
  margin-bottom: 0.4em;
}}
#content sup {{
  font-size: 0.6em;
  vertical-align: super;
  opacity: 0.6;
}}
.cue {{
  color: var(--cue);
  font-style: italic;
  font-weight: 600;
  font-family: system-ui, sans-serif;
  font-size: 0.85em;
}}
#progress-bar {{
  position: fixed;
  right: 0; top: 0; bottom: 0;
  width: 4px;
  background: var(--bar-border);
  z-index: 99;
}}
#progress-fill {{
  width: 100%;
  background: var(--cue);
  transition: height 0.3s;
}}
#center-line {{
  position: fixed;
  left: 1rem;
  top: 50%;
  transform: translateY(-50%);
  width: 4px;
  height: 6.8em;
  background: rgba(128,128,128,0.4);
  border-radius: 2px;
  z-index: 90;
  pointer-events: none;
}}
</style>
</head>
<body class="dark">
<div id="bar">
  <button id="btn-play" title="Play/Pause (Space)">&#9654;</button>
  <div class="sep"></div>
  <button id="btn-slower" title="Slower (-)">&#8722;</button>
  <span id="speed-display">{WPM} wpm</span>
  <button id="btn-faster" title="Faster (+)">+</button>
  <div class="sep"></div>
  <button id="btn-smaller" title="Smaller font ([)">A&#8722;</button>
  <button id="btn-larger" title="Larger font (])">A+</button>
  <div class="sep"></div>
  <button id="btn-dark" title="Toggle dark mode (d)">&#9790;</button>
  <div id="time-info">
    <span id="time-remaining">—</span>
    <span id="time-elapsed">0:00 elapsed</span>
    <span id="time-clock"></span>
  </div>
</div>
<div id="center-line"></div>
<div id="progress-bar"><div id="progress-fill" style="height:0%"></div></div>
<div id="layout">
<div id="content">
{content_html}
</div>
<div id="divider"></div>
<div id="slide-rail">
{slides_html}
</div>
</div>
<script>
const WORD_COUNT = {word_count};
const WPM = {WPM};

const STORAGE_KEY = 'teleprompter_settings';

let playing = false;
let speedMult = 1.0;
let fontSize = 2.0; // rem
let rafId = null;
let lastTs = null;
let resumeTimer = null;
let scrollAccum = 0;

const btnPlay = document.getElementById('btn-play');
const btnFaster = document.getElementById('btn-faster');
const btnSlower = document.getElementById('btn-slower');
const btnLarger = document.getElementById('btn-larger');
const btnSmaller = document.getElementById('btn-smaller');
const btnDark = document.getElementById('btn-dark');
const speedDisplay = document.getElementById('speed-display');
const timeRemaining = document.getElementById('time-remaining');
const timeElapsed = document.getElementById('time-elapsed');
const timeClock = document.getElementById('time-clock');
const progressFill = document.getElementById('progress-fill');
const content = document.getElementById('content');

let elapsedSecs = 0;
let elapsedRafId = null;
let elapsedLastTs = null;
let railWidth = 300;

function updateClock() {{
  const now = new Date();
  const h = now.getHours();
  const m = String(now.getMinutes()).padStart(2, '0');
  timeClock.textContent = h + ':' + m;
  setTimeout(updateClock, (60 - now.getSeconds()) * 1000);
}}

function elapsedFrame(ts) {{
  if (!playing) return;
  if (elapsedLastTs !== null) {{
    elapsedSecs += (ts - elapsedLastTs) / 1000;
    timeElapsed.textContent = formatTime(elapsedSecs) + ' elapsed';
  }}
  elapsedLastTs = ts;
  elapsedRafId = requestAnimationFrame(elapsedFrame);
}}

function setRailWidth(w) {{
  railWidth = Math.max(100, Math.min(800, Math.round(w)));
  document.getElementById('slide-rail').style.width = railWidth + 'px';
  positionSlides();
}}

const divider = document.getElementById('divider');
divider.addEventListener('mousedown', (e) => {{
  e.preventDefault();
  divider.classList.add('active');
  document.body.style.userSelect = 'none';
  document.body.style.cursor = 'col-resize';
  const startX = e.clientX;
  const startWidth = railWidth;
  function onMove(e) {{
    setRailWidth(startWidth + (startX - e.clientX));
  }}
  function onUp() {{
    divider.classList.remove('active');
    document.body.style.userSelect = '';
    document.body.style.cursor = '';
    document.removeEventListener('mousemove', onMove);
    document.removeEventListener('mouseup', onUp);
    saveSettings();
  }}
  document.addEventListener('mousemove', onMove);
  document.addEventListener('mouseup', onUp);
}});

function saveSettings() {{
  localStorage.setItem(STORAGE_KEY, JSON.stringify({{
    speedMult,
    fontSize,
    railWidth,
    dark: document.body.classList.contains('dark'),
  }}));
}}

function loadSettings() {{
  try {{
    const s = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{{}}');
    if (s.speedMult) speedMult = s.speedMult;
    if (s.fontSize) fontSize = s.fontSize;
    if (s.railWidth) setRailWidth(s.railWidth);
    if (s.dark !== undefined) document.body.classList.toggle('dark', s.dark);
    document.body.style.fontSize = fontSize + 'rem';
  }} catch(e) {{}}
}}

function scrollableHeight() {{
  return document.documentElement.scrollHeight - window.innerHeight;
}}

function basePixelsPerSecond() {{
  const durationSecs = (WORD_COUNT / WPM) * 60;
  return scrollableHeight() / durationSecs;
}}

function updateSpeedDisplay() {{
  speedDisplay.textContent = Math.round(WPM * speedMult) + ' wpm';
}}

function formatTime(secs) {{
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60);
  return m + ':' + String(s).padStart(2, '0');
}}

function updateProgress() {{
  const sh = scrollableHeight();
  const pct = sh > 0 ? (window.scrollY / sh) * 100 : 0;
  progressFill.style.height = pct + '%';
  if (sh > 0) {{
    const remainingFraction = 1 - (window.scrollY / sh);
    const totalSecs = (WORD_COUNT / (WPM * speedMult)) * 60;
    const remSecs = totalSecs * remainingFraction;
    timeRemaining.textContent = formatTime(remSecs) + ' remaining';
  }}
  updateStickySlide();
}}

function scrollFrame(ts) {{
  if (!playing) return;
  if (lastTs !== null) {{
    const dt = (ts - lastTs) / 1000;
    scrollAccum += basePixelsPerSecond() * speedMult * dt;
    if (scrollAccum >= 1) {{
      const toScroll = Math.floor(scrollAccum);
      window.scrollBy(0, toScroll);
      scrollAccum -= toScroll;
      updateProgress();
      if (window.scrollY >= scrollableHeight() - 1) {{
        setPlaying(false);
      }}
    }}
  }}
  lastTs = ts;
  rafId = requestAnimationFrame(scrollFrame);
}}

function setPlaying(val) {{
  playing = val;
  btnPlay.innerHTML = playing ? '&#9646;&#9646;' : '&#9654;';
  if (playing) {{
    lastTs = null;
    scrollAccum = 0;
    rafId = requestAnimationFrame(scrollFrame);
    elapsedLastTs = null;
    elapsedRafId = requestAnimationFrame(elapsedFrame);
  }} else {{
    if (rafId) cancelAnimationFrame(rafId);
    rafId = null;
    lastTs = null;
    scrollAccum = 0;
    if (elapsedRafId) cancelAnimationFrame(elapsedRafId);
    elapsedRafId = null;
    elapsedLastTs = null;
  }}
}}

function togglePlay() {{ setPlaying(!playing); }}

function changeSpeed(delta) {{
  const newWpm = Math.max(10, Math.min(600, Math.round(WPM * speedMult) + delta));
  speedMult = newWpm / WPM;
  updateSpeedDisplay();
  updateProgress();
  saveSettings();
}}

function positionSlides() {{
  const layout = document.getElementById('layout');
  const layoutTop = layout.getBoundingClientRect().top + window.scrollY;
  document.querySelectorAll('.slide-marker').forEach(marker => {{
    const id = marker.dataset.slideId;
    const item = document.querySelector(`.slide-item[data-slide-id="${{id}}"]`);
    if (!item) return;
    const markerTop = marker.getBoundingClientRect().top + window.scrollY;
    const naturalTop = markerTop - layoutTop;
    item.dataset.naturalTop = naturalTop;
    item.style.top = naturalTop + 'px';
  }});
  updateStickySlide();
}}

function updateStickySlide() {{
  const bar = document.getElementById('bar');
  const slideRail = document.getElementById('slide-rail');
  const barBottom = bar.getBoundingClientRect().bottom;
  const railPageTop = slideRail.getBoundingClientRect().top + window.scrollY;
  const stickyTop = window.scrollY + barBottom + 8 - railPageTop;

  const items = [...document.querySelectorAll('.slide-item')];
  let currentItem = null;
  for (const item of items) {{
    const nat = parseFloat(item.dataset.naturalTop);
    if (!isNaN(nat) && nat < stickyTop) currentItem = item;
  }}
  for (const item of items) {{
    const nat = parseFloat(item.dataset.naturalTop);
    item.style.top = (item === currentItem ? stickyTop : nat) + 'px';
  }}
}}

function changeFontSize(delta) {{
  const sh = scrollableHeight();
  const fraction = sh > 0 ? window.scrollY / sh : 0;
  fontSize = Math.max(0.8, Math.min(5, fontSize + delta));
  document.body.style.fontSize = fontSize + 'rem';
  saveSettings();
  requestAnimationFrame(() => {{
    const newSh = scrollableHeight();
    window.scrollTo(0, fraction * newSh);
    positionSlides();
  }});
}}

function manualScroll(direction) {{
  const wasPlaying = playing;
  setPlaying(false);
  window.scrollBy(0, direction * 80);
  updateProgress();
  if (wasPlaying) {{
    clearTimeout(resumeTimer);
    resumeTimer = setTimeout(() => setPlaying(true), 800);
  }}
}}

function jumpToClick(e) {{
  // Only handle clicks directly on content children, not images
  const target = e.target.closest('p, h1, h2, h3');
  if (!target) return;
  const wasPlaying = playing;
  setPlaying(false);
  const rect = target.getBoundingClientRect();
  window.scrollBy(0, rect.top - window.innerHeight * 0.3);
  updateProgress();
  clearTimeout(resumeTimer);
  if (wasPlaying) {{
    resumeTimer = setTimeout(() => setPlaying(true), 1200);
  }}
}}

// Controls
btnPlay.addEventListener('click', togglePlay);
btnFaster.addEventListener('click', () => changeSpeed(1));
btnSlower.addEventListener('click', () => changeSpeed(-1));
btnLarger.addEventListener('click', () => changeFontSize(0.2));
btnSmaller.addEventListener('click', () => changeFontSize(-0.2));
btnDark.addEventListener('click', () => {{ document.body.classList.toggle('dark'); saveSettings(); }});
content.addEventListener('click', jumpToClick);

document.addEventListener('keydown', (e) => {{
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
  switch (e.key) {{
    case ' ':
      e.preventDefault();
      togglePlay();
      break;
    case 'ArrowUp':
      e.preventDefault();
      manualScroll(-1);
      break;
    case 'ArrowDown':
      e.preventDefault();
      manualScroll(1);
      break;
    case '+':
    case '=':
      changeSpeed(1);
      break;
    case '-':
      changeSpeed(-1);
      break;
    case ']':
      changeFontSize(0.2);
      break;
    case '[':
      changeFontSize(-0.2);
      break;
    case 'd':
    case 'D':
      document.body.classList.toggle('dark');
      saveSettings();
      break;
  }}
}});

window.addEventListener('scroll', updateProgress, {{ passive: true }});
window.addEventListener('load', positionSlides);
window.addEventListener('resize', positionSlides);
loadSettings();
updateProgress();
updateSpeedDisplay();
positionSlides();
updateClock();
</script>
</body>
</html>"""


def main():
    print(f"Reading {ZIP_PATH} ...")
    with zipfile.ZipFile(ZIP_PATH) as zf:
        html_name = next(n for n in zf.namelist() if n.endswith(".html"))
        print(f"  Parsing {html_name} ...")
        raw = zf.read(html_name).decode("utf-8")

        bold_classes = extract_bold_classes(raw)
        print(f"  Bold classes detected: {bold_classes}")
        extractor = ContentExtractor(zf, bold_classes)
        print("  Extracting and embedding images (this may take a moment) ...")
        extractor.feed(raw)
        content_html, slides_html = extractor.get_html()

    content_html = mark_stage_cues(content_html)
    word_count = count_words(content_html)
    print(f"  Word count: {word_count} (~{word_count/WPM:.0f} min at {WPM} wpm)")

    print(f"Writing {OUT_PATH} ...")
    page = build_html(content_html, slides_html, word_count)
    OUT_PATH.write_text(page, encoding="utf-8")
    size_mb = OUT_PATH.stat().st_size / 1_048_576
    print(f"Done. {OUT_PATH.name} is {size_mb:.1f} MB")


if __name__ == "__main__":
    main()
