import streamlit as st
import os
from taobao_parser import run_parser

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
            zip_path = run_parser(url, progress_callback=log_callback)
            
            if zip_path and os.path.exists(zip_path):
                st.success("✅ Обработка завершена!")
                with open(zip_path, "rb") as f:
                    st.download_button(
                        label="📥 Скачать ZIP-архив",
                        data=f,
                        file_name=os.path.basename(zip_path),
                        mime="application/zip"
                    )
            else:
                st.error("❌ Ошибка при обработке товара")