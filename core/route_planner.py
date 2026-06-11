"""
路線規劃與排序演算法（核心商業邏輯）。

這支檔案是整個系統的「大腦」，負責把各服務模組的結果整合起來：
  地理編碼 → 找附近站牌 → 找可直達路線 → 算四段時間 → 加總排序 → 取前 N 名。

刻意把資料流寫得很直白，方便閱讀。各「外部動作」都委派給 services/，
這裡只做編排與運算（呼應企劃書的「資料整合與排序演算法」）。

四段時間定義（企劃書核心）：
  1. 步行至上車站  walk_to_board   （OSRM）
  2. 等待公車      wait            （TDX 即時到站 / 班表）
  3. 乘車          ride            （TDX 站間行駛時間 S2S，查無才退回站數估算）
  4. 下車步行至終點 walk_to_dest    （OSRM）
總耗時 total = 上述四者相加。
"""

from datetime import datetime

import config
from services import geocoding, bus_static, bus_realtime, walking


def _plan_one(connection, origin, destination):
    """
    把單一「可直達路線方案」算出完整四段時間。

    計算順序刻意「先便宜後昂貴」：先查等待時間（最可能讓方案出局），
    可搭才接著用 OSRM 算兩段真實步行。任一段步行超過上限則濾掉。
    回傳完整方案 dict；不可搭或步行過遠則回傳 None。
    """
    board = connection["board_stop"]
    alight = connection["alight_stop"]

    # 第 2 段：等待時間（查 TDX；最可能讓方案出局，先查可省下 OSRM 呼叫）
    wait = bus_realtime.get_wait_minutes(
        connection["city"], connection["route_name"],
        board["stop_uid"], connection["direction"],
    )
    if wait is None:
        return None  # 末班已過 / 未營運 / 查無資料 → 目前不可搭

    # 第 1 段：起點 → 上車站（OSRM 真實街道步行）
    walk_to_board = walking.get_walking_route(
        origin["lat"], origin["lon"], board["lat"], board["lon"])
    if walk_to_board["duration_min"] > config.MAX_WALK_MINUTES:
        return None

    # 第 4 段：下車站 → 終點
    walk_to_dest = walking.get_walking_route(
        alight["lat"], alight["lon"], destination["lat"], destination["lon"])
    if walk_to_dest["duration_min"] > config.MAX_WALK_MINUTES:
        return None

    # 第 3 段：乘車時間。優先用 TDX 站間行駛時間（S2S，反映真實站距與時段車速）；
    #          查無資料才退回「站數 × 每站固定值」估算。
    ride_min = bus_static.get_ride_minutes(
        connection["city"], connection["route_name"], connection["direction"],
        board["sequence"], alight["sequence"], datetime.now(),
    )
    ride_source = "s2s"
    if ride_min is None:
        ride_min = round(connection["ride_stop_count"] * config.RIDE_MINUTES_PER_STOP, 1)
        ride_source = "estimate"

    total = round(
        walk_to_board["duration_min"] + wait["minutes"]
        + ride_min + walk_to_dest["duration_min"],
        1,
    )

    # 整條路線的完整停靠站序（畫白色圓點站牌）＋道路真實形狀（畫貼路的路線）
    route_stops = bus_static.get_route_stops(
        connection["city"], connection["route_name"], connection["direction"])
    route_shape = bus_static.get_route_shape(
        connection["city"], connection["route_name"], connection["direction"])

    return {
        "route_name": connection["route_name"],
        "city": connection["city"],
        "direction": connection["direction"],
        "board_stop": board,
        "alight_stop": alight,
        "ride_stop_count": connection["ride_stop_count"],
        "route_stops": route_stops,  # 完整站序，含每站 sequence/座標
        "route_shape": route_shape,  # 道路真實形狀 [[lat,lon],...]（可能為空）
        "segments": {
            "walk_to_board_min": walk_to_board["duration_min"],
            "walk_to_board_dist_m": walk_to_board["distance_m"],
            "wait_min": wait["minutes"],
            "wait_source": wait["source"],  # realtime / schedule
            "ride_min": ride_min,
            "ride_source": ride_source,  # s2s（站間行駛時間）/ estimate（站數估算）
            "walk_to_dest_min": walk_to_dest["duration_min"],
            "walk_to_dest_dist_m": walk_to_dest["distance_m"],
        },
        "total_min": total,
        # 給 Folium 畫步行路徑用（GeoJSON [lon,lat] 座標串）
        "walk_to_board_geometry": walk_to_board["geometry"],
        "walk_to_dest_geometry": walk_to_dest["geometry"],
    }


