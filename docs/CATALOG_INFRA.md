# Catalog Infrastructure — авто-консистентность при добавлении товаров (включая НОВЫЕ категории)

> Цель: добавил партию товаров (даже из категории, которой раньше не было) → фасеты, фильтры, счётчики,
> «Shop by type», умные коллекции, дедуп, цены вариантов, AEO-описания — собираются САМИ, без ручных
> доделок и без поломок. Этот документ — единый источник по тому, как это устроено.

## 0. Что ломается СЕЙЧАС (и почему нужна инфраструктура)
- Пайплайн генерит описания, но НЕ проставляет фасет-теги / counts / map — это были разовые бэкфиллы.
- `gen_facets.derive()` — на ЖЁСТКИХ keyword-правилах под текущие 12 категорий (beauty/health).
  Новая категория (Electronics, Pet, Home, Fashion…) упадёт в фоллбэк «Health & Wellness» → мусор в фильтрах.
- `facet_counts`, `category_collections` (Shop by type), `canonical_map` — устаревают при доливе товаров.
- Цены вариантов иногда разъезжаются на скрейпе (8/3100) — нужна нормализация на создании.

## 1. ПРИНЦИП: таксономия = единый источник правды
Один версионируемый конфиг `taxonomy/facets.json`:
```
{ "categories": {
    "Skincare": { "keywords": [...], "params": ["Concern","Format","For"], "modules": ["ingredients","clinical_evidence","timeline","care"], "collection_handle": "cat-skincare" },
    "Electronics": { ... },   // ← новая категория добавляется ОДНОЙ записью
    ... },
  "params": {
    "Concern": { "values": {"Acne":[kw], "Anti-aging":[kw], ...} },
    "Format":  { ... }, "For": {...}, "Scent": {...} } }
```
Всё (facet engine, фильтр-UI группы, Designer-модули, smart-коллекции) читает ЭТОТ конфиг. Новая категория = +1 запись здесь, дальше система разворачивает её сама.

## 2. FACET ENGINE — taxonomy-driven + LLM-fallback (вот что закрывает «новые категории»)
`pipeline/tools/facet_engine.py :: classify(product) -> {category, concern[], format, for[], scent[], confidence, unclassified}`
1. **Fast path** — keyword-правила из `facets.json` (дёшево, детерминировано).
2. **LLM-fallback** — если уверенность ниже порога ИЛИ выпало в fallback: один дешёвый вызов (Haiku) с СПИСКОМ категорий таксономии + title/description → классифицирует в существующую категорию ЛИБО возвращает `NEW: <proposed>` (категории нет в таксономии).
3. Под-фасеты (Concern/Format/For) — так же: keyword → LLM-fallback.
4. Кэш классификаций по product_id (sessionless, в SQLite) — не дёргать LLM повторно.
→ Товары известных категорий классифицируются сами; НЕизвестные **всплывают флагом**, а не молча мусорятся.

## 3. PIPELINE HOOK (на СОЗДАНИИ товара)
В `Shopify_Pipeline.ipynb` добавить шаг между Designer и push (или сразу после push):
- `facet_engine.classify()` → проставить теги `Category:/Concern:/Format:/For:/Scent:`;
- `normalize_variant_prices` для этого товара (выровнять к моде/мин);
- привязать к smart-коллекции категории.
→ Новые товары РОЖДАЮТСЯ с фасетами. Фасеты — часть создания, не бэкфилл.

## 4. POST-BATCH ОРКЕСТРАТОР (одна команда после долива)
`pipeline/tools/post_load.py [--new-only|--since TS]` — идемпотентно + инкрементально:
1. `facet_backfill_full.py` (страховка: дотегировать всё, что без фасетов);
2. `compute_facet_counts.py` (пересчёт counts на затронутых нав-коллекциях);
3. `build_seo_collection_map.py` (Shop-by-type: category→SEO-под-коллекции, с дедупом);
4. `build_canonical_map.py` (новые дубли → canonical, недеструктивно);
5. `catalog_health.py` (отчёт + алерты, см. §7).
→ Это формализованный чеклист из CLAUDE.md, свёрнутый в ОДНУ команду. Можно как cron/CI-шаг.

## 5. ONBOARDING НОВОЙ КАТЕГОРИИ (полу-авто, 1 подтверждение)
Когда facet_engine флагует `unclassified`/`NEW:`:
1. `propose_category.py` (LLM) — по группе неклассифицированных товаров предлагает: имя категории + параметры
   (какие Concern/Format/… осмысленны) + keyword-правила + Designer-модули → выдаёт **патч `facets.json`** на ревью.
