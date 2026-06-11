"""
地圖視覺化模組（Folium → Leaflet）。

職責：把 route_planner 的規劃結果畫成一張互動式地圖，回傳 HTML 字串嵌入網頁。
對應企劃書強制技術棧中的「Folium 生成 Leaflet 地圖並嵌入網頁」。

繪製內容（每張地圖對應「一個方案」）：
  - 起點（綠）、終點（紅）標記
  - 該方案的上車站、下車站標記，以及兩段 OSRM 步行路徑（藍色虛線）
注意：Folium 的座標是 [lat, lon]，而 OSRM geometry 是 [lon, lat]，畫線前要對調。

前端會為每個方案各取得一張地圖 HTML（見 render_maps），點方案卡片即切換顯示。
"""

import re

import folium


def _swap_lonlat(coords):
    """把 OSRM 的 [lon, lat] 座標串轉成 Folium 要的 [lat, lon]。"""
    return [[lat, lon] for lon, lat in coords]


def _add_endpoint_markers(fmap, origin, destination):
    """在地圖加上起點（綠）與終點（紅）標記。"""
    folium.Marker(
        [origin["lat"], origin["lon"]],
        tooltip="起點",
        popup=origin.get("display_name", "起點"),
        icon=folium.Icon(color="green", icon="play"),
    ).add_to(fmap)
    folium.Marker(
        [destination["lat"], destination["lon"]],
        tooltip="終點",
        popup=destination.get("display_name", "終點"),
        icon=folium.Icon(color="red", icon="flag"),
    ).add_to(fmap)


def render_map(plan_result, plan_index=0):
    """
    依規劃結果中「指定的某一個方案」產生地圖 HTML。

    參數：
      plan_result ── core.route_planner.plan_routes() 的回傳。
      plan_index  ── 要繪製第幾個方案（預設 0，即最快方案）。
    回傳：str（完整地圖 HTML，可直接塞進前端 iframe）。
    """
    origin = plan_result["origin"]
    destination = plan_result["destination"]

    # 地圖中心取起訖點中點；縮放層級適合市區
    center = [
        (origin["lat"] + destination["lat"]) / 2,
        (origin["lon"] + destination["lon"]) / 2,
    ]
    fmap = folium.Map(location=center, zoom_start=14, tiles="OpenStreetMap")
    _add_endpoint_markers(fmap, origin, destination)

    # 畫出指定方案：捷運圖風格的完整路線 + 兩段步行路徑
    plans = plan_result.get("plans", [])
    if plans and 0 <= plan_index < len(plans):
        _draw_plan(fmap, plans[plan_index])

    # 回傳完整 HTML（含 Leaflet 所需的 JS/CSS），並注入點擊回報腳本
    return _inject_click_reporter(fmap.get_root().render())


# 路線顏色：搭乘區段（深藍）、未搭乘區段（淺藍）
_RIDDEN_COLOR = "#2563eb"    # 實際搭乘區段：深藍
_UNRIDDEN_COLOR = "#7da7e8"  # 未搭乘區段：中藍（明顯但仍比深藍淺）


def _nearest_shape_index(shape, lat, lon):
    """找出形狀座標串中離 (lat, lon) 最近的頂點索引（用平方距離即可，免開根號）。"""
    best_i, best_d = 0, None
    for i, (s_lat, s_lon) in enumerate(shape):
        d = (s_lat - lat) ** 2 + (s_lon - lon) ** 2
        if best_d is None or d < best_d:
            best_d, best_i = d, i
    return best_i


def _draw_route_shape(fmap, shape, board_stop, alight_stop):
    """
    用道路真實形狀畫整條路線，並切成三段：
      上車前（淺藍）、上車→下車（深藍，實際搭乘）、下車後（淺藍）。

    做法：在形狀上找離上/下車站最近的頂點，依索引切分。
    若兩索引順序顛倒（少數路線形狀方向與站序相反），則對調確保區段正確。
    """
    i_board = _nearest_shape_index(shape, board_stop["lat"], board_stop["lon"])
    i_alight = _nearest_shape_index(shape, alight_stop["lat"], alight_stop["lon"])
    lo, hi = sorted((i_board, i_alight))

    # 三段折線；+1 讓相鄰段端點重疊、線條不留縫
    segments = [
        (shape[: lo + 1], False),        # 上車前
        (shape[lo: hi + 1], True),       # 搭乘區段
        (shape[hi:], False),             # 下車後
    ]
    for coords, ridden in segments:
        if len(coords) < 2:
            continue
        folium.PolyLine(
            coords,
            color=_RIDDEN_COLOR if ridden else _UNRIDDEN_COLOR,
            weight=6 if ridden else 4,
            opacity=0.9 if ridden else 0.8,
        ).add_to(fmap)


