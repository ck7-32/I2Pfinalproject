# 即時公車導航與步行時間最佳化地圖系統

以「即時公車動態」為核心的路線規劃平台，輸入起點與終點關鍵字，系統會拆解並計算
**步行至站牌 → 等待 → 乘車 → 下車步行** 四段時間，列出總耗時最短的前 10 筆方案，
並在互動式地圖上呈現。

## 技術棧

| 用途 | 技術 |
|------|------|
| 後端框架 | Python Flask |
| 地理編碼 | Nominatim API |
| 路徑規劃（步行）| OSRM API |
| 即時公車 | TDX 運輸資料流通服務 |
| 地圖渲染 | Folium（產生 Leaflet 地圖） |

## 安裝與執行

```bash
# 1. 安裝套件
pip install -r requirements.txt

# 2. 設定 TDX 金鑰（建立 .env，內容如下）
#    TDX_CLIENT_ID=你的_client_id
#    TDX_CLIENT_SECRET=你的_client_secret

# 3.（首次）下載公車靜態資料到 data/
#    含路線、站牌、站序、路線形狀、站間行駛時間（S2S）。
#    註：S2S 端點限流較嚴（每分鐘 5 次），會逐路線慢慢抓，可能要數分鐘；
#        中斷後重跑會自動續傳。若只想補抓 S2S：加 --s2s-only。
python download_bus_data.py Hsinchu HsinchuCounty

# 4. 啟動網站
python app.py
# 瀏覽器開 http://127.0.0.1:5001
# （macOS 的 AirPlay 接收器佔用 5000，故預設用 5001；可用環境變數 PORT 覆寫）
```

> 注意：方案排序依賴 TDX 即時到站資料，**非公車營運時段（深夜）查詢會無方案**，屬正常現象。

## 專案結構（模組化）

資料流：`routes/`（HTTP）→ `core/`（商業邏輯）→ `services/`（外部 API）→ `utils/`（共用工具）

```
app.py                  # Flask 入口（建立 app、註冊路由、啟動）
config.py               # 集中設定（API 網址、半徑、快取秒數、城市清單）
download_bus_data.py    # 一次性：下載公車路線/站牌靜態資料到 data/

data/                   # 本機 JSON 快取（站牌、路線、路線站序）

services/               # 一個檔案對應一個外部服務
├── geocoding.py        #   Nominatim：地點 → 座標（含 1 req/s 限流、快取）
├── bus_static.py       #   讀本機 JSON：找最近站牌、找可直達路線
├── bus_realtime.py     #   TDX：即時到站 → 等待時間
├── walking.py          #   OSRM：步行時間與路徑幾何
└── map_render.py       #   Folium：規劃結果 → Leaflet 地圖 HTML

core/
└── route_planner.py    # 大腦：整合四段時間、排序、取前 N 名

utils/
├── cache.py            # TTL 記憶體快取
└── rate_limiter.py     # 最小間隔限流（遵守 Nominatim 每秒 1 次）

routes/
└── api.py              # HTTP 端點：/（首頁）、/api/plan（規劃 API）

templates/index.html    # 前端頁面
static/style.css        # 樣式
static/app.js           # 前端互動（呼叫 API、渲染方案與地圖）
```

## 設計重點

- **模組化**：HTTP 層、商業邏輯、外部 API、共用工具各自分離，符合「不可全寫在單一檔案」。
- **快取 + 限流**：`utils/` 提供共用機制；即時資料快取 60 秒、地理編碼快取一天，
  並對 Nominatim 強制每秒 1 次，避免被封鎖。
- **跨縣市**：同時載入新竹市與新竹縣資料（見 `config.CITIES`），涵蓋交界路線。
- **時間估算**：步行採 OSRM 真實街道時間；乘車時間以站數 × 每站分鐘數估算
  （`config.RIDE_MINUTES_PER_STOP`，可調）。
