import requests
import re

def get_coordinates_from_google_url(google_maps_url):
    """
    從 Google Maps 連結（支援短網址與長網址）中提取經緯度 (latitude, longitude)
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    current_url = google_maps_url
    
    # 步驟 1：如果是 goo.gl 或 maps.app.goo.gl 短網址，追蹤重定向獲取長網址
    if "goo.gl" in google_maps_url:
        try:
            # allow_redirects=True 會自動追蹤到最後一網頁
            response = requests.head(google_maps_url, headers=headers, allow_redirects=True, timeout=5)
            current_url = response.url
        except requests.RequestException as e:
            print(f"無法解析短網址: {e}")
            return None

    # 步驟 2：使用正則表達式解析長網址中的經緯度
    
    # 規則一：尋找 @緯度,經度 (最常見的瀏覽器網址格式)
    match_at = re.search(r'@([-+]?\d+\.\d+),([-+]?\d+\.\d+)', current_url)
    if match_at:
        lat = float(match_at.group(1))
        lng = float(match_at.group(2))
        return lat, lng
        
    # 規則二：尋找 !3d緯度!4d經度 (部分手機 App 分享出來的內部參數格式)
    match_param = re.search(r'!3d([-+]?\d+\.\d+).*?!4d([-+]?\d+\.\d+)', current_url)
    if match_param:
        lat = float(match_param.group(1))
        lng = float(match_param.group(2))
        return lat, lng

    return None

# ==================== 測試程式碼 ====================
if __name__ == "__main__":
    # 測試範例（以清大光復校區某處為例，你可以換成你們測試的 Google Map 連結）
    test_url = "https://maps.app.goo.gl/PjCPb5HXzBGcoYAV6" 

    coords = get_coordinates_from_google_url(test_url)
    if coords:
        print(f"解析成功！緯度 (Lat): {coords[0]}, 經度 (Lng): {coords[1]}")
    else:
        print("解析失敗，請檢查網址是否正確。")