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

