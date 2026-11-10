# Selenite design preflight

Before any pixel, this receipt ties the title, the stone and the purpose together. It follows the `kyanite-product-design-preflight` skill. Every later design choice cites a line from this file. A choice this file can't back is an assumption and is marked that way.

## 1. Purpose (the job)

Selenite finds the human steps that your agents keep handing back to you: approvals, credentials, clicks and re-asks. It ranks them by how often they come back, then drafts the fix that removes the next one. It also improves itself from its own ledger.

- Outcome for the user: fewer interruptions and a calmer operator.
- Core interaction: see the recurring gate, mark it fixed, or ask for a drafted fix.

## 2. Title, stone and purpose

| Layer | Content | Evidence class |
|---|---|---|
| Title | **Selenite**. The product name is the mineral name, the same pattern as the org name Kyanite. The stone comes from the name. | Simon's naming, 2026-11-10 |
| Mineral fact | Gypsum, CaSO4·2H2O, Mohs 2. "Selenite" is the transparent, cleavable crystal form. "Satin spar" is the silky, fibrous form. It is slightly soluble in water. The name comes from the Greek word for the Moon, after its pearly lustre. | Wikipedia (Gypsum); fetched 2026-11-10 |
| Retail canon | "Commonly used to charge and cleanse other crystals". "Provides mental clarity". "A calming crystal". | Crystal Vaults selenite page, fetched 2026-11-10. This records what retailers believe, not a product claim. |
| Product fit | Selenite is the stone used to clear the other stones. Selenite the product clears friction from the rest of the toolchain (every other agent and skill) and improves itself. Clarity means the ranked list, and calm means fewer interruptions. | Our metaphor, built on the retail canon above |

Rejected metaphors:
- **Moon, tide or crescent.** The etymology is real, but Simon rejected this direction on 2026-11-10 because it was invented and ungrounded. Do not use crescents, tides or lunar phases.
- **Purple or lavender identity.** Selenite is white.

## 3. Material reference

- Habit: **satin spar**, the fibrous form. That is the habit the KyaniteLabs family already renders as "selenite". The family references are:
  - OpenGlaze C2, the upper-right field of the approved UMF triangle: `kanban/attachments/t_aadd970b/openglaze-c2.png`.
  - Innerscape j2, the middle slab of the cairn: `kanban/attachments/t_aadd970b/innerscape-j2-512.png`.
- Appearance:
  - Pearly white to faintly warm white.
  - Dense straight fibres that run along the length.
  - A silky band of light (chatoyance) moving across the fibres.
  - Translucent edges.
  - No colour of its own.
- Material-realism rule: "clear gypsum plates and fibrous satin spar are different habits". Do not call satin spar clear selenite.
- **Assumption, open to Simon's eye-gate.** I chose satin spar because the family already renders selenite that way. If Simon prefers clear bladed selenite plates, only the material changes.

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
  - The SVG in `assets/icon.svg` is a concept guide only. The family mark is a raster render made through the icon pipeline, and it needs Simon's eye-gate. That render can't run on the NucBox until 2026-11-17.

## 5. Typography (lockup law)

- Wordmark: **SELENITE** in Chakra Petch Bold 700, uppercase, with unmodified glyphs and native kerning.
- Endorsement: "by KyaniteLabs" in Chakra Petch Medium 500.
- The OFL licence ships with every export.
- On a dark canvas, invert only the ink. Never change the typeface, weights or metrics.
- In-app UI uses the host's fonts. Chakra Petch is for identity surfaces only: the banner, the README hero and the page title.

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
