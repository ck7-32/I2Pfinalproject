"""
本機公車靜態資料模組。

職責：載入 data/ 底下由 download_bus_data.py 產生的 JSON（站牌、路線、路線站序），
並提供兩個導航核心查詢：
  1. find_nearby_stops()  ── 找出某座標步行半徑內的站牌
  2. find_connections()   ── 找出能從「上車站」搭到「下車站」的路線（含正確方向與站序）

對應企劃書「站牌位置、編號、各公車路線先儲存在本機 JSON」的需求。
此模組完全不碰外部 API，純讀本機檔案 + 計算。
"""

import os
import json
import math

import config

# ---- 模組載入時把資料讀進記憶體（只讀一次）----
# _stops_of_route：所有城市的「路線→依序站牌」攤平成一個 list
# _stop_index：stop_uid -> 站牌基本資料（座標），供快速查座標用
# _shape_index：(city, route_name, direction) -> 道路形狀座標串 [[lat,lon],...]
# _s2s_index：(city, route_id, direction) -> [時段, ...]，每個時段含 weekday/時區/站間秒數表
_stops_of_route = []
_stop_index = {}
_shape_index = {}
_s2s_index = {}
_route_id_by_name = {}  # (city, route_name) -> route_id


def _load_city(city):
    """讀取單一城市的 stops、stops_of_route、shapes JSON，併入模組層級資料。"""
    stops_path = os.path.join(config.DATA_DIR, f"{city}_stops.json")
    sor_path = os.path.join(config.DATA_DIR, f"{city}_stops_of_route.json")

    if not (os.path.exists(stops_path) and os.path.exists(sor_path)):
        print(f"[警告] 找不到 {city} 的資料檔，已略過。請先執行 download_bus_data.py。")
        return

    with open(stops_path, "r", encoding="utf-8") as f:
        for stop in json.load(f):
            _stop_index[stop["stop_uid"]] = stop

    with open(sor_path, "r", encoding="utf-8") as f:
        for route in json.load(f):
            route["city"] = city  # 標記來源城市，查即時到站時要用
            _stops_of_route.append(route)

    # 路線形狀（道路真實走向）；舊資料若無此檔則略過，地圖會退回站到站連線。
    shapes_path = os.path.join(config.DATA_DIR, f"{city}_shapes.json")
    if os.path.exists(shapes_path):
        with open(shapes_path, "r", encoding="utf-8") as f:
            for shape in json.load(f):
                key = (city, shape["route_name"], shape["direction"])
                _shape_index[key] = shape["geometry"]

    # 路線名 → route_id 對照（S2S 行駛時間以 route_id 為鍵）
    routes_path = os.path.join(config.DATA_DIR, f"{city}_routes.json")
    if os.path.exists(routes_path):
        with open(routes_path, "r", encoding="utf-8") as f:
            for r in json.load(f):
                if r.get("route_name") and r.get("route_id"):
                    _route_id_by_name[(city, r["route_name"])] = r["route_id"]

    # 站間行駛時間（S2STravelTime）；舊資料若無此檔則略過，乘車時間退回站數估算。
    s2s_path = os.path.join(config.DATA_DIR, f"{city}_s2s_travel_time.json")
    if os.path.exists(s2s_path):
        with open(s2s_path, "r", encoding="utf-8") as f:
            for entry in json.load(f):
                key = (city, entry["route_id"], entry["direction"])
                _s2s_index[key] = entry["windows"]


def _ensure_loaded():
    """確保資料已載入（lazy load）；重複呼叫只會載入一次。"""
    if _stops_of_route:
        return
    for city in config.CITIES:
        _load_city(city)
    print(f"[系統] 已載入 {len(_stops_of_route)} 條路線方向、{len(_stop_index)} 個站牌座標。")


def haversine_m(lat1, lon1, lat2, lon2):
    """計算兩經緯度之間的直線距離（公尺）。用於初步篩選最近站牌。"""
    r = 6371000.0  # 地球半徑（公尺）
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def find_nearby_stops(lat, lon, radius_m=None):
    """
    找出座標 (lat, lon) 步行半徑內的所有站牌，依直線距離由近到遠排序。

    回傳：list[dict]，每筆含 {stop_uid, stop_name, lat, lon, distance_m}。
    """
    _ensure_loaded()
    radius_m = radius_m if radius_m is not None else config.NEARBY_RADIUS_M

    nearby = []
    for stop in _stop_index.values():
        pos = stop.get("position", {})
        s_lat, s_lon = pos.get("lat"), pos.get("lon")
        if s_lat is None or s_lon is None:
            continue

        dist = haversine_m(lat, lon, s_lat, s_lon)
        if dist <= radius_m:
            nearby.append({
                "stop_uid": stop["stop_uid"],
                "stop_name": stop["stop_name"],
                "lat": s_lat,
                "lon": s_lon,
                "distance_m": round(dist, 1),
            })

    nearby.sort(key=lambda s: s["distance_m"])
    return nearby


