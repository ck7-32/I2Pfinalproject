"""
下載指定縣市的公車「路線」與「站牌」靜態資料，並以 JSON 格式儲存於本機 data/ 資料夾。

資料來源：TDX 運輸資料流通服務 (Public Transport Data eXchange)
用途：作為即時公車導航系統的本機快取，避免每次查詢都重新呼叫 API。

對應企劃書「即時公車資料模組」中『站牌位置、編號、各公車路線先儲存在本機 JSON』的需求。
"""

import os
import re
import time
import json
import requests
from dotenv import load_dotenv

# TDX 預設的縣市代碼（City 路徑參數）
#   新竹市 = Hsinchu，新竹縣 = HsinchuCounty
DEFAULT_CITY = "Hsinchu"

# 公路客運（InterCity）虛擬城市名稱與其路線清單來源檔
INTERCITY_NAME = "InterCityHsinchu"
EXTRA_ROUTE_MD = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "extra_route.md")

# 資料輸出資料夾（相對於本檔案所在目錄）
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


class TDXClient:
    """負責 TDX OAuth2 授權與公車靜態資料下載。"""

    AUTH_URL = (
        "https://tdx.transportdata.tw/auth/realms/TDXConnect/"
        "protocol/openid-connect/token"
    )
    BASE_URL = "https://tdx.transportdata.tw/api/basic/v2/Bus"

    def __init__(self, client_id, client_secret):
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = None
        self.token_expires_at = 0

    def _get_token(self):
        # token 尚未過期就直接重用（保留 60 秒緩衝）
        if self.access_token and time.time() < self.token_expires_at - 60:
            return self.access_token

        payload = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }

        response = requests.post(self.AUTH_URL, data=payload, timeout=15)
        response.raise_for_status()
        token_data = response.json()

        self.access_token = token_data.get("access_token")
        self.token_expires_at = time.time() + token_data.get("expires_in", 86400)
        print(f"[系統] 成功獲取 TDX Token，有效期限至: {time.ctime(self.token_expires_at)}")
        return self.access_token

    def _get(self, path, params=None):
        """對 TDX 公車 API 發出 GET 請求，回傳已解析的 JSON。"""
        query = {"$format": "JSON"}
        if params:
            query.update(params)

        # 最多重試 3 次：處理 429 限流與暫時性連線/逾時錯誤。
        last_error = None
        for attempt in range(3):
            time.sleep(0.5)  # 請求間稍作間隔，降低觸發限流機率
            try:
                headers = {"authorization": f"Bearer {self._get_token()}"}
                response = requests.get(
                    f"{self.BASE_URL}/{path}", headers=headers, params=query, timeout=30
                )
                if response.status_code == 429 and attempt < 2:
                    print("[系統] 被 TDX 限流，等待 15 秒後重試...")
                    time.sleep(15)
                    continue
                response.raise_for_status()
                return response.json()
            except requests.exceptions.RequestException as e:
                last_error = e
                if attempt < 2:
                    print(f"[系統] 連線異常（{type(e).__name__}），等待 5 秒後重試...")
                    time.sleep(5)

        raise last_error

    def get_routes(self, city):
        """取得該縣市所有公車路線（含路線名稱、起訖站、營運業者）。"""
        return self._get(f"Route/City/{city}")

    def get_stops(self, city):
        """取得該縣市所有不重複的公車站牌（含座標與站牌編號）。"""
        return self._get(f"Stop/City/{city}")

    def get_stops_of_route(self, city):
        """取得該縣市每條路線「依序」經過的站牌列表（導航排序用）。"""
        return self._get(f"StopOfRoute/City/{city}")

    def get_shapes(self, city):
        """取得該縣市每條路線「貼著道路」的真實路線形狀（供地圖畫線）。"""
        return self._get(f"Shape/City/{city}")

    def get_s2s_travel_time(self, city, route_id):
        """
        取得該縣市指定路線的「站間行駛時間」（每段 From→To 的實際秒數）。
        注意：此端點須帶 route_id（如 83 號的 0008），不是路線名。
        此端點限流較嚴（每分鐘 5 次），故呼叫前多等一段時間。
        """
        time.sleep(13)  # 每分鐘最多 5 次 → 間隔約 12-13 秒才安全
        return self._get(f"S2STravelTime/City/{city}/{route_id}")

    # ---- 公路客運（InterCity）：端點不分縣市，以路線名 $filter 篩選 ----

    def _intercity_filter(self, endpoint, route_names):
        """查 InterCity 端點，用 $filter 只取指定路線名（一次帶多條，以 or 串接）。"""
        quoted = " or ".join(f"RouteName/Zh_tw eq '{n}'" for n in route_names)
        return self._get(f"{endpoint}/InterCity", params={"$filter": quoted})

    def get_intercity_routes(self, route_names):
        """取得指定公路客運路線（含起訖站、業者）。"""
        return self._intercity_filter("Route", route_names)

    def get_intercity_stops_of_route(self, route_names):
        """取得指定公路客運路線「依序」經過的站牌。"""
        return self._intercity_filter("StopOfRoute", route_names)

    def get_intercity_shapes(self, route_names):
        """取得指定公路客運路線的道路形狀。"""
        return self._intercity_filter("Shape", route_names)

    def get_intercity_s2s_travel_time(self, route_id):
        """取得指定公路客運路線的站間行駛時間（限流嚴，呼叫前先等）。"""
        time.sleep(13)
        return self._get(f"S2STravelTime/InterCity/{route_id}")


