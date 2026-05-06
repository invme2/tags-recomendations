# Pipeline Patches

Журнал точечных правок `pipeline/Shopify_Pipeline.ipynb`.

Каждая правка — отдельная запись (см. ADR-003). Никаких ручных правок JSON,
только через `pipeline/tools/apply_patch.py`. Перед опасной правкой —
snapshot в `pipeline/.snapshots/`.

Формат:
```
## YYYY-MM-DD — fix/feat/refactor: короткое описание
Cell: N (название/назначение)
Cell ID: <id из notebook, если стабилен>
Snapshot: pipeline/.snapshots/YYYYMMDD_HHMMSS_before-xxx.ipynb
Что было: <старый код / симптом>
Что стало: <новый код>
Зачем: <причина / тикет / риск регрессии>
Тест: <как убедиться что не сломалось — добавлен тест X / прогнал Y>
Коммит: <hash> (опционально)
```

---

## 2026-05-05 — security: hardcoded secrets → os.environ
Cell: #2 (CONFIG)
Cell ID: 477e495d
Snapshot: pipeline/.snapshots/20260505_103029_before-secret-removal.ipynb

Что было: в config-ячейке захардкожены 6 секретов / PII —
`ANTHROPIC_API_KEY` (sk-ant-...), `SHOPIFY_STORE`, `SHOPIFY_CLIENT_ID`,
`SHOPIFY_CLIENT_SECRET` (shpss_...), `DATAFORSEO_LOGIN` (gmail),
`DATAFORSEO_PASSWORD`.

Что стало: каждое значение заменено на `os.environ["KEY"]` (KeyError при
отсутствии — fail-loud). В начало ячейки добавлен `import os`.

Зачем: GitHub Push Protection заблокировал push коммита `be4dcd7`
(`GH013`, локации `pipeline/Shopify_Pipeline.ipynb:1061` и `:1064`).
По правилам в CLAUDE.md «Соглашения» — секреты только через `os.environ`
и `.env` (в .gitignore). Bypass через UI не использовали — секреты
**убраны**, не обойдены.

Тест: `python pipeline/tools/notebook_smoke.py` → 17 ячеек валидны.
Полный grep по ноутбуку на отпечатки секретов — не найдено.

⚠️ **Действие на стороне пользователя:** ANTHROPIC_API_KEY и
SHOPIFY_CLIENT_SECRET, попавшие в коммит `be4dcd7` (локально, до push),
**рекомендуется отозвать и перевыпустить** в Anthropic Console и
Shopify Partners, потому что они были видны в git-объектах локально и
при заливке файла через UI могли где-то закэшироваться.

Коммит: будет ссылка на новый, без секретов.

---

## 2026-05-06 — feat: modular HTML assembly via page_builder.py + Opus designer
Cells: #2 (CONFIG), #14 (vision prompt), новая cell #13 (page_builder fetch), #15 (writer)
Snapshot: pipeline/.snapshots/20260506_091918_before-modular-html.ipynb

### Что было
Sonnet 4.5 (`MODEL_WRITER`) генерировала всю длинную HTML-презентацию
сама, используя `wa-*` CSS-фреймворк (~3 KB CSS в `WA_CSS_FRAMEWORK`,
inline-инжект). Она же подставляла цвета из Stage 1 (Haiku 4.5) в
inline-стилях. Каждый продукт получал свой полный HTML-блок,
структура страниц могла плавать.

### Что стало
Модульная сборка через `pipeline/page_builder.py`:

1. **Cell #2 (CONFIG):** добавлены `MODEL_DESIGNER = "claude-opus-4-7"`,
   `PAGE_BUILDER_URL` (raw URL `pipeline/page_builder.py` на main),
   `USE_MODULAR_HTML = True` (флаг для быстрого rollback на Sonnet).

2. **Cell #14 (Stage 1 vision prompt):** Haiku теперь возвращает
   `palette: {brand_1, brand_2, brand_3, brand_soft, brand_deep}` —
   5 hex-цветов под `:root` Lumea-шаблона. Старые `accent`/`accent_soft`
   оставлены для backward-compat (используются в fallback и текстовом
   `_build_vision_context`).

3. **Cell #13 (новая, после taxonomy loader):** runtime-fetch
   `page_builder.py` через `urllib.request` + `exec` в namespace.
   Экспортирует `assemble_page`, `MODULE_CATALOG`, `render_badges`.
   Если `USE_MODULAR_HTML=False` — фетч пропускается.

