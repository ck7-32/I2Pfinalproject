"""
即時公車資料模組（TDX 運輸資料流通服務）。

職責：查詢「某路線在某站牌的下一班車還要多久」，換算成使用者的「等待時間」。
對應企劃書「即時公車資料模組：行經站牌的即時公車預估到站時間」。

兩層資料來源（依序）：
  1. EstimatedTimeOfArrival（即時預估）── 有車在跑、StopStatus=0 時提供秒數，最準。
  2. Schedule（班表）── 當即時拿不到（多數班次是「尚未發車」StopStatus=1，
     TDX 不給預估秒數）時，改用班表算「今日該站下一班到站時刻」。

StopStatus 代碼意義（TDX 定義）：
  0 = 正常（有 EstimateTime 可用）   1 = 尚未發車
  2 = 交管不停靠                     3 = 末班車已過      4 = 今日未營運
"""

import time
from datetime import datetime

import requests

import config
from services import bus_static
from utils.cache import TTLCache
from utils.rate_limiter import RateLimiter

# 即時資料 TTL 短；班表一天才更新一次，可快取久一點
_eta_cache = TTLCache(config.CACHE_TTL_SECONDS)
_schedule_cache = TTLCache(config.SCHEDULE_CACHE_TTL_SECONDS)

# TDX 流量限制器：請求之間至少間隔設定秒數，避免被回 429
_limiter = RateLimiter(config.TDX_RATE_LIMIT_SECONDS)

# TDX token 狀態（模組層級保存，重複利用直到過期）
_token = None
_token_expires_at = 0.0

# 星期幾對應 TDX ServiceDay 的鍵
_WEEKDAY_KEYS = [
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
]


def _get_token():
    """取得（必要時更新）TDX 授權 token。"""
    global _token, _token_expires_at

    if _token and time.time() < _token_expires_at - 60:
        return _token

    payload = {
        "grant_type": "client_credentials",
        "client_id": config.TDX_CLIENT_ID,
        "client_secret": config.TDX_CLIENT_SECRET,
    }
    response = requests.post(config.TDX_AUTH_URL, data=payload, timeout=15)
    response.raise_for_status()
    data = response.json()

    _token = data.get("access_token")
    _token_expires_at = time.time() + data.get("expires_in", 86400)
    return _token


def _tdx_get(path, cache, cache_key, params=None):
    """對 TDX 發 GET 並快取；失敗回傳 []。params 為額外查詢參數（如 InterCity 的 $filter）。"""
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    url = f"{config.TDX_BUS_BASE_URL}/{path}"
    headers_factory = lambda: {"authorization": f"Bearer {_get_token()}"}
    query = {"$format": "JSON"}
    if params:
        query.update(params)

    # 被 429 限流時，稍候再重試一次；仍失敗才放棄
    data = None
    for attempt in range(2):
        try:
            _limiter.wait()  # 遵守 TDX 流量間隔
            response = requests.get(
                url, headers=headers_factory(),
                params=query, timeout=20,
            )
            if response.status_code == 429 and attempt == 0:
                time.sleep(1.0)  # 被限流，稍等後重試
                continue
            response.raise_for_status()
            data = response.json()
            break
        except requests.exceptions.RequestException as e:
            print(f"[錯誤] TDX 查詢失敗 ({path}): {e}")
            return []

    if data is None:
        return []

    # 班表查無路線時 TDX 會回 dict {"message": "Resouce Not Found"}，統一成 []
    if not isinstance(data, list):
        data = []

    cache.set(cache_key, data)
    return data


def _intercity_batch_filter(city):
    """
    把該虛擬城市關心的所有 InterCity 路線名組成一個 $filter（以 or 串接），
    讓即時/班表都能「一次撈回這些路線」，避免逐路線打 API 觸發限流。
    """
    names = bus_static.get_city_route_names(city)
    clause = " or ".join(f"RouteName/Zh_tw eq '{n}'" for n in names)
    return {"$filter": clause}


