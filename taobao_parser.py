import requests
import json
import os
import re
import zipfile
import tempfile
from datetime import datetime
from PIL import Image

# --- 1. Настройки API (безопасно, через переменные окружения) ---
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "")
RAPIDAPI_HOST = "toabao-open-api.p.rapidapi.com"
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

if not RAPIDAPI_KEY or not DEEPSEEK_API_KEY:
    raise ValueError("❌ Отсутствуют API-ключи. Добавьте их в Secrets Streamlit Cloud или в файл .streamlit/secrets.toml")

IMAGE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://item.taobao.com/",
    "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
}

def translate_text(text):
    TRANSLATION_MAP = {
        '雪尼尔': 'шенилл', '亚麻': 'лён', '麻': 'лён', '超纤皮': 'микрофибра',
        '马鞍皮': 'седельная кожа', '皮': 'кожа', '布': 'ткань',
        '不锈钢': 'нержавеющая сталь', '金属': 'металл',
        '伯爵黄白': 'жёлто-белый', '黄白': 'жёлто-белый', '黄棕': 'жёлто-коричневый',
        '棕黄': 'коричнево-жёлтый', '黑色': 'чёрный', '星空': 'звёздное небо',
        '葡萄红': 'виноградно-красный', '奶杏白': 'молочно-абрикосовый',
        '芬迪条纹': 'полосатый', '条纹': 'полосатый',
        '定制': 'на заказ', '餐椅': 'обеденный стул', '可定色': 'цвет на выбор',
    }
    result = text
    for ch, ru in TRANSLATION_MAP.items():
        result = result.replace(ch, ru)
    result = result.replace('+', ' ')
    result = re.sub(r'[\u4e00-\u9fff]+', '', result)
    result = re.sub(r'[^\w\s\-]', ' ', result)
    result = re.sub(r'\s+', ' ', result).strip()
    return result if result else text

def extract_product_id(url):
    match = re.search(r'[?&]id=(\d+)', url)
    return match.group(1) if match else None

def get_taobao_product(item_id):
    url = "https://toabao-open-api.p.rapidapi.com/BatchGetItemFullInfo"
    querystring = {"itemId": item_id, "language": "ru"}
    headers = {"x-rapidapi-key": RAPIDAPI_KEY, "x-rapidapi-host": RAPIDAPI_HOST}
    response = requests.get(url, headers=headers, params=querystring)
    return response.json() if response.status_code == 200 else None

def sanitize_filename(name):
    forbidden = '<>:"/\\|?*'
    for char in forbidden:
        name = name.replace(char, '')
    return name.strip()[:50]

def is_valid_image_url(url):
    if not url:
        return False
    url_lower = url.lower()
    exclude = ['icon', 'logo', 'avatar', 'button', 'banner', 'qrcode',
               'weixin', 'alipay', '_100x100', '_50x50', '1x1', 'blank',
               'track', 'beacon', 'pixel', 'spacer', 'transparent']
    for word in exclude:
        if word in url_lower:
            return False
    return True

def extract_images_from_html(html):
    urls = []
    matches = re.findall(r'src=["\']([^"\']+\.(jpg|jpeg|png|webp))["\']', html, re.IGNORECASE)
    for match in matches:
        url = match[0]
        if url.startswith('//'):
            url = 'https:' + url
        elif not url.startswith('http'):
            continue
        if is_valid_image_url(url):
            urls.append(url)
    return urls

