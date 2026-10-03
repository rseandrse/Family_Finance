# Файлы в work/

## sources.json — как читать каждую выписку
Список, по объекту на файл.

```json
[
  {"file": "uploads/wise.csv", "account": "Wise",
   "header_row": 0, "date": "Date", "date_format": "%d-%m-%Y",
   "amount": "Amount", "description": ["Description", "Merchant", "Payment Reference"],
   "balance": "Running Balance",
   "time": "Date Time", "time_format": "%d-%m-%Y %H:%M:%S.%f",
   "currency": "Currency"},
  {"file": "uploads/bank.xlsx", "account": "Общий счёт", "sheet": 0, "header_row": 3,
   "date": "Booking date", "debit": "Debit", "credit": "Credit", "description": ["Text"],
   "balance": "Balance", "skip_regex": "Opening balance|Closing balance|Previous balance"},
  {"file": "uploads/es.csv", "account": "Карта Bizum", "delimiter": ";", "decimal": ",",
   "date": "Fecha", "date_format": "%d/%m/%Y", "amount": "Importe", "description": ["Concepto", "Movimiento"], "balance": "Saldo"}
]
```

| Поле | Что значит |
|---|---|
| `file` | путь к выписке |
| `account` | название счёта на дашборде (коротко и понятно семье) |
| `header_row` | номер строки с названиями колонок в «сырой» таблице (из `inspect_statement.py`) |
| `sheet` | лист Excel (имя или номер) |
| `encoding`, `delimiter` | для CSV, если автоопределение ошиблось |
| `date`, `date_format` | колонка даты и формат strptime; без формата — автоматически, день первым |
| `amount` | одна колонка со знаком (минус — списание) |
| `debit` + `credit` | две колонки: списания и поступления (положительные числа) |
| `invert` | `true`, если банк пишет списания плюсом |
| `decimal` | `","` для чисел вида `1.234,56` |
| `description` | колонка или список колонок; склеиваются через ` \| ` |
| `balance` | остаток после операции — нужен для блока «Счета» |
| `time`, `time_format` | точное время, чтобы правильно упорядочить операции одного дня |
| `currency` | колонка с валютой операции (мультивалютные карты) |
| `account_currency` | валюта всего файла, если в выписке её нет (`"RUB"`, `"USD"`) |
| `keep_currency` | оставить только операции в этой валюте (остальные отбросить) |
| `skip_regex` | строки, которые не являются операциями (итоги, начальный остаток) |

Если выписки одного счёта пришли несколькими файлами за разные периоды, сделайте по записи на файл с одинаковым `account` — они склеятся. Не допускайте пересечения периодов, иначе операции задвоятся.

`normalize.py` пишет `work/transactions.csv`: `date, amount, account, description, balance, currency, seq`. Суммы остаются в исходной валюте, в основную их переводит `build.py`.

## fx.json — курсы (если валют больше одной)
Создаётся `fx_rates.py`; можно поправить руками. Значение — сколько единиц основной валюты стоит 1 единица другой в этом месяце.
```json
{"USD": {"2026-01": 0.853, "2026-02": 0.861, "_source": "ECB monthly average (frankfurter.dev)"},
 "EUR": {"2026-07": 93.97, "_source": "approx: current rate (open.er-api.com)"}}
```
Если курса для месяца нет, `build.py` остановится и подскажет, чего не хватает.

## family.json — настройки семьи

```json
{
  "title": "Семейные финансы",
  "year": 2026,
  "currency": "EUR",
  "adults": [
    {"name": "Анна", "hobbyTitle": "Хобби Анны", "hobbyDesc": "йога, курсы"},
    {"name": "Иван", "hobbyTitle": "Хобби Ивана", "hobbyDesc": "фото, велосипед"}
  ],
  "kidsDesc": "школа, кружки, лагеря",
  "noKids": false,
  "incomeGroups": ["Зарплата Анны", "Зарплата Ивана"],
  "excludedNote": "Рабочие расходы, которые возмещает компания. Видны здесь, но не входят в итоги",
  "excludedTile": "рабочие расходы — показаны отдельно",
  "bigExcludeRegex": "Снятие наличных",
  "accountColors": {"Wise": "#3b6fd8"},
  "accountOwners": {"Wise": "Анна", "Карта Ивана": "Иван", "Общий счёт": "общий"},
  "kidsName": "Дети",
  "categoryNames": {"fun": "Спорт и развлечения"}
}
```
- Первый взрослый — категория `hobby_s`, второй — `hobby_m`. Один взрослый — один элемент в `adults`.
- До 4 групп дохода. Остальные поступления попадают в «Прочее».
- `currency` — основная валюта семьи (ISO-код: RUB, GEL, EUR, USD, KZT…). Символ берётся автоматически; `currencySymbol` и `currencyLabel` («рубли») можно задать вручную.
- `bigThreshold` — сумма за месяц по одной статье, начиная с которой трата попадает в «Крупное». Без значения — ~12% среднего месячного расхода. Продукты, кафе и платежи, которые повторяются в большинстве месяцев (аренда, кредит), туда не попадают.
- `smallIncomeThreshold` — поступления «Прочее» меньше этой суммы сворачиваются в «Мелкие поступления». Без значения — ~4% месячного расхода.
- `accountOwners` — чей счёт; показывается в блоке «Счета». Нужен, когда загружены выписки обоих партнёров.
- `noKids: true` скрывает фильтр, плитку и строку «Дети». `kidsName` и `categoryNames.kids` позволяют использовать эту категорию под другое (например, питомца).
- `categoryNames` переименовывает любые категории на дашборде; id категорий не меняются.

