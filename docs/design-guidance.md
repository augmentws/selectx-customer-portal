# Select Exterminating — Design Guidance

Pulled from the live site (selectexterminating.com) on Oct 21, 2026: colors sampled from the logo artwork and the site's computed CSS / Elementor global tokens, fonts and component styles read from the rendered page.

---

## 1. Core palette — Black, Green, Yellow

| Role | Name | Hex | RGB | Where it comes from |
|---|---|---|---|---|
| **Black** | Select Black | `#000000` | 0, 0, 0 | Logo wordmark, header overlays, footer |
| Black (UI) | Ink | `#171C1A` | 23, 28, 26 | Dark section backgrounds (a green-tinted near-black) |
| **Green** | Select Green | `#2B935C` | 43, 147, 92 | Primary CTA buttons, links, accents (Elementor global color) |
| Green (deep) | Forest | `#186839` | 24, 104, 57 | Hover / pressed states, small green text on white (Elementor global color) |
| Green (logo) | Logo Green | `#098543` | 9, 133, 67 | Logo shield / mark — use for brand marks, not UI |
| Green (icon) | Vivid Green | `#009868` | 0, 152, 104 | Favicon / app icon |
| **Yellow** | Select Gold | `#FDCF0E` | 253, 207, 14 | Most saturated yellow in the logo — highlights, badges, rules |
| Yellow (soft) | Honey | `#FED95A` | 254, 217, 90 | Average logo yellow — tints, gradient end |

## 2. Supporting neutrals

| Name | Hex | Use |
|---|---|---|
| Charcoal | `#353E43` | Secondary button ("Residential" toggle), dark UI chrome |
| Body Text | `#333333` | All paragraph text on light backgrounds |
| Graphite | `#1F2124` | Deep text / form labels |
| Stone | `#878B89` | Muted UI, dividers on dark |
| Mist | `#D9D9D9` | Borders, rules on light |
| Paper | `#F8F7F7` | Light section background (alternate with white) |
| White | `#FFFFFF` | Default page background, text on black/green |

## 3. Color rules

- **Proportion: ~60 / 30 / 10.** 60% white + black/ink (structure), 30% green (action and brand), 10% yellow (highlight only).
- **Green is the action color.** Every primary CTA ("GET A QUOTE TODAY") is Select Green with white text. Don't introduce a second CTA color.
- **Yellow is an accent, never a field.** Use it for underlines, rules, badges, stat numbers on black, or a single highlighted word. Never large yellow backgrounds behind body copy, and never yellow text on white (fails contrast).
- **Black carries authority.** Hero panels, statement sections, and the footer sit on black/Ink with white headlines.
- **Contrast checks (WCAG):**
  - White on Select Green `#2B935C` ≈ 3.9:1 → OK for buttons/large text (18px bold or 24px+); **not** for small body text.
  - White on Forest `#186839` ≈ 6.8:1 → use Forest when green carries small white text.
  - Forest on white ≈ 6.8:1 → use Forest (not Select Green) for small green links/text on white.
  - Select Gold on black ≈ 13:1 → excellent.
  - Black/Ink text on Select Gold → excellent; white text on yellow → never.

## 4. Typography

| Role | Typeface | Weight | Size (web) | Notes |
|---|---|---|---|---|
| Hero headline (H1) | **Oswald** | 700 | ~48–56px | ALL CAPS, white on black/photo |
| Section headline (H2) | **Oswald** | 700 | 25–36px | ALL CAPS, `#333333` on light |
| Card / feature title (H3) | **Oswald** | 700 | 22px | Title case OK |
| Body | **Lato** | 400 | 18px / 27px line-height (1.5) | `#333333` |
| Small / links | **Lato** | 400 | 14px | Green links |
| Buttons | System sans (or Lato) | 500 | 18px | See components |

Google Fonts: `https://fonts.googleapis.com/css2?family=Oswald:wght@400;500;700&family=Lato:wght@400;700&display=swap`

Rules:
- Headlines are condensed, bold, and shouted: Oswald, uppercase, tight leading (~1.1).
- Body copy stays calm and readable: Lato regular at 18px, 1.5 line height.
- Don't mix in additional display faces. Two families only.

## 5. Components

**Primary button** — bg `#2B935C`, text `#FFFFFF`, 18px / 500, padding `10px 28px`, **border-radius 0** (square corners), uppercase label ("GET A QUOTE TODAY"). Hover: bg `#186839`.

**Secondary button** — bg `#353E43`, text white, same geometry. Used for toggles (Residential / Commercial).

**Text link** — `#2B935C` (or `#186839` on white for small text), Lato 14–18px, arrow suffix allowed ("Get Your Quote Today →").

**Industry / service tiles** — line icon (single color) + Oswald H3 title; grid of 5 across on desktop.

**Stat strip** — big Oswald numbers + small Lato labels: "70+ Years In Business · 9 Branches · 900+ Technicians". On black, numbers can go Select Gold.

**Corners** — square everywhere (buttons, cards). If a radius is needed, max 3px.

## 6. Layout

