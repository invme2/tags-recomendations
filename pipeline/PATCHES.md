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

Коммит: 2f17678.

---

## 2026-05-06 — feat(prompts): HTML_CLEAN_OUTPUT_RULES для всех HTML-промптов
Cells: #2 (добавлена константа), #4 (collection html), #10 (legacy writer), #15 (modular designer)
Snapshot: pipeline/.snapshots/<TS>_before-clean-rules.ipynb

### Что было
Промпты HTML-генерации не запрещали явно невидимые символы (zero-width
spaces, BOM, directional marks, PUA), AI-водяные атрибуты (`data-ai`,
`data-watermark`), скрытый SEO-стаффинг (off-screen, transparent text,
font-size:0) и homoglyph-подмены. LLM иногда такое генерируют —
особенно при кэшированных system-промптах с инструкциями «отметить» вывод.

### Что стало
В config-ячейке (#2) появилась константа `HTML_CLEAN_OUTPUT_RULES` с двумя
секциями: «Silently remove these characters» (16 классов unicode) и
«NEVER include in output» (12 видов AI-водяных знаков и stealth-content).

Константа подставляется в три prompt'а:
- `generate_collection_html` (cell #4) — короткий collection page description.
- `WRITER_SYSTEM_PROMPT` (cell #10, legacy Sonnet writer).
- `_designer_system` (cell #15, modular Opus designer).

Все три используют конкатенацию `… + HTML_CLEAN_OUTPUT_RULES` — изменение
правил в одном месте автоматически применяется ко всем.

### Зачем
- Защита от AI-watermarking: data-* атрибуты, скрытые комментарии с
  generation context, invisible chars иногда используются как стелс-маркеры
  AI-генерации. Google и другие краулеры могут это распознавать.
- Защита от homoglyph-подмен: модель иногда вставляет кириллические/греческие
  буквы в латинский текст — выглядит идентично, но ломает text-search и
  даёт «mixed-script» флаг в Lighthouse.
- Защита от классического hidden SEO: position:absolute;left:-9999px,
  font-size:0, transparent text — за такое Google штрафует.

### Тест
- `python pipeline/tools/notebook_smoke.py` → 18 ячеек валидны.
- `python -m pytest pipeline/tests/ taxonomy/tests/` → 53/53 passed.
- Реальная проверка эффективности — на стороне пользователя в Colab dry-run:
  открыть выходной HTML в редакторе, искать символы из списка (Python-regex
  `r"[​-‏ -‮⁠-⁯﻿­͏؜᠎]|[-]"`),
  искать атрибуты `data-ai|data-generated|data-watermark|data-model`.
  Если что-то всё-таки проникает — добавим Python-postprocessor в
  `sanitize_html` (defense in depth).

Коммит: 039594d.

---

## 2026-05-06 — fix(designer): Sonnet 4.6 вместо Opus 4.7 + детерминированная SEO-перелинковка
Cells: #2 (MODEL_DESIGNER + cost), #15 (assemble_page interlinks + designer prompt)
File: pipeline/page_builder.py (новая render_collections_section + interlinks param в assemble_page)
Snapshot: pipeline/.snapshots/<TS>_before-model-swap-and-interlinks.ipynb

### Что было — два бага
**Cost.** `MODEL_DESIGNER = "claude-opus-4-7"` (~$15/$75 per M). Per-product
~$0.50, что в 5× дороже legacy Sonnet writer ($3/$15).

**SEO interlinking конфликт.** `get_smart_interlinks()` собирает 4-6 коллекций
для каждого продукта, прокидывает в writer prompt как `interlink_block`.
Legacy `WRITER_SYSTEM_PROMPT` инструктирует Sonnet weave inline + footer
`<a class="wa-link">`. Но мой modular `_designer_system` вообще не упоминал
interlinks → Opus игнорировал коллекции либо вставлял ссылки в P-слоты
произвольно. validate_html() удалял невалидные хэндлы, но не восполнял
отсутствующие → SEO-перелинковка ломалась полностью на modular пути.

### Что стало
**Cost:** `MODEL_DESIGNER = "claude-sonnet-4-6"` (новейший Sonnet, того же
$3/$15). Cost calculation в writer cell обновлён под Sonnet pricing.
Per-product designer cost: ~$0.50 → ~$0.10 (5× экономия). Опционально
можно поднять обратно до Opus, поменяв одну строку.

**Interlinking:** перевёл на детерминированную сборку — без участия LLM:
- `pipeline/page_builder.py`: новая `render_collections_section(interlinks)`
  рендерит pill-кнопки с keyword-rich anchor text (первый из `anchors[]`,
  fallback `title`). class="wa-link" для совместимости с validate_html.
- `assemble_page` принимает `interlinks=` и `interlinks_kicker=` ("Explore
  more" по умолчанию, можно поменять на "См. также" если язык товара RU).
- В cell #15 modular path: `assemble_page(..., interlinks=interlinks)`.
- `_designer_system` промпт обновлён: «DO NOT include /collections/ links
  in any slot text — Related-collections appended automatically». Меньше
  ошибок и токенов в ответе.

Преимущества детерминизма:
- Ссылки **гарантированно** есть, если interlinks не пустой.
- Все хэндлы — из реально созданных Shopify коллекций (validate_html не
  будет их удалять).
- Не зависит от настроения модели и не «галлюцинируется».

### Тест
- pipeline/tests/test_page_builder.py: +9 тестов (32/32 passed) — empty
  interlinks, anchor text fallback, dedup handles, blank handle skip,
  custom kicker, append after modules, no duplication при повторных
  вызовах.
- python -m pytest pipeline/tests/ taxonomy/tests/ → 62/62 passed.
- python pipeline/tools/notebook_smoke.py → 18 ячеек валидны.

### Что не задето
- Legacy `WRITER_SYSTEM_PROMPT` (Sonnet 4.5) — продолжает плести
  interlinks inline через свой собственный flow. Не трогал — рискованно
  ломать рабочий код, у пользователя есть rollback через `USE_MODULAR_HTML=False`.
- `get_smart_interlinks()` — без изменений, тот же формат данных.
- `ALL_SHOP_COLLECTIONS` фетч и Stage 1-9 SEO — не задеты.

Коммит: 655149d.

---

## 2026-05-06 — fix(urls): TAXONOMY_URL placeholder + private-repo support
Cells: #2 (GITHUB_BRANCH/REPO/TOKEN), #12 (taxonomy fetch), #13 (page_builder fetch)
Snapshot: pipeline/.snapshots/<TS>_before-taxonomy-url-fix.ipynb

### Что было — три связанных бага
1. **TAXONOMY_URL placeholder.** В config-ячейке оставался дефолт
   `https://raw.githubusercontent.com/YOUR-ORG/taxonomy/main/taxonomy.json`,
   что давало 404 при первом запуске ноутбука.
2. **PAGE_BUILDER_URL хардкодил `main`**, а page_builder.py пока живёт
   только в feature-ветке. После merge — пришлось бы править в двух местах.
3. **Репо приватный** на real github.com (api.github.com отдаёт 403). Без
   token'а Colab не может фетчить ни taxonomy.json, ни page_builder.py.

### Что стало
- `GITHUB_BRANCH` и `GITHUB_REPO` — две переменные в config-ячейке.
  `TAXONOMY_URL` и `PAGE_BUILDER_URL` собираются из них через f-string.
  После merge feature → main: одна правка `GITHUB_BRANCH = "main"`.
- Опциональный `os.environ["GITHUB_TOKEN"]` в обоих fetch-ячейках:
  если установлен — добавляется `Authorization: Bearer …` header. Без него
  ноутбук работает только для public-репо.
- Понятные RuntimeError'ы на 404: говорят что чинить (ветка / приватность
  / token), вместо безликого `HTTPError 404 Client Error: Not Found`.
- Импорт `urllib.error` добавлен в page_builder-fetch для exception-обработки.

### Действие на стороне пользователя
Один из двух вариантов (любой работает):

**A. Сделать репо публичным** (проще всего):
   github.com/invme2/tags-recomendations → Settings → Change visibility → Public.
   После этого никаких токенов, raw URL работает из коробки.

**B. GitHub token в Colab**:
```python
import os
from google.colab import userdata
os.environ["GITHUB_TOKEN"] = userdata.get("GITHUB_TOKEN")
```
   Token: Settings → Developer settings → Personal access tokens →
   Fine-grained → выбрать репо → Read access на Contents.

После merge feature-ветки в main: `GITHUB_BRANCH = "main"` в config-ячейке.

### Тест
- `python pipeline/tools/notebook_smoke.py` → 18 ячеек валидны.
- `python -m pytest pipeline/tests/ taxonomy/tests/` → 62/62 passed.
- В этом контейнере real github.com выдаёт 403 на наш приватный репо,
  поэтому full E2E test возможен только из Colab после действия (A) или (B).

Коммит: b10332a.

---

## 2026-05-06 — fix(schema): primary_collection column + Cell 6 defensive SELECT
Cells: #2 (Cell 1 — ALTER list), #15 (Cell 6 — Product Loop)
Snapshot: pipeline/.snapshots/<TS>_before-primary-collection-fix.ipynb

### Что было — пре-existing баг
Cell 1 в migration-блоке `ALTER TABLE products ADD COLUMN ...` НЕ добавлял
`primary_collection`, хотя:
- Cell 1 Excel-parser пишет: `UPDATE products SET primary_collection=?`
  (в try/except — тихо падает).
- Cell 3 Stage 4 SEO пишет туда же (тоже try/except).
- Cell 6 fallback ЧИТАЕТ: `SELECT primary_collection FROM products...`
  и НЕ обёрнут в try/except → крашит loop.

В предыдущих запусках это «работало», потому что junction-таблица
`product_collections` была заполнена и до fallback-ветки не доходило.
В свежей сессии пользователя:
  Product links: 0 | Keywords saved: 26
  ...
  ERROR: no such column: primary_collection
junction пустой → fallback срабатывает → крах на отсутствующем столбце.

### Что стало
1. В Cell 1 ALTER-list: добавлен `'primary_collection'` → столбец
   создаётся при первом запуске свежего ноутбука.
2. В Cell 6 SELECT обёрнут в try/except — safety net на случай отсутствия
   столбца в legacy DB (которая была создана до этого фикса).

### Действие пользователя для уже работающей сессии
В Colab остановить runtime + выполнить разовый patch-cell с:
  ALTER TABLE products ADD COLUMN primary_collection TEXT
  + relink products → collections через Excel re-parsing
  + сброс status='error' (см. чат-сообщение от 2026-05-06).

### Тест
- python pipeline/tools/notebook_smoke.py → 18 ячеек валидны.
- python -m pytest pipeline/tests/ taxonomy/tests/ → 62/62 passed.

Коммит: 1d489fa.

---

## 2026-05-06 — chore(models): bump to latest Anthropic model IDs
Cells: #2 (Cell 1 — CONFIG), #4 (Cell 2 — Helpers)
Snapshot: pipeline/.snapshots/<TS>_before-model-bump.ipynb

### Что было
- `MODEL_WRITER = "claude-sonnet-4-5-20250929"` (Sonnet 4.5 — устарел).
- `MODEL = "claude-opus-4-6"` в Cell 4 для `call_claude` (SEO-категоризация).
  Fallback при ошибке: `claude-sonnet-4-5-20250929` (тоже устарел).

### Что стало
Все ссылки на модели приведены к актуальным ID:
- `MODEL_VISION   = "claude-haiku-4-5-20251001"` (без изменений — уже актуальный).
- `MODEL_WRITER   = "claude-sonnet-4-6"` (был 4.5).
- `MODEL_DESIGNER = "claude-sonnet-4-6"` (без изменений).
- `MODEL`         в Cell 4: `"claude-opus-4-7"` (был 4.6).
- Fallback в Cell 4: `"claude-sonnet-4-6"` (был 4.5).

### Зачем
Sonnet 4.6 и Opus 4.7 — последние Claude-модели по состоянию на январь 2026
(см. system prompt в Claude Code). Старые ID продолжают работать, но без
улучшений последних поколений.

### Pricing impact
Без изменений: Sonnet 4.5 и 4.6 имеют одинаковую цену ($3/$15 per M).
Opus 4.6 и 4.7 — также одинаковая ($15/$75 per M).

### Тест
- python pipeline/tools/notebook_smoke.py → 18 ячеек валидны.
- python -m pytest pipeline/tests/ taxonomy/tests/ → 62/62 passed.

Коммит: edf11dd.

---

## 2026-05-06 — feat(ux): RESET_DB flag вместо интерактивного y/n prompt
Cell: #2 (CONFIG)
Snapshot: pipeline/.snapshots/<TS>_before-reset-flag.ipynb

### Что было
В Cell 1 при наличии данных в DB шёл `input('Upload new files? (y=reset / Enter=continue): ')`.
Интерактивный prompt в Colab требует кликать в input-field, неудобно при
повторных прогонах. Пользователь хотел явный флаг.

### Что стало
В config-ячейке добавлен булев-флаг:
```python
RESET_DB = False  # True = wipe DB before run, False = continue/resume
```

Логика:
- `n_prods > 0 and RESET_DB` → wipe всё и upload свежие файлы.
- `n_prods > 0 and not RESET_DB` → continue с существующими данными (resumable).
- `n_prods == 0` → upload свежие файлы (как и было).

Никакого input() — флаг переключается одной строкой в начале CONFIG-ячейки.

### Тест
- python pipeline/tools/notebook_smoke.py → 18 ячеек валидны.

Коммит: следующий после этой записи.

---

## 2026-05-26 — fix(pipeline): EPROLO storage_state + redirect guard (Bug A)
Cell: #4 (Cell 2 — Helpers, `get_shared_browser_ctx` + `scrape_eprolo`)
Cell ID: `b810afd7`
Snapshot: `pipeline/.snapshots/20260526_144444_before-bug-a-storage-state.ipynb`

### Что было — продолжение Bug A
TROUBLESHOOTING #002 + commit `ba799f3` добавили только частичный defense
(hard-fail на marketing-title в `validate_scrape`). Pipeline по-прежнему
открывал EPROLO незалогиненным → 100% товаров терялись на скрейпе.

### Что стало
**Op 1 — `get_shared_browser_ctx` (Cell 2):** перед `new_context()`
читает `EPROLO_STATE_FILE` env var. Если файл существует — передаёт
`storage_state=...`. Иначе печатает предупреждение. Без правки сигнатуры
функции, чтобы не задеть call-sites.

```python
_ctx_kwargs = {"user_agent": "..."}
_state_file = os.environ.get("EPROLO_STATE_FILE", "")
if _state_file and os.path.exists(_state_file):
    _ctx_kwargs["storage_state"] = _state_file
    print(f"  ⚙ EPROLO session loaded from {_state_file}")
elif _state_file:
    print(f"  ⚠ EPROLO_STATE_FILE={_state_file} doesn't exist — Bug A risk")
else:
    print(f"  ⚠ EPROLO_STATE_FILE not set — Bug A risk (unauthenticated session)")
_PW_STATE["ctx"] = await _PW_STATE["browser"].new_context(**_ctx_kwargs)
```

**Op 2 — `scrape_eprolo` (Cell 2):** defense-in-depth — после `page.goto`
проверяет, осталась ли `page.url` в `/app/product/`. Если EPROLO
редиректнул на home/signup (товар удалён / session expired) — ранний
выход с пустым `result['title']`, который `validate_scrape` ловит как
`empty/short title` → `status='error'`, без push в Shopify.

```python
await page.goto(url, wait_until="networkidle", timeout=60000)
_final_url = page.url or ""
if "/app/product/" not in _final_url:
    result["_redirect_target"] = _final_url
    print(f'    ⚠ EPROLO redirect: {url[:60]} -> {_final_url[:60]}')
    await page.close()
    return result
await page.wait_for_timeout(5000)
```

### Связанные новые tools
- `pipeline/tools/eprolo_login.py` — headed Chromium для ручного логина;
  периодически сохраняет state в `pipeline/.eprolo_state.json` пока
  пользователь не закроет окно.
- `pipeline/tools/eprolo_verify_scrape.py <url>` — проверяет, что
  сохранённый state работает: scrape возвращает реальный product title,
  не marketing-redirect.

### Действия на стороне пользователя
1. Установить playwright и chromium локально (на Windows):
   `pip install playwright python-dotenv && python -m playwright install chromium`.
2. Один раз залогиниться: `python pipeline/tools/eprolo_login.py` →
   откроется headed Chromium → login → закрыть окно.
3. Положить в `.env` (gitignored): `EPROLO_STATE_FILE=<абсолютный путь
   к pipeline/.eprolo_state.json>`.
4. Verify: `python pipeline/tools/eprolo_verify_scrape.py <product-url>`
   → должно вернуть `RESULT: Real product page reached`.
5. Перезапустить ноутбук — `get_shared_browser_ctx` подхватит state.
   В логах должно появиться `⚙ EPROLO session loaded from ...`.

### Тест
- `PYTHONIOENCODING=utf-8 python pipeline/tools/notebook_smoke.py` →
  «Notebook валиден. Ячеек: 17 (code: 8).»
- `python -m pytest pipeline/tests/ -q` → **566 passed**.
- Manual verify через `eprolo_verify_scrape.py`: 2/3 URL'а из тестового
  батча — реальный product page; 3-й (OceAura body glitter) — товар
  удалён с EPROLO, redirect на home корректно ловится Op 2 + Op 1 из
  commit `ba799f3` (`marketing_page`).

Коммит: следующий после этой записи.


