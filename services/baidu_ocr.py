import os
import base64
import uuid
import requests
import fitz  # PyMuPDF
from config.settings import Config


def get_baidu_access_token():
    url = "https://aip.baidubce.com/oauth/2.0/token"
    params = {
        "grant_type": "client_credentials",
        "client_id": Config.BAIDU_API_KEY,
        "client_secret": Config.BAIDU_SECRET_KEY,
    }
    resp = requests.post(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if "access_token" in data:
        return data["access_token"]
    raise RuntimeError(f"Baidu token error: {data}")


def baidu_ocr(image_path):
    token = get_baidu_access_token()
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("utf-8")

    url = f"https://aip.baidubce.com/rest/2.0/ocr/v1/accurate_basic?access_token={token}"
    payload = {
        "image": img_b64,
        "detect_direction": "true",
        "paragraph": "true",
    }
    resp = requests.post(
        url,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    # 百度出错时返回的是 HTTP 200 + error_code（配额耗尽、token 失效、图片过大等），
    # raise_for_status 拦不住。旧写法把它当成"没识别到文字"返回空串，
    # 扫描版 PDF 会静默少审几页 —— 审核系统最不能接受的失败模式。
    if data.get("error_code"):
        raise RuntimeError("百度OCR失败(%s): %s" % (data.get("error_code"), data.get("error_msg", "")))
    words = []
    for item in data.get("words_result") or []:
        words.append(item.get("words", ""))
    return "\n".join(words)


def pdf_ocr(pdf_path):
    """Extract text from PDF. Uses native text extraction first; falls back to OCR only for pages that yield no text."""
    doc = fitz.open(pdf_path)
    all_text = []
    try:
        for page_num in range(len(doc)):
            page = doc[page_num]
            native_text = page.get_text("text").strip()

            if native_text:
                all_text.append(f"--- 第 {page_num + 1} 页 ---\n{native_text}")
                continue

            # Scanned page — fall back to OCR
            pix = page.get_pixmap(dpi=200)
            img_bytes = pix.tobytes("png")

            # 文件名带随机串：固定名 _pdf_page_0.png 在并发下会互相覆盖/互删，
            # A 可能读到 B 的页面图片，把别人的单证内容审进你的档案
            tmp_path = os.path.join(
                Config.UPLOAD_FOLDER, "_pdf_page_%d_%s.png" % (page_num, uuid.uuid4().hex[:12])
            )
            with open(tmp_path, "wb") as f:
                f.write(img_bytes)

            try:
                text = baidu_ocr(tmp_path)
                if text.strip():
                    all_text.append(f"--- 第 {page_num + 1} 页 (OCR) ---\n{text}")
            finally:
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
    finally:
        # 异常路径也要关，否则 Windows 上句柄泄漏、后续删不掉文件
        doc.close()
    return "\n\n".join(all_text)
