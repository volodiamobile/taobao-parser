# -*- coding: utf-8 -*-
"""Пул аккаунтов RapidAPI для парсера Taobao.

Зачем: у бесплатного тарифа RapidAPI жёсткий лимит запросов на аккаунт
(по умолчанию 20, подтверждено владельцем 30.10.2026). Модуль считает
израсходованные запросы по каждому аккаунту и переключается на следующий,
когда у текущего лимит подходит к концу.

Файлы:
  rapidapi_accounts.json      — список аккаунтов (id, label, key, limit, period, enabled)
  _usage/rapidapi_usage.json  — счётчики (used, quota_remaining из заголовков, period_start)

Логика лимита:
  остаток = min(limit - used, quota_remaining)   # quota_remaining приходит от RapidAPI
  Если RapidAPI прислал заголовки x-ratelimit-requests-limit / -remaining,
  они имеют приоритет: остаток синхронизируется с реальным состоянием тарифа.

CLI:
  python api_pool.py status                       # таблица аккаунтов и остатков
  python api_pool.py add --label acc2 --key XXX   # добавить аккаунт (ключ можно не печатать)
  python api_pool.py disable --id acc2
  python api_pool.py enable --id acc2
  python api_pool.py reset --id acc2              # обнулить счётчик периода
  python api_pool.py sync --id acc1 --remaining 7 # ручная коррекция остатка
  python api_pool.py next                         # какой аккаунт будет выбран следующим
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
ACCOUNTS_PATH = os.path.join(BASE, "rapidapi_accounts.json")
USAGE_DIR = os.path.join(BASE, "_usage")
USAGE_PATH = os.path.join(USAGE_DIR, "rapidapi_usage.json")

DEFAULT_LIMIT = 20          # запросов на аккаунт за период (бесплатный тариф RapidAPI)
DEFAULT_PERIOD = "month"    # "month" | "day" | "total"
DEFAULT_RESERVE = 1         # оставляем 1 запрос в запасе, чтобы не упереться в 429


class ApiPoolError(RuntimeError):
    """Аккаунтов с доступным остатком нет."""


# ---------------------------------------------------------------- storage ---

def _read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except Exception:
        return default


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_accounts():
    data = _read_json(ACCOUNTS_PATH, {"provider": {}, "accounts": []})
    if isinstance(data, list):          # старый/упрощённый формат
        data = {"provider": {}, "accounts": data}
    data.setdefault("provider", {})
    data.setdefault("accounts", [])
    return data


def save_accounts(data):
    _write_json(ACCOUNTS_PATH, data)


def load_usage():
    data = _read_json(USAGE_PATH, {"accounts": {}})
    data.setdefault("accounts", {})
    return data


def save_usage(data):
    _write_json(USAGE_PATH, data)


# ------------------------------------------------------------------ period ---

def period_key(period):
    now = datetime.now(timezone.utc).astimezone()
    p = (period or DEFAULT_PERIOD).lower()
    if p == "day":
        return now.strftime("%Y-%m-%d")
    if p == "total":
        return "all"
    return now.strftime("%Y-%m")     # month


def _state_for(usage, acc):
    """Состояние аккаунта с автосбросом при смене периода."""
    acc_id = acc["id"]
    pkey = period_key(acc.get("period"))
    st = usage["accounts"].get(acc_id)
    if not st or st.get("period") != pkey:
        st = {
            "period": pkey,
            "used": 0,
            "quota_remaining": None,
            "limit_from_api": None,
            "last_status": None,
            "last_call": None,
        }
        usage["accounts"][acc_id] = st
    return st


def _limit_of(acc, st):
    lim = st.get("limit_from_api") or acc.get("limit") or DEFAULT_LIMIT
    try:
        lim = int(lim)
    except (TypeError, ValueError):
        lim = DEFAULT_LIMIT
    return lim


def remaining_of(acc, st):
    """Сколько запросов ещё доступно у аккаунта в текущем периоде."""
    lim = _limit_of(acc, st)
    rest = lim - int(st.get("used") or 0)
    qr = st.get("quota_remaining")
    if qr is not None:
        try:
            rest = min(rest, int(qr))
        except (TypeError, ValueError):
            pass
    return max(0, rest)


# -------------------------------------------------------------------- pool ---

def pick_account(need=1, exclude=None):
    """Возвращает (account, state) с наибольшим остатком. None — если всё исчерпано."""
    accounts = load_accounts()
    usage = load_usage()
    exclude = set(exclude or ())
    best = None
    changed = False
    for acc in accounts["accounts"]:
        if not acc.get("enabled", True) or not (acc.get("key") or "").strip():
            continue
        if acc.get("id") in exclude:
            continue
        st = _state_for(usage, acc)
        rest = remaining_of(acc, st)
        if rest < need:
            continue
        # приоритет: больше остатка; при равенстве — меньше потрачено
        score = (rest, -int(st.get("used") or 0))
        if best is None or score > best[0]:
            best = (score, acc, st)
    if changed:
        save_usage(usage)
    if not best:
        return None, None
    return best[1], best[2]


def next_key(need=1, exclude=None):
    """(account_id, key) для следующего запроса. Бросает ApiPoolError, если всё исчерпано."""
    acc, _ = pick_account(need=need, exclude=exclude)
    if not acc:
        raise ApiPoolError(describe_exhausted())
    return acc["id"], acc["key"].strip()


def record_call(acc_id, status=None, headers=None, exhausted=False, count=True):
    """Учитывает один запрос: +1 в счётчик и синхронизация с заголовками RapidAPI.

    count=False — запрос не дошёл до API (гео-блок 451, сетевой сбой), квота не тратится.
    """
    accounts = load_accounts()
    usage = load_usage()
    acc = next((a for a in accounts["accounts"] if a.get("id") == acc_id), None)
    if not acc:
        return
    st = _state_for(usage, acc)
    if count:
        st["used"] = int(st.get("used") or 0) + 1
    st["last_status"] = status
    st["last_call"] = datetime.now().astimezone().isoformat(timespec="seconds")
    if status == 451:
        st["geo_blocked"] = True
    elif count:
        st["geo_blocked"] = False
    if headers:
        h = {str(k).lower(): v for k, v in dict(headers).items()}
        lim = h.get("x-ratelimit-requests-limit")
        rem = h.get("x-ratelimit-requests-remaining")
        try:
            if lim not in (None, ""):
                st["limit_from_api"] = int(lim)
        except (TypeError, ValueError):
            pass
        try:
            if rem not in (None, ""):
                st["quota_remaining"] = int(rem)
        except (TypeError, ValueError):
            pass
        if h.get("x-ratelimit-requests-reset"):
            st["reset_at"] = str(h["x-ratelimit-requests-reset"])
    if exhausted:
        st["quota_remaining"] = 0
    elif count and st.get("quota_remaining") is not None:
        st["quota_remaining"] = max(0, int(st["quota_remaining"]) - 1)
    save_usage(usage)


def get_proxy():
    """Прокси для запросов к RapidAPI (dict для requests) или None.

    Приоритет: env RAPIDAPI_PROXY > provider.proxy в rapidapi_accounts.json.
    Нужен потому, что RapidAPI отдаёт 451 (Nokia/эмбарго) на российские адреса.
    """
    raw = (os.environ.get("RAPIDAPI_PROXY") or
           (load_accounts().get("provider") or {}).get("proxy") or "").strip()
    if not raw:
        return None
    return {"http": raw, "https": raw}


def remaining_for(acc_id):
    """Остаток конкретного аккаунта (None, если аккаунт не найден)."""
    accounts = load_accounts()
    usage = load_usage()
    acc = next((a for a in accounts["accounts"] if a.get("id") == acc_id), None)
    if not acc:
        return None
    return remaining_of(acc, _state_for(usage, acc))


def set_remaining(acc_id, remaining):
    accounts = load_accounts()
    usage = load_usage()
    acc = next((a for a in accounts["accounts"] if a.get("id") == acc_id), None)
    if not acc:
        raise SystemExit(f"Аккаунт {acc_id} не найден")
    st = _state_for(usage, acc)
    st["quota_remaining"] = max(0, int(remaining))
    save_usage(usage)


def reset_account(acc_id=None):
    accounts = load_accounts()
    usage = load_usage()
    ids = [a["id"] for a in accounts["accounts"]] if not acc_id else [acc_id]
    for aid in ids:
        usage["accounts"].pop(aid, None)
    save_usage(usage)


def add_account(label, key, limit=DEFAULT_LIMIT, period=DEFAULT_PERIOD, acc_id=None):
    data = load_accounts()
    acc_id = acc_id or label or f"acc{len(data['accounts']) + 1}"
    for a in data["accounts"]:
        if a.get("id") == acc_id:
            a["label"] = label
            a["key"] = key
            a["limit"] = limit
            a["period"] = period
            a["enabled"] = True
            break
    else:
        data["accounts"].append({
            "id": acc_id,
            "label": label,
            "key": key,
            "limit": limit,
            "period": period,
            "enabled": True,
            "added_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        })
    save_accounts(data)
    return acc_id


def describe_exhausted():
    accounts = load_accounts()
    usage = load_usage()
    rows = []
    for acc in accounts["accounts"]:
        if not acc.get("enabled", True):
            continue
        st = _state_for(usage, acc)
        rows.append(f"{acc['label']}: остаток {remaining_of(acc, st)}/{_limit_of(acc, st)}")
    tail = ("; ".join(rows)) if rows else "аккаунтов нет"
    return ("Лимит RapidAPI исчерпан по всем аккаунтам (" + tail +
            "). Добавьте аккаунт: python api_pool.py add --label accN --key <ключ>")


# --------------------------------------------------------------------- CLI ---

def _fmt_reset(seconds):
    if seconds <= 0:
        return "сейчас"
    h, rem = divmod(int(seconds), 3600)
    m = rem // 60
    return f"{h} ч {m} мин" if h else f"{m} мин"


def cmd_status():
    accounts = load_accounts()
    usage = load_usage()
    if not accounts["accounts"]:
        print("Аккаунтов RapidAPI нет. Добавьте: python api_pool.py add --label acc1 --key <ключ>")
        return 1
    print(f"{'id':<8}{'название':<16}{'период':<8}{'исп.':>6}{'лимит':>7}{'остаток':>9}  состояние")
    total_rest = 0
    for acc in accounts["accounts"]:
        st = _state_for(usage, acc)
        lim = _limit_of(acc, st)
        rest = remaining_of(acc, st)
        total_rest += rest if acc.get("enabled", True) else 0
        state = "ок" if acc.get("enabled", True) else "выключен"
        if acc.get("enabled", True) and rest <= 0:
            state = "исчерпан"
        print(f"{acc['id']:<8}{(acc.get('label') or '')[:15]:<16}{(acc.get('period') or DEFAULT_PERIOD):<8}"
              f"{int(st.get('used') or 0):>6}{lim:>7}{rest:>9}  {state}")
    print(f"\nВсего доступно запросов: {total_rest}")
    tips = usage.get("accounts", {})
    last = max((s.get("last_call") or "" for s in tips.values()), default="")
    if last:
        print(f"Последний запрос: {last}")
    return 0


def cmd_next():
    acc, st = pick_account(need=1)
    if not acc:
        print(describe_exhausted())
        return 1
    print(f"Следующий аккаунт: {acc['id']} ({acc.get('label')}), остаток {remaining_of(acc, st)}/"
          f"{_limit_of(acc, st)}")
    return 0


def main(argv):
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd = argv[0]
    opts = {}
    i = 1
    while i < len(argv):
        a = argv[i]
        if a.startswith("--"):
            if "=" in a:
                k, v = a[2:].split("=", 1)
                opts[k] = v
            elif i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                opts[a[2:]] = argv[i + 1]
                i += 1
            else:
                opts[a[2:]] = True
        i += 1

    if cmd == "status":
        return cmd_status()
    if cmd == "next":
        return cmd_next()
    if cmd == "add":
        label = opts.get("label") or opts.get("id") or f"acc{len(load_accounts()['accounts']) + 1}"
        key = opts.get("key")
        if not key:
            print("Нужен --key <ключ RapidAPI>")
            return 2
        aid = add_account(label, key,
                          limit=int(opts.get("limit") or DEFAULT_LIMIT),
                          period=opts.get("period") or DEFAULT_PERIOD,
                          acc_id=opts.get("id") or label)
        print(f"Добавлен аккаунт {aid} (лимит {opts.get('limit') or DEFAULT_LIMIT}, период "
              f"{opts.get('period') or DEFAULT_PERIOD})")
        return 0
    if cmd in ("disable", "enable"):
        data = load_accounts()
        aid = opts.get("id")
        for a in data["accounts"]:
            if a.get("id") == aid:
                a["enabled"] = (cmd == "enable")
                save_accounts(data)
                print(f"Аккаунт {aid}: {'включён' if cmd == 'enable' else 'выключен'}")
                return 0
        print(f"Аккаунт {aid} не найден")
        return 2
    if cmd == "reset":
        reset_account(opts.get("id"))
        print("Счётчики сброшены: " + (opts.get("id") or "все аккаунты"))
        return 0
    if cmd == "sync":
        if not opts.get("id") or opts.get("remaining") is None:
            print("Нужно: sync --id <acc> --remaining <N>")
            return 2
        set_remaining(opts["id"], int(opts["remaining"]))
        print(f"Остаток {opts['id']} установлен: {opts['remaining']}")
        return 0
    print(f"Неизвестная команда: {cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
