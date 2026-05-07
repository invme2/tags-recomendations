# WANELO Theme Setup — JSON-driven product pages

Pipeline пишет 9 JSON-метафилдов на товар. Тема рендерит каждую секцию из своего метафилда через одну Liquid-секцию с 9 снипетами.

## Файловая структура

```
theme/
├── assets/
│   ├── wanelo.css        ← скопировать целиком
│   └── wanelo.js         ← скопировать целиком (~400 байт, IntersectionObserver)
├── sections/
│   └── wanelo-product-page.liquid   ← добавляешь в product.json
└── snippets/
    ├── wanelo-palette.liquid        ← :root{--brand-*} per-product
    ├── wanelo-hero.liquid           ← hero секция
    ├── wanelo-story.liquid          ← story chapters
    ├── wanelo-features.liquid       ← 3 features cards
    ├── wanelo-stats.liquid          ← 4-cell stats grid
    ├── wanelo-reviews.liquid        ← 12 mini-reviews, 3-col animated
    ├── wanelo-faq.liquid            ← accordion + JSON-LD FAQPage schema
    ├── wanelo-cta.liquid            ← centered CTA
    └── wanelo-interlinks.liquid     ← collection pills
```

## Установка в тему (15 минут)

### 1. Открыть редактор темы

Shopify Admin → **Online Store → Themes** → активная тема → `...` → **Edit code**

### 2. Скопировать assets (2 файла)

В редакторе слева — раздел **Assets**:

- **Add a new asset** → **Create a blank file** → name `wanelo`, ext `.css` → Done
- Открой [wanelo.css RAW](https://raw.githubusercontent.com/invme2/tags-recomendations/claude/enrich-shopify-taxonomy-kMPmA/pipeline/theme_assets/assets/wanelo.css) → выдели всё (Ctrl+A) → копируй → вставь в Shopify → **Save**
- Повтори для **wanelo.js** ([RAW URL](https://raw.githubusercontent.com/invme2/tags-recomendations/claude/enrich-shopify-taxonomy-kMPmA/pipeline/theme_assets/assets/wanelo.js))

### 3. Скопировать snippets (9 файлов)

В разделе **Snippets**:

- **Add a new snippet** → name `wanelo-palette` → Done → вставь содержимое из [RAW](https://raw.githubusercontent.com/invme2/tags-recomendations/claude/enrich-shopify-taxonomy-kMPmA/pipeline/theme_assets/snippets/wanelo-palette.liquid) → Save

Повтори для остальных 8 снипетов: `wanelo-hero`, `wanelo-story`, `wanelo-features`, `wanelo-stats`, `wanelo-reviews`, `wanelo-faq`, `wanelo-cta`, `wanelo-interlinks`. Все RAW URL'ы:

- https://raw.githubusercontent.com/invme2/tags-recomendations/claude/enrich-shopify-taxonomy-kMPmA/pipeline/theme_assets/snippets/wanelo-hero.liquid
- https://raw.githubusercontent.com/invme2/tags-recomendations/claude/enrich-shopify-taxonomy-kMPmA/pipeline/theme_assets/snippets/wanelo-story.liquid
- https://raw.githubusercontent.com/invme2/tags-recomendations/claude/enrich-shopify-taxonomy-kMPmA/pipeline/theme_assets/snippets/wanelo-features.liquid
- https://raw.githubusercontent.com/invme2/tags-recomendations/claude/enrich-shopify-taxonomy-kMPmA/pipeline/theme_assets/snippets/wanelo-stats.liquid
- https://raw.githubusercontent.com/invme2/tags-recomendations/claude/enrich-shopify-taxonomy-kMPmA/pipeline/theme_assets/snippets/wanelo-reviews.liquid
- https://raw.githubusercontent.com/invme2/tags-recomendations/claude/enrich-shopify-taxonomy-kMPmA/pipeline/theme_assets/snippets/wanelo-faq.liquid
- https://raw.githubusercontent.com/invme2/tags-recomendations/claude/enrich-shopify-taxonomy-kMPmA/pipeline/theme_assets/snippets/wanelo-cta.liquid
- https://raw.githubusercontent.com/invme2/tags-recomendations/claude/enrich-shopify-taxonomy-kMPmA/pipeline/theme_assets/snippets/wanelo-interlinks.liquid

### 4. Скопировать секцию

В разделе **Sections**:

- **Add a new section** → name `wanelo-product-page` → Done → вставь содержимое из [RAW](https://raw.githubusercontent.com/invme2/tags-recomendations/claude/enrich-shopify-taxonomy-kMPmA/pipeline/theme_assets/sections/wanelo-product-page.liquid) → Save

### 5. Добавить секцию в product template

- Online Store → Themes → активная тема → **Customize** (НЕ "Edit code")
- Сверху селектор шаблона → выбери **"Products → Default product"**
- В левой панели секций → **Add section** → найди **"Wanelo Product Page"** → Add
- Перетащи секцию в нужное место (под product info, под gallery — на твой вкус)
- **Save**

### 6. Удалить старую custom Liquid-секцию (если была)

Если у тебя там была кастомная Liquid-секция со старым кодом (рендеринг `product.metafields.custom.html_description` + JSON-LD) — **удалить её** (нажми трёхточечное меню секции → Remove). Иначе будет дублирование.

## ⚠ Перед прогоном — пополни 3 сервиса

Anthropic, OpenAI, DataForSEO — все три должны быть с балансом. Подробности и расход на товар в [`pipeline/BILLING.md`](../BILLING.md):

| Сервис | Dashboard |
|---|---|
| Anthropic | https://console.anthropic.com/settings/billing |
| OpenAI | https://platform.openai.com/settings/organization/billing/overview |
| DataForSEO | https://app.dataforseo.com/billing |

Если хоть один в нуле — прогон встанет посередине. Расход на 1 товар при `IMAGE_GEN_QUALITY="medium"`: ~$0.75 (Anthropic ~$0.25 + OpenAI ~$0.50) + ~$3.75 на батч от DataForSEO.

## Env-переменные перед запуском (Colab → Secrets)

| Имя                 | Зачем                                                  | Обязательно                |
| ------------------- | ------------------------------------------------------ | -------------------------- |
| `ANTHROPIC_API_KEY` | Claude API (vision + strategy + designer)              | да                         |
| `SHOPIFY_STORE`     | например `wanelo.myshopify.com`                        | да                         |
| `SHOPIFY_CLIENT_ID` / `SHOPIFY_CLIENT_SECRET` | Admin API custom app credentials | да                         |
| `DATAFORSEO_LOGIN` / `DATAFORSEO_PASSWORD`    | SEO keyword research              | да                         |
| `OPENAI_API_KEY`    | gpt-image-2 для 5 главных фото + inline-картинок       | если `USE_IMAGE_GEN=True` |
| `GITHUB_TOKEN`      | если репо приватный — нужен для taxonomy fetch         | optional                   |

В Cell 1 ноутбука есть параметры:
- `USE_IMAGE_GEN = True` — генерить ли через gpt-image-2 (если `False` — берутся фото EPROLO как есть)
- `IMAGE_GEN_QUALITY = "medium"` — `low` ($0.005-0.006) / `medium` ($0.041-0.053) / `high` ($0.165-0.211) per image
- `GALLERY_PHOTO_COUNT = 5` — сколько фото в основной карусели Shopify

## Запустить пайплайн

1. Открой ноутбук: [Open in Colab](https://colab.research.google.com/github/invme2/tags-recomendations/blob/claude/enrich-shopify-taxonomy-kMPmA/pipeline/Shopify_Pipeline.ipynb)
2. `RESET_DB ✓` → выполни Cell 1 → загрузи CSV/Excel
3. Cell 2 — увидишь `Metafield definitions ensured: 9`
4. Cell 3-5.5 → как обычно
5. Cell 6 — для каждого товара лог:
   ```
   [N/total] Product
     → Scraping...
     → Vision...
     → Strategy (Opus 4.7)... voice=warm-confidant | idea: Twenty minutes of stalking equals an evening of peace
     → Generating JSON content...
       JSON OK: hero=True story=2 feat=3 stat=4 rev=12 faq=5 | $0.0234
       Briefs: 5 gallery + 5 metafield
       Tags: 8 valid
     → Generating 10 images (gpt-image-2/medium)...
       [1/10] gallery/1: OK $0.041
       [2/10] gallery/2: OK $0.041
       ...
       Total: 10 OK / 0 fail | $0.45
     → Shopify... Created: gid://shopify/...
       Metafields: 9/9 written (8423 chars total)
       Gallery: 5/5 (AI)
   ```

## Как это работает

```
PIPELINE                                       SHOPIFY                            BROWSER
─────────                                      ────────                           ─────────
Strategy (Opus) → Designer (Sonnet) writes:
  • content JSON (9 sections)                 ──→ 9 custom.* metafields (json)   ──→ 9 wanelo-*.liquid snippets
  • gallery_briefs[5]   (Shopify carousel)
  • metafield_briefs[N] (inline photos)

Image gen (gpt-image-2):
  • generates 5 gallery photos                ──→ Shopify product images          ──→ /products/handle карусель
  • generates N inline photos                 ──→ url substituted into metafields ──→ внутри long-form sections

CSS framework loads ONCE from theme:  /assets/wanelo.css (~30KB cached)
JS observer loads ONCE:               /assets/wanelo.js (~400 bytes)
```

**Преимущества:**

- AI пишет ~5 KB JSON (vs 100 KB HTML) → **в 3-5 раз дешевле** ($0.02 vs $0.06 на товар)
- CSS грузится 1 раз и кешируется → **в 3-4 раза быстрее** загрузка страницы
- Изменения дизайна → правишь Liquid файл → **все товары обновляются мгновенно**
- Нет дублирования контента, нет 65k лимитов
- Можно править отдельные товары через Shopify Admin → Metafields → JSON

## Если что-то не так

- **Section добавлена но пусто** — пайплайн ещё не записал метафилды для этого товара. Запусти Cell 6.
- **`Liquid error: Metafield not found`** — определение метафилда не создано. Проверь Cell 2 вывод `Metafield definitions ensured: 9`. Если 0 — `SHOPIFY_TOKEN` не работает.
- **JSON-LD FAQPage не валиден** — скорее всего designer написал кавычки или \n в quotes. Liquid filter `| json` экранирует.
- **Анимации не идут** — wanelo.js не загрузился. Проверь Network tab на наличие `wanelo.js → 200 OK`.