2. Человек смотрит/правит → апрув (1 клик).
3. Апрув → авто: создаётся smart-коллекция `cat-<x>` (rule `tag=Category:<X>`), категория попадает в фильтры/Shop-by-type,
   парент-маппинг — через оркестратор.
→ Добавить НОВУЮ категорию = подтвердить предложенную запись таксономии. Тема не трогается (см. §6).

## 6. ТЕМА УЖЕ GENERIC (это сильная сторона — менять не нужно)
Ozon-фильтр, Shop-by-type, reveal-анимации — всё **data-driven** (читают теги/метафилды/таксономию).
Новая категория/коллекция рендерится САМА, как только появились данные. Theme-правок на категорию НЕ требуется.

## 7. ВАЛИДАЦИЯ / ГАРД (никаких молчаливых поломок)
`pipeline/tools/catalog_health.py` (расширение catalog_audit) — пост-батч + по расписанию:
- % товаров без `Category:`-тега (цель 100%), % `unclassified` (алерт если > X);
- коллекции без `facet_counts`; битые `canonical`; товары с разъездом цен вариантов;
- битые `image_url` в метафилдах (правило оператора); товары без описания/мусорный product_type.
Алерт (порог превышен) → блок публикации / уведомление. CI-чек перед публикацией.

## 8. ГРАБЛИ → защита (зафиксировано, чтобы не повторять)
- `products_count` в списках ненадёжен → `/products/count.json`.
- `collection.current_tags` пуст на smart → активные фильтры из `request.path`.
- Liquid `for x in EXPR|filter` запрещён → `assign` сначала.
- counts в Liquid по всей коллекции нельзя → метафилд `facet_counts`.
- Новая категория в derive() → LLM-fallback + флаг (а не тихий fallback-мусор).
- flex-лента без `min-width:0` не скроллится; reveal — на IntersectionObserver, не на scroll-check-до-layout.
- Массовые/деструктивные/ценовые записи — за guardrail (явное подтверждение).

## 9. IDEMPOTENCY / СТОИМОСТЬ
- Все скрипты идемпотентны (пишут только изменившееся), инкрементальны (обрабатывают только новый батч).
- LLM-затраты: facet-fallback только для неизвестных (центы); описания уже в пайплайне; оркестратор — Shopify-API (бесплатно).

## 10. ROADMAP (что построить)
- **P0 (фундамент) — ✅ ПОСТРОЕН 2026-06-08:**
  - `taxonomy/facets.json` — единый источник (12 категорий + Format/Concern/For/Scent, keyword-правила, per-category params/modules/collection_handle). Сборка: `taxonomy/tools/build_facets_config.py`.
  - `pipeline/tools/facet_engine.py` — taxonomy-driven `classify()/derive()/to_tags()`. **Word-boundary матчинг** (чинит подстрочные ложняки: `massage`→Anti-aging, `bluetooth`→Oral, `Leather`→Women) + **LLM-fallback (Haiku)** для НЕизвестных категорий → возвращает категорию или флаг `unclassified`/`proposed_category`.
  - `pipeline/tools/gen_facets.py` — теперь COMPAT-ШИМ над facet_engine (единый источник; оригинал в `gen_facets_legacy.py`). Все вызывающие (`facet_backfill_full`, `build_seo_collection_map`, `catalog_audit`) автоматически читают facets.json.
  - `pipeline/tools/post_load.py` — оркестратор: backfill→counts→seo-map→canonical→health одной командой. НЕ включает guardrailed-операции (цены/301).
  - `pipeline/tools/catalog_health.py` — read-only валидатор (coverage/unclassified/engine-drift/counts/canonical/price-variance/hygiene), exit≠0 = pre-publish gate.
  - **Базовый прогон (live, read-only) 2026-06-08:** 3100 товаров · 142 unclassified (4.6%) · engine-drift 329 (−322 ложных / +88 корректных тегов, в т.ч. −184 false Anti-aging) · counts 25/25 · canonical 46/0 битых · price-variance 8.
- **P1 (интеграция):** hook в ноутбук (facet+price на создании) + авто-создание `cat-*` smart-коллекций.
- **P2 (онбординг):** `propose_category.py` + апрув-флоу новой категории.
- **P3 (автоматизация):** post_load как CI/cron-шаг + health-алерты + pre-publish gate.
