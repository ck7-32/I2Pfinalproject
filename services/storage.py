"""
歷史記錄與我的最愛儲存模組。

職責：把「起點→終點」查詢配對存進本機 JSON 檔，供前端快速查找與收藏。
  - 歷史記錄：查詢成功時自動記，去重、最新置頂、限制筆數。
  - 我的最愛：使用者從歷史面板手動收藏，永久保留。

每筆配對的結構：
  {
    "origin": {"keyword": 顯示文字, "lat": 緯度, "lon": 經度},
    "destination": {"keyword": ..., "lat": ..., "lon": ...}
  }
點選時前端會用座標（@lat,lon）重新查詢，故座標為主、keyword 僅供顯示。
"""

import os
import json

import config

HISTORY_PATH = os.path.join(config.DATA_DIR, "history.json")
FAVORITES_PATH = os.path.join(config.DATA_DIR, "favorites.json")

MAX_HISTORY = 20  # 歷史記錄最多保留筆數（超過捨棄最舊的）


def _load(path):
    """讀取 JSON 清單；檔案不存在或損壞則回傳空清單。"""
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save(path, items):
    """把清單寫回 JSON 檔。"""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def _pair_key(pair):
    """以起訖點座標（取到小數 5 位）當作配對的唯一鍵，供去重比對。"""
    o, d = pair.get("origin", {}), pair.get("destination", {})
    return (
        round(o.get("lat", 0), 5), round(o.get("lon", 0), 5),
        round(d.get("lat", 0), 5), round(d.get("lon", 0), 5),
    )


# ---- 歷史記錄 ----

def get_history():
    """回傳歷史記錄清單（最新在前）。"""
    return _load(HISTORY_PATH)


def add_history(pair):
    """
    新增一筆查詢配對到歷史（最新置頂、去重、限制筆數）。
    回傳更新後的歷史清單。
    """
    items = _load(HISTORY_PATH)
    key = _pair_key(pair)
    # 移除既有相同配對（避免重複，並讓它重新置頂）
    items = [it for it in items if _pair_key(it) != key]
    items.insert(0, pair)
    items = items[:MAX_HISTORY]
    _save(HISTORY_PATH, items)
    return items


# ---- 我的最愛 ----

def get_favorites():
    """回傳我的最愛清單。"""
    return _load(FAVORITES_PATH)


def add_favorite(pair):
    """加入一筆最愛（去重）。回傳更新後的最愛清單。"""
    items = _load(FAVORITES_PATH)
    key = _pair_key(pair)
    if not any(_pair_key(it) == key for it in items):
        items.insert(0, pair)
        _save(FAVORITES_PATH, items)
    return items


def remove_favorite(pair):
    """移除一筆最愛。回傳更新後的最愛清單。"""
    items = _load(FAVORITES_PATH)
    key = _pair_key(pair)
    items = [it for it in items if _pair_key(it) != key]
    _save(FAVORITES_PATH, items)
    return items


def _apply_label(path, key, label):
    """把指定路徑檔內、與 key 相符的配對都設上自訂顯示名稱 label。"""
    items = _load(path)
    changed = False
    for it in items:
        if _pair_key(it) == key:
            it["label"] = label
            changed = True
    if changed:
        _save(path, items)
    return items


def rename_favorite(pair, label):
    """
    替一筆配對設定自訂顯示名稱（label）。
    同步套用到我的最愛與歷史中座標相同的配對，讓兩邊顯示一致。
    label 為空字串代表清除自訂名稱。
    回傳更新後的最愛清單。
    """
    key = _pair_key(pair)
    label = (label or "").strip()
    favorites = _apply_label(FAVORITES_PATH, key, label)
    _apply_label(HISTORY_PATH, key, label)
    return favorites
