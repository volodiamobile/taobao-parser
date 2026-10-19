"""Суточный лимит разборов товаров (защита от перерасхода RapidAPI).

Basic-план Toabao Open API: 20 запросов в день, сверх — $0.008 за запрос.
Счётчик хранится в usage_counter.json рядом с приложением; на Streamlit Cloud
файловая система эфемерная (сбрасывается при перезапуске/редеплое), поэтому
лимит — мягкая защита, а не биллинг.
"""

import json
import os
import tempfile
from datetime import date

_DIR = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(_DIR, "usage_counter.json")
LIMIT = int(os.environ.get("DAILY_PARSE_LIMIT", "20"))


def _load():
    try:
        with open(_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save(data):
    try:
        fd, tmp = tempfile.mkstemp(dir=_DIR, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, _PATH)
    except Exception:
        pass  # счётчик не должен ломать приложение


def used_today():
    return int(_load().get(date.today().isoformat(), 0))


def remaining_today():
    return max(0, LIMIT - used_today())


def consume():
    """Резервирует один разбор. Возвращает остаток или -1, если лимит исчерпан."""
    day = date.today().isoformat()
    data = _load()
    used = int(data.get(day, 0))
    if used >= LIMIT:
        return -1
    data[day] = used + 1
    # храним только последние 14 дней
    for k in sorted(data)[:-14]:
        data.pop(k, None)
    _save(data)
    return LIMIT - used - 1