## rules.json — правила семьи
Список. Проверяется сверху вниз, затем стартовые правила. Первое совпадение побеждает.

```json
[
  {"id": "own", "match": "SENT MONEY TO ANNA PETROVA|TRANSFER OWN FUNDS", "type": "internal", "note": "переводы между своими счетами"},
  {"id": "salary-anna", "match": "PAYROLL ACME", "dir": "in", "type": "inc", "label": "Зарплата Анны (ACME)", "group": "Зарплата Анны"},
  {"id": "rent", "match": "ALQUILER|GARCIA LOPEZ", "dir": "out", "cat": "housing", "label": "Аренда квартиры"},
  {"id": "school", "match": "OLIVE TREE", "cat": "kids", "label": "Школа Olive Tree"},
  {"id": "yoga", "match": "YOGA STUDIO", "cat": "hobby_s", "label": "Йога"},
  {"id": "bizum-dance", "match": "BIZUM.*ZARINA", "cat": "hobby_m", "label": "Танцы: Зарина", "note": "сказала Анна 3.10"},
  {"id": "work", "match": "FREELANCE PROJECT", "type": "excl", "label": "Расходы проекта", "reason": "Работа: возместит клиент"},
  {"id": "big-cash", "match": "ATM", "account": "Wise", "min": 1000, "cat": "other", "label": "Крупное снятие наличных"}
]
```

| Поле | Значение |
|---|---|
| `match` | регулярное выражение по описанию операции, без учёта регистра |
| `type` | `exp` (по умолчанию), `inc`, `internal`, `excl` |
| `cat` | категория для `exp` (см. categories.md) |
| `label` | как статья будет названа на дашборде; без него — очищенное описание банка |
| `group` | группа дохода для `inc` |
| `reason` | причина для `excl` («Работа», «Проект X») |
| `who` | чей доход для `inc` («Анна») |
| `dir` | `out` — только списания, `in` — только поступления |
| `account` | regex по названию счёта |
| `min`, `max` | границы суммы (по модулю) |
| `from`, `to` | границы дат `YYYY-MM-DD` |
| `id`, `note` | для людей: откуда правило |

Правило без `dir` ловит и возвраты: возврат от магазина уменьшит ту же категорию.

## trips.json — поездки

```json
[
  {"id": "lisbon", "name": "Поездка в Лиссабон", "short": "Лиссабон", "start": "2026-06-10", "end": "2026-06-14",
   "cat": "travel", "match": "LISBOA|LISBON|RYANAIR|HOTEL|BOLT",
   "extra": [{"match": "RYANAIR", "from": "2026-04-01", "to": "2026-04-30"}]},
  {"id": "clinic", "name": "Поездка в клинику (Мюнхен)", "start": "2026-03-03", "end": "2026-03-10", "cat": "health"}
]
```
- Без `match` в поездку попадут все траты в эти даты из категорий travel, cafe, groceries, transport, fun, shopping, health, other. Добавляйте `match` (города, отели, авиакомпании), если кто-то из семьи оставался дома и тратил там.
- `exclude` — regex того, что не относится к поездке.
- `extra` — билеты или отели, купленные заранее, вне дат поездки.
- `accounts` — regex счетов, с которых платили в поездке.

## manual.json — покупки вне выписок

```json
[{"month": "2026-06", "title": "Машина: первый взнос", "amount": 9000, "cat": "transport",
  "financed": true, "incomeTitle": "Кредит на машину", "note": "оплачено автосалону напрямую из банка-кредитора"}]
```
Эти покупки попадают в траты месяца, в «Крупное» и на счёт «Оплата вне выписок». `financed: true` добавляет ту же сумму в доход, тогда на итог месяца покупка не влияет.

## notes.json

```json
{"2026-09": ["Плюс 2,5 тыс. €.", "Продукты — 3,9 тыс. €, максимум за год."]}
```

## review.json — вопросы семье

```json
[{"id": "bizum-gracias", "order": 1, "title": "Bizum «Gracias»", "amount": 940, "count": 12,
  "months": ["2026-02", "2026-05"], "current": "other", "suggest": "other",
  "question": "Кому эти переводы? Это помощь, долги или оплата услуг?",
  "src": ["14.02 · 120.00 € · Карта Bizum · Bizum enviado | Gracias"]}]
```
`current` и `suggest` — id категории, либо `income` или `excluded`. Семья отвечает на вкладке «Проверка».
