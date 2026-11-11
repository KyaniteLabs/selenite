# Selenite design system

Selenite runs inside Hermes. It takes the host's theme and adds three things of its own: the stone, a display typeface for identity surfaces, and one meaning per colour. Each choice cites `docs/DESIGN-PREFLIGHT.md` (shortened to **PF** below). Choices still waiting on the owner's eye-gate are marked **(A)**.

## Principles

1. **Quiet by default.** Selenite watches for overload, so its own UI must not add any. Nothing loops or animates, red appears only when something is broken, and no number ticks live.
2. **One question per surface.**
   - Status chip: *is anything waiting on me today?*
   - Page: *which human step should we remove next?*
   - Kanban badge: *is this card blocked on me?*
3. **The host owns the components; the page owns its colours.** Panes, buttons, badges and empty states come from Hermes components. The page paints its own solid Walnut sand ground and re-points the host's theme variables at Walnut values inside `.sel-host`, so it looks the same under any host theme (PF §7).

## Stone and glyph

- **The stone is white satin-spar selenite** (PF §2–3): pearly white, dense straight fibres along the length, one silky chatoyant band, translucent edges. Selenite has no colour of its own, and it is never shown as purple or lavender.
- **Glyph:** one satin-spar wand set diagonally, with a chisel tip, its fibres running the length and a narrow dark bevel on the shadowed edge (PF §4).
  - In the app it is drawn as the approved round-14 E shard: thick, raw, set diagonally, with an off-centre tip (PF §8).
  - It is a static mark and never shows state.
  - In the app it draws in Walnut ink `#3b342e` (`--sel-id`), with the bevel stroke in the same ink. The page is always the light sand ground, so the glyph never flips to white.
- **App icon:** `assets/icon.svg` is a **concept guide only (A)**.
  - It follows the family law: crystal material, turquoise `#00FFE6` edge, magenta `#FF1A6E` and yellow `#FFD11A` catches, white specular, dark inner plane and a transparent background.
  - The shipped `icon.png` (512) will be a pipeline raster render behind the owner's eye-gate. It is not rendered yet.
- **Rejected:** the moon, crescents, tides, lunar phases and a purple identity (PF §2). The etymology is real, but it is not the product.

## Type

| Role | Face | Size and weight | Notes |
|---|---|---|---|
| Lockup (banner, README hero) | Chakra Petch | **SELENITE** Bold 700 uppercase, with "by KyaniteLabs" in Medium 500 | Glyphs unmodified, native kerning, OFL shipped (PF §5) |
| Page title and section labels | Chakra Petch | Title 600 at 20px uppercase with +0.06em tracking; section labels 600 at 13.5px in mixed case with +0.02em; tags use the body face | Embedded as a Latin subset WOFF. Only weights 500 and 600 are embedded in the app (A) |
| Big numerals | Chakra Petch | 600 at 28px | Values refresh every 30 s and never tick |
| Body and rows | Host sans (`--font-sans`) | 13px at 400; meta text 11.5px | Long text stays in the app's face |
| Ledger keys and counts | Host mono (`--font-mono`) | 12px, tabular figures | Counts line up down the column |

## Colour (Walnut sand film, round 6)

| Meaning | Variable | Always paired with |
|---|---|---|
| Ground | Solid Walnut sand `#f3ebdf`; cards `#fbf5ec` | Not applicable |
| Identity: glyph, meter, wordmark, text | Walnut ink `#3b342e` (`--ui-text-primary`) | Not applicable; identity only |
| Human gate | Walnut ink `#3b342e`, the darkest mark on the page (PF §7) | A count and the label "Recurring gates"; the Kanban badge (`neutral` tone) says "waiting on you" |
| Approval prompt | Ink-weight Walnut blue `#375684` (`--ui-blue`) | The label "Approval prompts" |
| Calm trigger and high load | Walnut sand `#7d7064`; calm dots are hollow rings (PF §7) | The words "Load: High" and the reason line |
| Fix landed | Ink-weight Walnut green `#46622a` (`--ui-green`) | The word "fixed" |
| Everything else | `--ui-text-secondary/tertiary`, `--ui-stroke-*`, `--ui-bg-card` | Not applicable |

