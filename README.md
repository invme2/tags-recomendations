# tags-recomendations

Моно-репо из двух связанных продуктов:

- **`taxonomy/`** — JSON-база ~765 кластеров для тегирования товаров.
- **`pipeline/`** — Jupyter-ноутбук Shopify-пайплайна (скрейп EPROLO →
  SEO-генерация через Claude API → тегирование по taxonomy → загрузка в Shopify).

## Источник правды

Все актуальные правила, структура репо, соглашения, журналы изменений и
архитектурные решения лежат в корневых memory-файлах. **Перед любой работой
прочитать в этом порядке:**

1. [`CLAUDE.md`](./CLAUDE.md) — конституция проекта, статус «что работает / что сломано».
2. [`DECISIONS.md`](./DECISIONS.md) — ADR (архитектурные решения).
3. [`CHANGELOG.md`](./CHANGELOG.md) — журнал изменений.
4. [`TROUBLESHOOTING.md`](./TROUBLESHOOTING.md) — известные проблемы и фиксы.

## Быстрый старт (dev-машина)

```bash
pip install -r requirements-dev.txt
python tools/health_check.py            # общий smoke-тест
python taxonomy/tools/validate_taxonomy.py
python pipeline/tools/notebook_smoke.py
python -m pytest taxonomy/tests/ -v
```

## CI

GitHub Actions:
- `validate-taxonomy.yml` — pytest + валидация `taxonomy.json`.
- `smoke-pipeline.yml` — `nbformat`-валидация `pipeline/Shopify_Pipeline.ipynb`.

Триггеры: `push` и `pull_request` на любую ветку.
