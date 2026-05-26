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
- ✅ Каркас моно-репо и memory-файлы (CLAUDE/DECISIONS/CHANGELOG/TROUBLESHOOTING/HANDOFF)
- ✅ `taxonomy.json` (790 кластеров: 430 v3.1 approved + 335 v3.2 draft + **25 v3.3 draft, gap-fill итерации 1+2**, 36 sections, 27 personas, 14 intents, 9 demos) валиден против `schema.json`
- ✅ `taxonomy/tools/gap_test.py` — matching тестовых продуктов (или CSV-каталога) против таксономии через cosine; auto-fallback `sentence-transformers/MiniLM` → `sklearn TfidfVectorizer` (sandbox блокирует huggingface.co)
- ✅ `taxonomy/schema.json` отражает реальную структуру (ADR-006, supersedes ADR-005)
- ✅ `taxonomy/tools/validate_taxonomy.py` — JSON Schema + 9 бизнес-правил
  (дубли cluster/persona/intent/demo/section, broken section_id/section_slug/related,
  unknown persona/intent/gender/age, empty embed_text)
- ✅ `taxonomy/tools/enrich_taxonomy.py` — реальный скрипт пользователя (обогащение через Claude API + FAISS-related)
- ✅ `pipeline/Shopify_Pipeline.ipynb` (17 ячеек, 8 code, ветка `apple-design-rounds-5-6`) проходит `notebook_smoke`. Pipeline: Strategy(Opus 4.7) → Designer(Sonnet 4.6, выдаёт **до 35 JSON-секций** с FILL/SKIP per category) → Shopify push (метафилды + EPROLO gallery).
- ✅ Theme: **35 storefront-метафилдов** (round 1-4 + round 5 +6 +round 6 +8) + 2 admin-only (`photo_pack` ZIP, `source` EPROLO origin record) = 37 total. Файлы темы в `pipeline/theme_assets/` (Apple aesthetic: 1 master section + 35 snippets + wanelo.css ~65KB + wanelo.js). Snippets с пустым метафилдом скипаются в Liquid.
- ✅ `pipeline/tools/notebook_smoke.py` — `nbformat.validate` + `ast.parse` + межъячеечная дефинированность только на module-level scope (не лезет в тела функций — иначе 75 false-positive)
- ✅ `pipeline/tools/extract_cells.py`, `apply_patch.py` — работают
- ✅ `tools/health_check.py` — на реальных данных всё зелёное
- ✅ `taxonomy/tests/test_taxonomy.py` — 15/15: синтетика покрывает все классы ошибок + контрактный тест на реальный `taxonomy.json`
- ✅ `pipeline/tests/` — **566 passed** (на ветке `apple-design-rounds-5-6` после Round 5+6).
- ✅ CI: `validate-taxonomy.yml` + `smoke-pipeline.yml`
- ✅ **`validate_scrape` hard-fail на EPROLO marketing-page redirects** (`'EPROLO -' / 'Sign Up' / 'Sign In' / 'Log In' / 'Login' / 'Dropshipping Supply' / 'All-in-One Dropshipping'` в title → status=error, не пушится в Shopify).
- ✅ **Verbose metafieldsSet diagnostics** — top-level GraphQL errors + per-input key/type/value_len + до 10 userErrors с code/message при `0/N written`.

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
- 🔴 **Bug A — EPROLO redirects на signup без залогиненной сессии.**
  Код-defense есть (marketing_page hard-fail), но pipeline сейчас фейлит
  100% товаров. Нужен Playwright `storage_state.json` после логина
  пользователя в EPROLO. **См. `HANDOFF.md` секцию 1.**
- 🔴 **Bug B — метафилды пусто в Shopify Admin у уже созданных
  товаров.** Корневая причина не подтверждена (нет логов с новой
  диагностикой). Гипотеза №1: токен `shpss_*` вместо `shpat_*`. Нужен
  следующий прогон с verbose-логом. **См. `HANDOFF.md` секцию 1.**
- 🟡 **Cleanup мусорных Shopify-товаров** — `gid://shopify/Product/8889396002994`
  и `gid://shopify/Product/8889396265138`. Удалить вручную или через
  Admin API после получения корректного токена. После — откат status
  в `pipeline.db` (SQL в `HANDOFF.md` секция 1).
- 🟡 **Secrets rotation.** Пользователь засветил Anthropic / Shopify /
  OpenAI / DataForSEO ключи в чат-логе. Должны быть отозваны и
  перевыпущены. См. `HANDOFF.md` секция 4.
