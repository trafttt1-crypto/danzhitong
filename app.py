import hashlib
import logging
import os
import secrets
import time
import threading
from collections import defaultdict
from flask import Flask, request, jsonify, session, redirect, render_template

from config.settings import Config, check_env_vars

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# ---- Rate Limiter (in-memory, per-IP) ----
class RateLimiter:
    def __init__(self, max_requests=20, window_seconds=60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._clients = defaultdict(list)
        self._lock = threading.Lock()

    def is_allowed(self, ip):
        now = time.time()
        with self._lock:
            # Purge old entries
            self._clients[ip] = [t for t in self._clients[ip] if now - t < self.window_seconds]
            if len(self._clients[ip]) >= self.max_requests:
                return False
            self._clients[ip].append(now)
            return True

    def cleanup(self):
        """Periodic cleanup of stale entries."""
        now = time.time()
        with self._lock:
            expired = [ip for ip, times in self._clients.items()
                       if not any(now - t < self.window_seconds for t in times)]
            for ip in expired:
                del self._clients[ip]

limiter = RateLimiter(Config.RATE_LIMIT, Config.RATE_WINDOW)


def create_app():
    # ---- Startup safety check ----
    check_env_vars()

    from routes import main_bp
    from services.history import init_db, close_db
    from services.archive import init_archive
    from services.assistant import init_chat
    from services.practice import init_practice

    app = Flask(__name__)

    # Static config
    app.config["UPLOAD_FOLDER"] = Config.UPLOAD_FOLDER
    app.config["MAX_CONTENT_LENGTH"] = Config.MAX_CONTENT_LENGTH

    # Ensure directories
    os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)

    # Init databases
    init_db()
    init_archive()
    init_chat()
    init_practice()

    # Register DB teardown
    app.teardown_appcontext(close_db)

    # ---- 会话密钥：设了口令就由口令推导（重启不掉登录），否则每次启动随机 ----
    if Config.SECRET_KEY:
        app.secret_key = Config.SECRET_KEY
    elif Config.ACCESS_PASSWORD:
        app.secret_key = hashlib.sha256(("danzhitong:" + Config.ACCESS_PASSWORD).encode("utf-8")).hexdigest()
    else:
        app.secret_key = secrets.token_hex(32)

    # ---- 访问口令（默认关闭，设了 DZT_ACCESS_PASSWORD 才启用）----
    if Config.ACCESS_PASSWORD:
        @app.before_request
        def require_login():
            if request.path.startswith("/static/") or request.path in ("/login", "/logout"):
                return None
            if session.get("dzt_ok"):
                return None
            if request.path.startswith("/api/"):
                return jsonify({"error": "未登录或登录已过期，请刷新页面重新登录"}), 401
            return redirect("/login")

        @app.route("/login", methods=["GET", "POST"])
        def login():
            error = ""
            if request.method == "POST":
                if secrets.compare_digest(request.form.get("password") or "", Config.ACCESS_PASSWORD):
                    session["dzt_ok"] = True
                    return redirect("/")
                error = "口令不正确"
            return render_template("login.html", error=error)

        @app.route("/logout")
        def logout():
            session.pop("dzt_ok", None)
            return redirect("/login")

        logger.info("访问口令已启用：未登录的访问会被拦截")
    else:
        logger.warning(
            "未设置 DZT_ACCESS_PASSWORD —— 当前没有访问口令，"
            "本机自己用没问题；一旦通过隧道/局域网给别人访问，任何人可读取全部单证数据"
        )

    # ---- 统一 JSON 错误体：前端全线按 JSON 解析，返回 HTML 会让用户看到解析错误 ----
    @app.errorhandler(413)
    def payload_too_large(e):
        limit_mb = Config.MAX_CONTENT_LENGTH // (1024 * 1024)
        return jsonify({"error": "文件太大，请压缩到 %dMB 以内" % limit_mb}), 413

    @app.errorhandler(500)
    def internal_error(e):
        logger.exception("未处理的服务端异常")
        return jsonify({"error": "服务器内部错误，请重试或查看控制台日志"}), 500

    # ---- Rate-limit middleware ----
    @app.before_request
    def check_rate_limit():
        # Only limit API endpoints; GET 是廉价查询，不限流（避免聊天界面切会话时误触限流）
        if request.path.startswith("/api/") and request.method != "GET":
            ip = request.remote_addr or "127.0.0.1"
            if not limiter.is_allowed(ip):
                return jsonify({"error": "请求过于频繁，请稍后再试"}), 429

    # ---- Periodic rate-limiter cleanup ----
    def cleanup_loop():
        while True:
            time.sleep(300)
            limiter.cleanup()

    cleanup_thread = threading.Thread(target=cleanup_loop, daemon=True)
    cleanup_thread.start()

    # Register routes
    app.register_blueprint(main_bp)

    # 静态资源版本号：跟随文件修改时间，改了前端刷新即生效（免手动强刷）
    @app.context_processor
    def inject_asset_version():
        def asset_v(path):
            full = os.path.join(app.static_folder, path)
            try:
                return int(os.path.getmtime(full))
            except OSError:
                return 0
        return {"asset_v": asset_v, "edition": Config.EDITION}

    return app


if __name__ == "__main__":
    app = create_app()
    host = os.environ.get("FLASK_HOST", "0.0.0.0")
    port = int(os.environ.get("FLASK_PORT", 5000))
    app.run(debug=False, host=host, port=port)