4. **Cell #15 (Stage 4 writer):** обёрнут в `if USE_MODULAR_HTML`:
   - **Modular path:** строится designer-промпт с каталогом 9 модулей
     (kind/description/slots) + palette hint от Haiku. Opus 4.7 возвращает
     один JSON `{design: {layout, palette, slots}, meta: {short_description,
     seo_meta, product_tags}}`. Затем `assemble_page(layout, slots, palette,
     output_format="shopify_fragment")` собирает финальный HTML.
   - **Legacy path:** Sonnet writer без изменений (можно вернуться при
     проблемах через `USE_MODULAR_HTML=False`).
   - Meta-парсинг (`===META_START===` маркеры) выполняется только в legacy
     path; в modular meta уже распарсен из JSON.

### Зачем
- Стабильная структура страниц: одни и те же 4-8 модулей в каноническом
  порядке (hero → intro → story → features → facts → reviews).
- Дизайнерское качество: модули вёрстаны вручную в `docs/claude-prompts/template.html`,
  не галлюцинируются LLM-ом.
- Цвета из фото: Haiku даёт palette hint, Opus уточняет под mood продукта.
- Легко расширять: добавить вариант = одна запись в `_MODULE_HTML` +
  `MODULE_CATALOG` в `page_builder.py`. Никаких правок ноутбука.
- Не ломаем downstream: `assemble_page(output_format="shopify_fragment")`
  выдаёт `<div class="rte wa-page">…</div>`, совместимо с существующей
  `validate_html()`.
- Никаких topbar / footer / shipping / returns в выходе (требование
  пользователя — эти блоки идут от темы Shopify).

### Cost
- Opus 4.7 ≈ 5× Sonnet 4.5 для writer'а. Per-product: ~$0.10 → ~$0.50.
- При проблемах с бюджетом — `USE_MODULAR_HTML = False` возвращает Sonnet.

### Тест
- `python -m pytest pipeline/tests/ taxonomy/tests/` → 53/53 passed
  (включая 23 теста page_builder: catalog, slot substitution, palette
  injection, output_format, anti-invariants no-topbar/footer/shipping).
- `python pipeline/tools/notebook_smoke.py` → 18 ячеек валидны.
- Реальный прогон в Colab — на стороне пользователя, требует обновления
  env-переменных (см. ноутбук cell #2) и merge ветки в main, чтобы
  PAGE_BUILDER_URL разрешался.

### Действия на стороне пользователя
1. Слить ветку `claude/enrich-shopify-taxonomy-kMPmA` в `main` — иначе
   `PAGE_BUILDER_URL` (указывающий на `main`) не найдёт `page_builder.py`.
2. (Опционально) проверить, что тема Shopify уже подключает
   `Inter` + `Fraunces` шрифты через theme.liquid. Если нет — `FONTS_LINK`
   внутри fragment'а их подгрузит.
3. Запустить ноутбук в Colab end-to-end на 1-2 продуктах в dry-run
   (без публикации в Shopify), проверить визуал.

Коммит: следующий после этой записи.

---

## 2026-05-06 — fix(logging): API error messages identify service (Anthropic / DataForSEO) + 401 fail-fast
Cells: #4 (call_claude), #6 (api_post_with_retry)
Snapshot: pipeline/.snapshots/<TS>_before-error-prefixes.ipynb

### Что было
В `call_claude` (Anthropic) и `api_post_with_retry` (DataForSEO) логи ретраев
были одинаково безликие: `[API err 401, retry 1]`, `[Timeout, retry 1/3]`,
`[FAILED: ...]`. На реальном прогоне пользователь не мог понять, какой
именно сервис отвалился (Anthropic / DataForSEO / Shopify).

Дополнительно: 401 (auth-error) ретраился 4 раза подряд без шансов на успех —
ANTHROPIC_API_KEY либо есть, либо нет.

### Что стало
- **`call_claude`** (Anthropic): все retry/error-сообщения с префиксом
  `[Anthropic …]`. На 401/403 — fail-fast (без ретраев) с actionable хинтом
  `check ANTHROPIC_API_KEY in env`.
- **`api_post_with_retry`** (DataForSEO): сервис определяется по URL хосту
  (`api.dataforseo.com → DataForSEO`). На 401 — fail-fast с хинтом
  `check DATAFORSEO_LOGIN/DATAFORSEO_PASSWORD env`. На 402 (баланс) и 403
  — fail-fast с пометкой kind.
- `shopify_gql` уже имел префикс `[Shopify …]` — не трогал.

### Зачем
Сэкономить время диагностики: в выводе сразу видно, у какого сервиса
проблема и что чинить (env-переменная). Авто-ретрай 401 был бессмысленным
(пятикратное повторение auth-fail только тратит время и токены).

### Тест
- `python pipeline/tools/notebook_smoke.py` → 18 ячеек валидны.
- `python -m pytest pipeline/tests/ taxonomy/tests/` → 53/53 passed
  (тесты не зависят от ноутбука, но регресс-проверка инфраструктуры в порядке).

Коммит: следующий после этой записи.

