#!/usr/bin/env bash
# 单智通 一键部署（Ubuntu 22.04 / 24.04，国内云服务器）
#
# 用法（在服务器上，以 root 身份）：
#   git clone https://gitee.com/<你的用户名>/danzhitong.git /opt/danzhitong
#   cd /opt/danzhitong
#   cp .env.example .env && nano .env        # 填密钥，并且一定要设 DZT_ACCESS_PASSWORD
#   bash deploy/install.sh
#
# 可以反复运行：代码更新后（git pull）再跑一次，就是重新装依赖并重启服务。
# 端口默认 8000，可用 DZT_PORT=8080 bash deploy/install.sh 改。
# 云服务器控制台的「安全组 / 防火墙」里要放行这个端口，否则外面打不开。
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${DZT_PORT:-8000}"
SERVICE=danzhitong
RUN_USER=dzt
# 国内服务器直连 pypi.org 很慢，默认走阿里云镜像；要换就设 PIP_INDEX
PIP_INDEX="${PIP_INDEX:-https://mirrors.aliyun.com/pypi/simple/}"

say() { printf '\n==> %s\n' "$*"; }
die() { printf '\n[部署中止] %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "请用 root 运行：sudo bash deploy/install.sh"
[ -f "$APP_DIR/app.py" ] || die "没在项目目录里找到 app.py：$APP_DIR"

# ---- 1. 先查 .env：公网服务器上不设口令，等于把 DeepSeek 余额和全部审核记录交给任何人 ----
ENV_FILE="$APP_DIR/.env"
[ -f "$ENV_FILE" ] || die "缺少 .env。先执行：cp .env.example .env，再把密钥和访问口令填进去"
# grep 找不到时退出码是 1，在 set -e + pipefail 下会让脚本一声不吭地退出，所以兜一个 || true
env_val() { { grep -E "^$1=" "$ENV_FILE" || true; } | tail -n1 | cut -d= -f2- | tr -d '\r' | sed -e 's/^["'\'']//' -e 's/["'\'']$//'; }
for k in DEEPSEEK_API_KEY BAIDU_API_KEY BAIDU_SECRET_KEY; do
    v="$(env_val "$k")"
    [ -n "$v" ] || die ".env 里 $k 是空的"
    case "$v" in *your-*) die ".env 里 $k 还是模板占位值，换成真实密钥" ;; esac
done
[ -n "$(env_val DZT_ACCESS_PASSWORD)" ] || die ".env 里必须设置 DZT_ACCESS_PASSWORD（访问口令）。公网部署不设口令，任何人都能用你的额度、看你的记录"
if [ -z "$(env_val DZT_SECRET_KEY)" ]; then
    say "生成会话密钥 DZT_SECRET_KEY"
    sed -i '/^DZT_SECRET_KEY=/d' "$ENV_FILE"
    echo "DZT_SECRET_KEY=$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')" >> "$ENV_FILE"
fi

# ---- 2. 系统依赖：Python 和中文字体（没有中文字体，导出的 PDF 中文全是方框）----
say "安装系统依赖"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3 python3-venv python3-pip fonts-wqy-microhei fonts-dejavu-core curl

python3 - <<'PY' || die "需要 Python 3.10 或更高版本"
import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)
PY

# ---- 3. 运行账号：不用 root 跑网站 ----
id -u "$RUN_USER" >/dev/null 2>&1 || useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$RUN_USER"

# ---- 4. Python 依赖 ----
say "安装 Python 依赖（镜像：$PIP_INDEX）"
[ -d "$APP_DIR/.venv" ] || python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install -q -i "$PIP_INDEX" --upgrade pip
"$APP_DIR/.venv/bin/pip" install -q -i "$PIP_INDEX" -r "$APP_DIR/requirements.txt" "gunicorn>=21"

mkdir -p "$APP_DIR/uploads"
chown -R "$RUN_USER:$RUN_USER" "$APP_DIR"
chmod 600 "$ENV_FILE"

# ---- 5. systemd 服务：开机自启、崩了自动拉起 ----
# 只开 1 个进程：限流计数在进程内存里，多进程会把名额拆散。
# timeout 180：一次 AI 审核最长可等 120 秒，gunicorn 默认 30 秒会把请求中途杀掉。
say "写入并启动服务 $SERVICE（端口 $PORT）"
cat > "/etc/systemd/system/$SERVICE.service" <<UNIT
[Unit]
Description=Danzhitong trade document audit
After=network-online.target
Wants=network-online.target

[Service]
User=$RUN_USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/.venv/bin/gunicorn --workers 1 --threads 8 --timeout 180 --bind 0.0.0.0:$PORT --access-logfile - "app:create_app()"
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable "$SERVICE" >/dev/null
systemctl restart "$SERVICE"

# ---- 6. 自检 ----
say "等待服务启动"
for _ in $(seq 1 30); do
    if curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1; then
        curl -fsS "http://127.0.0.1:$PORT/healthz"; echo
        ip="$(curl -fsS --max-time 5 https://ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')"
        say "部署完成。浏览器打开：http://$ip:$PORT"
        echo "    打不开的话，去云服务器控制台的「安全组/防火墙」放行 TCP $PORT 端口。"
        echo "    查看日志：journalctl -u $SERVICE -f"
        exit 0
    fi
    sleep 1
done
journalctl -u "$SERVICE" -n 40 --no-pager
die "服务没起来，上面是最近的日志"
