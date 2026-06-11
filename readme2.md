graph TD
    %% 前端介面層
    subgraph Frontend["前端展示層 (Client-Side)"]
        UI["index.html\n(使用者介面)"]
        JS["app.js\n(互動邏輯 & API呼叫)"]
        CSS["style.css\n(視覺樣式)"]
        UI --- JS
        UI --- CSS
    end

    %% 後端路由與入口
    subgraph Controller["控制與路由層 (Controller)"]
        App["app.py\n(Flask 主程式)"]
        API["routes/api.py\n(API 端點定義)"]
        Config["config.py\n(環境設定)"]
        App --> Config
        App --> API
    end

    %% 核心邏輯層
    subgraph Core["核心邏輯層 (Core Business Logic)"]
        Planner["core/route_planner.py\n(圖論與路徑規劃演算法大腦)"]
    end

    %% 領域服務層
    subgraph Services["領域服務層 (Services)"]
        Geo["geocoding.py\n(地址座標轉換)"]
        Walk["walking.py\n(步行距離/時間計算)"]
        BusStatic["bus_static.py\n(靜態路網資料加載)"]
        BusReal["bus_realtime.py\n(即時動態到站資料)"]
        Map["map_render.py\n(地圖圖層數據生成)"]
        Storage["storage.py\n(本地資料讀寫管理)"]
    end

    %% 基礎設施層
    subgraph Utilities["基礎設施 (Utilities)"]
        Cache["utils/cache.py\n(快取機制)"]
        RateLimit["utils/rate_limiter.py\n(API 請求限流)"]
    end

    %% 資料持久層
    subgraph DataStore["資料持久層 (Data)"]
        StaticDB[("data/*_routes/stops.json\n(公車靜態開放資料)")]
        UserDB[("data/history & favorites.json\n(使用者偏好與歷史)")]
    end

    %% 外部系統
    subgraph External["外部系統 (External)"]
        TDX["交通部 TDX 平台"]
        MapsAPI["圖資/Geocoding API"]
    end

    %% --- 關聯線路 ---
    
    %% 前後端互動
    JS -- "HTTP Request (JSON)" --> API
    
    %% 控制層呼叫核心與儲存
    API --> Planner
    API --> Storage
    Storage --> UserDB
    
    %% 核心呼叫各項服務
    Planner --> Geo
    Planner --> Walk
    Planner --> BusStatic
    Planner --> BusReal
    Planner --> Map
    
    %% 服務層對接資料與外部
    BusStatic --> StaticDB
    BusReal -- "HTTP 請求" --> TDX
    Geo -- "HTTP 請求" --> MapsAPI
    
    %% 服務層依賴基礎設施 (降載與穩定性)
    BusReal -.-> Cache
    BusReal -.-> RateLimit
    Geo -.-> Cache
    Geo -.-> RateLimit