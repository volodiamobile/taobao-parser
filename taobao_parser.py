import requests
import json
import os
import re
import zipfile
import tempfile
from datetime import datetime
from PIL import Image

# --- 1. Настройки API ---
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "")
RAPIDAPI_HOST = "toabao-open-api.p.rapidapi.com"
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

if not RAPIDAPI_KEY or not DEEPSEEK_API_KEY:
    raise ValueError("❌ Отсутствуют API-ключи.")

IMAGE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://item.taobao.com/",
    "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
}

def extract_product_id(url):
    match = re.search(r'[?&]id=(\d+)', url)
    if match:
        return match.group(1)
    match = re.search(r'/item/(\d+)\.htm', url)
    if match:
        return match.group(1)
    return None

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

        target_size = 800
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

def detect_item_type(product_data, title, original_title):
    root_path = product_data.get("RootPath", {}).get("Content", [])
    category_names = [cat.get("Name", "").lower() for cat in root_path if cat.get("Name")]
    
    type_keywords = {
        "стул": ["стул", "кресло", "chair", "табурет", "банкетка", "пуф"],
        "стол": ["стол", "table", "desk"],
        "диван": ["диван", "sofa", "кушетка", "тахта"],
        "кровать": ["кровать", "bed"],
        "шкаф": ["шкаф", "cabinet", "wardrobe"],
        "светильник": ["свет", "лампа", "lamp", "люстра", "бра", "торшер"],
    }
    
    for cat_name in category_names:
        for item_type, keywords in type_keywords.items():
            if any(kw in cat_name for kw in keywords):
                return item_type
    
    text_to_search = (title + " " + original_title).lower()
    for item_type, keywords in type_keywords.items():
        if any(kw in text_to_search for kw in keywords):
            return item_type
    
    return ""

