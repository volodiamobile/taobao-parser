# -*- coding: utf-8 -*-
# Временная проверка (read-only): Description у товара 665495018283 (давал desc-картинки 15-16.08)
import requests, json, re, sys, time
sys.stdout.reconfigure(encoding='utf-8')

with open('.streamlit/secrets.toml', encoding='utf-8') as f:
    secrets_text = f.read()
key = re.search(r'RAPIDAPI_KEY\s*=\s*["\']([^"\']+)["\']', secrets_text).group(1)
host = 'toabao-open-api.p.rapidapi.com'
h = {'x-rapidapi-key': key, 'x-rapidapi-host': host}

for item_id in ['665495018283', '1069647269903']:
    for attempt in range(3):
        r = requests.get('https://' + host + '/BatchGetItemFullInfo',
                         headers=h, params={'itemId': item_id, 'language': 'ru'}, timeout=30)
        if r.status_code == 429:
            time.sleep(8)
            continue
        d = r.json()
        item = d.get('Result', {}).get('Item', {})
        desc = item.get('Description', '')
        imgs = re.findall(r'src=["\']([^"\']+\.(?:jpg|jpeg|png|webp))["\']', desc, re.I) if desc else []
        print(item_id, '| HTTP', r.status_code, '| Description present:', 'Description' in item,
              '| len:', len(desc), '| imgs in desc:', len(imgs), '| Pictures:', len(item.get('Pictures', [])))
        break
    time.sleep(6)
