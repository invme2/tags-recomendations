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

### Notes
- Стартовые файлы пользователя (`taxonomy.json`, `enrich_taxonomy.py`,
  `Shopify_Pipeline_v9_with_taxonomy.ipynb`) **не доставлены** в этой сессии —
  ждём способ передачи. Все тулы корректно репортят отсутствие источника
  вместо тихого падения.