- Full-bleed photo heroes with a black overlay (`rgba(0,0,0,0.8)`) and white Oswald headline.
- Alternate section backgrounds: White → Paper `#F8F7F7` → Black/Ink statement band.
- Generous padding; centered content column; CTA repeated at top of page, mid-page and in the closing band.
- Photography: real technicians, facilities, warehouses — documentary, not stock-cute bugs.

## 7. Voice & messaging

- Confident, protective, established. Short declarative lines.
- Proof points to reuse: *since 1959*, *70+ years of family leadership*, *PCT Top 100 — 29th largest in the USA*, *largest family-owned pest control company in the Northeast*, *9 branches*, *900+ technicians*.
- Taglines in use: "We lead the Northeast in pest control" · "Big enough to back you, small enough to know you." · "We don't just service accounts. We engineer protection."
- Named programs carry ™: Select Sense™, The Select Assurance™.
- Contact: 800-311-6655.

## 8. Do / Don't

| Do | Don't |
|---|---|
| Green for every primary action | Yellow buttons or yellow body text |
| Oswald caps for headlines | Script, rounded or novelty fonts |
| Square corners | Pill buttons, big rounded cards |
| Black statement bands with gold highlights | Gradients across green→yellow as a background |
| Forest green for small text on white | Select Green small text on white (low contrast) |
| Real crew & facility photos | Cartoon bugs |

---

## 9. Application UI (customer portal)

Sections 1–8 describe the marketing site. The portal is a dense, task-focused app, so these rules adapt them. Tokens live in `web/src/app/globals.css`; `pnpm lint` runs `scripts/check-contrast.mjs`, which fails if any token pair drops below WCAG 2.2 AA.

**Color mapping (semantic tokens → brand)**

| Token | Value | Why |
|---|---|---|
| `primary` | Forest `#186839` (hover `#11502B`) | App buttons use 14–16px text; white on Select Green (3.87:1) only passes for large text. Forest is 6.82:1. |
| `brand-green` | Select Green `#2B935C` | Logo-adjacent and large display use only. |
| `secondary` | Charcoal `#353E43` (hover `#2A3135`) | Secondary buttons. |
| `highlight` / `warning` | Select Gold `#FDCF0E` with Ink `#171C1A` text | Rules, badges, stat numbers on black. Never text on white (1.49:1). |
| `foreground` | Body Text `#333333` | |
| `muted` | Paper `#F8F7F7` | App page background; cards are white. |
| `muted-foreground` | `#646967` | Stone (`#878B89`) is 3.45:1, too light for small text. |
| `border` | Mist `#D9D9D9` | Decorative dividers only. |
| `input` | Stone `#878B89` | Form-control borders need 3:1. |
| `ring` | Forest `#186839` | Focus indicator (Gold on white is invisible). |
| `destructive` | `#B42318` (tint `#FCEBE9`) | Errors and destructive actions; not part of the marketing palette. |
| `success` | Forest on tint `#E6F2EB` | Status only. Never a filled green chip, so status can't be mistaken for a button. |
| `pending` | Charcoal on tint `#DDE2E6` | In-progress status (Open, Draft, Queued, Syncing). Replaces filled Charcoal chips, which read as secondary buttons. |
| `ink` | `#171C1A` | Black statement bands. |

**Typography:** Oswald 700 uppercase for page titles (`h1`, `h2`, styled globally); Oswald 500 for card titles; Lato for everything else. Body is 16px (`text-base`) and dense lists/labels are 14px, not the site's 18px. Lato replaces "system sans" on buttons, so there are exactly two families.

**Buttons:** primary and secondary are uppercase, bold, square. Ghost, outline, and link actions (Remove, Deactivate, Test connection) stay sentence case so rows of inline actions remain scannable.

**Tabs:** `@/components/page-tabs`, not `components/ui/tabs` directly: shadcn's line style, a full-width Mist rule under the list, inactive labels in `muted-foreground` (the primitive's 60% foreground fails AA on Paper), and the active tab in body text with a Forest underline.

**Badges:** one meaning per style.
- State of a record or job: `pending` (in progress or waiting: Open, Draft, Queued, Syncing, Received), `success` (done: Worked, Final, Synced, Verified, Processed), `warning` (needs attention: Partly synced, Not verified, Inactive in PestPac, medium severity, a balance), `destructive` (failed, invalid, high severity).
- Finished history and plain labels: `outline` (Billed, Superseded, Inactive, Deleted; document type, category, On portal, revision, "You").
- Never `default` or `secondary` (filled Forest or Charcoal): they're the button colours. Sync statuses also carry an icon, since they're scanned in passing.

**Shape:** `--radius: 0`. Every component radius derives from it, so the whole UI is square.

**Logo:** `web/public/brand/select-exterminating-logo.webp` (black lettering on transparency) goes on white surfaces only. The header has a 4px Gold bottom rule.

**Public pages:** the login and landing pages use a black (`ink`) statement band with a white Oswald headline, a Gold rule, and Gold proof-point numbers, next to the form on Paper.

**Favicon:** the site's own icons (`cropped-…-VIVID-GREEN` 32/180/192px from selectexterminating.com), installed as `web/src/app/icon1.png`, `icon2.png`, and `apple-icon.png`.

**Not yet defined:** a dark theme (Select Green on Ink is 4.46:1, just under AA for text), an SVG logo, and a light-on-dark logo.
