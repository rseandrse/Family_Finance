# База дашборда (capability `db`)

Страница читает эти коллекции в реальном времени. Пишет их Claude через ArtifactData; семья пишет только `decisions` (решения совета) и ответы в `review`.

| Документ | Кто пишет | Содержимое |
|---|---|---|
| `config/main` | Claude | `{title, currency, currencySymbol, currencyLabel?, bigThreshold, adults:[{name, hobbyTitle, hobbyDesc}], kidsDesc, kidsName?, noKids, incomeGroups:[…], categoryNames?, excludedNote, excludedTile}` — из family.json. Пока в `months` нет ни одного документа, страница показывает встроенное демо; демо в базу не пишется |
| `months/YYYY-MM` | Claude | `{month, income:[{source, who, amount, group}], expenses:[{cat, amount, items:[{label, amount}]}], events:[…], excluded:[…], notes:[…]}` |
| `tx/YYYY-MM` | Claude | `{month, rows:[[день, сумма, cat \| "income" \| "excluded", статья, счёт, деталь]]}` — все операции месяца для окон подробностей |
| `accounts/YYYY` | Claude | `{year, accounts:[{id, name, owner?, currency? (если счёт не в основной валюте), color?, offStatement?, months:{YYYY-MM:{start, end, inc, exp, tin, tout, xl, cats, top, diff}}}]}` |
| `review/<id>` | Claude создаёт, семья отвечает | `{order, title, amount, count, months, current, suggest, question, src, status:"open"\|"ok"\|"move"\|"exclude", target, comment, answeredAt}` |
| `decisions/<auto>` | семья | `{month, text, done, createdAt}` |

`events`:
- поездка: `{type:"trip", cat, title, short, amount, dates:"ДД.ММ–ДД.ММ", details:["N операций с … по …", "Продавец — 12.34 € (3 оп.)", …], br:{Билеты, Жильё, Еда, Транспорт, "Покупки и прочее"}}`;
- крупная трата: `{type:"big", cat, title, amount, details:["ДД.ММ · 12.34 € · Счёт · описание банка", …]}`.

В расходах сумма положительная, возврат — отрицательный. Поступления в `tx` положительные.

## Загрузка
`build.py` готовит `out/upload_plan.json` — список пакетов. Каждый пакет передаётся в один вызов ArtifactData:

```
ArtifactData(action="batch", url=<URL дашборда>, writes=<пакет из upload_plan.json>)
```

В каждой записи пакета есть `op: "set"`, `collection`, `doc_id` и `file_path` (абсолютный путь к JSON). Ограничения батча: до 50 записей и 1 МБ, план уже разбит с запасом.

**Обновление существующих документов.** Запись в документ, который уже есть, без `if_version` будет отклонена. Перед загрузкой:
1. `ArtifactData(action="list", collection="months", url=…, query={"limit": 100})` — то же для `tx`, `accounts`, `config`, `review`;
2. добавьте `"if_version": <version>` в каждую запись пакета, у которой документ уже есть;
3. если пакет отклонён из-за смены версии (семья в этот момент ответила на вопрос и т.п.), перечитайте версию и повторите только эту запись.

**Не перезаписывайте ответы семьи.** Документы `review`, на которые уже ответили (status ≠ "open"), не загружайте заново. Новые вопросы создавайте с новыми id.

**Слишком большой месяц.** Если `tx/YYYY-MM.json` больше ~900 КБ (это примерно 8–9 тысяч операций), уберите из `rows` шестую колонку «деталь» у мелких операций или сократите описания. Дашборд читает один документ на месяц.

## Удаление
Если месяц удалили из выписок, удалите его документы: `ArtifactData(action="delete", collection="months", doc_id="YYYY-MM", if_version=…)` и то же для `tx`.
