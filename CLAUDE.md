# Project: tags-recomendations

> Конституция проекта. Эта страница читается ПЕРВОЙ в каждой сессии.
> Если правила здесь и поведение Claude расходятся — правила здесь главнее.

## О проекте
Моно-репо из двух связанных продуктов:

- **A. Taxonomy** (`taxonomy/`) — JSON-база ~765 кластеров для тегирования товаров.
  Источник истины. Лежит в Git, потребляется Shopify-пайплайном по raw-URL.
- **B. Shopify Pipeline** (`pipeline/`) — Jupyter-ноутбук, который скрейпит
  товары EPROLO, генерирует SEO-страницы через Claude API, тегирует по taxonomy
  и заливает в Shopify. **Прод-система. Любая регрессия = потеря денег.**

## Стек
- Python 3.11+
- Jupyter (правки строго через `nbformat`)
- Anthropic SDK (Claude API: обогащение taxonomy + SEO-генерация)
- Shopify GraphQL Admin API
- SQLite (`pipeline.db`)
- FAISS + sentence-transformers (семантический поиск по taxonomy)
- jsonschema (валидация taxonomy)
- pytest (тесты)

## Структура репо
```
tags-recomendations/
├── CLAUDE.md                       ← этот файл, конституция
├── DECISIONS.md                    ← ADR (архитектурные решения)
├── CHANGELOG.md                    ← журнал изменений (Keep a Changelog)
├── TROUBLESHOOTING.md              ← известные проблемы и фиксы
├── README.md                       ← короткий, ссылается сюда
├── .gitignore
├── requirements-dev.txt            ← зависимости тулинга
├── .github/workflows/
│   ├── validate-taxonomy.yml       ← CI: pytest + схема taxonomy
│   └── smoke-pipeline.yml          ← CI: nbformat-валидация ноутбука
├── taxonomy/
│   ├── taxonomy.json               ← источник истины (НЕ доставлен пока)
│   ├── schema.json                 ← JSON Schema (черновая, см. DECISIONS ADR-005)
│   ├── data/                       ← черновые источники (.md, .py)
│   ├── tools/
│   │   ├── validate_taxonomy.py    ← ✅ работает
│   │   ├── build_taxonomy.py       ← ⏳ stub (NotImplementedError)
│   │   ├── enrich_taxonomy.py      ← ⏳ ждём доставки от пользователя
│   │   ├── stats.py                ← ⏳ stub
│   │   └── export_to_csv.py        ← ⏳ stub
│   └── tests/
│       └── test_taxonomy.py        ← ✅ тестирует валидатор на синтетике
├── pipeline/
│   ├── Shopify_Pipeline.ipynb      ← главный артефакт (НЕ доставлен пока)
│   ├── PATCHES.md                  ← журнал точечных правок ноутбука
│   ├── .snapshots/                 ← бекапы перед опасными правками
│   └── tools/
│       ├── notebook_smoke.py       ← ✅ nbformat + ast + межъячейные имена
│       ├── extract_cells.py        ← ✅ .ipynb → .py для чтения
│       └── apply_patch.py          ← ✅ точечный str_replace через nbformat
├── tools/
│   └── health_check.py             ← ✅ общий smoke (taxonomy + notebook)
└── docs/claude-prompts/            ← архив версий bootstrap-промпта
```

## Соглашения
- Стиль: black, line-length 100
- Импорты: stdlib → 3rd-party → local
- Никаких `localStorage` — не работает в Colab
- Правки `.ipynb` — только через `pipeline/tools/apply_patch.py`, никогда вручную в JSON
- Перед опасной правкой ноутбука: snapshot в `pipeline/.snapshots/`
- Каждое архитектурное решение → ADR в `DECISIONS.md`
- Каждый коммит → запись в `CHANGELOG.md`
- Каждая исправленная проблема → запись в `TROUBLESHOOTING.md`
- Один логический сдвиг = один коммит (атомарность)
- Секреты — через `os.environ` и `.env` (в `.gitignore`)
- Прямые правки `main` запрещены, только через PR

## Быстрые команды
- Общий чек: `python tools/health_check.py`
- Валидация taxonomy: `python taxonomy/tools/validate_taxonomy.py`
- Smoke ноутбука: `python pipeline/tools/notebook_smoke.py`
- Тесты: `python -m pytest taxonomy/tests/ -v` (форма `python -m` гарантирует, что pytest подхватит `jsonschema`/`nbformat` из того же интерпретатора)
- Snapshot ноутбука: `cp pipeline/Shopify_Pipeline.ipynb pipeline/.snapshots/$(date +%Y%m%d_%H%M%S).ipynb`
- Установка dev-deps: `pip install -r requirements-dev.txt`

## Стандарт начала сессии
1. `cat CLAUDE.md && git log --oneline -20 && git status`
2. Проговорить состояние пользователю одной фразой
3. Только после этого — задача

## Стандарт конца сессии
1. Обновить раздел «Что СЕЙЧАС работает / сломано» ниже
2. Дописать в `CHANGELOG.md`
3. Если решал проблему → запись в `TROUBLESHOOTING.md`
4. Если архитектурное решение → ADR в `DECISIONS.md`
5. `git add -A && git commit -m "..." && git push -u origin <branch>`

## Что СЕЙЧАС работает (не трогай без причины)
- ✅ Каркас моно-репо и memory-файлы (CLAUDE/DECISIONS/CHANGELOG/TROUBLESHOOTING)
- ✅ `tools/health_check.py` — общий чек, корректно репортит отсутствие источников
- ✅ `taxonomy/tools/validate_taxonomy.py` — JSON Schema + дубли + ссылочная целостность + непустой `embed_text`
- ✅ `pipeline/tools/notebook_smoke.py` — `nbformat.validate` + `ast.parse` + межъячейные имена
- ✅ `pipeline/tools/extract_cells.py` — `.ipynb` → плоский `.py`
- ✅ `pipeline/tools/apply_patch.py` — точечный str_replace через nbformat
- ✅ `taxonomy/tests/test_taxonomy.py` — тесты валидатора на синтетике
- ✅ CI: `validate-taxonomy.yml` + `smoke-pipeline.yml`

## Что СЕЙЧАС сломано / в работе
- ⏳ Стартовые файлы пользователя (`taxonomy.json`, `enrich_taxonomy.py`,
  `Shopify_Pipeline_v9_with_taxonomy.ipynb`, старый `README.md`) **не доставлены**
  в рабочую папку — лежат на Windows-temp у пользователя, Linux-окружению Claude
  недоступны. Ждём способ доставки (коммит с локальной машины / inline / URL).
- ⏳ `taxonomy/schema.json` — **черновая**, написана по описанию из bootstrap-промпта
  (см. ADR-005). Должна быть сверена с реальной структурой `taxonomy.json` и
  при необходимости ужесточена.
- ⏳ `taxonomy/tools/build_taxonomy.py`, `stats.py`, `export_to_csv.py` —
  заглушки с `raise NotImplementedError`. Реализуем по запросу.
- ⏳ `taxonomy/tools/enrich_taxonomy.py` — пока пусто, ждём оригинал от пользователя.
