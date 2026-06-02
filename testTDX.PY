import os
import requests
import time
import json
from dotenv import load_dotenv # 引入 dotenv 模組

# (這裡保留先前的 TDXClient 類別定義，為節省版面省略)
class TDXClient:
    def __init__(self, client_id, client_secret):
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = None
        self.token_expires_at = 0

    def _get_token(self):
        if self.access_token and time.time() < self.token_expires_at - 60:
            return self.access_token

        auth_url = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
        payload = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret
        }

        try:
            response = requests.post(auth_url, data=payload)
            response.raise_for_status() 
            token_data = response.json()

            self.access_token = token_data.get("access_token")
            self.token_expires_at = time.time() + token_data.get("expires_in", 86400)

            print(f"[系統] 成功獲取 TDX Token，有效期限至: {time.ctime(self.token_expires_at)}")
            return self.access_token

        except requests.exceptions.RequestException as e:
            print(f"[錯誤] TDX 授權失敗: {e}")
            return None

    def get_nearby_stations(self, lat, lon, radius=500):
        token = self._get_token()
        if not token:
            return []

        url = "https://tdx.transportdata.tw/api/advanced/v2/Bus/Station/NearBy"
        headers = {"authorization": f"Bearer {token}"}
        params = {
            "$spatialFilter": f"nearby(StationPosition,{lat},{lon},{radius})",
            "$format": "JSON"
        }

        try:
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            
            cleaned_stations = []
            for station in response.json():
                cleaned_stations.append({
                    "station_uid": station.get("StationUID"),
                    "station_name": station.get("StationName", {}).get("Zh_tw"),
                    "position": {
                        "lat": station.get("StationPosition", {}).get("PositionLat"),
                        "lon": station.get("StationPosition", {}).get("PositionLon")
                    }
                })
            return cleaned_stations

        except requests.exceptions.RequestException as e:
            print(f"[錯誤] 獲取站牌資料失敗: {e}")
            return []

# --- 測試區塊 (更新為讀取 .env) ---
if __name__ == "__main__":
    # 載入當前目錄下的 .env 檔案
    load_dotenv() 

    # 透過 os.getenv 讀取環境變數
    YOUR_CLIENT_ID = os.getenv("TDX_CLIENT_ID")
    YOUR_CLIENT_SECRET = os.getenv("TDX_CLIENT_SECRET")

    # 簡單的防呆機制：確保有讀取到變數
    if not YOUR_CLIENT_ID or not YOUR_CLIENT_SECRET:
        print("[錯誤] 無法讀取到 TDX 憑證，請檢查 .env 檔案是否存在且格式正確。")
        exit()

    # 建立客戶端實例
    tdx = TDXClient(YOUR_CLIENT_ID, YOUR_CLIENT_SECRET)
    
    # 測試：查詢實齋周邊 500 公尺內的公車站位
    test_lat, test_lon = 24.793, 120.991
    stations = tdx.get_nearby_stations(test_lat, test_lon)
    
    print(f"\n[結果] 找到 {len(stations)} 個站位:")
    print(json.dumps(stations[:3], indent=2, ensure_ascii=False))