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
