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
- **ФОТО / МЕДИА-ОПЕРАЦИИ (правило оператора 2026-06-02): после ЛЮБОЙ замены медиа товара (загрузка фото-паков, замена карусели, реуплоад) ВСЕГДА сразу проверять битые `image_url` в метафилдах.** Замена карусели удаляет старые галерейные медиа, на которые ссылаются секции (features/story и т.п.) → 404. Интейк-тул `pipeline/tools/process_photo_intake.py` делает авто-репар после загрузки; ручная проверка/ремонт — `pipeline/tools/fix_broken_metafield_images.py`. Лишние inline-фото (больше брифов) авто-размещаются в lifestyle_gallery (`place_orphan_photos.py`). Фото-паки кидать в `pipeline/runs/photo_intake/`, блэклист по SHA-256 (`_processed.json`) защищает от повторов. Маппинг архив→товар: slug имени архива == handle товара.
- **🖼 ФОТО В МЕТАФИЛДАХ — НЕ УДАЛЯТЬ (правило оператора 2026-06-06): дизайнерские метафилды содержат ссылки на фото (`custom.hero.image_url`, `custom.features[].image_url`, `custom.story` chapters image_url, и т.п.), которые лежат в Shopify Files (`cdn.shopify.com/s/files/...`).** НИКОГДА не удалять эти Files/фото и не чистить метафилды с фото. При ЛЮБОЙ медиа-операции (замена галереи, intake, cleanup Files, удаление метафилдов) — сначала собрать все `image_url` из `product.metafields.custom.*` и исключить их из удаления. Vibe-страница товара (`sections/vibe-product.liquid`) рендерит эти фото как `background-image` — read-only, не трогает источник. Если фото метафилда пропадёт — секция покажет пустой блок. Проверка битых: `pipeline/tools/fix_broken_metafield_images.py`.
- **🧠 ПЕРСОНАЛИЗИРОВАННОЕ РАНЖИРОВАНИЕ НА ГЛАВНОЙ (правило оператора 2026-06-06): НЕ ЛОМАТЬ умный фид.** Движок — `assets/personalized-feed.js` (65KB, клиентский скоринг: W_VIEW=4 / feed-click=1 / cart, time-decay по `lastSeen`, cold-start ×3 первые 3 клика, jitter 0.12; бакеты products/types×0.8/**tags×0.45**/collections×0.9/categories-иерархия) + `sections/personalized-feed.liquid` (отдаёт fallback-JSON в `<script type="application/json" data-personalized-feed-fallback>`, грид, `data-*`). Профиль интересов — в `sessionStorage`/`localStorage`. **Опасные зоны при редизайне (Vibe Phase 2+):** (1) не удалять/переименовывать `data-personalized-feed-fallback` и любые `data-*` атрибуты, которые читает JS; (2) не менять разметку `snippets/card-product.liquid`, на которую вешаются клики/сигналы; (3) не вырезать `tags`/`type`/`collections`, прокинутые в fallback-JSON (это входы скоринга); (4) не трогать ключи storage. Ре-скин — только цвета/шрифты/отступы, контракт данных не трогать. Секция на главной = `personalized_feed_cqj9Ri`. (Примечание: `assets/personalized-feed copy.js` — неиспользуемый дубль, не трогать без отдельного запроса.)
- **🖼 КАРТОЧКА ТОВАРА В КОЛЛЕКЦИЯХ (правило оператора 2026-06-06): при редизайне/ре-скине (Vibe Phase 2+) НЕ ЛОМАТЬ листалку фото при наведении** (`pcard-carousel`: `.pcard-carousel__track` + слайды `position:absolute;inset:0` с opacity-свопом + JS-маунт). НИКОГДА не менять селекторы `.pcard-carousel*` (позиционирование/opacity/слайды/дотсы) и не трогать монтирующий JS. **И всегда оставлять ~2px отступа фото от подложки карточки**: padding на `.product-card__image-wrapper` (media-обёртка) + прозрачный фон, чтобы подложка просвечивала рамкой вокруг фото. Реализация — в `snippets/wanelo-vibe-tokens.liquid` (НЕ в core `theme.css`). Любую правку карточки проверять ховером (фото листается) до коммита.
- **⚠️ ВАРИАНТ-ФОТО (правило оператора 2026-06-05): при замене медиа товара (загрузчик архивов / carousel REPLACE) НЕ УДАЛЯТЬ медиа, привязанные к вариантам (`variant.featuredImage`/`mediaId`) — иначе ломается переключение фото при выборе варианта (Color/Style).** Перед REPLACE собрать список variant-assigned mediaId и исключить их из удаления (либо после реуплоада переназначить). Пер-вариантные фото берутся из `scrape_json.variants[]._value_photos`; ретрофит — `pipeline/tools/retrofit_variant_images.py`.
- **ДУБЛИ ТОВАРОВ: дедуп по нормализованному `source_url`** (режется под-суффикс `-N`: `--1709-1`→`--1709`, EPROLO-перелистинги одного товара). Тул `pipeline/tools/delete_duplicate_products.py`. Пайплайн нормализует source_url при хранении + в дедуп-проверке.
- **ЛЕДЖЕР ОБРАБОТАННЫХ CSV: `pipeline/PROCESSED_CSVS.md`** — какие категории уже залиты (DONE) и что осталось (PENDING). ОБНОВЛЯТЬ после завершения каждой категории (перенести из PENDING в DONE). Проверять перед запуском новой категории, чтобы не залить дважды. Машинный ledger — `pipeline/tools/csv_ledger.py` → `runs/.csv_ledger.json` (gitignored).
- Правки `.ipynb` — только через `pipeline/tools/apply_patch.py`, никогда вручную в JSON
- Перед опасной правкой ноутбука: snapshot в `pipeline/.snapshots/`
- Каждое архитектурное решение → ADR в `DECISIONS.md`
- Каждый коммит → запись в `CHANGELOG.md`
- Каждая исправленная проблема → запись в `TROUBLESHOOTING.md`
- Один логический сдвиг = один коммит (атомарность)
- Секреты — через `os.environ` и `.env` (в `.gitignore`)
- Прямые правки `main` запрещены, только через PR
- **МЕДИА-ГЕНЕРАЦИЯ (правило оператора 2026-05-29): сайт СВЕТЛЫЙ — НИКОГДА не использовать чёрный/тёмный фон ни в генерации изображений, ни в видео.** Фоны только светлые/белые/пастельные/воздушные при дневном свете. Видео-промпты строить через `pipeline/tools/video_prompts.py` (ротация светлых сцен + light-guard). Видео-стандарт: 8 роликов БЕЗ Unboxing (модель выдумывает содержимое коробки), Hyper Motion=`product_showcase` всегда index 0 (верх). Водяной знак «wanelo.com» лёгкий+движущийся, апскейл до 1080p, self-host на Shopify Files.

