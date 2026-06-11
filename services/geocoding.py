"""
地理編碼模組（Nominatim API）。

職責：把使用者輸入的「地點關鍵字」轉換為經緯度座標與候選地點清單。
對應企劃書強制技術棧中的「Nominatim API：搜尋地點與候選位置」。

注意事項：
  - Nominatim 公開服務規定「每秒最多 1 次請求」，且必須帶 User-Agent，
    因此這裡接上 RateLimiter 與 TTLCache。
  - 搜尋範圍用 viewbox 限制在新竹一帶，避免同名地點解析到外縣市。
"""

import re

import requests

import config
from utils.cache import TTLCache
from utils.rate_limiter import RateLimiter

# 「@緯度,經度」格式（使用者直接在地圖上點選位置時用），可跳過 Nominatim 查詢
_COORD_PATTERN = re.compile(r"^\s*@?\s*(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)\s*$")

# 模組層級的限流器與快取（整個程式共用一份）
_limiter = RateLimiter(config.NOMINATIM_RATE_LIMIT_SECONDS)
_cache = TTLCache(config.GEOCODE_CACHE_TTL_SECONDS)


def geocode(keyword, limit=5):
    """
    將地點關鍵字解析為候選座標清單。

    回傳：list[dict]，每筆含 {display_name, lat, lon}；查無結果或失敗回傳 []。
    """
    keyword = (keyword or "").strip()
    if not keyword:
        return []

    # 先查快取（同一關鍵字一天內不重複打 API）
    cache_key = f"{keyword}|{limit}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    params = {
        "q": keyword,
        "format": "json",
        "limit": limit,
        "viewbox": config.NOMINATIM_VIEWBOX,
        "bounded": 1,  # 只回傳 viewbox 範圍內的結果
    }
    headers = {"User-Agent": config.NOMINATIM_USER_AGENT}

    try:
        _limiter.wait()  # 遵守每秒 1 次的限制
        response = requests.get(
            config.NOMINATIM_URL, params=params, headers=headers, timeout=15
        )
        response.raise_for_status()
        raw_results = response.json()
    except requests.exceptions.RequestException as e:
        print(f"[錯誤] Nominatim 地理編碼失敗: {e}")
        return []

    results = [
        {
            "display_name": item.get("display_name"),
            "lat": float(item["lat"]),
            "lon": float(item["lon"]),
        }
        for item in raw_results
    ]

    _cache.set(cache_key, results)
    return results


def _parse_coordinate(text):
    """
    若輸入是「@緯度,經度」或「緯度,經度」格式（地圖點選），直接解析為座標 dict，
    跳過 Nominatim 查詢。否則回傳 None（代表是一般地名關鍵字）。
    """
    m = _COORD_PATTERN.match(text or "")
    if not m:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    # 粗略合理範圍檢查（台灣一帶），避免把「12,34」之類誤判為座標
    if not (21 <= lat <= 26 and 119 <= lon <= 122):
        return None
    return {
        "display_name": f"地圖選點（{lat:.5f}, {lon:.5f}）",
        "lat": lat,
        "lon": lon,
    }


def geocode_best(keyword):
    """
    便利函式：把輸入解析為最佳座標，回傳 dict 或 None。
    支援兩種輸入：地圖點選的「@緯度,經度」座標（直接解析）、或一般地名關鍵字（查 Nominatim）。
    """
    coord = _parse_coordinate(keyword)
    if coord:
        return coord
    results = geocode(keyword, limit=1)
    return results[0] if results else None
