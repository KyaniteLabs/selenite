# Selenite design preflight

Before any pixel, this receipt ties the title, the stone and the purpose together. It follows the `kyanite-product-design-preflight` skill. Every later design choice cites a line from this file. A choice this file can't back is an assumption and is marked that way.

## 1. Purpose (the job)

Selenite takes friction off the human. Friction means every effort a person spends that a tool could have spent: manual steps, logins, clicks, things to remember, read or decide. It is an accessibility problem as much as an agent-to-agent one. Selenite clears every other tool in the agent stack (skills, plugins, hooks, approval allowlists, runbooks, Kanban boards), ranks what costs the human most, drafts the fix, and shrinks any step it can't remove to one accessible command. One test runs through three facets: steps handed to a person (Gate), waits between agents that end up on a person's desk (fake gates), and checks that can't change the decision but still delay it (pedantry). Walls stand in all three. Overload detection is a small input that switches replies to Calm. It is not the product.

**Requirement: Selenite needs no cleansing.** It adds no upkeep: nothing to set up after install, state that trims itself, and a CI gate that keeps its own skill clean, so it never appears as the human's finding.

- Outcome for the user: fewer and smaller human steps, because the rest of the stack was cleared first.
- Core interaction: see what to clear next across the stack, clear it or mark it fixed, or ask for a drafted fix.
- Scope confirmed by the owner on 2026-11-10. Accessibility framing and the needs-no-cleansing requirement added by the owner the same day.

## 2. Title, stone and purpose

| Layer | Content | Evidence class |
|---|---|---|
| Title | **Selenite**. The product name is the mineral name, the same pattern as the org name Kyanite. The stone comes from the name. | The owner's naming, 2026-11-10 |
| Mineral fact | Gypsum, CaSO4·2H2O, Mohs 2. "Selenite" is the transparent, cleavable crystal form. "Satin spar" is the silky, fibrous form. It is slightly soluble in water. The name comes from the Greek word for the Moon, after its pearly lustre. | Wikipedia (Gypsum); fetched 2026-11-10 |
| Retail canon | "Commonly used to charge and cleanse other crystals". "Provides mental clarity". "A calming crystal". | Crystal Vaults selenite page, fetched 2026-11-10. This records what retailers believe, not a product claim. |
| Product fit | Each retail belief maps to one product behaviour. **Charges and cleanses other crystals** → the cleanse pass clears every other tool, agent, skill and plugin in the stack, then recharges it with a fix. **Mental clarity** → one ranked view of what to clear next, across the whole stack. **Calming** → fewer interruptions reach the human, because the stack was cleared first; Calm mode is the small reply-style part of this. **Never needs cleansing itself** → a product requirement: no upkeep, self-trimming state, and a CI gate in place of self-findings. | Our metaphor, built on the retail canon above; mapping confirmed by the owner, 2026-11-10. The no-cleansing requirement is the owner's, 2026-11-10. |

Rejected metaphors:
- **Moon, tide or crescent.** The etymology is real, but the owner rejected this direction on 2026-11-10 because it was invented and ungrounded. Do not use crescents, tides or lunar phases.
- **Purple or lavender identity.** Selenite is white.

## 3. Material reference

- Habit: **satin spar**, the fibrous form. That is the habit the KyaniteLabs family already renders as "selenite". The family references are:
  - OpenGlaze C2, the upper-right field of the approved UMF triangle.
  - Innerscape j2, the middle slab of the cairn. Innerscape uses selenite only as icon inspiration.
  - Both renders are held in the KyaniteLabs design archive.
- Appearance:
  - Pearly white to faintly warm white.
  - Dense straight fibres that run along the length.
  - A silky band of light (chatoyance) moving across the fibres.
  - Translucent edges.
  - No colour of its own.
- Material-realism rule: "clear gypsum plates and fibrous satin spar are different habits". Do not call satin spar clear selenite.
- **Assumption, open to the owner's eye-gate.** I chose satin spar because the family already renders selenite that way. If the owner prefers clear bladed selenite plates, only the material changes.

## 4. Family law (icon)

- The icon must be obviously an icon: a compact, bold silhouette that reads at 32 px and 16 px. No scene, no pedestal, no text, no rays or glow.
- The real mineral should show in broad regions.
- Family palette:
  - Crystal material.
  - Turquoise `#00FFE6` edges.
  - Magenta `#FF1A6E` and yellow `#FFD11A` catches.
  - White speculars and dark inner planes.
  - Transparent background.
- The family-cohesion rule that "selenite can be pale" applies.
- **Form proposal:** a single satin-spar blade, the classic selenite wand, set diagonally. It has a chisel-cut tip, with the fibres running its full length and one chatoyant band across them.
  - It is one object with one gesture, which suits a tool that clears things.
  - The SVG in `assets/icon.svg` is a concept guide only. The family mark is a raster render made through the icon pipeline, and it needs the owner's eye-gate. The render is scheduled once the render host is free.

## 5. Typography (lockup law)