## 🗂 КАТАЛОГ / ФАСЕТЫ / ФИЛЬТРЫ (Ozon-слой) — операционка (2026-06-07)
Storefront-фильтры и навигация построены на СЛОЕ ТЕГОВ поверх товаров (НЕ на Search & Discovery — его конфиг недоступен через Admin API). Движок фасетов: единый источник `taxonomy/facets.json` → исполняется `pipeline/tools/facet_engine.py` (`gen_facets.py` теперь шим над ним) → 12 категорий + Concern/Format/For/Scent. **Новая категория = +1 запись в facets.json** (keyword-правила) ИЛИ LLM-fallback флагует её `unclassified` (не молчит).

**⚠️ ГЛАВНОЕ ПРАВИЛО ОПЕРАТОРА: после загрузки ЛЮБЫХ новых товаров — ОДНА команда (иначе новые товары НЕ попадут в фильтры/«Shop by type» и поедут с SEO-проблемами):**
```
python pipeline/tools/post_load.py --llm --seo     # ПОЛНАЯ гигиена: facets+counts+maps+canonical + SEO title/desc + health
python pipeline/tools/post_load.py --health-only   # только read-only валидация (CI/preview gate, без записи)
```
`post_load.py` идемпотентно сворачивает скрипты + health-чек. Флаги: `--llm` (LLM-rescue неизвестных категорий), `--seo` (заполнить пустые `seo.title`/`seo.description`). Что внутри (можно и по-отдельности):
1. `facet_backfill_full.py` — теги `Category:/Concern:/Format:/For:/Scent:` всем товарам (PUT только изменившихся).
2. `compute_facet_counts.py` — `custom.facet_counts` на 25 smart-коллекциях (Ozon-счётчики).
3. `build_seo_collection_map.py` — shop-метафилд `custom.category_collections` (Shop-by-type + дедуп).
4. `build_canonical_map.py` — shop-метафилд `custom.canonical_map` (недеструктивный дедуп).
5. `catalog_health.py` — read-only: coverage/unclassified/engine-drift/counts/canonical/price-variance/hygiene, exit≠0 = gate.
- `post_load.py` НЕ запускает guardrailed-операции (нормализация цен вариантов, 301-дедуп) — только по явной отмашке.
- ⚠️ Движок перешёл на **word-boundary матчинг** (facet_engine) — чинит подстрочные ложняки (`massage`→Anti-aging, `bluetooth`→Oral). Первый `facet_backfill_full` после этого перетегирует ~329 товаров (−322 ложных/+88 корректных). Оригинальные хардкод-правила — в `gen_facets_legacy.py`.

