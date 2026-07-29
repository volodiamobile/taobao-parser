import streamlit as st
import os
import json
from taobao_parser import run_parser
from shop_uploader import ShopScriptUploader

st.set_page_config(page_title="Taobao/Tmall Parser", page_icon="🛒", layout="wide")

# Пароль из secrets или переменной окружения
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

if st.button("🚀 Обработать товар", type="primary", disabled=not url):
    if "taobao.com" not in url and "tmall.com" not in url:
        st.error("❌ Ссылка должна быть на сайт Taobao или Tmall.")
    else:
        log_container = st.empty()
        logs = []
        
        def log_callback(msg):
            logs.append(msg)
            log_container.text("\n".join(logs[-20:]))
        
        with st.spinner("Идет обработка, подождите..."):
            result = run_parser(url, progress_callback=log_callback)
            
            if result and result.get('zip_path') and os.path.exists(result['zip_path']):
                st.success("✅ Обработка завершена!")
                with open(result['zip_path'], "rb") as f:
                    st.download_button(
                        label="📥 Скачать ZIP-архив",
                        data=f,
                        file_name=os.path.basename(result['zip_path']),
                        mime="application/zip"
                    )
                
                # Сохраняем результат в сессии для кнопки загрузки
                st.session_state.parsed_result = result
                
                # Кнопка загрузки в магазин
                shop_token = os.environ.get("SHOP_API_TOKEN", st.secrets.get("SHOP_API_TOKEN", ""))
                if shop_token:
                    if st.button("🛒 Загрузить в E-Mall (черновик)", type="primary"):
                        with st.spinner("Загрузка в магазин..."):
                            try:
                                st.write('🔍 Токен:', shop_token[:10] + '...')
                                uploader = ShopScriptUploader(shop_token)
                                st.write('🔍 title:', str(result.get('title',''))[:50])
                                st.write('🔍 gallery:', str(len(result.get('gallery_urls',[]))))
                                st.write('🔍 skus:', str(len(result.get('skus',[]))))
                                title = result['title']
                                taobao_url = result['taobao_url']
                                gallery = result['gallery_urls'][:5]
                                skus = result['skus']
                                
                                product_id, logs = uploader.run(title, taobao_url, gallery, skus)
                                st.success(f"✅ Товар #{product_id} создан (черновик)!")
                                st.text('\n'.join(logs[-10:]))
                            except Exception as e:
                                st.error(f"❌ Ошибка: {e}")
                                import traceback
                                st.error(traceback.format_exc())
                else:
                    st.warning("⚠️ SHOP_API_TOKEN не найден. Загрузка в магазин недоступна.")
            else:
                st.error("❌ Ошибка при обработке товара")