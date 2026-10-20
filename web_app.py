import streamlit as st
import os
import json
from taobao_parser import run_parser, extract_url_from_text
from shop_uploader import ShopScriptUploader

st.set_page_config(page_title="Taobao/Tmall Parser", page_icon="🛒", layout="wide")

ACCESS_PASSWORD = os.environ.get("APP_PASSWORD", st.secrets.get("APP_PASSWORD", "taobao2024"))

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("🔐 Вход в парсер Taobao/Tmall")
    password = st.text_input("Введите пароль доступа:", type="password")
    if st.button("Войти"):
        if password == ACCESS_PASSWORD:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("❌ Неверный пароль")
    st.stop()

st.title("🛒 Парсер товаров Taobao/Tmall")
st.markdown("Вставьте ссылку на товар и нажмите кнопку «Обработать»")

try:
    import usage_guard
    st.sidebar.caption("Разборов сегодня: %d из %d (осталось %d)" % (usage_guard.used_today(), usage_guard.LIMIT, usage_guard.remaining_today()))
except Exception:
    pass

if st.sidebar.button("🚪 Выйти"):
    st.session_state.authenticated = False
    st.rerun()

# === Разбор через локальный парсер (очередь заданий) ===
import time as _time
QUEUE_URL = "https://e-mall.su/taobao-queue/api.php"
queue_token = os.environ.get("TAOBAO_QUEUE_TOKEN", st.secrets.get("TAOBAO_QUEUE_TOKEN", ""))

st.markdown("Вставьте ссылку — задание заберёт локальный парсер на ПК, результат появится здесь через 20–60 секунд.")

url = st.text_input("Ссылка на товар Taobao/Tmall:", placeholder="https://item.taobao.com/item.htm?id=...")
if not queue_token:
    st.warning("Не задан TAOBAO_QUEUE_TOKEN в Secrets — разбор недоступен.")

if st.button("Разобрать товар", type="primary", disabled=not (url and queue_token)):
    import requests as _rq
    try:
        created = _rq.get(QUEUE_URL, params={"action": "create", "token": queue_token, "url": url}, timeout=30).json()
        if not created.get("ok"):
            st.error("Не удалось создать задание: %s" % created.get("error"))
        else:
            job_id = created["id"]
            state, result = "new", None
            with st.spinner("Локальный парсер собирает данные..."):
                for _ in range(60):
                    _time.sleep(2)
                    got = _rq.get(QUEUE_URL, params={"action": "get", "token": queue_token, "id": job_id}, timeout=30).json()
                    state = got.get("state")
                    result = got.get("result")
                    if state in ("done", "expired"):
                        break
            if state == "done" and result and not result.get("error"):
                st.session_state.parsed_result = result
                st.success("Готово: %s | картинок: %d | вариантов: %d" % (
                    result.get("title", "?"), len(result.get("gallery_urls") or []), len(result.get("skus") or [])))
                st.json({k: result.get(k) for k in ("item_id", "title", "price", "taobao_url")})
            elif result and result.get("error"):
                st.error("Парсер вернул ошибку: %s" % result.get("error"))
            else:
                st.error("Парсер не ответил за 2 минуты (состояние: %s). Проверьте, что воркер на ПК запущен." % state)
    except Exception as e:
        st.error("Ошибка очереди: %s" % e)

# === Загрузка в магазин (ВНЕ блока обработки!) ===
if st.session_state.get('parsed_result'):
    shop_token = os.environ.get("SHOP_API_TOKEN", st.secrets.get("SHOP_API_TOKEN", ""))
    if shop_token:
        if st.button("🛒 Загрузить в E-Mall (черновик)", type="primary"):
            with st.spinner("Загрузка в магазин..."):
                try:
                    data = st.session_state.parsed_result
                    # нормализуем SKU: строки -> объекты {name, price}
                    _skus = data.get('skus') or []
                    if _skus and isinstance(_skus[0], str):
                        _price = data.get('price') or 0
                        data['skus'] = [{'name': s[:255], 'price': _price} for s in _skus if str(s).strip()]
                    uploader = ShopScriptUploader(shop_token)
                    # ВСЕ картинки: главные + из описания, без дублей (порядок сохраняется)
                    all_images = list(dict.fromkeys(
                        (data.get('gallery_urls') or []) + (data.get('desc_images') or [])
                    ))
                    product_id, logs = uploader.run(
                        data['title'], data['taobao_url'],
                        all_images, data['skus']
                    )
                    st.success(f"✅ Товар #{product_id} создан (черновик)!")
                    st.text('\n'.join(logs[-10:]))
                except Exception as e:
                    st.error(f"❌ Ошибка: {e}")
                    import traceback
                    st.error(traceback.format_exc())
    else:
        st.warning("⚠️ SHOP_API_TOKEN не найден. Загрузка в магазин недоступна.")
