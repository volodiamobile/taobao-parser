# -*- coding: utf-8 -*-
"""Обновление цен артикулов уже выложенного товара e-mall (без создания нового товара).

Как работает:
  1. разбирает товар Taobao (1 запрос к RapidAPI) → артикулы с ценой со скидкой в юанях;
  2. берёт артикулы магазина через shop.product.getInfo;
  3. сопоставляет по названию (без учёта регистра, скобок и лишних пробелов);
  4. показывает таблицу изменений;
  5. с --apply обновляет purchase_price через shop.product.skus.update.

Запуск (по умолчанию только показывает, ничего не меняет):
  python update_prices.py --product 123 --url "https://item.taobao.com/item.htm?id=987854389766"
  python update_prices.py --product 123 --url ... --apply
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import requests  # noqa: E402
from shop_uploader import ShopScriptUploader  # noqa: E402
import taobao_parser as tp  # noqa: E402

API_URL = "https://e-mall.su/api.php/"


def _token():
    tok = (os.environ.get("SHOP_API_TOKEN") or "").strip()
    if tok:
        return tok
    for path in (os.path.join(BASE, ".streamlit", "secrets.toml"),
                 os.path.join(BASE, "secrets.toml")):
        try:
            txt = io.open(path, encoding="utf-8").read()
        except OSError:
            continue
        m = re.search(r"SHOP_API_TOKEN\s*=\s*[\"']([^\"']+)", txt)
        if m:
            return m.group(1).strip()
    raise SystemExit("Нет SHOP_API_TOKEN (env или .streamlit/secrets.toml)")


def _norm(name):
    s = (name or "").lower()
    s = re.sub(r"[()（）]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", required=True, help="id товара в магазине")
    ap.add_argument("--url", required=True, help="ссылка или id товара Taobao")
    ap.add_argument("--apply", action="store_true", help="записать изменения (иначе только показать)")
    args = ap.parse_args()

    url = args.url
    if url.isdigit():
        url = f"https://item.taobao.com/item.htm?id={url}"

    print("🔎 Разбор Taobao...")
    res = tp.run_parser(url)
    if not res:
        raise SystemExit("Не удалось разобрать товар Taobao")
    new_map = {}
    for sku in res["skus"]:
        new_map.setdefault(_norm(sku["name"]), sku)

    print("🛒 Чтение товара в магазине...")
    tok = _token()
    r = requests.get(API_URL + "shop.product.getInfo", params={"access_token": tok, "id": args.product}, timeout=30)
    info = r.json()
    product = info.get("product", info)
    shop_skus = product.get("skus") or []
    if not shop_skus:
        raise SystemExit("В товаре магазина нет артикулов")

    up = ShopScriptUploader(tok)
    changed = 0
    print("\n%-52s %10s %10s" % ("артикул", "сейчас", "новая"))
    print("-" * 76)
    for s in shop_skus:
        key = _norm(s.get("name"))
        new = new_map.get(key)
        cur = s.get("purchase_price")
        if not new:
            print("%-52s %10s %10s  (нет пары в Taobao)" % ((s.get("name") or "")[:52], cur, "-"))
            continue
        target = int(new["price"])
        mark = "" if str(cur) == str(target) else "  ← изменить"
        print("%-52s %10s %10s%s" % ((s.get("name") or "")[:52], cur, target, mark))
        if str(cur) != str(target):
            changed += 1
            if args.apply:
                resp = up._post("shop.product.skus.update", params={"id": s["id"]},
                                data={"purchase_price": target})
                if resp.get("error"):
                    print("   ❌ ", resp.get("error_description", resp["error"]))
                else:
                    print("   ✅ обновлено")

    print("\nИтого к изменению: %d" % changed)
    if not args.apply and changed:
        print("Запустите с --apply, чтобы записать.")


if __name__ == "__main__":
    main()