def _draw_plan(fmap, plan):
    """把單一方案畫成捷運圖風格：完整路線連線 + 白色圓點停靠站 + 步行虛線。"""
    board_seq = plan["board_stop"]["sequence"]
    alight_seq = plan["alight_stop"]["sequence"]
    route_stops = plan.get("route_stops", [])
    route_shape = plan.get("route_shape", [])

    # 1) 畫整條路線：優先用 TDX 的道路真實形狀（貼著馬路），
    #    否則退回站到站直線連線。搭乘區段深藍、其餘淺藍。
    if route_shape:
        _draw_route_shape(fmap, route_shape, plan["board_stop"], plan["alight_stop"])
    else:
        for prev, curr in zip(route_stops, route_stops[1:]):
            ridden = board_seq <= prev["sequence"] and curr["sequence"] <= alight_seq
            folium.PolyLine(
                [[prev["lat"], prev["lon"]], [curr["lat"], curr["lon"]]],
                color=_RIDDEN_COLOR if ridden else _UNRIDDEN_COLOR,
                weight=6 if ridden else 4,
                opacity=0.9 if ridden else 0.8,
            ).add_to(fmap)

    # 2) 每個停靠站一個白色圓點（搭乘區段的點描深藍框、其餘描淺藍框）
    for stop in route_stops:
        ridden = board_seq <= stop["sequence"] <= alight_seq
        folium.CircleMarker(
            [stop["lat"], stop["lon"]],
            radius=5,
            color=_RIDDEN_COLOR if ridden else _UNRIDDEN_COLOR,  # 外框色
            weight=2,
            fill=True,
            fill_color="#ffffff",  # 白色圓點，像捷運圖
            fill_opacity=1.0,
            tooltip=f"{stop['sequence']}. {stop['stop_name']}",
        ).add_to(fmap)

    # 3) 上車站、下車站特別標示（較大的實心圓 + 文字）
    board, alight = plan["board_stop"], plan["alight_stop"]
    folium.CircleMarker(
        [board["lat"], board["lon"]], radius=8, color=_RIDDEN_COLOR, weight=3,
        fill=True, fill_color=_RIDDEN_COLOR, fill_opacity=1.0,
        tooltip=f"上車：{board['stop_name']}（{plan['route_name']} 線）",
    ).add_to(fmap)
    folium.CircleMarker(
        [alight["lat"], alight["lon"]], radius=8, color="#f59e0b", weight=3,
        fill=True, fill_color="#f59e0b", fill_opacity=1.0,
        tooltip=f"下車：{alight['stop_name']}",
    ).add_to(fmap)

    # 4) 兩段步行路徑（灰色虛線，與公車路線區隔）
    folium.PolyLine(
        _swap_lonlat(plan["walk_to_board_geometry"]),
        color="#6b7280", weight=4, opacity=0.8, dash_array="6",
        tooltip="步行至上車站",
    ).add_to(fmap)
    folium.PolyLine(
        _swap_lonlat(plan["walk_to_dest_geometry"]),
        color="#6b7280", weight=4, opacity=0.8, dash_array="6",
        tooltip="下車步行至終點",
    ).add_to(fmap)


def render_maps(plan_result):
    """
    為「每一個方案」各產生一張地圖 HTML，供前端點選方案時切換顯示。

    回傳：list[str]，長度與 plan_result['plans'] 相同；無方案則回傳空 list。
    """
    plans = plan_result.get("plans", [])
    return [render_map(plan_result, i) for i in range(len(plans))]


def render_empty_map(center=None):
    """查無方案時的備援：回傳一張只有中心點的空白地圖 HTML。"""
    center = center or [24.8016, 120.9717]  # 預設新竹火車站
    fmap = folium.Map(location=center, zoom_start=13, tiles="OpenStreetMap")
    return _inject_click_reporter(fmap.get_root().render())


def _inject_click_reporter(html):
    """
    在 Folium 產生的地圖 HTML 注入互動腳本：點地圖會落一個「可拖拽圖釘」，
    點擊或拖動圖釘都會透過 postMessage 把座標回報給外層頁面（供「點地圖選位」用）。

    Folium 把地圖命名為全域變數 map_xxxx，其宣告位於 HTML 尾端的 <script> 內，
    故本腳本附加在整份 HTML 最後，並以 window[varName] + 輪詢等待，避免時序問題。
    """
    m = re.search(r"var (map_\w+) = L\.map", html)
    if not m:
        return html  # 找不到地圖變數就原樣返回（功能降級，不影響顯示）
    map_var = m.group(1)
    script = f"""
<script>
(function() {{
  function hook() {{
    var map = window["{map_var}"];
    if (!map || typeof L === 'undefined') {{ setTimeout(hook, 100); return; }}

    // 起點(綠)、終點(紅)各維護一個可拖拽圖釘；activeTarget 由外層指定目前要設哪個。
    var markers = {{origin: null, dest: null}};
    var colors = {{origin: 'green', dest: 'red'}};
    var activeTarget = null;

    function report(target, latlng) {{
      // 回報時帶上 target，外層據此填對應輸入框（起點/終點）
      window.parent.postMessage(
        {{type: 'map-click', target: target, lat: latlng.lat, lon: latlng.lng}}, '*');
    }}

    function setMarker(target, latlng) {{
      if (markers[target]) {{
        markers[target].setLatLng(latlng);
      }} else {{
        var icon = new L.Icon({{
          iconUrl: 'https://cdn.jsdelivr.net/gh/pointhi/leaflet-color-markers@master/img/marker-icon-' + colors[target] + '.png',
          shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/0.7.7/images/marker-shadow.png',
          iconSize: [25, 41], iconAnchor: [12, 41]
        }});
        var mk = L.marker(latlng, {{draggable: true, icon: icon}}).addTo(map);
        // 拖動該圖釘 → 回報「該圖釘對應的目標」新座標
        mk.on('dragend', function() {{ report(target, mk.getLatLng()); }});
        markers[target] = mk;
      }}
    }}

    // 外層告知「現在要設哪個目標」（點了起點或終點的『點地圖』按鈕）
    window.addEventListener('message', function(e) {{
      if (e.data && e.data.type === 'set-pick-target') {{
        activeTarget = e.data.target; // 'origin' | 'destination' | null
      }}
    }});

    // 點地圖：落下/移動「目前作用中目標」的圖釘並回報
    map.on('click', function(e) {{
      if (!activeTarget) return; // 未進入選位模式則不反應
      setMarker(activeTarget, e.latlng);
      report(activeTarget, e.latlng);
    }});
  }}
  hook();
}})();
</script>
"""
    # 附加在最尾端，確保 Folium 定義地圖的 <script> 已先執行
    return html + script
