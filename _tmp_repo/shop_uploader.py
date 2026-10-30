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
    # Наборы Shop-Script, в которые товар добавляется СРАЗУ при создании (16.08.2026, команда Вована)
    SET_IDS = ['GoogleMC', 'FacebookPro', 'pinterest', 'Y.Market']

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
            'name': title,
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
            # Повтор при разовом сбое сети: 3 попытки с паузой
            r = None
            for attempt in range(3):
                try:
                    r = requests.get(image_url, headers=headers, timeout=30, stream=True)
                    r.raise_for_status()
                    break
                except Exception:
                    if attempt == 2:
                        raise
                    time.sleep(2)
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

    def apply_sets(self, product_id, set_ids):
        """Добавить товар в наборы (static sets).

        Проверено 16.08.2026: shop.product.add НЕ применяет sets (молча игнорирует);
        shop.product.update с sets[i][id]=<set_id> применяет (id — в query, по уроку 15.08).
        """
        data = {f'sets[{i}][id]': sid for i, sid in enumerate(set_ids)}
        resp = self._post('shop.product.update', params={'id': product_id}, data=data)
        if 'error' in resp and resp['error']:
            raise Exception(f"Ошибка добавления в наборы: {resp.get('error_description', resp['error'])}")
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

        # Сразу добавляем в наборы (GoogleMC, FacebookPro, pinterest, Y.Market)
        try:
            self.apply_sets(product_id, self.SET_IDS)
            l(f"✅ Наборы применены: {len(self.SET_IDS)} ({', '.join(self.SET_IDS)})")
        except Exception as e:
            l(f'⚠️ Наборы не применились: {e}')

        # Получаем реальные id артикулов Shop-Script (порядок = порядку создания)
        # Нужны для привязки картинок: API принимает id артикула магазина, НЕ таобао-id
        try:
            _info = self._get('shop.product.getInfo', {'id': product_id})
            _p = _info.get('product', _info)
            _shop_skus = _p.get('skus', [])
            for _i, _sku in enumerate(skus_data):
                if _i < len(_shop_skus):
                    _sku['shop_sku_id'] = _shop_skus[_i]['id']
            l(f'🔗 Артикулы Shop-Script: {len(_shop_skus)} шт')
        except Exception as e:
            l(f'⚠️ Не удалось получить id артикулов: {e}')

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
                        # Привязка картинки к артикулу (иначе артикул остаётся без картинки)
                        try:
                            # id — в query (иначе 400 "недостаточно id"), image_id — в body
                            _shop_sku_id = sku.get('shop_sku_id')
                            if not _shop_sku_id:
                                l(f'  ⚠️ sku_{i+1:02d}: нет shop_sku_id, привязка пропущена')
                            else:
                                upd = self._post('shop.product.skus.update', params={'id': _shop_sku_id}, data={'image_id': resp['id']})
                                if upd.get('error'):
                                    l(f'  ⚠️ sku_{i+1:02d}: привязка не удалась: {upd.get("error_description", upd["error"])}')
                        except Exception as e:
                            l(f'  ⚠️ sku_{i+1:02d}: привязка: {e}')
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