def _clean_routes(raw_routes):
    """精簡路線資料，只保留導航會用到的欄位。"""
    cleaned = []
    for route in raw_routes:
        cleaned.append({
            "route_uid": route.get("RouteUID"),
            "route_id": route.get("RouteID"),
            "route_name": route.get("RouteName", {}).get("Zh_tw"),
            "departure_stop": route.get("DepartureStopNameZh"),
            "destination_stop": route.get("DestinationStopNameZh"),
            "operators": [
                op.get("OperatorName", {}).get("Zh_tw")
                for op in route.get("Operators", [])
            ],
        })
    return cleaned


def _clean_stops(raw_stops):
    """精簡站牌資料，只保留站名、編號與經緯度。"""
    cleaned = []
    for stop in raw_stops:
        position = stop.get("StopPosition", {})
        cleaned.append({
            "stop_uid": stop.get("StopUID"),
            "stop_id": stop.get("StopID"),
            "stop_name": stop.get("StopName", {}).get("Zh_tw"),
            "position": {
                "lat": position.get("PositionLat"),
                "lon": position.get("PositionLon"),
            },
        })
    return cleaned


def _clean_stops_of_route(raw_stops_of_route):
    """精簡『路線 → 依序站牌』資料，保留方向與站序。"""
    cleaned = []
    for route in raw_stops_of_route:
        stops = []
        for stop in route.get("Stops", []):
            position = stop.get("StopPosition", {})
            stops.append({
                "stop_uid": stop.get("StopUID"),
                "stop_id": stop.get("StopID"),
                "stop_name": stop.get("StopName", {}).get("Zh_tw"),
                "stop_sequence": stop.get("StopSequence"),
                "position": {
                    "lat": position.get("PositionLat"),
                    "lon": position.get("PositionLon"),
                },
            })
        cleaned.append({
            "route_uid": route.get("RouteUID"),
            "route_name": route.get("RouteName", {}).get("Zh_tw"),
            "direction": route.get("Direction"),  # 0=去程, 1=返程
            "stops": stops,
        })
    return cleaned


def _parse_wkt_linestring(wkt):
    """
    解析 TDX Shape 的 WKT 字串為座標串。

    輸入如 "LINESTRING(120.97974 24.77892,120.97984 24.77882,...)"，
    WKT 是「經度 緯度」順序；回傳 [[lat, lon], ...]（Folium/Leaflet 要的順序）。
    解析失敗回傳 []。
    """
    if not wkt or "(" not in wkt:
        return []
    try:
        inner = wkt[wkt.index("(") + 1: wkt.rindex(")")]
        coords = []
        for pair in inner.split(","):
            lon, lat = pair.strip().split()
            coords.append([float(lat), float(lon)])
        return coords
    except (ValueError, IndexError):
        return []


def _clean_shapes(raw_shapes):
    """精簡路線形狀資料，保留路線名、方向與道路座標串。"""
    cleaned = []
    for shape in raw_shapes:
        cleaned.append({
            "route_name": shape.get("RouteName", {}).get("Zh_tw"),
            "direction": shape.get("Direction"),  # 0=去程, 1=返程
            "geometry": _parse_wkt_linestring(shape.get("Geometry", "")),
        })
    return cleaned


