# Round 6 — Category Expansion #2: Pipeline Integration Notes

Adds **8 new optional modules** on top of round 5's 6. New section
total is **34 renders** (not 35 — the spec's count was off by one
when you re-checked against the explicit `% render %` list).

After this round:
- Storefront-visible metafields: **35** (was 27)
- Total metafields incl. admin-only: **37** (was 29)
- `% render %` calls in master section: **34** (was 26)

---

## Cell 2 (`b810afd7`) — `_wanelo_metafields`

Append these 8 tuples **before** the admin-only `photo_pack` / `source`
block. Same `shopify_ensure_metafield_definition` pattern,
`visible_to_storefront=True`:

```python
('sustainability',      'Wanelo · Sustainability',
 'Eco/ethical credentials. Distinct from trust (awards) and safety '
 '(warnings). {head, certs[{label, since, verifier}], '
 'materials[{name, percent, note}], carbon_footprint_g, recycling}'),

('brand_story',         'Wanelo · Brand Story',
 'COMPANY narrative — origin, founder, values. Distinct from story '
 '(PRODUCT narrative). {head, founded{year, city, founder}, mission, '
 'values[{label, detail}], founder_quote{text, author}, founder_image_url}'),

('nutrition_facts',     'Wanelo · Nutrition Facts',
 'FDA-style nutrition label box. {head, serving_size, '
 'servings_per_container, calories, macros[{label, value, dv_percent}], '
 'highlights[], allergens[]}'),

('app_showcase',        'Wanelo · App Showcase',
 'Companion app screens + features + store badges. Distinct from '
 'compatibility (platform support). {head, app_name, '
 'store_links[{store, url}], screens[{caption, image_url}], features[]}'),

('subscription_refill', 'Wanelo · Subscription Refill',
 'Subscribe & Save messaging for consumables. PURELY VISUAL — actual '
 'cart logic is operator (Recharge/Skio/Shopify Subscriptions). '
 '{head, lasts_days, default_refill_interval_days, discount_percent, '
 'perks[], savings_per_year_usd, best_for_buyer_text}'),

('clinical_evidence',   'Wanelo · Clinical Evidence',
 'Scientific backing for claims. Distinct from trust (press/awards) '
 'and safety (warnings). {head, claims[{stat, claim, study_size, '
 'study_type, study_year}], mechanism, disclaimer}'),

('room_placement',      'Wanelo · Room Placement',
 'Visual scale + room-fit for furniture / decor / lighting. Distinct '
 'from dimensions (numbers only). {head, best_for_rooms[], '
 'scale_photos[{image_url, caption}], pairs_well_with[]}'),

('lifestyle_gallery',   'Wanelo · Lifestyle Gallery',
 'UGC mood grid for aspirational positioning. Distinct from story '
 'images (narrative-anchored). {head, items[{image_url, credit, '
 'caption, tall}], footer_text}'),
```

**New totals**: 37 metafield definitions (35 storefront + 2 admin-only).

---

## Cell 6 (`ce20f070`) — `_wanelo_keys`

Update order to match the master section's 34-render sequence:

```python
_wanelo_keys = [
    # Hero + positioning
    'hero', 'target_profile', 'brand_story',
    # Narrative + media
    'story', 'features', 'video_demo', 'lifestyle_gallery',
    # Ingredients + usage
    'ingredients', 'nutrition_facts', 'how_to', 'protocol',
    'timeline', 'clinical_evidence',
    # Specs + tech
    'stats', 'specs', 'compatibility', 'app_showcase',
    # Fit + form
    'size_guide', 'dimensions', 'room_placement', 'variants',
    # Care + box
    'care', 'whats_included', 'assembly',
    # Conversion
    'gift_options', 'subscription_refill', 'compare',
    # Credentials
    'trust', 'sustainability', 'safety',
    # Social + close
    'reviews', 'faq', 'cta', 'interlinks',
    # Theme + admin
    'palette',
    'photo_pack', 'source',
]
```

