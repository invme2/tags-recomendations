# HANDOFF — приём смены для следующего ИИ-агента

> Этот файл читай **сразу после `CLAUDE.md`**.
> Дата составления: 2026-05-26.  Активная ветка: `apple-design-rounds-5-6`.

---

## TL;DR за 30 секунд

Проект Wanelo (Shopify-дропшиппинг через EPROLO) в состоянии: **сборка
кода готова, но реальный прогон pipeline на проде только что выявил два
прод-бага.** Один починен в коде, второй — диагностика добавлена, нужен
повторный запуск. Плюс срочное cleanup-действие в магазине пользователя.

Следующий шаг — **поднять pipeline локально у пользователя на Windows**
(EPROLO требует залогиненной сессии, Colab без cookies редиректит на
маркетинг-страницу).

---

## 1. Прод-баги в работе

### Bug A — EPROLO редиректит на signup без логина (📌 ROOT CAUSE)

**Симптом.** Все 11 товаров последнего прогона получили title
`"EPROLO - All-in-One Dropshipping Supply Chain Platform"` или
`"Sign Up -EPROLO"` вместо реальных названий. В Shopify создались два
мусорных продукта:

- `gid://shopify/Product/8889396002994` ("Sign Up -EPROLO")
- `gid://shopify/Product/8889396265138` ("EPROLO - All-in-One...") —
  товары [3..11] перезаписали друг друга через тот же handle.

**Корневая причина.** `scrape_eprolo` (Cell 2) открывает страницу
Playwright'ом без cookies. EPROLO для незалогиненных редиректит
product-URL на signup/home. Скрейпер берёт `<h1>` этой страницы и
успешно сдаёт его дальше по pipeline'у.

**Что уже сделано в коде** (коммит `ba799f3`):
- `validate_scrape` теперь распознаёт известные маркетинг-тайтлы как
  hard-fail (`'EPROLO -' / 'Sign Up' / 'Sign In' / 'Log In' / 'Login' /
  'Dropshipping Supply' / 'All-in-One Dropshipping'`).
- Cell 6 при `marketing_page` сразу ставит `status='error'` и **не**
  пушит товар в Shopify.

**Что ещё нужно** (НЕ сделано):
1. Поднять Playwright **с залогиненной EPROLO-сессией** через
   `storage_state.json` — пользователь логинится один раз в Chromium,
   сохраняем cookies в файл, `get_shared_browser_ctx` подгружает их.
2. В `scrape_eprolo` добавить проверку финального `page.url` после
   `goto` — если редирект сменил path, валидируем как ошибку.
3. Очистить два мусорных товара в Shopify Admin (пользователь сам или
   через Admin API после получения корректного токена).
4. После cleanup в БД откатить status:
   ```sql
   UPDATE products SET status='pending', shopify_product_id=NULL
     WHERE shopify_product_id IN (
       'gid://shopify/Product/8889396002994',
       'gid://shopify/Product/8889396265138'
     );
   ```

---

### Bug B — Метафилды пусто в Shopify Admin (root cause UNKNOWN)

**Симптом.** Пользователь открывает товар в Shopify Admin → Metafields,
видит список из ~19 определений Wanelo · ..., но все **значения пустые**.

**Что известно.** В логах прогона видна строка
`JSON OK: hero=True story=3 feat=3 stat=4 rev=12 faq=7` (Designer
сгенерировал контент), потом `Created: gid://shopify/Product/...`, потом
сразу краш `TypeError: object of type 'NoneType' has no len()` в Cell 6
на строке 1542.

**Что починено** (коммит `ba799f3`):
- `_ok_mf = len(_data_mf.get('metafields') or [])` — было
  `.get('metafields', [])`, что возвращает `None` (не default), если
  Shopify прислал `{"metafields": null}`.

**Что добавлено для диагностики** (коммит `4927a82`):
- Top-level GraphQL `errors` теперь логгируются (раньше игнорировались).
- При `0/N written` распечатывается каждый input — `key`, `type`,
  `value_len`. Сразу видно, был ли Designer-output пустой.
- Все `userErrors` логгируются (раньше только первые 2).

**Что нужно следующему агенту.**
1. Запустить ноутбук на 1-2 product URL.
2. Скопировать блок логов от `→ Shopify...` до конца товара.
3. По диагностическим строкам определить класс ошибки:
   - `GraphQL top-level errors: ...` → токен / scope / throttle.
   - `userErrors: ... code=INVALID_VALUE` → JSON value не соответствует
     схеме metafield definition (типичный случай: тип `json` ожидает
     валидный JSON, а value содержит управляющие символы).
   - `value_len=0` для всех → Designer не наполнил `_sections`.

**Гипотезы (от приоритетной к маловероятной).**
1. **Scope токена.** Пользователь дал `shpss_` (OAuth shared secret),
   не `shpat_` (Admin API access token). См. секцию 4. Скорее всего
   токен в `os.environ["SHOPIFY_TOKEN"]` тоже не тот, и `shopify_gql`
   получает 401/403, но silently возвращает `None`.
