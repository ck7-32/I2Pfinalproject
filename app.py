"""
Flask 應用程式入口。

刻意保持精簡：只負責「建立 app、註冊路由、啟動伺服器」。
實際邏輯分散在 routes/（HTTP 層）、core/（商業邏輯）、services/（外部 API）。

啟動方式：
    python app.py
然後瀏覽器開 http://127.0.0.1:5001
（macOS 的 AirPlay 接收器佔用 5000，故預設用 5001；可用環境變數 PORT 覆寫）
"""

from flask import Flask

import config
from routes.api import bp as api_blueprint


def create_app():
    """應用工廠：建立並設定 Flask app。"""
    app = Flask(__name__)
    app.register_blueprint(api_blueprint)
    return app


app = create_app()


if __name__ == "__main__":
    # 啟動前簡單檢查 TDX 憑證是否就緒，避免之後查詢才失敗
    if not config.TDX_CLIENT_ID or not config.TDX_CLIENT_SECRET:
        print("[警告] 未讀到 TDX 憑證，即時到站功能將無法使用。請檢查 .env。")

    app.run(host=config.SERVER_HOST, port=config.SERVER_PORT, debug=True)