def _fetch_city_eta(city, route_name):
    """
    查即時到站預估。不論市區公車或公路客運，整城（或整批路線）只打 1 次、其餘走快取。

    一般市區公車：城市層級端點一次撈全城。
    公路客運（InterCity）：端點不分城市，用 $filter 一次撈回所有關心的路線。
    """
    if city == config.INTERCITY_CITY:
        return _tdx_get(
            "EstimatedTimeOfArrival/InterCity",
            _eta_cache, f"eta|{city}",
            params=_intercity_batch_filter(city),
        )
    return _tdx_get(
        f"EstimatedTimeOfArrival/City/{city}",
        _eta_cache, f"eta|{city}",
    )


def _fetch_city_schedule(city, route_name):
    """查班表。市區公車一次撈全城；公路客運（InterCity）以 $filter 一次撈回所有關心路線。"""
    if city == config.INTERCITY_CITY:
        return _tdx_get(
            "Schedule/InterCity",
            _schedule_cache, f"sched|{city}",
            params=_intercity_batch_filter(city),
        )
    return _tdx_get(
        f"Schedule/City/{city}",
        _schedule_cache, f"sched|{city}",
    )


def _wait_from_realtime(city, route_name, stop_uid, direction):
    """從即時預估中，篩出該路線該站該方向的等待分鐘數；無正常預估回傳 None。"""
    for rec in _fetch_city_eta(city, route_name):
        if rec.get("RouteName", {}).get("Zh_tw") != route_name:
            continue
        if rec.get("StopUID") != stop_uid or rec.get("Direction") != direction:
            continue
        # 只採用 StopStatus=0 且有 EstimateTime 的（真正有車在跑、可預估）
        if rec.get("StopStatus") == 0 and rec.get("EstimateTime") is not None:
            return round(rec["EstimateTime"] / 60.0, 1)
    return None


def _wait_from_schedule(city, route_name, stop_uid, direction):
    """
    從整城班表推算「今日該路線該站該方向，現在之後最早一班」的等待分鐘數。
    今日已無班次或查無班表則回傳 None。
    """
    now = datetime.now()
    weekday_key = _WEEKDAY_KEYS[now.weekday()]
    now_minutes = now.hour * 60 + now.minute

    upcoming = []  # 今日尚未到站的班次（以「當日分鐘數」表示）
    for entry in _fetch_city_schedule(city, route_name):
        if entry.get("RouteName", {}).get("Zh_tw") != route_name:
            continue
        if entry.get("Direction") != direction:
            continue
        for timetable in entry.get("Timetables", []):
            # 這個班次今天是否行駛
            if timetable.get("ServiceDay", {}).get(weekday_key, 0) != 1:
                continue
            for stop_time in timetable.get("StopTimes", []):
                if stop_time.get("StopUID") != stop_uid:
                    continue
                arrival = stop_time.get("ArrivalTime")  # 格式 "HH:MM"
                if not arrival:
                    continue
                hh, mm = map(int, arrival.split(":"))
                arrival_minutes = hh * 60 + mm
                if arrival_minutes >= now_minutes:
                    upcoming.append(arrival_minutes)

    if not upcoming:
        return None
    return float(min(upcoming) - now_minutes)


def get_wait_minutes(city, route_name, stop_uid, direction):
    """
    取得「在指定站牌、指定方向，該路線下一班車還要多久」。

    回傳 dict：{"minutes": float, "source": "realtime" | "schedule"}
      或 None ── 即時與班表都查不到（末班已過 / 今日未營運 / 該站無此路線）。

    優先用即時預估（最準）；拿不到時退回班表推算（standby）。
    """
    # 1) 即時預估優先
    minutes = _wait_from_realtime(city, route_name, stop_uid, direction)
    if minutes is not None:
        return {"minutes": minutes, "source": "realtime"}

    # 2) 退回班表推算
    minutes = _wait_from_schedule(city, route_name, stop_uid, direction)
    if minutes is not None:
        return {"minutes": minutes, "source": "schedule"}

    return None