def _pick_nearest_valid_pair(board_candidates, alight_candidates, origin_pos,
                             dest_pos, total_stops=None):
    """
    在「方向正確且不繞大圈」的組合中，挑直線步行距離總和最小的 (board, alight)。

    選站主要看步行距離（最直覺）；唯一額外限制是「排除明顯繞圈」的組合 ——
    環狀線或同名站重複的路線（如藍線1區的「火車站」出現在序1與序56），
    若上下車站序相差超過「全線站數的一半」，幾乎一定是繞了一大圈，直接剔除。

    候選站通常很少，直接 O(n×m) 逐組評分；找不到合法組合回傳 None。
    """
    def dist_to_origin(s):
        return haversine_m(origin_pos["lat"], origin_pos["lon"],
                           s["position"]["lat"], s["position"]["lon"])

    def dist_to_dest(s):
        return haversine_m(dest_pos["lat"], dest_pos["lon"],
                          s["position"]["lat"], s["position"]["lon"])

    # 繞圈門檻：坐超過「全線一半站數」視為繞圈（total_stops 未知時不設限）
    max_ride = total_stops / 2 if total_stops else float("inf")

    best_pair = None
    best_dist = None
    for b in board_candidates:
        for a in alight_candidates:
            if b["stop_sequence"] >= a["stop_sequence"]:
                continue  # 方向不對（要正向搭）
            if a["stop_sequence"] - b["stop_sequence"] > max_ride:
                continue  # 明顯繞大圈，排除
            total = dist_to_origin(b) + dist_to_dest(a)
            if best_dist is None or total < best_dist:
                best_dist = total
                best_pair = (b, a)
    return best_pair


def find_connections(origin_stop_uids, dest_stop_uids, origin_pos, dest_pos):
    """
    在所有路線中，找出能從「起點附近任一站」搭到「終點附近任一站」的直達方案。

    參數：
      origin_stop_uids / dest_stop_uids：起訖點周邊站牌的 stop_uid 清單
      origin_pos / dest_pos：起點與終點座標 dict，含 {"lat","lon"}，
        用來在同一條路線上挑「步行最近」的上車站與下車站。

    選站邏輯：在所有「上車站序 < 下車站序」的合法組合中，
    挑使「起點→上車站 + 下車站→終點」直線步行距離最小的那組
    （直線距離夠接近真實街道距離，可當選站依據；最終步行時間仍用 OSRM 算）。

    回傳：list[dict]，每筆代表一個可行的搭乘段，含：
      route_name, city, direction,
      board_stop / alight_stop（各含 uid, name, sequence, lat, lon），
      ride_stop_count（中間經過幾站，供估算乘車時間）。
    """
    _ensure_loaded()
    origin_set = set(origin_stop_uids)
    dest_set = set(dest_stop_uids)

    connections = []
    for route in _stops_of_route:
        stops = route["stops"]

        # 找出這條路線方向上，落在起點集合與終點集合的站（記錄站序）
        board_candidates = [s for s in stops if s["stop_uid"] in origin_set]
        alight_candidates = [s for s in stops if s["stop_uid"] in dest_set]
        if not board_candidates or not alight_candidates:
            continue

        # 在「方向正確且不繞大圈」的上下車組合中，挑步行距離總和最小的那組。
        # 傳入全線站數，讓環狀線能排除「繞超過半圈」的不合理組合。
        best = _pick_nearest_valid_pair(
            board_candidates, alight_candidates, origin_pos, dest_pos,
            total_stops=len(stops))
        if best is None:
            continue
        board, alight = best

        connections.append({
            "route_name": route["route_name"],
            "city": route["city"],
            "direction": route["direction"],
            "board_stop": {
                "stop_uid": board["stop_uid"],
                "stop_name": board["stop_name"],
                "sequence": board["stop_sequence"],
                "lat": board["position"]["lat"],
                "lon": board["position"]["lon"],
            },
            "alight_stop": {
                "stop_uid": alight["stop_uid"],
                "stop_name": alight["stop_name"],
                "sequence": alight["stop_sequence"],
                "lat": alight["position"]["lat"],
                "lon": alight["position"]["lon"],
            },
            "ride_stop_count": alight["stop_sequence"] - board["stop_sequence"],
        })

    return connections


