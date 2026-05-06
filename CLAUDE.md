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
│   ├── taxonomy.json               ← источник истины (765 кластеров, v3.2)
│   ├── schema.json                 ← JSON Schema под реальную структуру (ADR-006)
│   ├── data/
│   │   └── v3.1-README.md          ← оригинальный README пользователя
│   ├── tools/
│   │   ├── validate_taxonomy.py    ← ✅ полная схема + 9 бизнес-правил
│   │   ├── build_taxonomy.py       ← ⏳ stub (NotImplementedError)
│   │   ├── enrich_taxonomy.py      ← ✅ реальный скрипт обогащения через Claude API
│   │   ├── stats.py                ← ⏳ stub
│   │   └── export_to_csv.py        ← ⏳ stub
│   └── tests/
│       └── test_taxonomy.py        ← ✅ синтетика + контрактный тест на реальный taxonomy.json
├── pipeline/
│   ├── Shopify_Pipeline.ipynb      ← ✅ доставлен (17 ячеек, 8 code, ~310KB)
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
- Gap-тест на придуманных продуктах: `python taxonomy/tools/gap_test.py --self-test`
- Gap-тест на твоём каталоге: `python taxonomy/tools/gap_test.py --products catalog.csv --json report.json`

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
- ✅ `taxonomy.json` (790 кластеров: 430 v3.1 approved + 335 v3.2 draft + **25 v3.3 draft, gap-fill итерации 1+2**, 36 sections, 27 personas, 14 intents, 9 demos) валиден против `schema.json`
- ✅ `taxonomy/tools/gap_test.py` — matching тестовых продуктов (или CSV-каталога) против таксономии через cosine; auto-fallback `sentence-transformers/MiniLM` → `sklearn TfidfVectorizer` (sandbox блокирует huggingface.co)
- ✅ `taxonomy/schema.json` отражает реальную структуру (ADR-006, supersedes ADR-005)
- ✅ `taxonomy/tools/validate_taxonomy.py` — JSON Schema + 9 бизнес-правил
  (дубли cluster/persona/intent/demo/section, broken section_id/section_slug/related,
  unknown persona/intent/gender/age, empty embed_text)
- ✅ `taxonomy/tools/enrich_taxonomy.py` — реальный скрипт пользователя (обогащение через Claude API + FAISS-related)
- ✅ `pipeline/Shopify_Pipeline.ipynb` (18 ячеек, +cell для page_builder fetch) проходит `notebook_smoke`. Stage 4 writer теперь имеет два пути: modular (Opus 4.7 picks layout+palette+text → `assemble_page`) и legacy (Sonnet 4.5, фоллбэк через `USE_MODULAR_HTML=False`).
- ✅ `pipeline/page_builder.py` — модульная сборка product-page HTML из 9 модулей (hero1/hero2/m13/m16/m21/m22/m32/m41/m51) с инъекцией 5-цветной палитры. 23 unit-теста (`pipeline/tests/test_page_builder.py`).
- ✅ `pipeline/tools/notebook_smoke.py` — `nbformat.validate` + `ast.parse` + межъячеечная дефинированность только на module-level scope (не лезет в тела функций — иначе 75 false-positive)
- ✅ `pipeline/tools/extract_cells.py`, `apply_patch.py` — работают
- ✅ `tools/health_check.py` — на реальных данных всё зелёное
- ✅ `taxonomy/tests/test_taxonomy.py` — 15/15: синтетика покрывает все классы ошибок + контрактный тест на реальный `taxonomy.json`
- ✅ CI: `validate-taxonomy.yml` + `smoke-pipeline.yml`

## Что СЕЙЧАС сломано / в работе
- ⏳ `taxonomy/tools/build_taxonomy.py`, `stats.py`, `export_to_csv.py` —
  заглушки с `raise NotImplementedError`. Реализуем по запросу.
- ⏳ Gap-analysis ещё не делали — требуется дамп каталога EPROLO или Shopify (см. предложение по `gap_analysis.py`).
- ⏳ В реальном `taxonomy.json` все 783 кластера имеют пустые
  `personas/intents/demos/related/synonyms/title_ru/description/shopify_collection_hints` —
  это работа `enrich_taxonomy.py`. После прогона валидатор должен снова пройти.
- ⏳ 18 новых v3.3-кластеров (gap-fill итерация 1) — `status: draft`,
  ждут ревью пользователем и (после ревью) промоута в `approved`.
- ⏳ Реальный gap-анализ против каталога EPROLO/Shopify ещё не делали —
  нужен дамп каталога. Текущая итерация — только внутренний структурный
  + индустриальные эвристики (см. CHANGELOG раздел «Gap-analysis итерация 1»).
