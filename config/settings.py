import os
import sys
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def check_env_vars():
    """Check required environment variables on startup. Exit with helpful message if missing."""
    required = {
        "DEEPSEEK_API_KEY": "DeepSeek API 密钥，用于调用AI审核服务",
        "BAIDU_API_KEY": "百度 OCR API Key，用于图片文字识别",
        "BAIDU_SECRET_KEY": "百度 OCR Secret Key，用于图片文字识别",
    }
    missing = []
    for key, desc in required.items():
        if not os.environ.get(key):
            missing.append(f"  {key}  — {desc}")

    if missing:
        print("=" * 60)
        print("[启动失败] 缺少必要的环境变量：")
        for m in missing:
            print(m)
        print()
        print("请按以下步骤配置：")
        print("1. 复制 .env.example 为 .env")
        print("2. 在 .env 中填入你的API密钥")
        print("3. 重新启动应用")
        print("=" * 60)
        sys.exit(1)


class Config:
    # ---- 版本：trade = 标准版（外贸） / edu = 教育版（实训）----
    EDITION = os.environ.get("DZT_EDITION", "trade")

    # ---- DeepSeek ----
    DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-flash")

    # ---- Baidu OCR ----
    BAIDU_API_KEY = os.environ.get("BAIDU_API_KEY", "")
    BAIDU_SECRET_KEY = os.environ.get("BAIDU_SECRET_KEY", "")

    # ---- Upload ----
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB
    ALLOWED_IMAGE = {"jpg", "jpeg", "png"}
    ALLOWED_PDF = {"pdf"}
    ALLOWED_EXTENSIONS = ALLOWED_IMAGE | ALLOWED_PDF

    # ---- Rate Limiting ----
    RATE_LIMIT = 20       # requests per window
    RATE_WINDOW = 60      # window in seconds

    # ---- Access gate（可选）----
    # 不设置 = 不启用门禁（本机单人使用是主场景，不该给日常加摩擦）。
    # 要通过 cloudflared / 局域网暴露给别人访问时，务必在 .env 里设一个。
    ACCESS_PASSWORD = os.environ.get("DZT_ACCESS_PASSWORD", "")
    SECRET_KEY = os.environ.get("DZT_SECRET_KEY", "")

    # ---- Database ----
    DB_PATH = os.path.join(BASE_DIR, "history.db")

    # ---- Font ----
    FONT_PATH = os.path.join(BASE_DIR, "fonts")
