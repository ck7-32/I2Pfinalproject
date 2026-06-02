"""
全專案的設定集中管理。

把所有「可調參數」放在這裡（API 網址、搜尋半徑、快取秒數、城市清單），
其他模組一律從這裡 import，避免魔術數字散落各檔、也方便日後調整。
"""

import os
from dotenv import load_dotenv

# 載入 .env（TDX 金鑰）。在程式啟動時讀一次即可。
load_dotenv()

# ---- 專案路徑 ----
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

# ---- 網站伺服器 ----
# macOS 的 AirPlay 接收器預設佔用 5000，故預設改用 5001；可用環境變數 PORT 覆寫。
SERVER_HOST = "127.0.0.1"
SERVER_PORT = int(os.getenv("PORT", "5001"))

# ---- 服務範圍：要納入查詢的城市 ----
# 對應 data/ 底下的 JSON 檔名前綴。新竹市 + 新竹縣一起查，才能涵蓋跨縣市路線。
CITIES = ["Hsinchu", "HsinchuCounty"]

# ---- TDX 運輸資料流通服務 ----
TDX_CLIENT_ID = os.getenv("TDX_CLIENT_ID")
TDX_CLIENT_SECRET = os.getenv("TDX_CLIENT_SECRET")
TDX_AUTH_URL = (
    "https://tdx.transportdata.tw/auth/realms/TDXConnect/"
    "protocol/openid-connect/token"
)
TDX_BUS_BASE_URL = "https://tdx.transportdata.tw/api/basic/v2/Bus"
# TDX 對未付費用戶有流量上限，連續打太快會回 429；請求間至少間隔此秒數
TDX_RATE_LIMIT_SECONDS = 0.3

# ---- Nominatim 地理編碼服務 ----
# 注意：Nominatim 公開伺服器規定「每秒最多 1 次請求」，且必須帶 User-Agent。
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_USER_AGENT = "I2P-BusNavi/1.0 (course project)"
NOMINATIM_RATE_LIMIT_SECONDS = 1.0  # 兩次請求之間最少間隔秒數
# 把搜尋結果限制在新竹一帶，避免同名地點解析到外縣市（左下,右上 經緯度框）
# 格式：左經度,上緯度,右經度,下緯度
NOMINATIM_VIEWBOX = "120.85,24.90,121.25,24.55"

# ---- OSRM 路徑規劃服務（步行）----
# 公開 demo 伺服器；profile 用 foot 取得步行路線。
# 註：本機 macOS 內建 Python 用 LibreSSL（僅支援 TLS 1.2），無法與要求 TLS 1.3 的
#     https 端點握手，故改用 http 端點（OSRM demo 伺服器接受且不強制轉址）。
OSRM_BASE_URL = "http://router.project-osrm.org"
OSRM_RATE_LIMIT_SECONDS = 0.15
# 步行速度：4.5 km/h ≈ 75 m/min（含路口紅綠燈、市區實際體感）。
# 註：OSRM 公開伺服器的 foot profile 實際回傳開車速度（時間嚴重低估），
#     故我們只採用它的「真實街道路徑與距離」，步行時間一律用此步速自行換算。
WALKING_SPEED_M_PER_MIN = 75.0

# ---- 路線規劃參數 ----
NEARBY_RADIUS_M = 1000      # 起點/終點周邊「可步行抵達」的站牌搜尋半徑（公尺）
TOP_N_RESULTS = 10          # 最終回傳前幾名最快方案
MAX_WALK_MINUTES = 25       # 單段步行超過此值就視為不合理，直接濾掉
RIDE_MINUTES_PER_STOP = 2.0 # 乘車時間估算：每經過一站約幾分鐘（市區公車概值）
# 方案過濾：依總耗時取前 N 名，但濾掉「明顯荒謬」的長時間方案。
#   規則：總時間同時超過「最快 × 此倍數」與「此絕對分鐘數」才剔除，
#   避免出現要等 2-3 小時的不實用選項，但又不會因最快方案剛好超幸運而誤砍合理方案。
MAX_TOTAL_RATIO = 3.0        # 總時間超過最快方案的幾倍視為過長
MAX_TOTAL_ABSOLUTE_MINUTES = 120  # 且總時間超過此絕對值，才剔除

# ---- 快取 ----
CACHE_TTL_SECONDS = 60      # 即時資料（到站時間）快取秒數
GEOCODE_CACHE_TTL_SECONDS = 86400  # 地理編碼結果快取一天（地點座標幾乎不變）
SCHEDULE_CACHE_TTL_SECONDS = 86400 # 班表快取一天（班表一天才更新一次）
