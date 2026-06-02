"""
極簡的記憶體快取（含過期時間 TTL）。

用途：即時到站時間、地理編碼結果等會重複查詢的資料，存進記憶體一段時間，
避免短時間內對同一個外部 API 重複發請求（呼應企劃書的「快取機制」需求）。

設計刻意簡單：用一個 dict 存 {key: (過期時間戳, 值)}，方便閱讀。
"""

import time


class TTLCache:
    """有存活時間的鍵值快取。逾時的項目會在讀取時自動失效。"""

    def __init__(self, ttl_seconds):
        self.ttl = ttl_seconds
        self._store = {}  # key -> (expire_at, value)

    def get(self, key):
        """取得快取值；不存在或已過期則回傳 None。"""
        item = self._store.get(key)
        if item is None:
            return None

        expire_at, value = item
        if time.time() > expire_at:
            # 已過期，順手清掉
            del self._store[key]
            return None
        return value

    def set(self, key, value):
        """寫入快取，存活時間為建構時指定的 ttl 秒。"""
        self._store[key] = (time.time() + self.ttl, value)

    def clear(self):
        """清空整個快取。"""
        self._store.clear()