**🆕 ОНБОРДИНГ НОВОЙ КАТЕГОРИИ (3 шага, ~5 мин):**
1. Добавить запись в `taxonomy/tools/build_facets_config.py` (CATS): имя, keyword-список (специфичные термины, проверить что не цепляют существующее — read-only скан `classify(...,use_llm=False)` по каталогу), cluster-ключи, params, modules. Порядок важен (специфичные категории ВЫШЕ общих). → `python taxonomy/tools/build_facets_config.py`.
2. Создать smart-коллекцию с правилом `tag equals Category:<Имя>` (можно `published:false` пока 0 товаров). Handle = bare slug (`sexual-wellness`).
3. Загрузить товары → `python pipeline/tools/post_load.py` (тегирование + counts + maps + health). Опубликовать коллекцию + добавить в header-меню (ручной брендинг-шаг).
- Движок сам флагует неизвестные категории (`catalog_health.py` → `classification_coverage` + `proposed_category`), а LLM-rescue (`facet_engine.classify(use_llm=True)`) либо относит в существующую, либо предлагает имя новой.
- ✅ Онбоарднута **Sexual Wellness** (2026-06-08): движок (первой в order, чистые adult-ключи, 0 ложных среди 3100) + коллекция `sexual-wellness` (unpublished, id 365217808562). Готова принять товары.
- Все правки темы — через `pipeline/tools/theme_edit.py` (token/main_theme_id/fetch/upload/snapshot); published theme = 155750138034. Snapshot перед каждой правкой. НЕ `shopify theme push/publish/delete`.

