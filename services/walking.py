"""
步行時間過濾模組（OSRM API）。

職責：把兩個座標（起點→上車站、下車站→終點）送進 OSRM，
取得「考量實際街道」的真實步行時間與路徑幾何。
對應企劃書強制技術棧中的「OSRM API：取得真實步行時間，並以此過濾與排序」。

OSRM route 端點回傳：
  - duration（秒）：步行時間 → 用於排序
  - distance（公尺）
  - geometry（GeoJSON LineString）：路徑座標 → 交給 Folium 畫線
"""

import requests

import config
from utils.cache import TTLCache
from utils.rate_limiter import RateLimiter
from services.bus_static import haversine_m

_limiter = RateLimiter(config.OSRM_RATE_LIMIT_SECONDS)
# 步行路徑對固定兩點而言不太會變，可快取較久（沿用地理編碼的 TTL）
_cache = TTLCache(config.GEOCODE_CACHE_TTL_SECONDS)


def _fallback_walk(lat1, lon1, lat2, lon2):
    """OSRM 失敗時的備援：用直線距離 ÷ 估速概算，路徑退化為兩點直線。"""
    dist = haversine_m(lat1, lon1, lat2, lon2)
    minutes = round(dist / config.WALKING_SPEED_M_PER_MIN, 1)
    return {
        "duration_min": minutes,
        "distance_m": round(dist, 1),
        # GeoJSON 是 [lon, lat] 順序
        "geometry": [[lon1, lat1], [lon2, lat2]],
        "is_fallback": True,
    }


def get_walking_route(lat1, lon1, lat2, lon2):
    """
    取得 (lat1,lon1) → (lat2,lon2) 的步行時間與路徑。

    回傳 dict：{duration_min, distance_m, geometry, is_fallback}
      geometry：list[[lon, lat], ...]（GeoJSON LineString 座標，給 Folium 用）
    OSRM 失敗時自動退回直線估算（is_fallback=True）。
    """
    cache_key = f"{lat1:.5f},{lon1:.5f};{lat2:.5f},{lon2:.5f}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    # OSRM 座標順序是 經度,緯度
    coords = f"{lon1},{lat1};{lon2},{lat2}"
    url = f"{config.OSRM_BASE_URL}/route/v1/foot/{coords}"
    params = {"overview": "full", "geometries": "geojson"}

    try:
        _limiter.wait()
        response = requests.get(url, params=params, timeout=20)
        response.raise_for_status()
        data = response.json()
        route = data["routes"][0]
        distance_m = route["distance"]
        # 不採用 OSRM 回傳的 duration（公開伺服器的 foot profile 實為開車速度，
        # 會嚴重低估步行時間），改以真實街道「距離 ÷ 合理步速」自行換算。
        result = {
            "duration_min": round(distance_m / config.WALKING_SPEED_M_PER_MIN, 1),
            "distance_m": round(distance_m, 1),
            "geometry": route["geometry"]["coordinates"],
            "is_fallback": False,
        }
    except (requests.exceptions.RequestException, KeyError, IndexError) as e:
        print(f"[警告] OSRM 步行查詢失敗，改用直線估算: {e}")
        result = _fallback_walk(lat1, lon1, lat2, lon2)

    _cache.set(cache_key, result)
    return result