def _keep_fastest_per_route(sorted_plans):
    """
    同一條路線可能有多個可行方案（不同上下車站組合），這裡每條路線只留最快的一個。
    傳入的 plans 需已依 total_min 由小到大排序，故第一次遇到的即為最快。
    """
    seen_routes = set()
    unique = []
    for p in sorted_plans:
        if p["route_name"] in seen_routes:
            continue
        seen_routes.add(p["route_name"])
        unique.append(p)
    return unique


def _dedup_connections(connections):
    """
    同一條路線常因「同站雙向 UID」或多個鄰近站牌而重複。
    以 (route_name, direction, 上車站名, 下車站名) 為鍵去重，只留第一筆。
    """
    seen = set()
    unique = []
    for c in connections:
        key = (
            c["route_name"], c["direction"],
            c["board_stop"]["stop_name"], c["alight_stop"]["stop_name"],
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(c)
    return unique


def plan_routes(origin_keyword, dest_keyword, on_progress=None):
    """
    主要入口：輸入起點與終點關鍵字，回傳前 N 名最快搭乘方案。

    參數：
      on_progress：可選的進度回報 callback，簽名 on_progress(message)。
        會在各階段被呼叫（地理編碼、找站、算時間…），供前端即時顯示後台進度。

    回傳 dict：
      {
        "origin":  {keyword, display_name, lat, lon},
        "destination": {...},
        "plans": [ 方案, ... ]   # 依總耗時由少到多，最多 TOP_N_RESULTS 筆
      }
    若起點或終點無法解析，plans 為空並附帶 error 訊息。
    """
    def progress(msg):
        if on_progress:
            on_progress(msg)

    # 1) 地理編碼：關鍵字 → 座標
    progress(f"解析地點「{origin_keyword}」與「{dest_keyword}」座標…")
    origin = geocoding.geocode_best(origin_keyword)
    destination = geocoding.geocode_best(dest_keyword)
    if not origin or not destination:
        return {
            "origin": {"keyword": origin_keyword},
            "destination": {"keyword": dest_keyword},
            "plans": [],
            "error": "起點或終點無法解析為座標，請換個關鍵字試試。",
        }

    # 2) 找起訖點周邊可步行抵達的站牌（本機資料）
    progress("搜尋起訖點周邊的公車站牌…")
    origin_stops = bus_static.find_nearby_stops(origin["lat"], origin["lon"])
    dest_stops = bus_static.find_nearby_stops(destination["lat"], destination["lon"])

    # 3) 找可直達路線（本機資料）：每條路線挑步行最近的上/下車站，並去重
    connections = bus_static.find_connections(
        [s["stop_uid"] for s in origin_stops],
        [s["stop_uid"] for s in dest_stops],
        origin, destination,
    )
    connections = _dedup_connections(connections)
    progress(f"找到 {len(connections)} 條可直達路線，計算各方案時間…")

    # 4) 對每個候選方案算完整四段時間（先查等待、可搭才用 OSRM 算步行）
    plans = []
    for idx, conn in enumerate(connections, 1):
        progress(f"計算路線時間（{idx}/{len(connections)}）：{conn['route_name']} 線"
                 "　查即時動態與步行路徑…")
        plan = _plan_one(conn, origin, destination)
        if plan is not None:
            plans.append(plan)

    # 5) 依總耗時排序 → 每條路線只留最快的一個 → 剔除荒謬過長者 → 取前 N 名
    progress("彙整並排序最快的方案…")
    plans.sort(key=lambda p: p["total_min"])
    plans = _keep_fastest_per_route(plans)
    if plans:
        fastest = plans[0]["total_min"]
        # 同時超過「最快 × 倍數」與「絕對上限」才剔除（兩條件都成立才算荒謬）
        plans = [
            p for p in plans
            if not (
                p["total_min"] > fastest * config.MAX_TOTAL_RATIO
                and p["total_min"] > config.MAX_TOTAL_ABSOLUTE_MINUTES
            )
        ]
    plans = plans[: config.TOP_N_RESULTS]

    return {
        "origin": {
            "keyword": origin_keyword,
            "display_name": origin["display_name"],
            "lat": origin["lat"],
            "lon": origin["lon"],
        },
        "destination": {
            "keyword": dest_keyword,
            "display_name": destination["display_name"],
            "lat": destination["lat"],
            "lon": destination["lon"],
        },
        "plans": plans,
    }
