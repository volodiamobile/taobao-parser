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

# === Локальный парсинг: сюда загружается готовый JSON с ПК ===
st.info("Разбор выполняется локально на ПК (сессия Taobao). Загрузите сюда JSON из _tools/taobao-local/out/ — приложение только выкладывает товар в магазин.")
prepared_file = st.file_uploader("Подготовленный JSON товара", type=["json"])
if prepared_file is not None:
    try:
        prepared = json.load(prepared_file)
        st.session_state.parsed_result = prepared
        st.success("Загружено: %s | картинок: %d | вариантов: %d" % (
            prepared.get('title', '?'), len(prepared.get('gallery_urls') or []), len(prepared.get('skus') or [])))
        st.json({k: prepared.get(k) for k in ('item_id', 'title', 'price', 'taobao_url')})
    except Exception as e:
        st.error("Не удалось прочитать JSON: %s" % e)

# === Загрузка в магазин (ВНЕ блока обработки!) ===
if st.session_state.get('parsed_result'):
    shop_token = os.environ.get("SHOP_API_TOKEN", st.secrets.get("SHOP_API_TOKEN", ""))
    if shop_token:
        if st.button("🛒 Загрузить в E-Mall (черновик)", type="primary"):
            with st.spinner("Загрузка в магазин..."):
                try:
                    data = st.session_state.parsed_result
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