def _clean_s2s_travel_time(raw_entries):
    """
    精簡單一路線的站間行駛時間資料。

    保留：route_id、方向，以及各時段（星期/起訖小時）的站間秒數。
    結構：[{route_id, direction, windows: [{weekday, start_hour, end_hour,
            times: {"FromStopID->ToStopID": run_time_sec, ...}}]}]
    （把 S2STimes 轉成 dict 方便之後 O(1) 查某段行駛時間。RunTime=-1 代表無資料，略過。）
    """
    cleaned = []
    for entry in raw_entries:
        windows = []
        for tt in entry.get("TravelTimes", []):
            times = {}
            for s in tt.get("S2STimes", []):
                run = s.get("RunTime")
                if run is None or run < 0:
                    continue  # -1 = 該區間無資料
                times[f"{s['FromStopID']}->{s['ToStopID']}"] = run
            windows.append({
                "weekday": tt.get("Weekday"),
                "start_hour": tt.get("StartHour"),
                "end_hour": tt.get("EndHour"),
                "times": times,
            })
        cleaned.append({
            "route_id": entry.get("RouteID"),
            "direction": entry.get("Direction"),
            "windows": windows,
        })
    return cleaned


def _save_json(filename, data):
    """將資料寫入 data/ 資料夾下的 JSON 檔。"""
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[完成] 已儲存 {len(data)} 筆資料至 {path}")


def download_city_bus_data(client, city):
    """下載並儲存指定縣市的路線、站牌、路線站序三份資料。"""
    print(f"\n[開始] 下載 {city} 的公車靜態資料...")

    routes = _clean_routes(client.get_routes(city))
    _save_json(f"{city}_routes.json", routes)

    stops = _clean_stops(client.get_stops(city))
    _save_json(f"{city}_stops.json", stops)

    stops_of_route = _clean_stops_of_route(client.get_stops_of_route(city))
    _save_json(f"{city}_stops_of_route.json", stops_of_route)

    shapes = _clean_shapes(client.get_shapes(city))
    _save_json(f"{city}_shapes.json", shapes)

    download_s2s_travel_time(client, city)

    print(f"[結束] {city} 資料下載完成。\n")


def download_s2s_travel_time(client, city):
    """
    下載該縣市每條路線的站間行駛時間（須逐 route_id 查），合併成一份。

    route_id 從已存的 {city}_routes.json 讀取，所以可單獨重跑此步（不重抓其他資料）。
    具續傳能力：若先前已存部分結果，會跳過已下載的 route_id，方便被 429 中斷後接續。
    """
    routes_path = os.path.join(DATA_DIR, f"{city}_routes.json")
    with open(routes_path, "r", encoding="utf-8") as f:
        routes = json.load(f)
    route_ids = sorted({r["route_id"] for r in routes if r.get("route_id")})

    # 續傳：讀取已存結果，跳過已完成的 route_id
    out_path = os.path.join(DATA_DIR, f"{city}_s2s_travel_time.json")
    s2s_all = []
    done_ids = set()
    if os.path.exists(out_path):
        with open(out_path, "r", encoding="utf-8") as f:
            s2s_all = json.load(f)
        done_ids = {e["route_id"] for e in s2s_all}

    remaining = [rid for rid in route_ids if rid not in done_ids]
    print(f"[系統] 站間行駛時間：共 {len(route_ids)} 條，已完成 {len(done_ids)}，待下載 {len(remaining)}...")

    for route_id in remaining:
        raw = client.get_s2s_travel_time(city, route_id)
        if raw:  # 部分路線可能無資料，略過
            s2s_all.extend(_clean_s2s_travel_time(raw))
        # 每條都即時存檔，確保被限流中斷時不丟進度
        _save_json(f"{city}_s2s_travel_time.json", s2s_all)


def _read_route_names_from_md(md_path):
    """從 extra_route.md 解析出主路線編號清單（行首 4 位數字，如 5606）。"""
    names = []
    with open(md_path, "r", encoding="utf-8") as f:
        for line in f:
            m = re.match(r"^(\d{4})\s", line)
            if m:
                names.append(m.group(1))
    return names


