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
