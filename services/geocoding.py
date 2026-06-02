"""
地理編碼模組（Nominatim API）。

職責：把使用者輸入的「地點關鍵字」轉換為經緯度座標與候選地點清單。
對應企劃書強制技術棧中的「Nominatim API：搜尋地點與候選位置」。

注意事項：
  - Nominatim 公開服務規定「每秒最多 1 次請求」，且必須帶 User-Agent，
    因此這裡接上 RateLimiter 與 TTLCache。
  - 搜尋範圍用 viewbox 限制在新竹一帶，避免同名地點解析到外縣市。
"""

import requests

import config
from utils.cache import TTLCache
from utils.rate_limiter import RateLimiter

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


def geocode_best(keyword):
    """便利函式：只取最佳（第一筆）候選座標，回傳 dict 或 None。"""
    results = geocode(keyword, limit=1)
    return results[0] if results else None
