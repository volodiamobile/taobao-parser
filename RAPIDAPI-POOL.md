# RapidAPI — пул аккаунтов парсера Taobao (30.10.2026)

Задача владельца: бесплатный тариф RapidAPI даёт по 20 запросов на аккаунт,
аккаунтов теперь два — считать запросы и переключаться, чтобы не упираться в лимит.

## Что добавлено

| Файл | Назначение |
|---|---|
| `taobao-parser/api_pool.py` | пул аккаунтов: счётчики, лимит, автопереключение, CLI |
| `taobao-parser/rapidapi_accounts.json` | аккаунты (ключи) + `provider.host`, `provider.proxy` |
| `taobao-parser/_usage/rapidapi_usage.json` | счётчики по периодам (создаётся автоматически) |
| `taobao-parser/taobao_parser.py` | `get_taobao_product()` берёт ключ из пула, считает запрос, при 401/403/429 переключается на следующий аккаунт |

Бэкап парсера до правки: `taobao_parser.py.bak.2026-10-30-accounts-pool`.

## Как считается лимит

- Лимит по умолчанию: **20 запросов в СУТКИ на аккаунт** (`limit` в JSON, период `day`).
  Решение владельца 30.10.2026: 20 в день на аккаунт, два аккаунта → 40 в сутки.
- Период: `day` (текущий), `month` или `total`; при смене периода счётчик обнуляется сам.
- Квоту тратят все ответы, дошедшие до API; 401/403/407/451 (блокировка на входе) — не тратят.
- Если RapidAPI в ответе присылает `x-ratelimit-requests-limit` / `-remaining`, остаток
  синхронизируется с реальным состоянием тарифа (заголовки имеют приоритет).
- Остаток = min(лимит − израсходовано, остаток из заголовка).
- Выбирается аккаунт с **наибольшим остатком**; при равенстве — менее использованный.
- HTTP 451 (гео-блок) и сетевые ошибки квоту **не** расходуют.

## CLI

```powershell
cd C:\Users\Admin\.openclaw\workspace\taobao-parser
python api_pool.py status                       # таблица: сколько осталось по каждому аккаунту
python api_pool.py next                         # какой аккаунт будет выбран следующим
python api_pool.py add --label acc3 --key <ключ> [--limit 20] [--period month]
python api_pool.py disable --id acc3            # / enable
python api_pool.py reset --id acc2              # обнулить счётчик периода
python api_pool.py sync --id acc1 --remaining 7 # ручная коррекция остатка
```

## Аккаунты в пуле

- `acc1` (rapidapi-1) — ключ из `.streamlit/secrets.toml`, 20/сутки.
- `acc2` (rapidapi-2) — новый аккаунт владельца (ключ передан 30.10.2026), 20/сутки.

## Блокер: гео-блок 451 — обойдён через US-узел

Прямой выход (RU) и большинство узлов Clash отдают **HTTP 451** («Nokia services… embargoed
countries»). Проверено 30.10.2026: EE (178.130.46.183), CA (147.45.177.229), HK (62.60.232.9) — 451;
**USA-Phoenix-2 (212.18.104.51, США) — гео-блок проходит**. Многие узлы (DE/UK/FR/SE/HR/AT/BE/SP
и варианты -CF) на момент проверки не отвечают (connection reset 10054).

Инструменты: `_tools/clash_ctl.py` (API Clash через named pipe), `_tools/clash_groups.py`
(список групп/узлов), `_tools/rapidapi_egress_probe.py` (перебор узлов + проба RapidAPI).
Группа `🌍 Proxy` на момент отчёта переключена на `USA-Phoenix-2`.

## Текущий блокер: подписка не оформлена (403)

С US-узла оба ключа получают `403 {"message":"You are not subscribed to this API."}` —
подписка на листинг `toabao-open-api` не активна. Нужно на странице
`rapidapi.com/open-trade-commerce-open-trade-commerce-default/api/toabao-open-api`
нажать **Subscribe** на бесплатном плане под каждым аккаунтом. 403 квоту не тратит.

- переменная окружения `RAPIDAPI_PROXY=http://host:port`, или
- `"proxy": "http://host:port"` в `rapidapi_accounts.json` → `provider`.

Рабочая альтернатива сейчас — BHAPI (в черновиках, не используем с 30.10.2026:
файлы в `_drafts/bhapi/`).
