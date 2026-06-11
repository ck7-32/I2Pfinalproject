"""
HTTP 路由層。

職責刻意很薄：解析請求參數 → 呼叫 core 規劃 → 回傳 JSON / 地圖 HTML。
所有運算都在 core 與 services，本層不放商業邏輯，方便閱讀與維護。

提供的端點：
  GET /                  首頁（輸入表單 + 地圖容器）
  GET /api/plan          規劃路線，回傳 JSON（方案清單 + 地圖 HTML）
  GET /api/plan/stream   同上，但以 SSE 串流即時回報後台進度，最後送出結果
  GET  /api/history      取得歷史記錄；GET /api/favorites 取得我的最愛
  POST /api/favorites    新增/移除最愛（起訖點配對）
"""

import json
import queue
import threading

from flask import Blueprint, render_template, request, jsonify, Response

from core import route_planner
from services import map_render, storage

# 用 Blueprint 把路由模組化，再由 app.py 註冊進主程式
bp = Blueprint("api", __name__)


def _record_history(result):
    """查詢成功（有解析出座標）時，把起訖點配對寫入歷史記錄。"""
    o, d = result.get("origin", {}), result.get("destination", {})
    if o.get("lat") is None or d.get("lat") is None:
        return
    storage.add_history({
        "origin": {
            "keyword": o.get("keyword"),
            "display_name": o.get("display_name"),
            "lat": o["lat"], "lon": o["lon"],
        },
        "destination": {
            "keyword": d.get("keyword"),
            "display_name": d.get("display_name"),
            "lat": d["lat"], "lon": d["lon"],
        },
    })


def _build_result(origin_keyword, dest_keyword, on_progress=None):
    """跑規劃並補上每個方案的地圖 HTML，回傳完整結果 dict。"""
    result = route_planner.plan_routes(origin_keyword, dest_keyword, on_progress)

    if result.get("origin", {}).get("lat") is not None and result.get("plans"):
        if on_progress:
            on_progress("繪製路線地圖…")
        result["maps_html"] = map_render.render_maps(result)
        _record_history(result)  # 成功且有方案才記入歷史
    else:
        center = None
        if result.get("origin", {}).get("lat") is not None:
            center = [result["origin"]["lat"], result["origin"]["lon"]]
        result["maps_html"] = [map_render.render_empty_map(center)]

    return result


@bp.route("/")
def index():
    """首頁：回傳含表單與地圖容器的 HTML 模板。"""
    return render_template("index.html")


@bp.route("/api/blank-map")
def blank_map():
    """回傳一張可點選的空白地圖（首頁載入時顯示，供「點地圖選位」用）。"""
    return map_render.render_empty_map()


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

    return jsonify(_build_result(origin_keyword, dest_keyword))


@bp.route("/api/plan/stream")
def plan_stream():
    """
    路線規劃 API（SSE 串流版）：邊算邊把後台進度推給前端。

    事件格式（Server-Sent Events）：
      event: progress  data: {"message": "..."}   ── 每個階段一則
      event: result    data: {完整結果 JSON}        ── 最後送出
      event: error     data: {"message": "..."}     ── 發生例外時
    """
    origin_keyword = (request.args.get("origin") or "").strip()
    dest_keyword = (request.args.get("dest") or "").strip()

    def stream():
        if not origin_keyword or not dest_keyword:
            yield _sse("error", {"message": "請同時提供起點與終點。"})
            return

        # 規劃在背景執行緒跑，進度訊息透過 queue 傳回主執行緒邊收邊送。
        events = queue.Queue()
        DONE = object()

        def worker():
            try:
                result = _build_result(
                    origin_keyword, dest_keyword,
                    on_progress=lambda msg: events.put(("progress", {"message": msg})),
                )
                events.put(("result", result))
            except Exception as e:  # 確保前端不會卡在等待
                events.put(("error", {"message": f"查詢失敗：{e}"}))
            finally:
                events.put(DONE)

        threading.Thread(target=worker, daemon=True).start()

        while True:
            item = events.get()
            if item is DONE:
                break
            event_type, payload = item
            yield _sse(event_type, payload)

    return Response(stream(), mimetype="text/event-stream")


def _sse(event_type, payload):
    """組一筆 SSE 訊息字串。"""
    return f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


# ---- 歷史記錄與我的最愛 ----

@bp.route("/api/history")
def history():
    """取得歷史記錄（最新在前）。"""
    return jsonify(storage.get_history())


@bp.route("/api/favorites", methods=["GET", "POST"])
def favorites():
    """
    GET  取得我的最愛清單。
    POST 對一筆最愛操作（body: {action, pair, ...}），回傳更新後清單。
         action="add"    新增；action="remove" 移除；
         action="rename" 設定自訂顯示名稱（額外帶 label，空字串=清除）。
    """
    if request.method == "GET":
        return jsonify(storage.get_favorites())

    body = request.get_json(silent=True) or {}
    action = body.get("action")
    pair = body.get("pair")
    if not pair or action not in ("add", "remove", "rename"):
        return jsonify({"error": "需提供 action(add/remove/rename) 與 pair。"}), 400

    if action == "add":
        items = storage.add_favorite(pair)
    elif action == "rename":
        items = storage.rename_favorite(pair, body.get("label", ""))
    else:
        items = storage.remove_favorite(pair)
    return jsonify(items)
