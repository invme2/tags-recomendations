# 💰 Billing — три сервиса, которые надо пополнять

Пайплайн зависит от **трёх платных API**. Если хоть один в нуле — прогон встанет посередине, потратив деньги в остальных двух впустую. Перед каждой большой пачкой товаров — пройди по чек-листу ниже.

## Где и сколько

| Сервис | Где пополнять | Что списывает | Примерный расход на 1 товар |
|---|---|---|---|
| **Anthropic** (Claude API) | https://console.anthropic.com/settings/billing | Vision (Haiku 4.5) + Strategy (Opus 4.7) + Designer (Sonnet 4.6) | **~$0.25** |
| **OpenAI** (gpt-image-2) | https://platform.openai.com/settings/organization/billing/overview | 5 gallery + 3-7 metafield фото через `images.edit` | **~$0.50** (medium) / **$0.06** (low) / **$2.00** (high) |
| **DataForSEO** (SEO research) | https://app.dataforseo.com/billing | 1 раз на пачку: keyword volumes + KD + CPC. Не масштабируется на 1 товар | **~$3.75** на батч (не на товар) |

### Расход на разные размеры пачки

С `IMAGE_GEN_QUALITY = "medium"`:

| Товаров | Anthropic | OpenAI | DataForSEO | **Итого** |
|---|---|---|---|---|
| 3 | $0.75 | $1.50 | $3.75 | **$6.00** |
| 10 | $2.50 | $5.00 | $3.75 | **$11.25** |
| 50 | $12.50 | $25.00 | $7.50 | **$45.00** |
| 100 | $25.00 | $50.00 | $15.00 | **$90.00** |

Если хочешь резко уменьшить — `IMAGE_GEN_QUALITY = "low"` срежет OpenAI в ~7 раз. Качество фото хуже (заметные артефакты), но flow проверишь.

## Лимиты (hard limit) у каждого

### Anthropic
В Console → Settings → Billing → **Spend Limits**. Дефолт Tier 1 = $100/month. Если достигнут — все API-вызовы вернут `429`. Поднимать в зависимости от tier'а.

### OpenAI
Settings → **Limits** → **Monthly budget**. Дефолт зависит от способа оплаты. Если на prepaid — лимит = баланс. Постоянно проверяй **Current balance** в Billing overview.

❗ Если упрётся в лимит — `400 billing_hard_limit_reached` (тоже что было у тебя). Восстанавливается после пополнения / поднятия лимита, не моментально (~5 минут propagation).

### DataForSEO
Prepaid only — балансом. На главной dashboard видна сумма. Стоимость **очень предсказуемая** ($0.075 за live SERP запрос, ~50 запросов на пачку = ~$3.75). Класть стоит сразу $20-30 — хватит на ~5-7 пачек.

## API Organization Verification (только OpenAI, для gpt-image-2)

Без верификации (KYC через Persona) `gpt-image-2` отвечает 403 «model not found / must be verified». Один раз на org:

https://platform.openai.com/settings/organization/general → внизу страницы → **API Organization Verification** → ID + selfie (~5 минут) → подождать ~1 час на propagation.

## Если что-то упало посреди прогона

Пайплайн **resumable** — статус каждого товара в SQLite, при перезапуске Cell 6 продолжит с того же места. То есть:

1. Ловишь `429 / 400 billing limit` в логе
2. Идёшь в соответствующий dashboard, пополняешь
3. Запускаешь Cell 6 заново — пропустит `done` товары, переподнимет `pending`/`error` на нужном статусе

Стоимость уже потраченных шагов **не теряется** — только переcхватятся незавершённые товары.

## Диагностика gpt-image-2

`pipeline/tools/test_openai_image.py` — 5 пошаговых проверок (key + auth + org verify + generate + edit). Стоит ~$0.012. Запускать перед первым реальным прогоном после пополнения.

```python
import os
from google.colab import userdata
os.environ["OPENAI_API_KEY"] = userdata.get("OPENAI_API_KEY")

!pip install openai -q
!curl -sL https://raw.githubusercontent.com/invme2/tags-recomendations/claude/enrich-shopify-taxonomy-kMPmA/pipeline/tools/test_openai_image.py -o /tmp/t.py
!python /tmp/t.py
```
