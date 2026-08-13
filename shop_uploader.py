"""
shop_uploader.py — загрузка товара из Taobao парсера в Shop-Script (e-mall.su)

API эндпоинты:
- shop.product.add (POST) — создать товар
- shop.product.images.add (GET: product_id + POST: file) — загрузить картинку
- shop.product.update (GET: id + POST: features[...]) — установить характеристики
- shop.product.skus.add (POST) — добавить артикул

"""
import requests
import json
import os
import re
import time

class ShopScriptUploader:
    def __init__(self, api_token, api_url='https://e-mall.su/api.php/', brand='E-Mall'):
        self.token = api_token
        self.api_url = api_url
        self.brand = brand

    def _get(self, method, params=None):
        p = {'access_token': self.token}
        if params:
            p.update(params)
        r = requests.get(self.api_url + method, params=p, timeout=30)
        return r.json()

    def _post(self, method, data=None, params=None, files=None):
        if params is None:
            params = {}
        params['access_token'] = self.token
        if files:
            r = requests.post(self.api_url + method, params=params, data=data, files=files, timeout=60)
        else:
            r = requests.post(self.api_url + method, params=params, data=data, timeout=30)
        return r.json()

    def create_product(self, title, taobao_url, skus_data, currency='CNY', type_id=30):
        """Создать товар-черновик"""
        data = {
            'name': title or 'Без названия',
            'status': 0,  # черновик
            'currency': currency,
            'type_id': type_id,
        }
        # Добавляем артикулы
        for i, sku in enumerate(skus_data):
            data[f'skus[{i}][name]'] = sku['name'][:255]
            data[f'skus[{i}][price]'] = 0
            data[f'skus[{i}][purchase_price]'] = int(sku.get('price', 0))

        resp = self._post('shop.product.add', data=data)
        if 'error' in resp and resp['error']:
            raise Exception(f"Ошибка создания товара: {resp.get('error_description', resp['error'])}")
        return resp['id']

    def upload_image(self, product_id, image_url, filename=None):
        """Скачать картинку и загрузить в товар.

        Формат вывода: 800×800 WEBP quality=70 (через image_utils.process_image).
        При ЛЮБОМ сбое обработки — загружается оригинал, как было до правок (ничего не ломается).
        """
        import os
        import tempfile

        tmp_dir = None
        tmp_path = None
        try:
            from image_utils import process_image
            tmp_dir = tempfile.mkdtemp()
            tmp_path = os.path.join(tmp_dir, 'img')
            if process_image(image_url, tmp_path):
                with open(tmp_path, 'rb') as f:
                    img_data = f.read()
                base = filename or f'image_{int(time.time())}.webp'
                base = os.path.basename(base)
                if not base.lower().endswith('.webp'):
                    base = os.path.splitext(base)[0] + '.webp'
                mime = 'image/webp'
            else:
                raise RuntimeError('process_image вернул False')
        except Exception:
            # FALLBACK: как было до правок — оригинал без обработки
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'https://item.taobao.com/',
            }
            r = requests.get(image_url, headers=headers, timeout=30, stream=True)
            r.raise_for_status()
            img_data = r.content
            if not filename:
                filename = os.path.basename(image_url.split('?')[0])
                if not filename or '.' not in filename:
                    filename = f'image_{int(time.time())}.jpg'
            ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'jpg'
            mime_map = {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png', 'webp': 'image/webp'}
            mime = mime_map.get(ext, 'image/jpeg')
            base = filename
        finally:
            if tmp_path:
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
            if tmp_dir:
                try:
                    os.rmdir(tmp_dir)
                except Exception:
                    pass

        # Загружаем через API
        params = {'product_id': product_id}
        files = {'file': (base, img_data, mime)}
        resp = self._post('shop.product.images.add', params=params, files=files)
        return resp

    def set_features(self, product_id, taobao_url):
        """Установить характеристики: brand + fabrika"""
        params = {'id': product_id}
        data = {
            'features[brand]': self.brand,
            'features[fabrika]': taobao_url,
        }
        resp = self._post('shop.product.update', params=params, data=data)
        if 'error' in resp:
            raise Exception(f"Ошибка установки фич: {resp.get('error_description', resp['error'])}")
        return resp

    def run(self, title, taobao_url, gallery_urls, skus_data):
        """Полный цикл: товар → галерея → SKU → фичи"""
        log = []
        def l(msg):
            log.append(msg)
            print(msg)

        l(f'📦 Создание товара: {title[:50]}...')
        product_id = self.create_product(title, taobao_url, skus_data)
        l(f'✅ Товар создан: id={product_id}')

        # Загружаем галерею (главные картинки)
        l(f'🖼 Загрузка галереи ({len(gallery_urls)} шт)...')
        image_ids = []
        for i, url in enumerate(gallery_urls):
            try:
                resp = self.upload_image(product_id, url, f'gallery_{i+1:02d}.webp')
                if resp.get('id'):
                    image_ids.append(resp['id'])
                    l(f'  ✅ gallery_{i+1:02d}')
                else:
                    l(f'  ❌ gallery_{i+1:02d}: {resp.get("error","unknown")}')
            except Exception as e:
                l(f'  ❌ gallery_{i+1:02d}: {e}')
            time.sleep(0.5)

        # Загружаем SKU-картинки и привязываем
        l(f'🏷 Загрузка SKU-картинок ({len(skus_data)} шт)...')
        for i, sku in enumerate(skus_data):
            if sku.get('image_url'):
                try:
                    fname = f'sku_{i+1:02d}_{sku["name"][:30]}.webp'
                    fname = re.sub(r'[<>:"/\\|?*]', '', fname)[:60]
                    resp = self.upload_image(product_id, sku['image_url'], fname)
                    if resp.get('id'):
                        sku['image_id'] = resp['id']
                        l(f'  ✅ sku_{i+1:02d}: image_id={resp["id"]}')
                    else:
                        l(f'  ⚠️ sku_{i+1:02d}: no id')
                except Exception as e:
                    l(f'  ❌ sku_{i+1:02d}: {e}')
                time.sleep(0.3)

        # Устанавливаем фичи
        l(f'🏷 Установка характеристик...')
        self.set_features(product_id, taobao_url)
        l(f'✅ Характеристики: brand={self.brand}, fabrika={taobao_url}')

        l(f'\n🎉 Готово! Товар id={product_id} (черновик)')
        return product_id, log