- Colour never carries state on its own (PF §7).
- The only browns are the Walnut ink, sand and taupe values above. There is no orange: the host's `--ui-orange` and ochre `--ui-yellow` are never used (PF §7).
- The minimum text tone is `--ui-text-tertiary`. The quaternary tone is reserved for hairlines.
- Every text tone passes WCAG AA (4.5:1) on the sand ground; the lowest, `--ui-text-quaternary` `#62574d`, measures 5.9:1. State marks clear 3:1.

## Load

Load measures the human's overload over the last 24 hours, counted from Calm triggers. It shows as a three-bar meter plus a word.

| State | Bars | When |
|---|---|---|
| **Clear** | 1 | No Calm triggers |
| **Rising** | 2 | 1–2 triggers |
| **High** | 3, faint sand | 3 or more triggers in 24 hours, or at least 2 in 24 hours with the latest under 15 minutes ago |

An unknown value from the backend renders as Clear.

## Layout

The page sits on a 4-px grid with gaps of 8, 12, 16 and 24, and content is capped at 1120px. From top to bottom:

1. **Header:** the blade, the SELENITE title and the window switch (7d / 30d / 90d).
2. **Error strip**, shown only on a failed refetch: it keeps the last good data visible and offers Retry.
3. **Load strip:** the meter, "Load: *state*", a one-line reason, and the time of the last signal.
4. **Four stat tiles:** Human gates, Approval prompts, Calm triggers and Fixes landed.
5. **Cleanse: clear next.** The latest cleanse report, which is the page's answer to "which human step should we remove next?":
   - The top finding is set apart as *Clear next*, with its problem, where it lives and the fix.
   - Up to five more findings follow, plus a count per stone.
   - A *Run cleanse* button runs the read-only sweep. *Copy /frictionless cleanse* hands the clearing to an agent.
6. **Two columns:**
   - Recurring gates, ranked, each with its own "Mark *key* fixed" button. The confirmation toast offers Undo.
   - Fake gates between agents (the board audit's headline and its oldest fake waits), then Evolve (the latest proposal) and Signal health.
7. **The ledger timeline**, with kinds in words (Gate, Approval, Calm, Fix, Reopened, Blocked).

Below 760px the layout drops to one column and the bars and notes are hidden.

## Surfaces

| Surface | Where | Content |
|---|---|---|
| Desktop page | `ROUTES_AREA` `/selenite`, plus `SIDEBAR_NAV_AREA` (`wand` codicon: a selenite wand) | Everything above |
| Status chip | `STATUSBAR_AREAS.right` | The blade, plus the number of open gates today. Its aria-label is "Open Selenite"; its tooltip gives the load and the gate count. Clicking it opens the page |
| Kanban badge | `KANBAN_CARD_AREAS.badges` | "waiting on you" (`neutral`) on tasks blocked on a human gate. It clears when the card is unblocked, archived or done on the board |
| Palette | `PALETTE_AREA` | Open the friction ledger, run a cleanse, or draft an evolve proposal |
| Settings | `registerSettingsPage` | Chip toggle, chip style, Kanban badges and the privacy note |
| Web dashboard tab | `dashboard/manifest.json` tab `after:sessions`, entry `dist/index.js` | Load, the four totals, recurring gates with Mark fixed, and the Fake gates between agents card. Uses only the dashboard SDK components |

## Data and privacy

- **Where the data lives:** the ledger, reports and proposals sit in the Selenite state directory: `$SELENITE_STATE`, else `$XDG_STATE_HOME/selenite`, else `$HERMES_HOME/plugin-data/selenite`, else `~/.local/state/selenite`. A read-only folder falls through to the next, and readers look in all of them. The directory is 0700 and the files are 0600, on the host that runs the agent.
- **Who reads it:** both UIs read it only through the user's own Hermes gateway (`/api/plugins/selenite/`). Selenite makes no other network calls.
- **What a row holds:** no host name, and no secrets. Notes are capped at 200 characters.

## Errors

- Every write (mark fixed, undo, draft proposal) reports a failure through `host.notifyError`.
- A failed overview refetch never blanks the page.
