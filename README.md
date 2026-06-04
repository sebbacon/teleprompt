# Teleprompter

A self-contained, single-file teleprompter built from a Google Docs presentation export.

## Building

```bash
python build_teleprompter.py
```

This reads `presentation.zip` (a Google Docs `.zip` export) and writes `teleprompter.html`. Install [Pillow](https://pillow.readthedocs.io/) for image resizing; without it images are embedded at full size.

Open `teleprompter.html` in any browser — no server needed.

## Source format

Export your script from Google Docs as **File → Download → Web Page (.html, zipped)**. The build script understands:

- **Bold text** → highlighted for emphasis
- **Inline images** → extracted and moved to a right-hand column, anchored to the line where they appear in the text. A small triangle marker (▷) in the text shows where each image sits.
- `[bracketed notes]` and `<acting notes>` → rendered in amber as stage cues (brackets must contain 3–60 characters to avoid footnote markers like `[1]`)
- Headings, lists, horizontal rules, superscripts, and links (link text kept, href dropped)

## Controls

| Action | Keyboard | Button |
|---|---|---|
| Play / Pause | `Space` | ▶ / ⏸ |
| Faster | `+` or `=` | + |
| Slower | `-` | − |
| Larger font | `]` | A+ |
| Smaller font | `[` | A− |
| Scroll up | `↑` | — |
| Scroll down | `↓` | — |
| Toggle dark/light | `d` | ☾ |

Click any paragraph to jump to it (playback resumes automatically after a short pause).

## Toolbar

- **WPM** — current scroll speed in words per minute. The default is 135 wpm; adjust with `+` / `−`.
- **Time remaining** — estimated time left based on scroll position and current speed.
- **Elapsed** — time spent playing (pauses when you pause).
- **Clock** — current wall time.

## Settings persistence

Speed (wpm), font size, dark/light mode, and the width of the slide column are all saved to `localStorage` and restored on next open.

## Resizing the slide column

Drag the narrow vertical bar between the text and the image column to resize. Images scale to fill whatever width you set.

## Scroll speed model

Speed is set so the full page scrolls in exactly `word_count / wpm` minutes. This means font size and whitespace affect the pixel rate (a larger font scrolls faster in pixels/second) but not the total estimated duration. Time remaining is proportional to scroll position, so image-heavy or whitespace-heavy sections are treated as if they contained the same density of words as the rest of the script.

## Changing the default WPM

Edit the `WPM` constant at the top of `build_teleprompter.py` and rebuild. Once open in the browser, any speed adjustment is remembered in `localStorage` and will override the built-in default on subsequent loads.
