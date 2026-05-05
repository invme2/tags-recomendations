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

_Пока пусто. Первая запись появится при первой правке ноутбука._