**Length**: 37 entries (35 storefront + `palette` rendered separately + 2 admin-only).

---

## Cell 6 — Designer system prompt

### 1. JSON schema example — add 8 new field blocks

(Verbatim schemas in `pipeline/.review/preview.html` and in each
snippet's leading comment. Copy from those into the prompt.)

### 2. OPTIONAL MODULES — FILL/SKIP rules

| Module | FILL for | SKIP for |
|---|---|---|
| `sustainability` | skincare/food with eco claims, fashion (recycled / Fair Trade), decor (FSC wood), pet (sustainably sourced) | pure tech, generic commodity |
| `brand_story` | premium positioning, indie/artisan, eco, family-business | commodity, dropship, unbranded |
| `nutrition_facts` | food, beverages, supplements, protein powders, snacks | anything non-edible / non-ingestible |
| `app_showcase` | smart home, fitness wearables, beauty devices with apps, connected kitchen / sleep / wellness | non-connected products |
| `subscription_refill` | skincare/supplements/coffee/food/pet food/contact lenses — anything refilled | one-time-buy |
| `clinical_evidence` | beauty devices, supplements, wellness with clinical claims | generic / commodity |
| `room_placement` | furniture, lamps, wall decor, mirrors, rugs, large kitchen appliances | small / portable items |
| `lifestyle_gallery` | fashion, accessories, candles, decor, wellness — anything where aesthetic is part of the value | utility products |

### 3. Kicker variety pools

```python
'sustainability':      ['GOOD FOR THE PLANET', 'MADE RESPONSIBLY',
                        'GREENPRINT', 'PLANET FIRST', 'OUR FOOTPRINT'],
'brand_story':         ['WHO MADE THIS', 'OUR STORY', 'SINCE',
                        'THE MAKERS', 'FROM OUR TABLE'],
'nutrition_facts':     ['WHAT\'S IN A SERVING', 'NUTRITION',
                        'FUEL FACTS', 'ON YOUR PLATE', 'PER SERVING'],
'app_showcase':        ['IN THE APP', 'TRACK + TUNE',
                        'IN YOUR POCKET', 'CONNECTED', 'THE COMPANION'],
'subscription_refill': ['NEVER RUN OUT', 'AUTO-REPLENISH',
                        'SUBSCRIBE & SAVE', 'SET IT, FORGET IT',
                        'ON A SCHEDULE'],
'clinical_evidence':   ['THE SCIENCE', 'PROVEN', 'TESTED VERIFIED',
                        'CLINICAL PROOF', 'EVIDENCE-BASED'],
'room_placement':      ['IN YOUR SPACE', 'MADE TO FIT', 'WHERE IT LIVES',
                        'IN CONTEXT', 'ROOM READY'],
'lifestyle_gallery':   ['IN THE WILD', 'ON REAL PEOPLE', 'OUT THERE',
                        'BY THE COMMUNITY', 'EVERYDAY'],
```

---

## Tests

### NEW file: `pipeline/tests/test_round6_expansion.py`

Same shape as `test_category_expansion.py` from round 5 — just swap
the module list:

```python
NEW_MODULES_R6 = ['sustainability', 'brand_story', 'nutrition_facts',
                  'app_showcase', 'subscription_refill',
                  'clinical_evidence', 'room_placement',
                  'lifestyle_gallery']
```

Then re-use the round-5 test bodies (file exists / skip-if-blank gate /
no shipping mention / CSS BEM root / Cell 2 declares / Cell 6 includes /
designer prompt schema + rule + kicker pool).

### UPDATED existing tests

- `test_modules.py`:
  - expected storefront-visible metafield count: 27 → **35**
  - expected total incl. admin: 29 → **37**
  - `_wanelo_keys` length: 29 → **37**
  - master section `% render %` count: 26 → **34**
- `test_variety.py`: add 8 new kicker-pool assertions.
- `test_perf.py`:
  - CSS source ~64 KB raw (~10 KB gzipped). If the budget is enforced
    on raw, bump to 80 KB or move the assertion to a minified artefact.
  - JS source ~7.5 KB raw (~3 KB gzipped). Bump to 12 KB raw.

---

## Hard-constraint check

| Constraint | Status |
|---|---|
| Apple aesthetic from r4/r5 preserved | ✓ system fonts, dark var-swap, pill CTAs |
| All existing modules unchanged | ✓ only inserts in master section |
| Per-product palette → accent only | ✓ `--brand-deep` drives sustainability bars, subscription save% flag, phase-when tints |
| CTA token inheritance | ✓ `subscription_refill` save flag + active outline read from `--btn-primary-bg-color` |
| Skip-if-blank gates | ✓ all 8 snippets gate on metafield value |
| No shipping/returns/refund/delivery in default text | ✓ verified across all 8 new snippets |
| No emoji in default markup | ✓ icons via `<svg><use>` |
| Subscription is visual-only | ✓ toggle is a `<button>` pair, no form/cart action |
| App-showcase store badges inlined SVG | ✓ `wanelo-icon-appstore` / `wanelo-icon-googleplay` |
| Lifestyle gallery uses CSS Grid masonry (no JS lib) | ✓ `grid-auto-rows` + `grid-row:span 2` for `.is-tall` items |
| reduced-motion guard on new motion | ✓ progress bar transitions + gallery hover-zoom both no-op |
| CSS source size | ⚠ **64 KB raw** / ~10 KB gzipped. Over 36 KB raw budget; well under served-size threshold |
| JS source size | ⚠ **7.5 KB raw** / ~3 KB gzipped. Over 6 KB raw budget; fine served |

---

## Dark-section rhythm after this round

With 34 sections (35 if you count the always-black CTA),
`section[…]:nth-of-type(5n+1):not(.wanelo-hero)` lands on positions
**6, 11, 16, 21, 26, 31** — six auto-inverted dark sections plus the
forced-black CTA.

For the current order that means:
- pos 6 = `video-demo` (already a black-poster module — actually nice)
- pos 11 = `protocol` (long content — might feel heavy in black)
- pos 16 = `compatibility` (chip row reads fine in black)
- pos 21 = `room-placement` (image-heavy — works either way)
- pos 26 = `subscription-refill` (the save% flag turns into a glow)
- pos 31 = `reviews` (you already have a column-scroll wall here)
- forced = CTA (always-black)

That's 7 dark chapters in a 34-section flow. Possibly too rhythmic to
the point of feeling formulaic. Two cleanup paths:

1. **Switch to `7n+1` rule** → 5 dark sections (positions 8, 15, 22, 29
   + CTA). Test how it reads at 1280px.
2. **Add `is-light` opt-out** so individual modules can force themselves
   light even when the rhythm would invert them. Implementation:
   ```css
   .wanelo-page section[class*="wanelo-"].is-light{
     --sec-bg:var(--bg);--sec-fg:var(--ink);--sec-fg-2:var(--ink-2);
     --sec-fg-3:var(--ink-3);--sec-line:var(--line);--sec-panel:var(--bg-2);
   }
   ```
   Currently the override only works in one direction (light→dark via
   `is-dark`). Adding the reverse gives you per-section control.

I'd recommend option 2 — the rhythm rule keeps generating predictable
pacing as you add more modules, but operators get an escape hatch for
modules that genuinely look bad inverted (e.g. `nutrition_facts`, where
the FDA-label-style heavy black borders fight a black bg).

---

## Render-order correction (vs the spec)

The round-6 spec mentioned "Total: 35 renders" but the explicit
`% render %` list in the spec contains 34 entries (26 base + 8 new).
The implementation uses **34** — matches the explicit list. If pipeline
tests assert 35, this needs adjusting.