- Wordmark: **SELENITE** in Chakra Petch Bold 700, uppercase, with unmodified glyphs and native kerning.
- Endorsement: "by KyaniteLabs" in Chakra Petch Medium 500.
- The OFL licence ships with every export.
- On a dark canvas, invert only the ink. Never change the typeface, weights or metrics.
- In-app, Chakra Petch is limited to identity type on the Selenite page: the page title, section labels and the big numerals (weights 500 and 600, embedded as a Latin subset). Body text, rows, buttons and every other surface use the host's fonts. Off the page it appears only on the banner and the README hero.

## 6. Platform conventions (Hermes plugin catalog)

| Item | Requirement | Source |
|---|---|---|
| Catalog image | 2:1, 1200×600 PNG, hosted on raw.githubusercontent.com and pinned to the sha | `plugin-catalog` README and 453 existing entries |
| Icon | 512×512 PNG `icon.png` at the repo root | epoch-hermes |
| Banner | `docs/banner.png` | epoch-hermes |
| Dashboard manifest | Lucide icon name, `tab` position, `entry` → `dist/index.js` | memory-wiki, gadget, epoch |
| Desktop bundle imports | May import only `@hermes/plugin-sdk` and `react`; no DOM reach-ins | validator rule 8 |
| Risky behaviour | Disclosed in the README and in the catalog description ("Disclosure —") | rule 13 |
| `requires_hermes` | A SemVer floor, set in both the catalog entry and `plugin.yaml` | rule 14 |

## 7. UI colour

- Selenite's identity colour is white. On dark chrome the identity accent is pearl `#ECE9E2`.
- On light chrome a white tint would vanish, so the icon carries the identity and the UI uses host ink.
- Gate, approval and fix states use host semantic tokens, and every one of them is paired with a text label. Colour never carries state alone.
- **Correction from Simon, 2026-11-10: "this shonudl be very chill the colors of seleinte".** The page takes only the stone's own colours, with no saturated accents. This replaced round 1's magenta and turquoise, which were too loud.
- **Second correction from Simon, 2026-11-10: "i don tliek balck and white. make it ilike desrrt rose. white and tan".** The pearl-and-silver round read as black and white and is rejected. That round used desert rose: selenite's rosette habit, white blades with sand caught between them. Desert rose is a real habit of gypsum/selenite (mineral fact, mindat: gypsum "desert rose"), so the tan is the stone's own sand, not an invented colour.
- **Third correction from Simon, 2026-11-10: "i stills ee black and whit i said no black make it like the walnut color system".** The desert-rose round still sat on the host's black chrome and is rejected. The page now uses Simon's own Walnut design system (`~/.local/share/walnut/design-system/tokens/walnut.css`, and the Hermes skin `walnut.yaml`): warm mid-dark walnut ground, cream text, pastel accents, one fixed mode with no light/dark switch.
- **Standing rule vs. this ask.** The standing rule is "no brown or orange". Walnut is Simon's own named system, and his newest explicit instruction asks for it, so it governs this page. No other brown or orange is added, and the host's `--ui-orange` and `--ui-yellow` stay unused.
- **How:** `.sel-host` paints the Walnut ground `#655a50` and re-points the host `--ui-*` tokens it uses at Walnut values (cards `#564d44`, text `#f3ebdf`/`#e6dccf`/`#d8ccbd`, strokes cream at 7–24%). Scoped to the plugin page only.
- State colours, all from Walnut and all paired with a text label:
  - **Identity:** Walnut bold text `#fffaf2`.
  - **Human gate:** Walnut accent, amber cream `#f7d4ae`, the one state that asks for attention.
  - **Calm trigger and high load:** Walnut faint sand `#bcae9d`. Calm dots are hollow rings.
  - **Approval:** Walnut kyanite blue `#c6d8f3`. **Fix:** Walnut success green `#c9dead`. **Broken:** Walnut danger `#f5cec6`.
  - **Kanban badge:** the host's `neutral` tone.
- **Assumption:** forcing the Walnut ground inside the page is right even when the host runs another theme; Simon's own host already runs the Walnut skin. Pending Simon's eye.

## 8. Landed mark

- The owner picked round 14 E on 2026-11-10: a thick raw satin-spar shard, set diagonally, with an off-centre, moderately pointed tip. This follows the owner's corrections: a shard like a raw selenite wand, "more angled, more pointy but not ultra pointy, and not centered".
- Files: `branding/selenite.png` (1024² master, transparent), `branding/selenite-{512,192,32}.png`, and `icon.png` (512², the epoch-hermes plugin-icon convention).
- The concept SVG in `assets/icon.svg` stays as a construction note only.
- The 2:1 catalog banner is `docs/banner.png` (1200×600; the icon plus the SELENITE lockup in Chakra Petch Bold 700 and Medium 500, pearl ink `#ECE9E2` on dark).
- The catalog `image` field points at `docs/banner.png` on raw.githubusercontent.com, pinned to the same sha as the catalog entry.
