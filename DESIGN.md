# BraidCord design source of truth

BraidCord is a terminal product, so the design system is expressed in the output
grid rather than in CSS. These are the committed tokens; every command consumes
them, and no command invents its own palette, spacing or type.

## Direction

* Archetype: CLI. Style family: calm-precise. Density: compact.
* Surface: terminal dark - the tool inherits the braider's terminal theme and
  never paints its own background.
* Type: system monospace only (the terminal's own mono font). No webfonts, no
  unicode box-drawing, no glyph art.
* Signature: aligned columns; one accent role used for primary status lines; no
  colour-only signal - every state is also spelled out in words.

## Tokens

| Token | Value | Where it is used |
| --- | --- | --- |
| `--accent` | `oklch(0.58 0.12 191)` = `#00908b` | Documented accent for the primary status line (`finished`, `saved`, `deleted`); emitted only where a terminal can carry it, never as ANSI so piping stays clean |
| `--surface` | terminal default (dark) | Background for every screen |
| `--text` | terminal default foreground | Body text and table cells |
| `--text-muted` | terminal default, one shade dimmer where supported | Section headers (`Basis for the length estimator`), hints |
| `--rule` | `-` and `+` ASCII characters | Table rules, slot-map borders |
| `--warn` | plain text prefixed `warning:` | Quarantined store, missing colour references |
| `--error` | plain text prefixed `error:` | Every failure, on stderr |
| `--space` | one blank line between blocks | Section separation |
| `--radius` / `--elevation` | none | No chrome: the CLI has no boxes beyond ASCII rules |
| `--type-scale` | one size: the terminal's monospace cell | Headings are labels, not sizes |

## Rules the output follows

1. Plain ASCII only. No ANSI escapes, no emoji, no box-drawing characters: the
   output must survive a pipe and a diff (this overrides the "box-drawing
   separators" direction because the product requirement is plain ASCII text).
2. Columns align on a fixed grid: header, `----` rule, then rows. Numeric columns
   right-aligned or fixed-width so two runs diff cleanly.
3. Status is carried by words first, position second. Never colour alone.
4. Errors go to stderr, one line, prefixed `error:`. Results go to stdout.
5. Empty states are designed states: one line of why plus the exact command that
   fixes it (`No threads yet, add your first with: ...`).
6. The 32-slot disk map is a four-by-eight ASCII grid with a border, used
   identically for the plain pattern view and for the colour-labelled setup
   view.

## Where the accent hex is used outside a terminal

`#00908b` is the same accent expressed as hex for any non-terminal renderer
(screen-recorded demo captions, docs diagrams). The CLI itself never emits
colour, per the fidelity rule above.