2. **userErrors `INVALID_TYPE`.** Cell 2 создаёт metafield definitions
   с `type: json`, но если у магазина уже были definitions с другим
   `type` (например, `single_line_text_field` из ранней версии), новые
   значения отвергаются.
3. **`_sections` пустой.** Маловероятно — лог говорит `hero=True ...`.

---

## 2. Что было сделано в последней сессии (3 коммита на ветке)

```
4927a82 diag(pipeline): verbose metafieldsSet error logging
ba799f3 fix(pipeline): reject EPROLO marketing-page redirects + len(None) bug
db02cb4 feat(designer): extend system prompt with 14 new module schemas
```

Подробности — `CHANGELOG.md` (раздел `[Unreleased]`) и
`pipeline/.migrations/2026-05-23_*.py`.

---

## 3. Архитектура / ориентиры

- **Конституция:** `CLAUDE.md` (читай первым).
- **Архитектурные решения:** `DECISIONS.md` (ADR-001..006).
- **Журнал изменений:** `CHANGELOG.md`.
- **Известные проблемы:** `TROUBLESHOOTING.md`.

**Ключевые файлы пайплайна:**
- `pipeline/Shopify_Pipeline.ipynb` — 17 ячеек, 8 code:
  - Cell 1 (id `?`): env config (ANTHROPIC, SHOPIFY, DATAFORSEO).
  - Cell 2 (id `b810afd7`): clients, scrape_eprolo, validate_scrape,
    metafield definitions auto-ensure (37 штук).
  - Cell 5 (id `ea617348`): Strategy + Vision system prompts.
  - Cell 6 (id `ce20f070`): `_process_one` (главный async-цикл),
    Designer system prompt с FILL/SKIP, метафилд-пуш.
- `pipeline/theme_assets/` — 35 storefront snippets + 1 master section
  (`wanelo-product-page.liquid`) + 2 admin-only (photo_pack, source).
- `pipeline/.migrations/` — миграции notebook'а (применять через
  `python pipeline/.migrations/<name>.py`).
- `pipeline/.review/` — handoff-заметки между раундами дизайна.

**Что должно работать:**
- `python pipeline/tools/notebook_smoke.py` → ✅ valid
- `python -m pytest pipeline/tests/ -q` → 566 passed

---

## 4. Кредиты — СНАЧАЛА РОТАЦИЯ

⚠️ **Все секреты были в открытом виде в этом чате (загружен файл от
пользователя). Они должны быть отозваны и перевыпущены ДО любых
действий.**

Что было засвечено:
- Anthropic API key
- Shopify Client ID + Client Secret (OAuth, не Admin API)
- DataForSEO login / password
- OpenAI API key

**Чек-лист ротации:**
1. https://console.anthropic.com/settings/keys → revoke + new.
2. Shopify Admin → Settings → Apps → твоё кастом-app → Uninstall → reinstall
   (получишь свежий **Admin API access token формата `shpat_*`**).
3. https://platform.openai.com/api-keys → revoke + new.
4. DataForSEO password change.

**Важно — формат Shopify токена.** Для прямых вызовов GraphQL Admin API
(`X-Shopify-Access-Token: ...`) нужен токен формата **`shpat_*`**, а не
`shpss_*` (последний — OAuth shared secret, не годится для Admin API).
Пользователь в прошлом сообщении дал `shpss_*` и утверждал, что это
правильный токен — это заблуждение, нужно настоять на `shpat_*`.

**Где взять `shpat_*`:**
Shopify Admin → Settings → Apps and sales channels → Develop apps →
открыть app → API credentials → "Admin API access token" → Reveal once.
Scopes минимум:
```
write_products, read_products,
write_metafields, read_metafields,
write_metafield_definitions, read_metafield_definitions,
write_files, read_files,
write_publications, read_publications
```

Магазин: `wanelo-store-roman.myshopify.com`.

---

## 5. Среда выполнения

**Машина пользователя.**
- Windows 11, i9-13900K, 32 GB RAM, RTX 3060.
- Python — нужно проверить (`python --version` в PowerShell).
- Shopify CLI установлен (config token в
  `C:/Users/Roman Office/AppData/Roaming/shopify-cli-store-nodejs/Config/config.json`,
  TTL 24h).

**Где сейчас крутился pipeline.** Google Colab (по ссылке
`https://colab.research.google.com/github/invme2/tags-recomendations/blob/apple-design-rounds-5-6/pipeline/Shopify_Pipeline.ipynb`).
Colab — главная причина Bug A: нет stateful Playwright-сессии,
EPROLO редиректит на signup.

**Рекомендация (которую пользователь УЖЕ принял).** Переезд на локальный
PC с Claude Code Desktop. После установки:
1. `git clone https://github.com/invme2/tags-recomendations.git`
2. `git checkout apple-design-rounds-5-6`
3. `python -m venv .venv && .venv\Scripts\activate`
4. `pip install -r requirements-dev.txt` + `pip install playwright anthropic shopify python-dotenv && playwright install chromium`
5. `.env` с **ротированными** ключами (см. секцию 4).
6. EPROLO login → сохранить `storage_state.json` (см. план Bug A).

