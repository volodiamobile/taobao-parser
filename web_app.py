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
    # ключ для облака (Streamlit secrets) — если пул аккаунтов там недоступен
    if not os.environ.get("RAPIDAPI_KEY"):
        try:
            os.environ["RAPIDAPI_KEY"] = st.secrets.get("RAPIDAPI_KEY", "")
        except Exception:
            pass
    import api_pool
    _accs = [a for a in api_pool.load_accounts()["accounts"] if a.get("enabled", True)]
    if _accs:
        _left = sum(api_pool.remaining_for(a["id"]) or 0 for a in _accs)
        _lim = sum(api_pool.capacity_for(a["id"]) or int(a.get("limit") or 20) for a in _accs)
        _src = " из secrets" if any(a.get("source") == "secrets" for a in _accs) else ""
        st.sidebar.caption("Запросов сегодня: осталось %d из %d (%d акк.%s)" % (
            _left, _lim, len(_accs), _src))
    else:
        st.sidebar.caption("Пул аккаунтов не настроен — работа на одном ключе из secrets")
except Exception:
    pass


# --- Проверка реального остатка (один запрос на ключ) ---
if st.sidebar.button("🔄 Проверить остаток"):
    try:
        import api_pool as _ap
        import taobao_parser as _tp
        _ids = None
        if st.session_state.get("quota_all"):
            _ids = [a["id"] for a in _ap.load_accounts()["accounts"] if a.get("enabled", True)]
        with st.spinner("Запрос к RapidAPI..."):
            st.session_state["quota_check"] = _tp.check_quota(_ids)
        st.rerun()
    except Exception as _e:
        st.sidebar.error(f"Проверка не удалась: {_e}")

st.sidebar.checkbox("Проверить все ключи (1 запрос на ключ)", key="quota_all", value=False)

_qc = st.session_state.get("quota_check")
if _qc:
    for _aid, _r in _qc.items():
        if _r.get("error"):
            st.sidebar.caption(f"{_aid}: ошибка — {_r['error']}")
        else:
            st.sidebar.caption(f"{_aid}: HTTP {_r.get('status')}, requests {_r.get('requests')}, "
                               f"advanced {_r.get('advanced')}")

if st.sidebar.button("🚪 Выйти"):
    st.session_state.authenticated = False
    st.rerun()

url = st.text_input("Ссылка на товар Taobao/Tmall:", placeholder="https://item.taobao.com/item.htm?id=... или https://detail.tmall.com/item.htm?id=...")

# === Обработка товара и создание черновика — один запрос к RapidAPI ===
from taobao_parser import extract_product_id


def _valid_url(u):
    return any(host in u for host in ("taobao.com", "tmall.com", "m.tb.cn", "tb.cn",
                                      "s.click.taobao.com", "world.taobao.com"))


def _shop_token():
    tok = (os.environ.get("SHOP_API_TOKEN") or "").strip()
    if tok:
        return tok
    try:
        return (st.secrets.get("SHOP_API_TOKEN") or "").strip()
    except Exception:
        return ""


def _do_parse(processed_url):
    log_container = st.empty()
    logs = []

    def log_callback(msg):
        logs.append(msg)
        log_container.text("\n".join(logs[-20:]))

    with st.spinner("Идет обработка, подождите..."):
        try:
            res = run_parser(processed_url, progress_callback=log_callback)
        except Exception as exc:
            st.error(f"❌ Сбой при обработке: {exc}")
            import traceback
            st.code(traceback.format_exc(), language="text")
            return None
    if res and res.get('zip_path') and os.path.exists(res['zip_path']):
        st.session_state.parsed_result = res
        return res
    st.error("❌ Ошибка при обработке товара")
    if logs:
        st.code("\n".join(logs[-15:]), language="text")
    return None


def _show_zip(res):
    if res and res.get('zip_path') and os.path.exists(res['zip_path']):
        with open(res['zip_path'], 'rb') as f:
            st.download_button(
                label="📥 Скачать ZIP-архив",
                data=f,
                file_name=os.path.basename(res['zip_path']),
                mime="application/zip",
                key="zip_" + os.path.basename(res['zip_path']),
            )


def _do_upload(res, shop_token):
    with st.spinner("Загрузка в магазин..."):
        try:
            uploader = ShopScriptUploader(shop_token)
            all_images = list(dict.fromkeys(
                (res.get('gallery_urls') or []) + (res.get('desc_images') or [])
            ))
            product_id, logs = uploader.run(
                res['title'], res['taobao_url'], all_images, res['skus']
            )
            st.success(f"✅ Товар #{product_id} создан (черновик)!")
            st.text('\n'.join(logs[-10:]))
        except Exception as e:
            st.error(f"❌ Ошибка загрузки: {e}")
            import traceback
            st.error(traceback.format_exc())


_c1, _c2 = st.columns(2)
_parse_click = _c1.button("🚀 Обработать товар", disabled=not url)
_draft_click = _c2.button("🛒 Создать черновик + ZIP", type="primary", disabled=not url)

if _parse_click or _draft_click:
    # Поддержка мобильных шары: извлекаем URL из текста, если вставлен текст
    processed_url = extract_url_from_text(url) or url
    if not _valid_url(processed_url):
        st.error("❌ Ссылка должна быть на сайт Taobao или Tmall.")
    else:
        result = None
        cached = st.session_state.get('parsed_result')
        # этот же товар уже разобран — второй запрос к RapidAPI не тратим
        if cached and cached.get('product_id') == extract_product_id(processed_url):
            result = cached
            st.info("ℹ️ Товар уже разобран — использую результат без нового запроса к RapidAPI.")
        else:
            result = _do_parse(processed_url)

        if result:
            # ZIP собран тем же единственным запросом — сразу даём скачать
            _show_zip(result)
            if _draft_click:
                token = _shop_token()
                if token:
                    _do_upload(result, token)
                else:
                    st.warning("⚠️ SHOP_API_TOKEN не найден. ZIP готов, выгрузка в магазин недоступна.")