def translate_with_deepseek(text, api_key):
    """Переводит текст через DeepSeek (max_tokens: 200)"""
    if not re.search(r'[\u4e00-\u9fff]', text):
        return text
    try:
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        prompt = f"""Ты — профессиональный переводчик с китайского на русский в сфере мебели и товаров для дома.

Переведи название артикула ТОЧНО на русский язык:
'{text}'

ВАЖНО:
- Переведи КАЖДОЕ слово, ничего не пропускай.
- НЕ возвращай китайские иероглифы — ТОЛЬКО русский перевод.
- Если в названии есть модель — сохрани её латиницей.
- Пиши с маленькой буквы.

Верни ТОЛЬКО перевод, без пояснений."""
        
        payload = {"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}], "temperature": 0, "max_tokens": 200}
        response = requests.post("https://api.deepseek.com/v1/chat/completions", headers=headers, json=payload, timeout=10)
        if response.status_code == 200:
            raw = response.json()["choices"][0]["message"]["content"]
            return re.sub(r'\s+', ' ', raw).strip()
    except:
        pass
    return text

def run_parser(product_url, progress_callback=None):
    def log(msg):
        print(msg)
        if progress_callback:
            progress_callback(msg)

    log("🛒 Парсер товаров Taobao/Tmall")
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
    original_title = item.get("OriginalTitle", "")
    all_attributes = item.get("Attributes", [])
    pictures = item.get("Pictures", [])
    description = item.get("Description", "")
    configured_items = item.get("ConfiguredItems", [])
    videos = item.get("Videos", [])

    # --- Определяем тип товара ---
    detected_type = detect_item_type(product_data.get("Result", {}), title, original_title)
    log(f"🔍 Определён тип товара: {detected_type or 'не определён'}")

    # --- Переводим название товара с УНИКАЛЬНЫМ названием модели ---
    fixed_title = title
    if original_title:
        type_hint = f"Это {detected_type}." if detected_type else ""
        try:
            headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
            prompt = f"""Переведи на русский язык и добавь УНИКАЛЬНОЕ название модели.
Оригинал: '{original_title}'
{type_hint}
Формат: [Русское название] [Model Name]
ВАЖНО: Придумай НОВОЕ, УНИКАЛЬНОЕ название модели — итальянское или английское слово, передающее стиль люкс. 
НЕ используй распространённые названия (Milano, Roma, Venezia, Bellagio, Capri, Firenze, Verona).
Верни ТОЛЬКО готовое название."""
            payload = {"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}], "temperature": 0.9, "max_tokens": 120}
            response = requests.post("https://api.deepseek.com/v1/chat/completions", headers=headers, json=payload, timeout=30)
            if response.status_code == 200:
                fixed_title = response.json()["choices"][0]["message"]["content"].strip()
        except:
            pass

    log(f"📦 Название: {fixed_title[:50]}...")

    # --- Строим словари ---
    vid_to_name = {}
    for attr in all_attributes:
        vid = attr.get("Vid", "")
        if vid:
            original_name = attr.get('OriginalValue') or attr.get('Value') or ''
            original_name = re.sub(r'[【\[\]】]', '', original_name).strip()
            if original_name:
                vid_to_name[vid] = original_name

    vid_to_image = {}
    for attr in all_attributes:
        vid = attr.get("Vid", "")
        img_url = attr.get('ImageUrl', '')
        if vid and img_url:
            vid_to_image[vid] = img_url

    # Словарь Id → акционная цена из Promotions (ВСЕГДА используется, если есть)
    promotions = item.get("Promotions", [])
    promo_prices = {}
    use_promo = False
    if promotions:
        promo_config = promotions[0].get("ConfiguredItems", [])
        if promo_config:
            for pci in promo_config:
                price = pci.get("Price", {}).get("ConvertedPriceList", {}).get("Internal", {}).get("Price")
                if price:
                    promo_prices[pci.get("Id", "")] = price
            use_promo = True
            log(f"💰 Будут использованы акционные цены (со скидкой)")

    # --- Настоящие артикулы из ConfiguredItems ---
    real_skus = []
    for cfg_item in configured_items:
        configurators = cfg_item.get("Configurators", [])
        sku_id = cfg_item.get("Id", "")
        
        if use_promo and sku_id in promo_prices:
            price_cny = promo_prices[sku_id]
        else:
            price_cny = cfg_item.get("Price", {}).get("ConvertedPriceList", {}).get("Internal", {}).get("Price", 0)
        
        parts = []
        image_url = ""
        for cfg in configurators:
            vid = cfg.get("Vid", "")
            if vid in vid_to_name:
                parts.append(vid_to_name[vid])
            if not image_url and vid in vid_to_image:
                image_url = vid_to_image[vid]
        
        # Переводим названия SKU с китайского на русский
        translated_parts = []
        for part in parts:
            translated_parts.append(translate_with_deepseek(part, DEEPSEEK_API_KEY))
        sku_name = ', '.join(translated_parts) if translated_parts else f'Артикул {len(real_skus)+1}'
        
        real_skus.append({
            'id': sku_id,
            'name': sku_name,
            'price': price_cny,
            'image_url': image_url
        })

    # --- FALLBACK: Если нет артикулов — берём из Attributes ---
    if not real_skus:
        log("⚠️ ConfiguredItems не дали результатов, использую Attributes")
        for attr in all_attributes:
            if attr.get("IsConfigurator"):
                vid = attr.get("Vid", "")
                original_name = attr.get('OriginalValue') or attr.get('Value') or ''
                original_name = re.sub(r'[【\[\]】]', '', original_name).strip()
                if not original_name:
                    continue
                price = vid_to_price.get(vid, 0) if vid_to_price else 0
                image_url = attr.get('ImageUrl', '')
                real_skus.append({
                    'id': vid,
                    'name': original_name,
                    'price': price,
                    'image_url': image_url
                })

    log(f"🏷️ Артикулов: {len(real_skus)}")

    desc_images = extract_images_from_html(description)
    log(f"📄 Картинок в описании: {len(desc_images)}")

    temp_dir = tempfile.mkdtemp()
    log(f"\n📁 Временная папка: {temp_dir}")

    vendor_name = vendor.get("DisplayName") or vendor.get("ShopName") or "—"
    
    txt = f"=== ТОВАР ===\nНазвание: {fixed_title}\nБренд: {item.get('BrandName', '—')}\n"
    txt += f"Продавец: {vendor_name}\nСсылка: {item.get('TaobaoItemUrl', product_url)}\n"

    if videos:
        video_url = videos[0].get("Url", "")
        if video_url:
            txt += f"Видео: {video_url}\n"

    txt += f"\n=== АРТИКУЛЫ ({len(real_skus)} шт.) ===\n"

    processed = 0
    for i, sku in enumerate(real_skus, 1):
        sku_name = sku['name']
        price = sku['price']
        img_url = sku['image_url']
        
        txt += f"{str(i).zfill(2)}. {sku_name} — {price} ¥\n"
        
        if img_url and is_valid_image_url(img_url):
            filename = f"{str(i).zfill(2)}_{sanitize_filename(sku_name)}.webp"
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

    json_path = os.path.join(temp_dir, "api_response.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(product_data, f, indent=2, ensure_ascii=False)
    log(f"  ✅ api_response.json сохранён")

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

    # Возвращаем структурированные данные для shop_uploader
    gallery = [pic.get('Large', {}).get('Url') or pic.get('Medium', {}).get('Url') or pic.get('Url') for pic in pictures if pic.get('Url')]
    gallery = [u for u in gallery if u]
    
    result = {
        'zip_path': zip_path,
        'title': fixed_title,
        'taobao_url': product_url,
        'product_id': product_id,
        'skus': real_skus,
        'gallery_urls': gallery,
        'desc_images': desc_images,
        'videos': videos,
    }
    return result