---

## 6. Жёсткие констрейнты (КОТОРЫЕ НЕ ОБСУЖДАЮТСЯ)

- **Shopify Admin API: 5 req/sec hard cap.** Throttle на 4 req/sec safe.
  В `shopify_gql` есть retry — не убирать.
- **AI-reviews — НЕ верифицированные.** В `wanelo-product-schema.liquid`
  НЕ эмитить `aggregateRating` / `hasMerchantReturnPolicy` (FTC fraud
  risk). Operator явно сказал "Ai review не убирай" — оставлять как
  visual social proof, но не как schema.org-данные.
- **Никаких упоминаний** shipping / returns / refund / delivery /
  secure-checkout / money-back / warranty в любом дефолтном копирайте —
  это отдельный модуль checkout-страницы оператора.
- **Никаких внешних шрифтов `@import`** в production CSS. Apple-aesthetic
  использует system font stack.
- **Per-product palette CSS variables** (`--brand-1` etc.) — должны
  оставаться populated, но использовать только как акценты, не как
  фоны секций. CTA-token inheritance (`--btn-primary-bg-color` →
  `--ink` fallback) не ломать.
- **Skip-if-blank gates** на каждом snippet'е сохраняются.
- **`prefers-reduced-motion`** уважается для всех анимаций.
- **Notebook ТОЛЬКО через `nbformat`.** Никаких ручных правок JSON.
- **Один логический сдвиг = один коммит** (атомарность).
- **Develop ТОЛЬКО на ветке `apple-design-rounds-5-6`** (или новой
  feature-ветке от неё). НЕ пушить в `main` без явного разрешения
  пользователя.
- **Repository scope ограничен** `invme2/tags-recomendations` для
  GitHub MCP tools.
- **PR создавать ТОЛЬКО по явному запросу** пользователя.

---

## 7. Первые 10 шагов для тебя (нового агента)

1. `cat CLAUDE.md && cat HANDOFF.md` — забери контекст.
2. `git log --oneline -10 && git status` — проверь ветку.
3. `python -m pytest pipeline/tests/ -q` — должно быть `566 passed`.
4. Спроси пользователя: **готовы ли ротированные ключи?** Если нет —
   жди, ничего не запускай.
5. Подгрузи ротированные ключи в `.env` (Windows-локально). Magic value
   `SHOPIFY_TOKEN` должно быть формата `shpat_*`.
6. Sanity-вызов Admin API:
   ```bash
   curl -s -H "X-Shopify-Access-Token: $SHOPIFY_TOKEN" \
     "https://wanelo-store-roman.myshopify.com/admin/api/2024-10/graphql.json" \
     -H "Content-Type: application/json" \
     -d '{"query":"{ shop { name } }"}'
   ```
   Если `{"data":{"shop":{"name":"..."}}}` — токен ок.
7. Проверь metafield definitions:
   ```graphql
   { metafieldDefinitions(first: 50, ownerType: PRODUCT,
                          namespace: "custom") { nodes { key name type { name } } } }
   ```
   Если их < 37 — Cell 2 auto-ensure ещё не отработал на этом магазине,
   надо запустить.
8. Посмотри текущее состояние двух мусорных товаров:
   ```graphql
   query { product(id:"gid://shopify/Product/8889396002994") {
     title metafields(first:50,namespace:"custom") { nodes { key value } } } }
   ```
   Если value пустые — confirmed Bug B на старом продукте. Если есть —
   значит Bug B уже не воспроизводится, можно фокусироваться на
   Bug A + EPROLO login.
9. Реализуй EPROLO login flow:
   - Один раз: `playwright codegen --save-storage=eprolo_state.json eprolo.com/login`.
   - В `get_shared_browser_ctx` подгружай `storage_state="eprolo_state.json"`.
   - В `validate_scrape` добавь проверку финального URL после goto.
10. Запусти pipeline на 2-3 тестовых URL, смотри новые диагностические
    логи (см. Bug B), доложи пользователю.

---

## 8. Контакты / коммуникация

- **Пользователь:** ra@invme.com.
- **Язык общения:** русский (но код / коммиты / тесты — английский).
- **Стиль ответов:** короткие, конкретные, без воды. Один логический
  шаг — один абзац.
- **Когда сомневаешься в destructive-операции** (`DELETE` товаров,
  миграции БД, force-push) — ВСЕГДА спрашивай подтверждение явно.

---

## 9. Эта сессия не успела

- ❌ Реальный диагноз Bug B (пустые метафилды). Логов с новой
  диагностикой ещё не было — пользователь не успел перезапустить.
- ❌ Cleanup мусорных товаров в Shopify (нет доступа к Admin API
  отсюда — sandbox блокирует outbound).
- ❌ EPROLO login flow / `storage_state.json` — не реализован.
- ❌ Локальная установка pipeline на Windows — пользователь только
  планирует.

Удачи.