**🧱 ГРАБЛИ (НЕ наступать повторно):**
- `products_count` в `*_collections.json` (список) НЕНАДЁЖЕН (отдаёт None/0) → реальный счёт только `/products/count.json?collection_id=`.
- `collection.current_tags` ПУСТ на smart-коллекциях → активные фильтры детектить из `request.path` (split '/', tag-сегмент `pp[3]`, split '+', сравнивать по `handleize`).
- Legacy tag-filtering `/collections/<handle>/<tag>` (и `tag1+tag2` для AND) РАБОТАЕТ без S&D (проверено 427→146). На этом построены фильтры.
- Счётчики у значений фасета НЕЛЬЗЯ посчитать в Liquid по всей коллекции (`collection.products` = только текущая страница) → предвычислять в метафилд `custom.facet_counts`.
- Liquid `{% for x in EXPR | filter %}` — ЗАПРЕЩЕНО (422 при upload). Сначала `{% assign a = EXPR | filter %}`, потом `for x in a`.
- Доминантная категория коллекции для «Shop by type»: сначала искать коллекцию в `category_collections` (авторитетно), фоллбэк — Category-тег с макс. `facet_counts`, иначе первый.
- CSS: flex-элемент со `overflow-x:auto` НЕ скроллится без `min-width:0` (раздувается под контент) → горизонтальные ленты (`.fseo__row`, чипсы) обязаны иметь `min-width:0` + `touch-action:pan-x`.
- `backdrop-filter: url(#svgTurbulence)` на липком хедере = жёсткий scroll-jank → отключать warp, держать только лёгкий `blur()`.
- Скоупить глобальные CSS-правила через `:where(.vibe-home) ...` (специфичность 0,0,x — не перебивает компонентные классы вроде `.fpcard__add`).
- ⚠️ Программный `window.scrollTo/scrollBy` через CDP/Playwright НЕ шлёт scroll-событий → инфинити/мобильные ленты проверять РЕАЛЬНЫМ колесом (computer.scroll) или прямым вызовом, не синтетическим скроллом в eval.
- Python 3.11: бэкслеш в выражении f-string = SyntaxError (`f"{x[\"k\"]}"`) → использовать `%`-форматирование или одинарные кавычки внутри.
- Массовые/деструктивные операции (unpublish/301/удаление коллекций, запись цен) — guardrail блокирует без ЯВНОЙ отмашки; rel=canonical / дедуп-в-навигации — недеструктивные альтернативы.
- Бесконечная лента карточек: после append новых `.fpcard` — `document.dispatchEvent(new CustomEvent('shopify:section:load'))` чтобы переинициализировать hover-карусель `.vpc` (vibe.js слушает это событие).

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
- ✅ **EPROLO storage_state + redirect guard (Bug A full fix, 2026-05-26).** `get_shared_browser_ctx` подгружает state из `EPROLO_STATE_FILE` env var, `scrape_eprolo` бьёт `_redirect_target` и ранний return когда `/app/product/` не в финальном URL. Новые tools: `pipeline/tools/eprolo_login.py` (одноразовая ручная авторизация в headed Chromium) + `eprolo_verify_scrape.py` (smoke-проверка). Эмпирически подтверждено на 3 URL'ах. См. TROUBLESHOOTING #004.
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
- ✅ **Bug A — EPROLO redirects (FIXED 2026-05-26).** Полное решение
  через storage_state + redirect-guard, см. блок выше. Пользователь
  обязан один раз залогиниться через `eprolo_login.py` и держать
  `EPROLO_STATE_FILE` в `.env`.
- 🟡 **Bug B — пустые `namespace:custom` метафилды у созданных товаров.**
  Гипотезы из HANDOFF (`shpss_*` vs `shpat_*`) и моя ранняя
  («отсутствует `write_metafields` scope») **опровергнуты эмпирически
  2026-05-26**: OAuth flow работает (Cell 2 корректно обменивает
  `shpss_*` на `shpat_*` TTL 24h), у app `EproloImages` все 9 essential
  scopes присутствуют (`currentAppInstallation.accessScopes`), пустая
  `metafieldsSet` мутация даёт 200 OK. Реальная причина пока неизвестна
  — ждём verbose-логи `4927a82` от прогона на 1-2 реальных EPROLO URL.
- 🟡 **Cleanup мусорных Shopify-товаров** — `gid://shopify/Product/8889396002994`
  и `gid://shopify/Product/8889396265138`. Удалить вручную или через
  Admin API после получения корректного токена. После — откат status
  в `pipeline.db` (SQL в `HANDOFF.md` секция 1).
- 🟡 **Secrets rotation.** Пользователь засветил Anthropic / Shopify /
  OpenAI / DataForSEO ключи в чат-логе. Должны быть отозваны и
  перевыпущены. См. `HANDOFF.md` секция 4.
