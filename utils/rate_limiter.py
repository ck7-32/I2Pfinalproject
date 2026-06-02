"""
速率限制器：確保兩次呼叫之間至少間隔指定秒數。

用途：Nominatim 公開伺服器硬性規定「每秒最多 1 次請求」，違反會被封鎖；
OSRM demo 伺服器也建議自我限流。把這個邏輯獨立出來，各服務模組共用。

用法：
    limiter = RateLimiter(1.0)   # 每次呼叫之間至少隔 1 秒
    limiter.wait()               # 必要時 sleep 到可以發請求為止
"""

import time


class RateLimiter:
    """以「最小間隔」方式限流；非執行緒安全，單機單緒情境足夠。"""

    def __init__(self, min_interval_seconds):
        self.min_interval = min_interval_seconds
        self._last_call = 0.0

    def wait(self):
        """若距離上次呼叫不足 min_interval，就 sleep 補足差額。"""
        elapsed = time.time() - self._last_call
        remaining = self.min_interval - elapsed
        if remaining > 0:
            time.sleep(remaining)
        self._last_call = time.time()
