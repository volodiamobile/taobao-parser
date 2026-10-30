"""
image_utils.py — единая обработка изображений для taobao_parser и shop_uploader.

ВСЕ картинки (ZIP-архив и загрузка в магазин через API) приводятся одинаково:
- Размер: 800×800 (квадрат, белый фон, LANCZOS)
- Формат: WEBP, quality=70
"""
import os

import requests
from PIL import Image

TARGET_SIZE = 800
WEBP_QUALITY = 70

IMAGE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://item.taobao.com/",
    "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
}


def process_image(url, filepath):
    """Скачать изображение по URL и привести к 800×800 WEBP quality=70.

    Возвращает True при успехе, False при любой ошибке.
    """
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

        try:
            width, height = img.size
            scale = TARGET_SIZE / max(width, height)
            new_width = int(width * scale)
            new_height = int(height * scale)
            img_resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

            canvas = Image.new('RGB', (TARGET_SIZE, TARGET_SIZE), (255, 255, 255))
            x = (TARGET_SIZE - new_width) // 2
            y = (TARGET_SIZE - new_height) // 2

            if img_resized.mode == 'RGBA':
                canvas.paste(img_resized, (x, y), img_resized)
            else:
                canvas.paste(img_resized.convert('RGB'), (x, y))

            canvas.save(filepath, "WEBP", quality=WEBP_QUALITY)
        finally:
            # Windows: закрываем дескрипторы, иначе os.remove упадёт с PermissionError
            img.close()
            try:
                os.remove(temp_file)
            except Exception:
                pass
        return True
    except Exception:
        return False
