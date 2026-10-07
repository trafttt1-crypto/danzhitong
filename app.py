import hashlib
import logging
import os
import secrets
import time
import threading
from collections import defaultdict
from flask import Flask, request, jsonify, session, redirect, render_template

from config.settings import Config, check_env_vars
from config.version import VERSION, RELEASE_DATE, PRODUCT_NAME, CHANGELOG

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

    def is_blocked(self, ip):
        """只查不记：登录只在输错时才记一次，查询本身不该占名额。"""
        now = time.time()
        with self._lock:
            self._clients[ip] = [t for t in self._clients[ip] if now - t < self.window_seconds]
            return len(self._clients[ip]) >= self.max_requests

    def record(self, ip):
        with self._lock:
            self._clients[ip].append(time.time())

    def cleanup(self):
        """Periodic cleanup of stale entries."""
        now = time.time()
        with self._lock:
            expired = [ip for ip, times in self._clients.items()
                       if not any(now - t < self.window_seconds for t in times)]
            for ip in expired:
                del self._clients[ip]

limiter = RateLimiter(Config.RATE_LIMIT, Config.RATE_WINDOW)
# 口令输错 10 次锁 5 分钟。原来 /login 不在限流范围内，开了隧道就能一直猜
login_limiter = RateLimiter(10, 300)


def client_ip():
    """来访者 IP。

    经 cloudflared 隧道进来的请求，remote_addr 全是本机 127.0.0.1，所有人共用一个限流名额。
    只有请求确实来自本机（也就是本机上的 cloudflared）时才采信它带的 CF-Connecting-IP；
    局域网直连的请求不认这个头，免得别人伪造头绕过限流。
    """
    addr = request.remote_addr or "127.0.0.1"
    if addr in ("127.0.0.1", "::1"):
        forwarded = (request.headers.get("CF-Connecting-IP") or "").strip()
        if forwarded:
            return forwarded[:64]
    return addr


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
            # /healthz 只回状态和版本号，给监控与部署脚本探活用，不带任何业务数据
            if request.path.startswith("/static/") or request.path in ("/login", "/logout", "/healthz"):
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
                ip = client_ip()
                if login_limiter.is_blocked(ip):
                    return render_template("login.html", error="口令输错次数过多，请 5 分钟后再试"), 429
                # 按字节比：compare_digest 遇到含中文的字符串会直接抛 TypeError，
                # 输入法没切换、在口令框里打了中文，用户看到的就是 500 错误页
                typed = (request.form.get("password") or "").encode("utf-8")
                if secrets.compare_digest(typed, Config.ACCESS_PASSWORD.encode("utf-8")):
                    session["dzt_ok"] = True
                    return redirect("/")
                login_limiter.record(ip)
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

    def _wants_json():
        # 前端所有接口都在 /api/ 下；其余路径是用户在浏览器里直接打开的页面
        return request.path.startswith("/api/")

    @app.errorhandler(404)
    def not_found(e):
        if _wants_json():
            return jsonify({"error": "接口不存在"}), 404
        return render_template("error.html", code=404, title="页面不存在",
                               message="这个地址没有对应的页面，可能是链接输错了，或者页面已被移走。"), 404

    @app.errorhandler(500)
    def internal_error(e):
        logger.exception("未处理的服务端异常")
        if _wants_json():
            return jsonify({"error": "服务器内部错误，请重试或查看控制台日志"}), 500
        return render_template("error.html", code=500, title="服务器出错了",
                               message="处理请求时出了问题，已记录到控制台日志。请返回首页重试。"), 500

    # ---- Rate-limit middleware ----
    @app.before_request
    def check_rate_limit():
        # Only limit API endpoints; GET 是廉价查询，不限流（避免聊天界面切会话时误触限流）
        if request.path.startswith("/api/") and request.method != "GET":
            if not limiter.is_allowed(client_ip()):
                return jsonify({"error": "请求过于频繁，请稍后再试"}), 429

    # ---- Periodic rate-limiter cleanup ----
    def cleanup_loop():
        while True:
            time.sleep(300)
            limiter.cleanup()
            login_limiter.cleanup()

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
        return {
            "asset_v": asset_v,
            "edition": Config.EDITION,
            "app_version": VERSION,
            "release_date": RELEASE_DATE,
            "changelog": CHANGELOG,
        }

    # ---- 版本与探活 ----
    @app.route("/healthz")
    def healthz():
        return jsonify({"status": "ok", "product": PRODUCT_NAME, "version": VERSION})

    @app.route("/api/version")
    def api_version():
        return jsonify({
            "product": PRODUCT_NAME,
            "version": VERSION,
            "release_date": RELEASE_DATE,
            "edition": Config.EDITION,
            "changelog": CHANGELOG,
        })

    return app


if __name__ == "__main__":
    app = create_app()
    host = os.environ.get("FLASK_HOST", "0.0.0.0")
    port = int(os.environ.get("FLASK_PORT", 5000))
    app.run(debug=False, host=host, port=port)
