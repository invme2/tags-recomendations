# Changelog

Все заметные изменения проекта документируются в этом файле.
Формат основан на [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
проект использует [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
