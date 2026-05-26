# Troubleshooting

Журнал известных проблем и решений. Каждый раз, когда что-то сломалось и
починилось — добавляем запись.

Формат:
```
## #NNN — короткое название
Симптом: что пользователь видит
Корневая причина: настоящая причина (а не «починили вот так»)
Решение: что сделали
Дата: YYYY-MM-DD
Связанный коммит: <hash> (опционально)
```

---

## #001 — GitHub Push Protection: захардкоженные секреты в Shopify_Pipeline.ipynb
Симптом: `git push` отклоняется с ошибкой `GH013: Repository rule violations`,
push protection указывает на `Anthropic API Key` и `Shopify App Shared Secret`
в `pipeline/Shopify_Pipeline.ipynb:1061` и `:1064`.

Корневая причина: оригинальный ноутбук пользователя имел в config-ячейке
(`#2`, id=`477e495d`) шесть захардкоженных значений: `ANTHROPIC_API_KEY`,
`SHOPIFY_STORE`, `SHOPIFY_CLIENT_ID`, `SHOPIFY_CLIENT_SECRET`,
`DATAFORSEO_LOGIN`, `DATAFORSEO_PASSWORD`. Это нарушение правил из CLAUDE.md
«Чего никогда не делаешь → коммит секретов».

Решение:
1. Snapshot ноутбука: `pipeline/.snapshots/20260505_103029_before-secret-removal.ipynb`.
2. Через `nbformat` (см. ADR-003) каждое значение заменено на
   `os.environ["KEY"]` (KeyError при отсутствии — fail-loud).
3. В начало ячейки добавлен `import os`.
4. Откат коммита через `git reset --soft HEAD~1` (не destructive),
   пересборка коммита с очищенным ноутбуком, push прошёл.
5. Запись в `pipeline/PATCHES.md`.

**ВАЖНО для пользователя:** скомпрометированные ключи (Anthropic, Shopify
shared secret, DataForSEO password) **должны быть отозваны и
перевыпущены**, потому что они были видны в локальном git-объекте до
push'а и теоретически могли где-то закэшироваться (включая загрузку через
GitHub UI в формате ZIP внутри `files(4).zip`).

Дата: 2026-05-05
Связанные коммиты: be4dcd7 (с секретами, не запушен) → новый без секретов

---

## #002 — EPROLO scraper берёт маркетинговую страницу вместо товара
Симптом: pipeline создал в Shopify товары с title `"EPROLO - All-in-One
Dropshipping Supply Chain Platform"` и `"Sign Up -EPROLO"` вместо
реальных продуктов. Все товары [3..11] получили один handle и
перезаписали друг друга через `Updated: gid://shopify/Product/8889396265138`.

Корневая причина: `scrape_eprolo` (Cell 2) использует Playwright без
залогиненной EPROLO-сессии. EPROLO для незалогиненных редиректит
product-URL на signup/home, а скрейпер берёт `<h1>` этой страницы.
`validate_scrape` пропускал такой title — `"EPROLO - ..."` длиннее 5
символов, картинки на маркетинг-странице есть, проверка проходила.

Решение (частичное, defense-in-depth):
1. `validate_scrape` расширен — детектит маркетинг-тайтлы как issue
   `marketing_page` (`'EPROLO -' / 'Sign Up' / 'Sign In' / 'Log In' /
   'Login' / 'Dropshipping Supply' / 'All-in-One Dropshipping'`).
2. Cell 6 при `marketing_page` ставит `status='error'` и не пушит
   в Shopify.

Полное решение (в работе): Playwright `storage_state.json` после
ручного логина в EPROLO + проверка финального URL после `page.goto`.
См. `HANDOFF.md` секция 1, Bug A.

Дата: 2026-05-26
Связанный коммит: ba799f3

---

## #003 — `TypeError: object of type 'NoneType' has no len()` в Cell 6
Симптом: после `Created: gid://shopify/Product/...` pipeline крашится
строкой `_ok_mf = len(_data_mf.get('metafields', []))` →
`TypeError: object of type 'NoneType' has no len()`. Товар в Shopify
есть, но метафилды не записаны.

Корневая причина: Shopify возвращает `{"metafields": null}` (не
`[]`!) когда **все** метафилды в батче упали валидацию. `dict.get(key,
default)` возвращает default только при отсутствии ключа, а не при
значении `null` — поэтому `.get('metafields', [])` отдавал `None`.
`len(None)` ломал функцию ДО логирования `userErrors`, мы и не видели,
что именно отвергло Shopify.

Решение:
1. `_data_mf.get('metafields') or []` — теперь `None` тоже даёт `[]`.
2. Verbose-логгирование (отдельный коммит `4927a82`) — top-level
   GraphQL `errors` + per-input `key/type/value_len` + все
   `userErrors` с `field/code/message` при `0/N written`.

Дата: 2026-05-26
Связанные коммиты: ba799f3 (fix), 4927a82 (diagnostics)

---

## #004 — Bug A полное решение: EPROLO storage_state + redirect guard
Симптом: после `ba799f3` pipeline корректно отказывался пушить
маркетинг-redirects в Shopify, но 100% реальных EPROLO product URLs всё
равно скрейпились пустыми — `scrape_eprolo` открывал страницу без
залогиненной сессии, и EPROLO одинаково редиректил всех на signup.

Корневая причина: `get_shared_browser_ctx` создавал `new_context()` без
`storage_state`. Колаб не имеет stateful Playwright-сессии, кладовая
кук пустая, EPROLO считает запрос анонимным.

Решение:
1. Headed-режим Playwright для ручного логина один раз —
   `pipeline/tools/eprolo_login.py` сохраняет cookies + localStorage
   в `pipeline/.eprolo_state.json` (gitignored).
2. `get_shared_browser_ctx` теперь читает `EPROLO_STATE_FILE` из env,
   и если файл есть — передаёт `storage_state=...` в `new_context`.
3. `scrape_eprolo` defense-in-depth: после `page.goto` сверяет
   `page.url` с шаблоном `/app/product/`. Если редирект — ранний
   выход с пустым `title`, который `validate_scrape` ловит.

Проверено эмпирически: anti-aging-firming-micro-needling и
crest-3d-white возвращают реальные product titles. OceAura
(удалённый товар) ловится по `_redirect_target=/app/home.html`
+ `marketing_page` в `validate_scrape` (commit `ba799f3`).

TTL Shopify-токена 24h, TTL EPROLO-сессии — пока браузер не разлогинит
(в норме недели). Re-login через `eprolo_login.py` при необходимости.

Дата: 2026-05-26
Связанный коммит: следующий после этой записи.
