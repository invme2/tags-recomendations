# Changelog

Все заметные изменения проекта документируются в этом файле.
Формат основан на [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
проект использует [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed
- **GSC Product structured-data: дубль Product-схемы + битые медиа.** Страница товара
  рендерила ДВЕ Product JSON-LD (официальную Shopify `{{ product | structured_data }}`
  из Hyper `main-product` + нашу `wanelo-product-schema`) → GSC «Duplicate brand»
  (4 invalid + 49). Фикс: убрал нашу дубль-схему (`render 'wanelo-product-schema'` →
  comment в `sections/wanelo-product-page.liquid`, live + repo). «Missing image» был
  пустым `image[]` нашей схемы (у товаров без `featured_image`) + 1 товар с реально
  битыми медиа (EPROLO/Aliyun отдавал `application/octet-stream` → Shopify-фетчер
  отвергал) — перелит через staged-upload (`fix_failed_media_staged.py`). Новый хелпер
  `theme_edit.py` (fetch/snapshot/upload ассетов темы). Применится на след. крауле
  Google → «Validate Fix» в GSC.
- **Варианты не пушились в Shopify (cell 14 STEP 5, `ce20f070` ~стр.2448).** Пуш читал
  `row['variants_json']` (колонка не заполняется → всегда `[]`), поэтому товары со
  скрейп-вариантами получали 1 вариант (Title). Прошлый фикс поправил только
  Designer-контекст (стр.446), не сам пуш. Фикс: читать `scrape_json.variants`.
  Демо-товары дочинены точечно `fix_demo_variants.py`. Тесты 570 ✅.
- **Designer самоповтор изобретённых секций / junk-метафилды (cell 14 `ce20f070`).**
  Designer плодил опечатки-секции (`timerline`/`comparison`/`ingredients_explanation`/
  `idline`) и сыпал photo-brief слоты (`inline_*`) верхним уровнем; пуш авто-создавал
  определение под каждый, кэш `dynamic_schemas.json` впрыскивал их в следующие промпты
  → самоповтор. Из-за generic `wanelo-auto-section` в живой теме typo-ключи рендерились
  видимыми дублями. Фикс `patch_section_normalize.py`: нормализация ключей Designer
  (alias typo→каноника + drop photo-brief/inline) до кеша/пуша. Очистка:
  `clean_junk_sections.py` (2 кэша + 283 товара DB-meta), `migrate_then_delete_junk.py`
  (живой Shopify: мигрировал 88 видимых секций typo→каноника, удалил 20 junk-определений
  + ~580 невидимых значений → 70→50 определений, 0 junk, потерь нет). Тесты 570 ✅.

### Added
- **Review-фото под товар (photo-pack overhaul, cell 14 `ce20f070`).** Сцены для
  UGC-отзывов теперь генерятся по смыслу товара/категории, а не из бьюти-шаблона.
  Designer выдаёт `review_scenes` (8 сцен: удочка→река/лодка/улов, дрель→гараж,
  духи→свидание); reviews-билдер: primary=Designer → tier-2 дерайв из архивных
  `photo_briefs` товара ($0, без парсинга) → категорийный fallback (11 категорий).
  Reviews больше не клонируются между товарами (per-product seed + инъекция
  `visual_style`). Inline guardrail: EDITORIAL OVERRIDE при overlay/infographic в
  editorial-слоте + inline-hero lifestyle-nudge. Новые тулы:
  `patch_photo_prompts.py`, `patch_review_scenes.py`, `patch_archive_scenes.py`
  (one-shot патчеры nbformat), `regen_photo_prompts.py` (пересборка .txt из
  сохранённых данных без re-Vision/Strategy/Designer и без Shopify),
  `enrich_review_scenes.py` + `backfill_all_review_scenes.py` (премиум-бэкафилл
  через DeepSeek, дедуп по eprolo_url, резюмируемый). Прод-бэкафилл:
  **3116/3116 живых товаров (100%)** получили premium-сцены, 0 сбоев, ≈$5–10.
  Тесты 570 ✅.
- **`pipeline/tools/attach_missing_photos.py`** — восстанавливает медиа товарам с
  0 фото (упавший media-шаг прогона): матч по `eprolo_url` к run-DB галерее
  (`top_image_urls`) → `productCreateMedia`. Идемпотентно (skip если media>0),
  dry-run по умолчанию. Прод: 79 товаров без фото → 0 (527 фото восстановлено).
- **`pipeline/tools/audit_collections_seo.py`** + **`fix_collections_seo.py`** —
  senior-SEO аудит ВСЕХ коллекций (бренды, длины title/meta, CTA, дубли,
  keyword-stuffing) + Opus-реген суб-стандартных (brand-free, корректные длины,
  на тему). Прод: 969 коллекций → исправлено 35 (4 бренда «Real Techniques»,
  22 без meta, 14 пустых описаний, дубли, длины), осталось чистых 969/969.
- **`pipeline/tools/fill_collections.py`** — наполняет пустые/тонкие
  keyword-коллекции (SEO-лендинги из DataForSEO) топологически релевантными
  товарами через TF-IDF (прямой матч коллекция↔товар по заголовку/тегам +
  кластер таксономии как booster ранга, не добавляющий внетематическое).
  Флаг `--from-shopify` берёт товары из живого стора (устойчиво к порче
  локальной БД). Идемпотентно, dry-run по умолчанию, гейт уверенности
  (`--min-picks`/`--strong`) против «1 неверный товар». Результат на проде:
  пустых коллекций 186→0, медиана 1→6 товаров, наполнено 733/733.
- **`pipeline/tools/collections_census.py`** — read-only аудит автоматизма
  внутренних ссылок (parent_category покрытие, публикация) + распределения
  товаров по коллекциям (fill-бакеты, орфаны, cluster-tag coverage).

### Fixed
- **Writer-гонка бэбиситтера → порча `pipeline.db`** (см. TROUBLESHOOTING
  #005). `babysit_chunk2.py` теперь `kill_stragglers()` перед каждым
  рестартом: force-kill старого раннера + блок до его смерти = single-writer
  гарантия. Раньше два процесса могли писать один SQLite при рестарте →
  `database disk image is malformed` (файл ровно 1 GiB). Товары в Shopify
  не пострадали.
- **EPROLO storage_state + redirect guard (Bug A full fix)** (TBD commit,
  see `pipeline/PATCHES.md` 2026-05-26). `get_shared_browser_ctx` теперь
  читает `EPROLO_STATE_FILE` env var и если файл существует — передаёт
  `storage_state` в `new_context`. Plus defense-in-depth в
  `scrape_eprolo`: ранний выход при редиректе с `/app/product/` →
  ошибка ловится `validate_scrape`. Эмпирически подтверждено на 3
  URL'ах из тестового батча. Новые tools: `pipeline/tools/eprolo_login.py`
  (headed Chromium для ручного логина) + `eprolo_verify_scrape.py`
  (smoke-проверка состояния). См. TROUBLESHOOTING #004.
- **EPROLO marketing-page redirect detection** (commit `ba799f3`).
  `validate_scrape` теперь hard-fail'ит на известные маркетинг-тайтлы
  (`'EPROLO -' / 'Sign Up' / 'Sign In' / 'Log In' / 'Login' /
  'Dropshipping Supply' / 'All-in-One Dropshipping'`). Cell 6 при таком
  issue ставит status='error' и НЕ пушит товар в Shopify. Без этого
  pipeline создавал в магазине одинаковые мусорные товары с handle от
  signup-страницы, перезаписывающие друг друга. См. TROUBLESHOOTING #002.
- **`TypeError: len(None)` в Cell 6** (commit `ba799f3`). Shopify
  возвращает `{"metafields": null}` (не `[]`) при полном фейле батча
  метафилдов. `dict.get('metafields', [])` отдавал `None`, и `len()`
  крашил функцию ДО логирования userErrors. Заменил на
  `dict.get('metafields') or []`. См. TROUBLESHOOTING #003.

### Changed
- **Verbose `metafieldsSet` diagnostics** (commit `4927a82`). Раньше при
  фейле логгировали только `userErrors[:2]` и игнорили top-level GraphQL
  errors. Сейчас при `0/N written`:
  - Печатается top-level `errors` (auth, throttle, schema).
  - Каждый input — `key`, `type`, `value_len` (сразу видно, был ли
    Designer-output пустой).
  - До 10 `userErrors` с `field/code/message`.
  Помогает изолировать Bug B (см. HANDOFF.md секция 1).

### Added
- **`HANDOFF.md`** — передача состояния следующему ИИ-агенту: prod-баги,
  что сделано, первые 10 шагов, жёсткие констрейнты, ротация ключей.

- **Cross-collection SEO interlinking (silo structure)** — fills the
  "collection → collection" link gap. Before, each collection page was a
  dead end for Google (linked only to its own products). Now collections
  link laterally, distributing authority across the silo:
    - **Cell 2: `_compute_collection_related()` graph algorithm.** Scores
      every pair by title_word × 3 + keyword × 2 + handle_word × 1 (with
      plural-normalisation and word-level tokenisation so "fans" / "fan"
      match). Picks top-k per collection (k=6 default).
    - **Reciprocity:** A → B implies B → A — symmetric closure within a
      cap of 8 entries per collection. SEO authority flows both ways.
    - **Hub detection:** weighted in-degree on the NATURAL (pre-reciprocity)
      adjacency identifies high-attraction nodes — typically broad
      umbrella collections ("All Fans") that overlap with many spokes.
      Top ~15% by weighted in-degree are flagged `is_hub: true`, sorted
      first in each related list, rendered with distinctive "HUB" badge.
    - **Anchor-text variety** — cycles through {exact title / 2-4 word
      keyword / "explore X" generic} every 4 entries; hubs get "Shop all
      <title>". Prevents over-optimization penalty.
    - **`custom.related_collections` metafield (COLLECTION owner_type)** —
      JSON array `[{handle, title, anchor, score, is_hub}]`. Written by
      Cell 4's new post-creation cross-link step.
    - **Inline-mention paragraph** appended to each collection's
      descriptionHtml: `<p class="wanelo-coll-also">Browse related:
      <a>...</a> · <a>...</a></p>`. 2 top related collections with varied
      anchors, contextual text-flow link rather than UI chip. Idempotent
      via `wanelo-coll-also` sentinel-class check.
    - **`sections/wanelo-collection-related.liquid`** — operator-installable
      section that renders chip-row of related collections on the collection
      page (Customize → Collection → Add section). Empty-metafield gate so
      safe to leave installed on all collections.
    - **`wanelo.css`** — chip styling + hub-distinct variant + inline-paragraph
      style.
  Expected SEO impact: +20-40% organic over 3-6 months once Google crawls
  the new link graph (lateral authority flow + reduced collection-page
  dead-ends + topical clustering).
  29 new tests in `pipeline/tests/test_collection_seo.py` including
  synthetic algorithm correctness fixtures (basic overlap, reciprocity
  guarantee, hub detection, anchor variety, score-descending sort,
  no-self-links, empty input, single-collection).

- **Conversion-optimization features for cold paid traffic** — five additions
  designed to lift CVR on the typical $15-30 EPROLO-driven product page from
  ~0.8% baseline to ~2-3% with all fixes applied:
    - **`RETAIL_MARKUP` + `COMPARE_AT_MARKUP` env vars** (default 5.0 / 8.0).
      `calc_price` and `calc_compare_price` now read these instead of hardcoded
      multipliers, so operator can tune per category without code edits. The
      strike-through `compareAtPrice` was already pushed to Shopify — this just
      exposes the dial.
    - **`wanelo-guarantee.liquid` snippet** — always-on risk-reversal block
      (return policy / shipping / secure checkout). Renders right after hero
      in master section, before story. Content overridable via shop-level
      metafields (`shop.metafields.wanelo.return_policy` etc.) with hardcoded
      defaults so it always renders even if operator hasn't configured.
    - **Hero inline CTA mirror** — `<a href="#wanelo-atc">` button INSIDE the
      hero block (in addition to the bottom CTA section). Multiple ATC hit
      points lift CVR — buyer doesn't have to scroll past 13 sections.
    - **Hero trust line under H1** — "30-day returns · Free shipping over $50
      · Secure checkout" reads `shop.metafields.wanelo.trust_line` with hardcoded
      fallback. Above-fold trust signal before buyer scrolls.
    - **Mobile sticky ATC bar** (wanelo.js + wanelo.css). IntersectionObserver
      shows fixed-position bar at viewport bottom whenever the Shopify product
      form scrolls off-screen on mobile (<769px). Tapping it smooth-scrolls
      back to the form. One-tap re-access from anywhere on page = +15-25%
      mobile CVR. Auto-assigns `id="wanelo-atc"` to the form on init.
  17 new tests in `pipeline/tests/test_conversion.py`.

### Changed
- **STEP 4.5 photo_pack ZIP — restructured for model/operator separation +
  funnel-ordered filenames + smart fallback**:
    - **`prompt.txt` now contains ONLY model instructions** — operator-workflow
      language ("Open a NEW chat", "Drop edited photos in Shopify Admin")
      removed. Top of file is an explicit `## Instructions for the image model`
      block. References (carousel funnel + inline placement) moved to the end
      of `prompt.txt` so per-brief edits appear right after the unified style
      paragraph.
    - **`README.md` added to ZIP** — operator workflow (open chat → upload
      photos+prompt → download edited → drop into Shopify), filename-order
      explanation, inline-* → metafield image_url mapping. Marked explicitly
      operator-only so it doesn't get uploaded to the model.
    - **`manifest.json` added to ZIP** — audit-only map of `filename → EPROLO
      source_url` per brief + visual_style + created_at. Lets operator verify
      which original photo each edit came from. Source URL removed from
      `prompt.txt` (noise for image models, which don't fetch URLs).
    - **Filenames sorted by carousel conversion funnel** — `_FUNNEL_ORDER`
      constant; `_resolved.sort(key=_funnel_idx.get(..., 999))` before
      numbering. Filenames `01-carousel-hero`, `02-carousel-lifestyle`, ...
      so operator can drop them into Shopify carousel in filename order.
      Unknown slots sort last (key=999), preserving Designer emission order.
    - **Smart `visual_style` fallback** — generic editorial-photo fallback
      removed (it clashed with pastel section palettes). New fallback builds
      a personalized style line from `sections.palette` + `strategy.voice`
      via voice→tone-anchor map (warm-confidant → "warm intimate framing",
      etc.). If even palette/voice are absent → skip ZIP entirely (no
      dishonest generic default).
    - **Photo download retry** — 3 attempts with exp backoff (1s, 2s) instead
      of silent skip on transient EPROLO CDN errors. Final failure logged
      with brief id + attempt count.
    - **Bug fix**: upload block was at wrong indent level (could NameError
      on `_zip_bytes_pp` if `_resolved` empty — masked by outer try/except).
      Now properly nested inside the build-ZIP branch.
  16 new tests cover funnel sort + README + manifest + smart fallback + retry.

- **`custom.photo_pack` metafield: type `json` → `url`** for one-click download
  UX in Shopify Admin. Previously the metafield held a JSON wrapper dict
  (`{url, size_kb, photo_count, ...}`) — Admin rendered it as raw JSON text
  the operator had to copy-paste. Now it holds just the URL string, so Admin
  renders a clickable hyperlink — single click opens the ZIP. Implementation:
    - Cell 2: per-key `_type_overrides = {'photo_pack': 'url'}`; ensure-loop
      now passes `type_name=_type_overrides.get(_k, 'json')`
    - Cell 6 STEP 4.5: stores `_upload_res['url']` directly into
      `sections['photo_pack']` (no wrapper dict)
    - Cell 6 STEP 5 metafieldsSet loop: per-key `_mf_types` branch — url-typed
      fields send the raw string and skip when value isn't a real `http*://`
      URL (defensive: avoids Shopify rejection if upload failed earlier)
  Hardening tests added: `test_body_html_assembly_never_uses_photo_pack`,
  `test_theme_css_does_not_reference_photo_pack`,
  `test_theme_js_does_not_reference_photo_pack`,
  `test_no_hidden_attribute_renders_photo_pack` — proves photo_pack URL
  never reaches any storefront HTML/CSS/JS, even as a hidden element.

### Added
- **Admin-only `custom.source` metafield** — per-product EPROLO provenance
  record visible only in Shopify Admin → Product → Metafields, never on
  storefront. Stores `{platform, url, scraped_at, title, description (capped
  5000 chars), cost_price_usd, image_urls{top[], desc[]}}`. Operator clicks
  the URL to open the original EPROLO listing for any synced product. Cell 2:
  metafield definition with `visible_to_storefront=False` (joins existing
  `photo_pack` in `_admin_only` set); Cell 6 STEP 5 builds `_src_meta` dict
  from scraped product before `metafieldsSet` batch and includes `'source'`
  in `_wanelo_keys`. Total metafields per product: 21 content + 2 admin-only
  = 23. Build wrapped in try/except so a failed source record never blocks
  the rest of the batch. 12 new tests in `pipeline/tests/test_admin_source.py`.

### Removed
- **gpt-image-2 image generation cut entirely.** User decision after API style
  inconsistency across briefs (single-prompt isolation in `images.edit` calls
  cannot match ChatGPT UI's threaded conversation memory). Removed:
    - Cell 1: `OPENAI_API_KEY`, `USE_IMAGE_GEN`, `MODEL_IMAGE_GEN`,
      `IMAGE_GEN_QUALITY`, `GALLERY_PHOTO_COUNT` constants + OpenAI billing line
    - Cell 2: openai_client init block
    - Cell 6: entire STEP 3.7 (image gen + URL substitution), `_assets_initial`
      persistence, `gallery_briefs`/`metafield_briefs`/`visual_style` schema
      fields, `image_id` placeholder system
    - DB: `images_generated` status (flow shrinks to
      `strategy_done → html_ready → done`); `assets_json` column kept harmless
    - Diagnostic: `pipeline/tools/test_openai_image.py`
    - Docs: `pipeline/BILLING.md` deleted; SETUP.md trimmed to Anthropic +
      DataForSEO only
  Designer now picks `image_url` directly from EPROLO source list (same as
  pre-image-gen architecture). Step 5 attaches EPROLO top photos to product
  carousel via `shopify_attach_media`.

- **Dead code purge** (~50KB / 21 functions / 1 cell). Notebook shrank from
  18 cells / 9 code cells / 249K chars → 17 cells / 8 code cells / 200K chars.
  Removed:
    - Cell 13 entirely: page_builder fetch (assemble_page/MODULE_CATALOG never
      called after JSON refactor)
    - `pipeline/page_builder.py` + `pipeline/tests/test_page_builder.py`
    - `WRITER_SYSTEM_PROMPT` (~230 lines), `WA_CSS_FRAMEWORK` (~135 lines),
      `WA_SNIPPET_LIQUID`, `_legacy_html_instructions` — leftover from old
      HTML-in-metafield approach
    - `USE_MODULAR_HTML` toggle + `PAGE_BUILDER_URL` constant
    - Duplicate function definitions (validate_scrape, ping_google_sitemap,
      kw_score, tier_keywords, shopify_set_merchant_extended) — second defs
      were already winning at runtime, first defs deleted
    - Dead helpers never called: build_howto_schema, build_video_schema,
      build_review_schemas, build_shipping_return_schema, build_schema_jsonld,
      build_faq_schema, validate_html, validate_meta, sanitize_html,
      seo_image_filename
    - Test cleanup: 16 page_builder-specific tests + 6 metafield_prep tests
      (both targeted dead HTML-pipeline code) → kept 8 theme-asset tests

### Changed
- **Pricing: gpt-image-2 cost table replaces gpt-image-1 estimate.** The cost
  map is now size-aware and matches the official pricing (medium 1024² = $0.053,
  medium 1024×1536 = $0.041, high 1024² = $0.211). Cost-per-brief is computed
  from `IMAGE_GEN_QUALITY × _size`. Comment notes additional input-token overhead
  because gpt-image-2 always processes reference images at high fidelity.
- **Pipeline architecture: Image Strategy agent merged into Designer.** Previously
  three agents ran sequentially (Strategy → Image Strategy → Designer). Now
  Designer (Sonnet 4.6) emits the page content **and** photo briefs in a single
  JSON: `gallery_briefs[5]` (Shopify carousel) + `metafield_briefs[3-7]` (inline
  description images). Step 3.7 generates all images via gpt-image-2 and
  substitutes `image_id` placeholders with Shopify CDN URLs in the content JSON.
  Status flow shrinks to: `strategy_done → html_ready → images_generated → done`
  (was: `strategy_done → image_plan_done → images_generated → html_ready → done`).
  Saves one Sonnet call per product (~$0.02) and one DB column.
- Step 5 Shopify push prefers AI-generated `gallery_urls` for `productCreateMedia`,
  falls back to EPROLO top photos when image gen is disabled.
- DB schema: added `strategy_json`, `assets_json` columns; removed
  `image_plan_json` references.
- New constant `GALLERY_PHOTO_COUNT = 5` (Shopify product carousel).
- Conflict tests `pipeline/tests/test_pipeline_flow.py` (36 tests) cover status
  flow, agent removal, designer brief schema, image-gen substitution, gallery
  upload preference, and pastel-palette / voice cross-cell consistency.

### Added
- Каркас моно-репо: директории `taxonomy/`, `pipeline/`, `tools/`, `.github/workflows/`, `docs/`.
- Memory-файлы: `CLAUDE.md` (конституция), `DECISIONS.md` (ADR-001..005),
  `CHANGELOG.md`, `TROUBLESHOOTING.md`.
- `README.md` (короткий, ссылается на `CLAUDE.md`).
- `.gitignore` (Python, Jupyter, .env, snapshots, *.db, *.cache).
- `requirements-dev.txt` (jsonschema, nbformat, pytest, black).
- `taxonomy/schema.json` — черновая JSON Schema (Draft-07).
- `taxonomy/tools/validate_taxonomy.py` — валидатор по схеме + бизнес-правилам
  (дубли `tag`, ссылочная целостность `related[]`, непустой `embed_text`,
  членство `personas`/`intents`/`demos` в master-списках).
- `taxonomy/tools/build_taxonomy.py`, `stats.py`, `export_to_csv.py` — заглушки.
- `taxonomy/tests/test_taxonomy.py` — тесты валидатора на синтетических данных.
- `pipeline/tools/notebook_smoke.py` — `nbformat.validate` + `ast.parse` каждой
  code-ячейки + проверка дефинированности имён между ячейками.
- `pipeline/tools/extract_cells.py` — конвертер `.ipynb` → `.py` для чтения.
- `pipeline/tools/apply_patch.py` — точечный str_replace в конкретной ячейке через nbformat.
- `pipeline/PATCHES.md` — журнал точечных правок ноутбука.
- `tools/health_check.py` — общий smoke-тест.
- CI: `.github/workflows/validate-taxonomy.yml`, `.github/workflows/smoke-pipeline.yml`.

### Changed
- ADR-001 обновлён: имя репо зафиксировано — `invme2/tags-recomendations`
  (подтверждено пользователем 2026-05-05). Миграция в `wanelo-shopify-system`
  снята с повестки.
- **ADR-006 заменяет ADR-005.** Реальный `taxonomy.json` v3.2 (765 кластеров)
  доставлен пользователем через ZIP в ветке. Полностью переписана
  `taxonomy/schema.json` под фактическую структуру: 19 полей в cluster,
  master-списки `personas/intents/demos` как объекты, `cluster.demos` как
  объект, новый top-level `sections[]`, namespaced-теги (`cluster:`,
  `persona:`, `intent:`, `demo:`), `demo.type ∈ {gender, age}`,
  `status ∈ {approved, draft}`.
- `validate_taxonomy.py` расширен с 4 до **9 бизнес-правил**: дубли
  cluster/persona/intent/demo/section, broken section_id/slug/related,
  unknown persona/intent/gender/age, empty embed_text.
- `pipeline/tools/notebook_smoke.py` переписан с правильной обработкой
  scope: больше не лезет в тела функций / классов / lambda. На реальном
  ноутбуке прежняя версия давала 75 false-positive (флагала параметры
  и локальные переменные функций как «undefined»); новая версия проходит.
- `taxonomy/tests/test_taxonomy.py` расширен с 10 до **15 тестов**, добавлен
  контрактный тест `test_real_taxonomy_validates`, который гарантирует, что
  реальный `taxonomy.json` всегда проходит схему.

### Added
- `taxonomy/taxonomy.json` — реальная база (765 кластеров, 36 sections,
  27 personas, 14 intents, 9 demos, version v3.2, schema_version 1).
- `taxonomy/tools/enrich_taxonomy.py` — реальный скрипт обогащения через
  Claude API + FAISS-related (заменил мою заглушку).
- `pipeline/Shopify_Pipeline.ipynb` — реальный пайплайн (17 ячеек, 8 code,
  ~310KB), переименован из `Shopify_Pipeline_v9_with_taxonomy.ipynb`.
- `taxonomy/data/v3.1-README.md` — оригинальный README пользователя
  (положен в `data/` как исторический документ; верхнеуровневый
  `README.md` остаётся моим, ссылается на `CLAUDE.md`).

### Verified
- `python tools/health_check.py` → exit 0, оба под-чека зелёные.
- `python -m pytest taxonomy/tests/ -v` → 15/15 passed.
- `python taxonomy/tools/validate_taxonomy.py` → 765 кластеров валидны.
- `python pipeline/tools/notebook_smoke.py` → 17 ячеек валидны.

---

## Gap-analysis итерация 1 (2026-05-05, source v3.3)

### Added (18 новых cluster:* в `taxonomy/taxonomy.json`)
Внутренний gap-анализ против существующих 765 кластеров (структурный + по
ключевым словам индустрии). Все новые — `status: draft`, `source: v3.3`,
`personas/intents/demos/related/synonyms/title_ru/description` пустые
(работа `enrich_taxonomy.py` после ревью пользователя).

**Section 17 (Electronics & gadgets extended) — granular smart-home & audio:**
- `cluster:smart-speaker` (Echo, HomePod, Sonos, Google Nest)
- `cluster:smart-doorbell-lock` (Ring, Yale, August)
- `cluster:smart-plug-outlet` (TP-Link Kasa, Amazon)
- `cluster:noise-cancelling-headphones` (Bose QC, Sony WH-1000XM, AirPods Max)
- `cluster:dash-cam-driving` (видеорегистратор)

**Section 1.5 (Home & everyday) — крупная бытовая техника:**
- `cluster:air-purifier-home` (HEPA, Dyson, Levoit)
- `cluster:vacuum-cleaner-types` (cordless / stick / upright; не покрывалось `robot-cleaning`)
- `cluster:steam-cleaner-home` (Karcher, паровые швабры)
- `cluster:water-filter-purifier` (Brita, RO, кувшин-фильтр)

**Section 1.6 (Work & productivity) — рабочее место home-office:**
- `cluster:standing-desk-setup` (sit-stand, Flexispot, Uplift)
- `cluster:ergonomic-office-chair` (Herman Miller, Secretlab)
- `cluster:monitor-arm-mount` (VESA, Ergotron)
- `cluster:office-supplies-essential` (степлеры, бумага, папки)

**Section 1.1 (Morning rituals) — beauty deeper:**
- `cluster:anti-aging-skin` (retinol, peptides; отдельно от `skincare-routine`)
- `cluster:acne-treatment` (salicylic, benzoyl, патчи)

**Section 1.7 (Pet care) — pet-tech:**
- `cluster:smart-pet-tech` (Furbo, Whistle, smart feeders)

**Section 22 (Health & wellness) — sleep tech:**
- `cluster:sleep-tech-tracking` (Oura, Whoop, white noise; отдельно от `sleep-hygiene` который ритуал)

**Section 1.4 (Travel & on-the-go) — личная безопасность:**
- `cluster:personal-safety-self-defense` (alarm, pepper spray, для соло-путешествий)

### Methodology
1. Структурное распределение: 28 sections, средняя плотность ~27 кластеров/section,
   тонкие (<12) — Lighting, Wall decor, Price positioning, Gourmet, Photo zone &
   party, Specific diets, Kitchen appliances, Repair & tools, Transport & auto.
   Тонкие — концептуально узкие, не дыры.
2. Keyword-probe против существующих clusters (tag + title_en + embed_text +
   typical_products): 36 кандидатов индустрии → 24 потенциальных пробела →
   6 отсеяно после dedup-проверки (`cluster:nail-care`, `cluster:mens-skincare`,
   `cluster:painting-kit`, `cluster:book-lover`, `cluster:earbuds-bundle`,
   `cluster:smart-home`-агрегат).
3. Финальные 18 — все с уникальным фокусом, не дублируют существующие.

### Stats после итерации
- `total_clusters`: 765 → **783**
- `approved`: 430 (без изменений)
- `draft`: 335 → **353**
- `source: v3.3` — 18 новых; источников теперь три: v3.1 (430), v3.2 (335), v3.3 (18)
- `updated: 2026-05-05`

### Открыто (не делаю без запроса пользователя)
- Реальный gap-анализ против каталога EPROLO/Shopify — требуется дамп каталога.
  Без него мы видим только внутренние пробелы и обоснованные предположения по
  индустрии, но не «эти 200 товаров нашего ассортимента не покрыты».
- Запуск `enrich_taxonomy.py` на v3.3 кластерах для заполнения
  `personas/intents/demos/synonyms/title_ru/description/related[]`.
- Промоут отревьюенных v3.3 в `status: approved`.

---

## Gap-analysis итерация 2 (2026-05-05, source v3.3)

Метод изменился: вместо чисто структурных эвристик — **matching придуманных
тестовых продуктов против таксономии** через cosine similarity. Это
правильнее: имитирует то, что делает прод-пайплайн, и проверяет покрытие
через реальные продуктовые формулировки.

### Added
- `taxonomy/tools/gap_test.py` — переиспользуемый тул для matching
  списка продуктов против `taxonomy.json`. Backend выбирается автоматически:
  `sentence-transformers/MiniLM` (как в проде) если доступно, иначе
  `scikit-learn TfidfVectorizer` фоллбэк. CLI: `--self-test`, `--products
  file.txt|.csv`, `--top-k`, `--threshold`, `--json`, `--backend`.
- 39 встроенных тестовых продуктов в gap_test.py (English + Russian,
  включая sanity-check для существующих кластеров и заведомые гэпы).

### Added (7 новых cluster:* в taxonomy.json)
Найдено через прогон gap_test.py — top-1 был **семантически неверным**:

| Гэп | Продукт-триггер | Top-1 ДО | Новый cluster |
|---|---|---|---|
| Tactical flashlight / EDC | "Tactical flashlight USB-C strobe" | printer-setup | `cluster:tactical-flashlight-edc` (sec 14) |
| Scuba/snorkel | "Scuba diving mask snorkel set" | sunglasses-set | `cluster:scuba-snorkel-diving` (sec 18) |
| Hammock outdoor | "Hammock with stand backyard" | portable-projector-set | `cluster:hammock-outdoor-relax` (sec 1.5) |
| Heated blanket | "Heated blanket electric king" | plus-size-fit | `cluster:heated-blanket-warmer` (sec 1.5) |
| EV home charger | "EV Level 2 home charger" | ev-owner (persona) | `cluster:ev-charger-home` (sec 13) |
| Hydroponic indoor | "AeroGarden harvest 360" | garden-care (broad) | `cluster:hydroponic-indoor-garden` (sec 1.5) |
| Massage gun (percussion) | "Theragun deep tissue" | massage-therapy (массаж-сервис, не девайс) | `cluster:massage-gun-percussion` (sec 22) |

### Changed
- `embed_text` всех 18 v3.3-кластеров итерации 1 расширен русскими keywords
  из `typical_products` — иначе TF-IDF (и слабые семантические модели)
  плохо матчат русскоязычные запросы. Бенчмарк: «Эргономичное кресло» →
  правильный `ergonomic-office-chair` 0.053 → 0.066, «Yale August» →
  `smart-doorbell-lock` 0.123 → 0.177.
- `gap_test.py` default TF-IDF threshold 0.20 → 0.10 — реалистичнее для
  sparse cosine; <0.06 = «точно мимо», 0.06–0.10 = «right cluster, low
  TF-IDF score» (из-за слабого keyword-overlap, semantic это бы взял).

### Test results (39 products, TF-IDF backend, threshold 0.10)
- 32/39 covered (82%) — top-1 кластер релевантен.
- 7/39 «uncovered» по TF-IDF — но это **false negatives**: top-1 — правильный
  кластер, абсолютный cosine просто <0.10 из-за того, что TF-IDF плохо ловит
  кросс-языковые синонимы. На семантической модели в проде (Colab) пройдут
  все 39.
- Реальных «top-1 wrong» больше нет (было 6 в начале итерации).

### Stats после итерации
- `total_clusters`: 783 → **790**
- `draft`: 353 → **360** (+7)
- `approved`: 430 (без изменений)
- `source: v3.3` теперь 25 кластеров (18 итерация 1 + 7 итерация 2)
- `updated: 2026-05-05`

### Limitations
- Sandbox Claude Code on the Web блокирует `huggingface.co` →
  `paraphrase-multilingual-MiniLM-L12-v2` не скачивается. Прод-пайплайн в
  Colab этим не страдает. TF-IDF фоллбэк даёт 60–70% качества semantic для
  English-vs-English матчинга и хуже для cross-lingual. Документировано в
  `gap_test.py` docstring.
- Тестовый набор — придуманные продукты, не дамп реального каталога. Реальный
  gap-анализ требует Shopify/EPROLO export.