def _stops_from_stops_of_route(stops_of_route):
    """從『路線→依序站牌』導出不重複站牌清單（InterCity 無單獨的整城 Stop 端點）。"""
    seen = {}
    for route in stops_of_route:
        for s in route["stops"]:
            seen[s["stop_uid"]] = {
                "stop_uid": s["stop_uid"],
                "stop_id": s["stop_id"],
                "stop_name": s["stop_name"],
                "position": s["position"],
            }
    return list(seen.values())


def download_intercity_routes(client, city, route_names):
    """
    下載指定公路客運路線，存成虛擬城市（如 InterCityHsinchu）的各份 JSON。

    端點不分縣市、以路線名 $filter 篩選；站牌清單由 StopOfRoute 導出。
    存檔格式與市區公車一致，故 bus_static / route_planner 可直接沿用。
    """
    print(f"\n[開始] 下載公路客運（{city}，共 {len(route_names)} 條指定路線）...")

    routes = _clean_routes(client.get_intercity_routes(route_names))
    _save_json(f"{city}_routes.json", routes)

    stops_of_route = _clean_stops_of_route(client.get_intercity_stops_of_route(route_names))
    _save_json(f"{city}_stops_of_route.json", stops_of_route)

    # 站牌清單由站序資料導出（InterCity 無整城 Stop 端點）
    _save_json(f"{city}_stops.json", _stops_from_stops_of_route(stops_of_route))

    shapes = _clean_shapes(client.get_intercity_shapes(route_names))
    _save_json(f"{city}_shapes.json", shapes)

    download_intercity_s2s(client, city)

    print(f"[結束] 公路客運（{city}）資料下載完成。\n")


def download_intercity_s2s(client, city):
    """下載 InterCity 各路線站間行駛時間（逐 route_id、可續傳），同 download_s2s_travel_time。"""
    routes_path = os.path.join(DATA_DIR, f"{city}_routes.json")
    with open(routes_path, "r", encoding="utf-8") as f:
        routes = json.load(f)
    route_ids = sorted({r["route_id"] for r in routes if r.get("route_id")})

    out_path = os.path.join(DATA_DIR, f"{city}_s2s_travel_time.json")
    s2s_all, done_ids = [], set()
    if os.path.exists(out_path):
        with open(out_path, "r", encoding="utf-8") as f:
            s2s_all = json.load(f)
        done_ids = {e["route_id"] for e in s2s_all}

    remaining = [rid for rid in route_ids if rid not in done_ids]
    print(f"[系統] 公路客運站間行駛時間：共 {len(route_ids)} 條，已完成 {len(done_ids)}，待下載 {len(remaining)}...")

    for route_id in remaining:
        raw = client.get_intercity_s2s_travel_time(route_id)
        if raw:
            s2s_all.extend(_clean_s2s_travel_time(raw))
        _save_json(f"{city}_s2s_travel_time.json", s2s_all)


if __name__ == "__main__":
    import sys

    load_dotenv()

    client_id = os.getenv("TDX_CLIENT_ID")
    client_secret = os.getenv("TDX_CLIENT_SECRET")

    if not client_id or not client_secret:
        print("[錯誤] 無法讀取 TDX 憑證，請檢查 .env 檔案是否存在且格式正確。")
        raise SystemExit(1)

    # 可由命令列指定一個或多個城市，未指定則使用預設（新竹市）。
    #   範例：python download_bus_data.py Hsinchu HsinchuCounty
    #   加 --s2s-only 只下載站間行駛時間（其他資料已存在時，省 API 額度、可續傳）：
    #     python download_bus_data.py --s2s-only Hsinchu HsinchuCounty
    #   加 --intercity 下載 extra_route.md 列出的公路客運路線（虛擬城市 InterCityHsinchu）：
    #     python download_bus_data.py --intercity
    args = sys.argv[1:]
    s2s_only = "--s2s-only" in args
    intercity = "--intercity" in args
    cities = [a for a in args if not a.startswith("--")]

    tdx = TDXClient(client_id, client_secret)

    if intercity:
        route_names = _read_route_names_from_md(EXTRA_ROUTE_MD)
        if s2s_only:
            download_intercity_s2s(tdx, INTERCITY_NAME)
        else:
            download_intercity_routes(tdx, INTERCITY_NAME, route_names)
    else:
        for city in cities or [DEFAULT_CITY]:
            if s2s_only:
                download_s2s_travel_time(tdx, city)
            else:
                download_city_bus_data(tdx, city)