def get_route_stops(city, route_name, direction):
    """
    取得某路線某方向「完整、依序」的停靠站清單（供地圖畫整條路線用）。

    回傳：list[dict]，每筆含 {stop_uid, stop_name, sequence, lat, lon}，依站序排序；
    查無則回傳 []。
    """
    _ensure_loaded()
    for route in _stops_of_route:
        if (route["city"] == city
                and route["route_name"] == route_name
                and route["direction"] == direction):
            stops = sorted(route["stops"], key=lambda s: s["stop_sequence"])
            return [
                {
                    "stop_uid": s["stop_uid"],
                    "stop_id": s["stop_id"],
                    "stop_name": s["stop_name"],
                    "sequence": s["stop_sequence"],
                    "lat": s["position"]["lat"],
                    "lon": s["position"]["lon"],
                }
                for s in stops
            ]
    return []


def get_route_shape(city, route_name, direction):
    """
    取得某路線某方向「貼著道路」的真實形狀座標串。

    回傳：list[[lat, lon], ...]（Folium 可直接畫線）；查無則回傳 []
    （呼叫端可退回以站牌座標連線）。
    """
    _ensure_loaded()
    return _shape_index.get((city, route_name, direction), [])


def get_city_route_names(city):
    """回傳某城市（含虛擬城市）所有不重複的路線名清單。"""
    _ensure_loaded()
    return sorted({
        r["route_name"] for r in _stops_of_route
        if r["city"] == city and r.get("route_name")
    })


def _pick_s2s_window(windows, now):
    """
    從某路線方向的多個時段中，挑「最符合現在（星期＋小時）」的那個的站間秒數表。

    優先精準匹配當天 weekday 且 StartHour ≤ 現在小時 < EndHour；
    找不到再放寬（不分星期 weekday=99、或任一時段），都沒有才回 None。
    """
    weekday = now.weekday()  # 0=週一 ... 6=週日；TDX weekday 0=週日,1=週一...6=週六,99=不分
    tdx_weekday = (weekday + 1) % 7  # 轉成 TDX 的週日=0 制
    hour = now.hour

    def hour_match(w):
        return w.get("start_hour", 0) <= hour < w.get("end_hour", 24)

    # 1) 當天且時段吻合
    for w in windows:
        if w.get("weekday") == tdx_weekday and hour_match(w) and w.get("times"):
            return w["times"]
    # 2) 不分星期(99)且時段吻合
    for w in windows:
        if w.get("weekday") == 99 and hour_match(w) and w.get("times"):
            return w["times"]
    # 3) 退而求其次：任何一個有資料的時段
    for w in windows:
        if w.get("times"):
            return w["times"]
    return None


def get_ride_minutes(city, route_name, direction, board_seq, alight_seq, now):
    """
    用 TDX 站間行駛時間（S2STravelTime）算「上車站→下車站」的實際乘車分鐘。

    做法：取該路線方向、最符合現在時段的站間秒數表，沿著完整站序從上車站走到
    下車站，逐段把 RunTime 累加。

    回傳：float 分鐘數；若查無此路線的 S2S 資料、或途中缺太多段，回傳 None
    （呼叫端可退回「站數 × 每站固定值」估算）。
    """
    _ensure_loaded()
    route_id = _route_id_by_name.get((city, route_name))
    if route_id is None:
        return None
    windows = _s2s_index.get((city, route_id, direction))
    if not windows:
        return None
    times = _pick_s2s_window(windows, now)
    if not times:
        return None

    # 取完整站序中 [board_seq, alight_seq] 區間的站，依序累加相鄰段秒數
    stops = get_route_stops(city, route_name, direction)
    segment = [s for s in stops if board_seq <= s["sequence"] <= alight_seq]
    if len(segment) < 2:
        return None

    total_sec = 0.0
    missing = 0
    for prev, curr in zip(segment, segment[1:]):
        key = f"{prev['stop_id']}->{curr['stop_id']}"
        run = times.get(key)
        if run is None:
            missing += 1
        else:
            total_sec += run

    # 缺漏太多段（超過半數）代表資料對不上，視為不可用
    pairs = len(segment) - 1
    if missing > pairs / 2:
        return None
    # 少數缺漏的段用「已知段平均」補上，避免低估
    if missing and missing < pairs:
        avg = total_sec / (pairs - missing)
        total_sec += avg * missing

    return round(total_sec / 60.0, 1)
