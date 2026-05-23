# WANELO Theme Setup — JSON-driven product pages

Pipeline пишет до 23 метафилдов на товар: 21 storefront-JSON-секций + 2 admin-only (`photo_pack` — type `url`, кликабельная кнопка скачивания ZIP в Admin; `source` — JSON с EPROLO-происхождением). Тема рендерит storefront-секции из метафилдов через одну Liquid-секцию с 21 снипетом. Снеппеты с пустым метафилдом просто пропускаются (skip-if-blank gate), так что для каждого товара показывается только то что Designer счёл уместным (типично 11-13 секций из 21). Admin-only метафилды видны ТОЛЬКО в Shopify Admin → Product → Metafields, никогда не попадают в storefront HTML (даже скрытыми элементами).

## Файловая структура

```
theme/
├── assets/
│   ├── wanelo.css        ← один файл, ~465 строк, всё оформление
│   └── wanelo.js         ← ~400 байт, IntersectionObserver для анимаций
├── sections/
│   └── wanelo-product-page.liquid   ← одна master-секция, рендерит 21 сниппет
└── snippets/
    │ === Always-on (10): рендерятся для каждого товара
    ├── wanelo-palette.liquid           ← :root{--brand-*} per-product
    ├── wanelo-hero.liquid              ← hero блок (h1 + lead + image + inline CTA + trust line)
    ├── wanelo-guarantee.liquid         ← risk-reversal: return / shipping / secure (shop-level config)
    ├── wanelo-story.liquid             ← 1-3 главы alternating mirror
    ├── wanelo-features.liquid          ← 3 features cards
    ├── wanelo-stats.liquid             ← 4-cell stats grid
    ├── wanelo-reviews.liquid           ← 9-12 mini-reviews, 3-col animated
    ├── wanelo-faq.liquid               ← accordion + JSON-LD FAQPage
    ├── wanelo-cta.liquid               ← centered CTA
    ├── wanelo-interlinks.liquid        ← collection pills
    │ === Optional content (7): designer заполняет если product fit
    ├── wanelo-ingredients.liquid       ← chips ингредиентов (skincare/food)
    ├── wanelo-how-to.liquid            ← 3-7 numbered steps (rituals/setup)
    ├── wanelo-timeline.liquid          ← before/after milestones (transformations)
    ├── wanelo-specs.liquid             ← spec table (electronics/jewelry)
    ├── wanelo-whats-included.liquid    ← items in box (bundles/kits)
    ├── wanelo-compare.liquid           ← vs alternatives (research-buy)
    ├── wanelo-trust.liquid             ← certs + press (regulated/premium)
    │ === Optional physical (5): новые niche модули
    ├── wanelo-size-guide.liquid        ← размерная сетка (clothing/jewelry/pet)
    ├── wanelo-care.liquid              ← care chips (fashion/jewelry/textiles)
    ├── wanelo-dimensions.liquid        ← физ. размеры + scale-ref (decor/furniture)
    ├── wanelo-variants.liquid          ← color swatches (fashion/accessories)
    └── wanelo-gift-options.liquid      ← gift wrap + occasions
```

## Установка в тему (15 минут)

### 1. Открыть редактор темы

Shopify Admin → **Online Store → Themes** → активная тема → `...` → **Edit code**

### 2. Скопировать assets (2 файла)

В редакторе слева — раздел **Assets**:

- **Add a new asset** → **Create a blank file** → name `wanelo`, ext `.css` → Done
- Открой [wanelo.css RAW](https://raw.githubusercontent.com/invme2/tags-recomendations/claude/enrich-shopify-taxonomy-kMPmA/pipeline/theme_assets/assets/wanelo.css) → выдели всё (Ctrl+A) → копируй → вставь в Shopify → **Save**
- Повтори для **wanelo.js** ([RAW URL](https://raw.githubusercontent.com/invme2/tags-recomendations/claude/enrich-shopify-taxonomy-kMPmA/pipeline/theme_assets/assets/wanelo.js))

### 3. Скопировать snippets (21 файл)

В разделе **Snippets** для каждого: **Add a new snippet** → имя без `.liquid` → Done → вставь содержимое из RAW URL → Save.

Все RAW URL'ы — `https://raw.githubusercontent.com/invme2/tags-recomendations/claude/enrich-shopify-taxonomy-kMPmA/pipeline/theme_assets/snippets/<name>.liquid`:

**Always-on (10):**
- `wanelo-palette` · `wanelo-hero` · `wanelo-guarantee` · `wanelo-story` · `wanelo-features`
- `wanelo-stats` · `wanelo-reviews` · `wanelo-faq` · `wanelo-cta` · `wanelo-interlinks`

**Optional content (7):**
- `wanelo-ingredients` · `wanelo-how-to` · `wanelo-timeline` · `wanelo-specs`
- `wanelo-whats-included` · `wanelo-compare` · `wanelo-trust`

**Optional physical (5):**
- `wanelo-size-guide` · `wanelo-care` · `wanelo-dimensions` · `wanelo-variants`
- `wanelo-gift-options`

Совет: открой все 21 RAW в фоновых вкладках сразу — потом просто Ctrl+Tab между Shopify-редактором и каждой вкладкой.

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

### 7. Установить Related-Collections section на collection-страницы (для SEO)

В разделе **Sections** в редакторе тем:
- **Add a new section** → name `wanelo-collection-related` → Done → вставь содержимое из [RAW](https://raw.githubusercontent.com/invme2/tags-recomendations/claude/enrich-shopify-taxonomy-kMPmA/pipeline/theme_assets/sections/wanelo-collection-related.liquid) → Save

Подключить на collection-страницу:
- Online Store → Themes → **Customize** → сверху селектор → выбери **"Collections → Default collection"**
- В левой панели секций → **Add section** → найди **"Wanelo Related Collections"** → Add → перетащи вниз страницы (после product grid) → **Save**

Пустой метафилд = секция скрывается, поэтому безопасно оставить установленной на всех коллекциях даже если данных ещё нет. Pipeline (Cell 4) после создания коллекций сам впишет данные в `custom.related_collections` и вшит inline-`<p>` с ссылками в description.

## ⚠ Перед прогоном — пополни 2 сервиса

Anthropic + DataForSEO — оба должны быть с балансом, иначе прогон встанет посередине.

| Сервис | Dashboard |
|---|---|
| Anthropic | https://console.anthropic.com/settings/billing |
| DataForSEO | https://app.dataforseo.com/billing |

Расход: ~$0.25 на товар (Anthropic vision + strategy + designer) + ~$3.75 на батч (DataForSEO keyword research, не масштабируется на товар).

## Env-переменные перед запуском (Colab → Secrets)

| Имя                 | Зачем                                                  | Обязательно                |
| ------------------- | ------------------------------------------------------ | -------------------------- |
| `ANTHROPIC_API_KEY` | Claude API (vision + strategy + designer)              | да                         |
| `SHOPIFY_STORE`     | например `wanelo.myshopify.com`                        | да                         |
| `SHOPIFY_CLIENT_ID` / `SHOPIFY_CLIENT_SECRET` | Admin API custom app credentials | да                         |
| `DATAFORSEO_LOGIN` / `DATAFORSEO_PASSWORD`    | SEO keyword research              | да                         |
| `GITHUB_TOKEN`      | если репо приватный — нужен для taxonomy fetch         | optional                   |
| `RETAIL_MARKUP`     | retail price = cost × этот множитель (default 5.0)     | optional                   |
| `COMPARE_AT_MARKUP` | strike-through price = cost × этот множитель (default 8.0) | optional                |

## Shop-level metafields для wanelo-guarantee (настраивается ОДИН раз)

Risk-reversal блок (`wanelo-guarantee`) рендерится для всех товаров. Тексты конфигурируются на уровне магазина (один раз), а не per-product. Без настройки используются разумные дефолты.

Shopify Admin → **Settings → Custom data → Shop → Add definition** (namespace `wanelo`):

| Key                | Type                    | Дефолт (если не задан)                            |
|--------------------|-------------------------|---------------------------------------------------|
| `return_policy`    | Single line text        | `30-day money-back`                               |
| `return_note`      | Single line text        | `Not what you expected? Send it back, full refund.` |
| `shipping`         | Single line text        | `Free shipping over $50`                          |
| `shipping_note`    | Single line text        | `Fast delivery on US orders.`                     |
| `secure_checkout`  | Single line text        | `Secure checkout`                                 |
| `secure_note`      | Single line text        | `SSL encrypted. Apple Pay, Stripe, PayPal accepted.` |
| `trust_line`       | Single line text        | `30-day returns · Free shipping over $50 · Secure checkout` (отображается под H1 hero) |
| `cta_label`        | Single line text        | `Add to cart` (текст кнопки внутри hero)          |

После создания definitions: **Settings → Custom data → Shop → Edit values** → впиши свои тексты.

## Запустить пайплайн

1. Открой ноутбук: [Open in Colab](https://colab.research.google.com/github/invme2/tags-recomendations/blob/claude/enrich-shopify-taxonomy-kMPmA/pipeline/Shopify_Pipeline.ipynb)
2. `RESET_DB ✓` → выполни Cell 1 → загрузи CSV/Excel
3. Cell 2 — увидишь `Metafield definitions ensured: 23`
4. Cell 3-5.5 → как обычно
5. Cell 6 — для каждого товара лог:
   ```
   [N/total] Product
     → Scraping...
     → Vision...
     → Strategy (Opus 4.7)... voice=warm-confidant | idea: Twenty minutes of stalking equals an evening of peace
     → Generating JSON content...
       JSON OK: hero=True story=2 feat=3 stat=4 rev=12 faq=5 | $0.0234
       Tags: 8 valid
     → Shopify... Created: gid://shopify/...
       Metafields: 14/23 written (~14000 chars total)  ← число зависит от категории, optional модули скипаются
       Gallery: N/N (EPROLO)
   ```

## Как это работает

```
PIPELINE                                       SHOPIFY                            BROWSER
─────────                                      ────────                           ─────────
Strategy (Opus 4.7) — positioning per product
        ↓
Designer (Sonnet 4.6) — writes up to 21 content sections + 2 admin-only (photo_pack ZIP URL + source EPROLO origin record); FILL/SKIP per category;
        picks image_url's directly from EPROLO photo list
        ↓
Up to 23 custom.* JSON metafields              ──→ Shopify Admin Custom Data       ──→ 21 wanelo-*.liquid snippets
                                                                                    (skip-if-blank — невыделенные не рендерятся)
EPROLO photos (top images)                    ──→ productCreateMedia (carousel)   ──→ /products/handle карусель

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
- **`Liquid error: Metafield not found`** — определение метафилда не создано. Проверь Cell 2 вывод `Metafield definitions ensured: 23`. Если меньше 23 — старая версия Cell 2, обнови ноутбук.
- **JSON-LD FAQPage не валиден** — скорее всего designer написал кавычки или \n в quotes. Liquid filter `| json` экранирует.
- **Анимации не идут** — wanelo.js не загрузился. Проверь Network tab на наличие `wanelo.js → 200 OK`.