def process_image(url, filepath):
    try:
        if url.startswith('//'):
            url = 'https:' + url
        elif url.startswith('http:'):
            url = url.replace('http:', 'https:')

        response = requests.get(url, timeout=15, stream=True, headers=IMAGE_HEADERS)
        response.raise_for_status()

        content_type = response.headers.get('Content-Type', '')
        if not content_type.startswith('image/'):
            return False

        temp_file = filepath + ".tmp.jpg"
        with open(temp_file, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        img = Image.open(temp_file)
        img.verify()
        img = Image.open(temp_file)

        target_size = 1100
        width, height = img.size
        scale = target_size / max(width, height)
        new_width = int(width * scale)
        new_height = int(height * scale)
        img_resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

        canvas = Image.new('RGB', (target_size, target_size), (255, 255, 255))
        x = (target_size - new_width) // 2
        y = (target_size - new_height) // 2

        if img_resized.mode == 'RGBA':
            canvas.paste(img_resized, (x, y), img_resized)
        else:
            canvas.paste(img_resized.convert('RGB'), (x, y))

        canvas.save(filepath, "WEBP", quality=85)
        os.remove(temp_file)
        return True
    except:
        return False

def run_parser(product_url, progress_callback=None):
    """Запускает парсер и возвращает путь к ZIP-архиву"""
    
    def log(msg):
        print(msg)
        if progress_callback:
            progress_callback(msg)

    log(f"🛒 Парсер товаров Taobao")
    log("-" * 40)

    product_id = extract_product_id(product_url)
    if not product_id:
        log("❌ Не удалось извлечь ID товара.")
        return None

    log(f"📋 ID: {product_id}")
    log("🚀 Получаю данные...")

    product_data = get_taobao_product(product_id)
    if not product_data:
        log("Не удалось получить данные.")
        return None

    item = product_data.get("Result", {}).get("Item", {})
    vendor = product_data.get("Result", {}).get("Vendor", {})

    title = item.get("Title", "Нет названия")
    all_attributes = item.get("Attributes", [])
    pictures = item.get("Pictures", [])
    description = item.get("Description", "")
    configured_items = item.get("ConfiguredItems", [])
    videos = item.get("Videos", [])

    vid_to_price = {}
    for cfg_item in configured_items:
        configurators = cfg_item.get("Configurators", [])
        price_cny = cfg_item.get("Price", {}).get("ConvertedPriceList", {}).get("Internal", {}).get("Price", 0)
        for cfg in configurators:
            vid = cfg.get("Vid")
            if vid:
                vid_to_price[vid] = price_cny

    configurators = [a for a in all_attributes if a.get("IsConfigurator") == True]
    desc_images = extract_images_from_html(description)
    vendor_name = vendor.get("DisplayName") or vendor.get("ShopName") or "—"

    log(f"📦 Товар: {title[:50]}...")
    log(f"🏷️ Артикулов: {len(configurators)}")
    log(f"🖼️ Галерея: {len(pictures)}")
    log(f"📄 Картинок в описании: {len(desc_images)}")

    temp_dir = tempfile.mkdtemp()
    log(f"\n📁 Временная папка: {temp_dir}")

    processed = 0
    txt = f"=== ТОВАР ===\nНазвание: {title}\nБренд: {item.get('BrandName', '—')}\n"
    txt += f"Продавец: {vendor_name}\nСсылка: {item.get('TaobaoItemUrl', product_url)}\n"

    if videos:
        video_url = videos[0].get("Url", "")
        if video_url:
            txt += f"Видео: {video_url}\n"

    # SEO-заголовок
    base_seo_title = ""
    try:
        headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
        has_model = any(word in title.lower() for word in ['pagase', 'model', 'модель'])
        if has_model:
            prompt = f"Создай короткий SEO-заголовок для карточки товара на русском языке длиной от 40 до 60 символов. Название товара: '{title}'. Сохрани название модели (например, Pagase). Используй ключевые слова: дизайнерский, итальянский, люкс."
        else:
            prompt = f"Создай короткий SEO-заголовок для карточки товара на русском языке длиной от 40 до 60 символов. Название товара: '{title}'. Придумай и добавь итальянское или английское название модели в стиле люкс (например, Milano, Venezia, Capri). Используй ключевые слова: дизайнерский, итальянский, люкс."
        payload = {"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}], "temperature": 0.7, "max_tokens": 100}
        response = requests.post("https://api.deepseek.com/v1/chat/completions", headers=headers, json=payload, timeout=30)
        if response.status_code == 200:
            base_seo_title = response.json()["choices"][0]["message"]["content"].strip()
        else:
            base_seo_title = title[:50]
    except Exception as e:
        log(f"  ⚠️ Ошибка DeepSeek: {e}")
        base_seo_title = title[:50]

    log(f"  📝 Общий SEO-заголовок: {base_seo_title}")
    txt += f"\n=== ОБЩИЙ SEO-ЗАГОЛОВОК ===\n{base_seo_title}\n"
    txt += f"\n=== АРТИКУЛЫ ({len(configurators)} шт.) ===\n"

    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
    
    for i, cfg in enumerate(configurators, 1):
        original_name = cfg.get('OriginalValue') or cfg.get('Value') or f'Артикул {i}'
        vid = cfg.get('Vid')
        price = vid_to_price.get(vid, 0)

        readable_sku = ""
        try:
            rough_translation = translate_text(original_name)
            prompt = f"""Опиши материал и цвет данного артикула мебели на русском языке.
Исходный текст: '{original_name}'.
Примерный перевод: '{rough_translation}'.
Правила:
1. НЕ УПОМИНАЙ, что это за предмет мебели (стул, кресло и т.д.).
2. НЕ ПОВТОРЯЙ название бренда или модели (например, Pagase).
3. Опиши ТОЛЬКО текстуру, материал и цвет (3-5 слов).
4. Пиши с маленькой буквы.
5. Если есть комбинация материалов, укажи их через запятую или "и".
6. Верни ТОЛЬКО готовое описание, без кавычек и пояснений."""
            payload = {"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}], "temperature": 0.3, "max_tokens": 80}
            response = requests.post("https://api.deepseek.com/v1/chat/completions", headers=headers, json=payload, timeout=30)
            if response.status_code == 200:
                readable_sku = response.json()["choices"][0]["message"]["content"].strip()
            else:
                readable_sku = rough_translation
        except:
            readable_sku = translate_text(original_name)

        full_title = f"{base_seo_title}, {readable_sku}"
        if len(full_title) < 60:
            full_title = f"{full_title} купить с доставкой"
        elif len(full_title) > 120:
            full_title = full_title[:117].rsplit(' ', 1)[0] + "..."

        txt += f"{str(i).zfill(2)}. {full_title} — {price} ¥\n"

        img_url = cfg.get('ImageUrl')
        if img_url and is_valid_image_url(img_url):
            filename = f"{str(i).zfill(2)}_{sanitize_filename(readable_sku)}.webp"
            filepath = os.path.join(temp_dir, filename)
            if process_image(img_url, filepath):
                processed += 1
                log(f"  ✅ {filename}")

    txt += f"\n=== ГАЛЕРЕЯ ({len(pictures)} шт.) ===\n"
    for i, pic in enumerate(pictures, 1):
        txt += f"{str(i).zfill(2)}. Изображение {i}{' (главное)' if pic.get('IsMain') else ''}\n"
        img_url = pic.get('Large', {}).get('Url') or pic.get('Medium', {}).get('Url') or pic.get('Url')
        if img_url and is_valid_image_url(img_url):
            filename = f"gallery_{str(i).zfill(2)}.webp"
            if process_image(img_url, os.path.join(temp_dir, filename)):
                processed += 1
                log(f"  ✅ {filename}")

    if desc_images:
        txt += f"\n=== КАРТИНКИ ИЗ ОПИСАНИЯ ({len(desc_images)} шт.) ===\n"
        for i, img_url in enumerate(desc_images, 1):
            txt += f"{str(i).zfill(2)}. Из описания {i}\n"
            filename = f"desc_{str(i).zfill(2)}.webp"
            if process_image(img_url, os.path.join(temp_dir, filename)):
                processed += 1
                log(f"  ✅ {filename}")

    txt_path = os.path.join(temp_dir, "описание.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(txt)

    zip_name = f"taobao_{product_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    zip_path = os.path.join(temp_dir, zip_name)
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(temp_dir):
            for file in files:
                if file != zip_name:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, temp_dir)
                    zipf.write(file_path, arcname)

    log("-" * 40)
    log(f"✅ Готово! Файлов: {processed}")
    log(f"📦 Архив: {zip_name}")

    return zip_path
