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

if st.sidebar.button("🚪 Выйти"):
    st.session_state.authenticated = False
    st.rerun()

url = st.text_input("Ссылка на товар Taobao/Tmall:", placeholder="https://item.taobao.com/item.htm?id=... или https://detail.tmall.com/item.htm?id=...")

# === Обработка товара ===
if st.button("🚀 Обработать товар", type="primary", disabled=not url):
    # Поддержка мобильных шары: извлекаем URL из текста, если вставлен текст
    processed_url = extract_url_from_text(url) or url
    if not any(host in processed_url for host in ("taobao.com", "tmall.com", "m.tb.cn", "tb.cn", "s.click.taobao.com", "world.taobao.com")):
        st.error("❌ Ссылка должна быть на сайт Taobao или Tmall.")
    else:
        log_container = st.empty()
        logs = []
        
        def log_callback(msg):
            logs.append(msg)
            log_container.text("\n".join(logs[-20:]))
        
        with st.spinner("Идет обработка, подождите..."):
            result = run_parser(processed_url, progress_callback=log_callback)
            
            if result and result.get('zip_path') and os.path.exists(result['zip_path']):
                st.success("✅ Обработка завершена!")
                with open(result['zip_path'], "rb") as f:
                    st.download_button(
                        label="📥 Скачать ZIP-архив",
                        data=f,
                        file_name=os.path.basename(result['zip_path']),
                        mime="application/zip"
                    )
                st.session_state.parsed_result = result
            else:
                st.error("❌ Ошибка при обработке товара")

# === Загрузка в магазин (ВНЕ блока обработки!) ===
if st.session_state.get('parsed_result'):
    shop_token = os.environ.get("SHOP_API_TOKEN", st.secrets.get("SHOP_API_TOKEN", ""))
    if shop_token:
        if st.button("🛒 Загрузить в E-Mall (черновик)", type="primary"):
            with st.spinner("Загрузка в магазин..."):
                try:
                    data = st.session_state.parsed_result
                    uploader = ShopScriptUploader(shop_token)
                    product_id, logs = uploader.run(
                        data['title'], data['taobao_url'],
                        data['gallery_urls'][:5], data['skus']
                    )
                    st.success(f"✅ Товар #{product_id} создан (черновик)!")
                    st.text('\n'.join(logs[-10:]))
                except Exception as e:
                    st.error(f"❌ Ошибка: {e}")
                    import traceback
                    st.error(traceback.format_exc())
    else:
        st.warning("⚠️ SHOP_API_TOKEN не найден. Загрузка в магазин недоступна.")
