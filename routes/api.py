"""
HTTP 路由層。

職責刻意很薄：解析請求參數 → 呼叫 core 規劃 → 回傳 JSON / 地圖 HTML。
所有運算都在 core 與 services，本層不放商業邏輯，方便閱讀與維護。

提供的端點：
  GET /                  首頁（輸入表單 + 地圖容器）
  GET /api/plan          規劃路線，回傳 JSON（方案清單 + 地圖 HTML）
"""

from flask import Blueprint, render_template, request, jsonify

from core import route_planner
from services import map_render

# 用 Blueprint 把路由模組化，再由 app.py 註冊進主程式
bp = Blueprint("api", __name__)


@bp.route("/")
def index():
    """首頁：回傳含表單與地圖容器的 HTML 模板。"""
    return render_template("index.html")


@bp.route("/api/plan")
def plan():
    """
    路線規劃 API。

    查詢參數：
      origin ── 起點關鍵字（必填）
      dest   ── 終點關鍵字（必填）
    回傳 JSON：
      { origin, destination, plans:[...], map_html, error? }
    """
    origin_keyword = (request.args.get("origin") or "").strip()
    dest_keyword = (request.args.get("dest") or "").strip()

    if not origin_keyword or not dest_keyword:
        return jsonify({"error": "請同時提供起點 (origin) 與終點 (dest)。"}), 400

    # 委派給核心邏輯做規劃
    result = route_planner.plan_routes(origin_keyword, dest_keyword)

    # 為每個方案各產一張地圖 HTML（前端點方案卡片即切換）。
    # 座標解析成功且有方案時用 maps；否則回一張空白地圖讓前端至少有底圖。
    if result.get("origin", {}).get("lat") is not None and result.get("plans"):
        result["maps_html"] = map_render.render_maps(result)
    else:
        center = None
        if result.get("origin", {}).get("lat") is not None:
            center = [result["origin"]["lat"], result["origin"]["lon"]]
        result["maps_html"] = [map_render.render_empty_map(center)]

    return jsonify(result)
