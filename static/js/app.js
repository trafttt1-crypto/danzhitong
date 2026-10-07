// ===== DOM refs — Tabs =====
const tabs = document.querySelectorAll(".tab");
const tabContents = document.querySelectorAll(".tab-content");

// ===== DOM refs — Image =====
const uploadAreaImage = document.getElementById("uploadAreaImage");
const fileInputImage = document.getElementById("fileInputImage");
const previewAreaImage = document.getElementById("previewAreaImage");
const previewImage = document.getElementById("previewImage");
const btnReselectImage = document.getElementById("btnReselectImage");
const btnAuditImage = document.getElementById("btnAuditImage");

// ===== DOM refs — Text =====
const textInput = document.getElementById("textInput");
const btnClearText = document.getElementById("btnClearText");
const btnAuditText = document.getElementById("btnAuditText");

// ===== DOM refs — PDF =====
const uploadAreaPdf = document.getElementById("uploadAreaPdf");
const fileInputPdf = document.getElementById("fileInputPdf");
const previewAreaPdf = document.getElementById("previewAreaPdf");
const pdfFileName = document.getElementById("pdfFileName");
const btnReselectPdf = document.getElementById("btnReselectPdf");
const btnAuditPdf = document.getElementById("btnAuditPdf");

// ===== DOM refs — Shared =====
const loadingSection = document.getElementById("loadingSection");
const loadingText = document.getElementById("loadingText");
const stepOcr = document.getElementById("stepOcr");
const stepAi = document.getElementById("stepAi");
const resultSection = document.getElementById("resultSection");
const resultBody = document.getElementById("resultBody");
const ocrRawText = document.getElementById("ocrRawText");
const btnNewAudit = document.getElementById("btnNewAudit");
const errorSection = document.getElementById("errorSection");
const errorText = document.getElementById("errorText");
const btnRetry = document.getElementById("btnRetry");

let selectedImageFile = null;
let selectedPdfFile = null;
let activeMode = "home";

// ===== LC Terms Section =====
var lcSection = document.getElementById("lcSection");
lcSection.style.display = "none";  // generate tab is default, hide LC
var lcHeader = document.getElementById("lcHeader");
var lcBody = document.getElementById("lcBody");
var lcChevron = document.getElementById("lcChevron");
var lcExpanded = false;

lcHeader.addEventListener("click", function () {
    lcExpanded = !lcExpanded;
    lcBody.style.display = lcExpanded ? "block" : "none";
    lcChevron.style.transform = lcExpanded ? "rotate(90deg)" : "rotate(0deg)";
});

function getLcTerms() {
    return {
        lc_amount: document.getElementById("lcAmount").value.trim(),
        lc_expiry: document.getElementById("lcExpiry").value.trim(),
        lc_applicant: document.getElementById("lcApplicant").value.trim(),
        lc_partial: document.getElementById("lcPartial").value,
        lc_transship: document.getElementById("lcTransship").value,
        lc_shipment_date: document.getElementById("lcShipmentDate").value.trim(),
        lc_freight_terms: document.getElementById("lcFreightTerms").value,
        lc_originals: document.getElementById("lcOriginals").value,
        lc_consignee: document.getElementById("lcConsignee").value.trim(),
        lc_description: document.getElementById("lcDescription").value.trim(),
        lc_measurement: document.getElementById("lcMeasurement").value,
        lc_base_qty: document.getElementById("lcBaseQty").value.trim(),
        lc_tolerance_pct: document.getElementById("lcTolerancePct").value.trim(),
        lc_tolerance_clause: document.getElementById("lcToleranceClause").value.trim(),
    };
}

function hasLcTerms(lc) {
    return Object.keys(lc).some(function (k) { return !!lc[k]; });
}

// 卡片收起来的时候，看不出里面到底填没填条款。信用证条款是跨页签共用的，
// 上一张信用证的条款留在里面，下一次审别的单证就会被当成本次条件一起核查——
// 所以在标题栏挂个"已填 N 项"，收着也看得见。
var lcHeaderHint = document.getElementById("lcHeaderHint");
var lcHeaderBadge = document.getElementById("lcHeaderBadge");

function updateLcHeaderBadge() {
    var lc = getLcTerms();
    var n = Object.keys(lc).filter(function (k) { return !!lc[k]; }).length;
    if (n > 0) {
        lcHeaderBadge.textContent = "已填 " + n + " 项";
        lcHeaderBadge.style.display = "";
        lcHeaderHint.textContent = "将按这些条款做交叉核查";
    } else {
        lcHeaderBadge.style.display = "none";
        lcHeaderHint.textContent = "展开填写LC条款以进行交叉核查";
    }
}

lcBody.addEventListener("input", updateLcHeaderBadge);
lcBody.addEventListener("change", updateLcHeaderBadge);
updateLcHeaderBadge();

// ===== LC Paste Auto-Fill =====
// 信用证原文里分批/转运写的是英文，下拉框选项是中文，解析时做个映射
var _LC_SELECT_ALIASES = {
    "ALLOWED": "允许",
    "PERMITTED": "允许",
    "NOT ALLOWED": "禁止",
    "PROHIBITED": "禁止",
    "FORBIDDEN": "禁止"
};

document.getElementById("btnLcParse").addEventListener("click", function () {
    var raw = document.getElementById("lcPasteInput").value;
    if (!raw.trim()) return;

    var patterns = [
        // Amount（信用证金额，含 ABOUT 之类的措辞原样带进来）
        { re: /(?:^|\n)\s*(?:L\/C\s+|CREDIT\s+)?AMOUNT\s*[:：]\s*(.+)/i, field: "lcAmount" },
        { re: /信用证金额\s*[:：]\s*(.+)/, field: "lcAmount" },
        // Expiry / latest presentation
        { re: /(?:EXPIRY(?:\s+DATE)?|VALID(?:ITY)?\s+(?:UNTIL|THRU|TO)|LATEST\s+DATE\s+OF\s+PRESENTATION)\s*[:：]\s*(.+)/i, field: "lcExpiry" },
        { re: /(?:信用证效期|效期|最迟交单日)\s*[:：]\s*(.+)/, field: "lcExpiry" },
        // Applicant
        { re: /APPLICANT\s*[:：]\s*(.+)/i, field: "lcApplicant" },
        { re: /申请人\s*[:：]\s*(.+)/, field: "lcApplicant" },
        // Partial shipment / transshipment
        { re: /PARTIAL\s+SHIPMENT[S]?\s*[:：]?\s*(ALLOWED|NOT\s+ALLOWED|PROHIBITED|PERMITTED)/i, field: "lcPartial" },
        { re: /分批装运\s*[:：]?\s*(允许|禁止)/, field: "lcPartial" },
        { re: /TRANSSHIPMENT[S]?\s*[:：]?\s*(ALLOWED|NOT\s+ALLOWED|PROHIBITED|PERMITTED)/i, field: "lcTransship" },
        { re: /转运\s*[:：]?\s*(允许|禁止)/, field: "lcTransship" },
        // Date
        { re: /(?:LATEST\s+SHIPMENT\s+DATE|SHIPMENT\s+DATE|LATEST\s+DATE)\s*[:：]\s*(.+)/i, field: "lcShipmentDate" },
        { re: /最迟装船日\s*[:：]\s*(.+)/i, field: "lcShipmentDate" },
        // Freight
        { re: /(?:FREIGHT\s+TERMS?|FREIGHT)\s*[:：]\s*(FREIGHT\s+(PREPAID|COLLECT))/i, field: "lcFreightTerms" },
        { re: /运费条款\s*[:：]\s*(.+)/i, field: "lcFreightTerms" },
        // Originals
        { re: /(?:NUMBER\s+OF\s+ORIGINALS?|ORIGINALS?)\s*[:：]\s*(\d+)/i, field: "lcOriginals" },
        { re: /正本份数\s*[:：]\s*(\d+)/i, field: "lcOriginals" },
        // Consignee
        { re: /CONSIGNEE\s*[:：]\s*(.+)/i, field: "lcConsignee" },
        { re: /收货人\s*[:：]\s*(.+)/i, field: "lcConsignee" },
        // Description
        { re: /(?:DESCRIPTION\s+MUST\s+INCLUDE|REQUIRED\s+DESCRIPTION|GOODS\s+DESCRIPTION)\s*[:：]\s*(.+)/i, field: "lcDescription" },
        { re: /货物描述须包含\s*[:：]\s*(.+)/i, field: "lcDescription" },
        // Measurement (CBM/CFT)
        { re: /MEASUREMENT(?:\s+UNIT)?\s*[:：]\s*(CBM|CFT)/i, field: "lcMeasurement" },
        { re: /计量单位\s*[:：]\s*(CBM|CFT)/i, field: "lcMeasurement" },
        // Base Qty
        { re: /(?:BASE\s+Q(?:UA)?NTITY|LC\s+BASE\s+QTY|BASE\s+QTY)\s*[:：]\s*([\d,]+)/i, field: "lcBaseQty" },
        { re: /基准数量\s*[:：]\s*([\d,]+)/i, field: "lcBaseQty" },
        // Tolerance %
        { re: /TOLERANCE\s*(?:PCT|%)?\s*[:：]\s*(\d+)/i, field: "lcTolerancePct" },
        { re: /溢短装比例\s*[:：]\s*(\d+)/i, field: "lcTolerancePct" },
        // Tolerance clause
        { re: /TOLERANCE\s+CLAUSE\s*[:：]\s*(.+)/i, field: "lcToleranceClause" },
        { re: /溢短装条款\s*[:：]\s*(.+)/i, field: "lcToleranceClause" },
    ];

    var filled = [];
    patterns.forEach(function (p) {
        var m = raw.match(p.re);
        if (m) {
            var el = document.getElementById(p.field);
            if (el && el.tagName === "SELECT") {
                // For select, find option matching the extracted value
                var val = m[1].trim().toUpperCase();
                // 信用证原文写的是英文（ALLOWED / PROHIBITED），下拉框里是中文
                val = _LC_SELECT_ALIASES[val] || val;
                var opts = el.options;
                for (var i = 0; i < opts.length; i++) {
                    if (opts[i].value.toUpperCase() === val || opts[i].text.toUpperCase().indexOf(val) !== -1) {
                        el.value = opts[i].value;
                        break;
                    }
                }
            } else if (el) {
                el.value = m[1].trim();
            }
            filled.push(p.field);
        }
    });

    if (filled.length > 0) {
        lcExpanded = true;
        lcBody.style.display = "block";
        lcChevron.style.transform = "rotate(90deg)";
        updateLcHeaderBadge();
        alert("已解析填写 " + filled.length + " 个字段，请核对后提交。");
    } else {
        alert("未能解析到字段，请检查格式。\n\n支持的格式：\nLATEST SHIPMENT DATE: 2024-06-30\nFREIGHT: FREIGHT PREPAID\nCONSIGNEE: TO ORDER OF XX BANK\n等");
    }
});

// ===== Tab Switching =====
tabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
        var tabName = this.dataset.tab;
        tabs.forEach(function (t) { t.classList.remove("active"); });
        this.classList.add("active");
        tabContents.forEach(function (c) { c.classList.remove("active"); });
        document.getElementById("tab" + tabName.charAt(0).toUpperCase() + tabName.slice(1)).classList.add("active");
        activeMode = tabName;
        hideAllShared();
        restoreCurrentTabUI();
    });
});

// ===== 报告里的规则编号：点一下跳到「审核规则」页并筛到那一条 =====
// 用事件委托，因为报告是动态渲染的，每渲染一次都重新绑定会漏。
// 规则页的条目没有 data-rule-id，就用 data-rule-text 的开头匹配
// （模板里那一串是「编号 名称 严重度 依据 检查 修改 分类」，编号在头一个）。
document.addEventListener("click", function (e) {
    var t = e.target;
    if (!t || !t.classList || !t.classList.contains("rpt-rule-link")) return;
    var rid = t.dataset.ruleId;
    if (!rid) return;
    var tab = document.querySelector('.tab[data-tab="rules"]');
    if (!tab) return;
    tab.click();
    var input = document.getElementById("rulesFilter");
    if (input) {
        input.value = rid;
        input.dispatchEvent(new Event("input", { bubbles: true }));
    }
    // 滚到那一条并闪一下。等一拍再做 —— 切页签是同步的，但条目刚被筛选过。
    setTimeout(function () {
        var item = Array.prototype.filter.call(
            document.querySelectorAll("#tabRules .rule-item"),
            function (el) { return (el.dataset.ruleText || "").indexOf(rid + " ") === 0; }
        )[0];
        if (!item) return;
        item.scrollIntoView({ block: "center", behavior: "smooth" });
        item.classList.remove("rule-flash");
        void item.offsetWidth;      // 强制重排，连点同一条也能重放动画
        item.classList.add("rule-flash");
        setTimeout(function () { item.classList.remove("rule-flash"); }, 2700);
    }, 80);
});

function restoreCurrentTabUI() {
    var showLc = (activeMode === "image" || activeMode === "text" || activeMode === "pdf");
    lcSection.style.display = showLc ? "block" : "none";

    if (activeMode === "history") {
        // 切走再切回来，之前开着的那条记录详情应该还在（别的页签都是这么恢复的）
        if (currentHistoryId) applyHistoryDetailLayout();
        else backToHistoryList();
    }
    else if (activeMode === "compare") {
        document.querySelector(".compare-container").style.display = "flex";
        document.querySelector(".compare-actions").style.display = "flex";
        compareResult.style.display = "none";
    }
    else if (activeMode === "generate") {
        document.querySelector(".gen-form").style.display = "block";
        genResult.style.display = "none";
    }
    else if (activeMode === "archive") {
        backToArchiveList();
        loadArchive();
    }
    else if (activeMode === "image") {
        // 审核时 hideAllTabs() 把上传区整个藏了，切走再切回必须自己恢复，
        // 否则整页只剩一个空的信用证折叠区，用户只能刷新浏览器
        if (selectedImageFile) {
            uploadAreaImage.style.display = "none";
            previewAreaImage.style.display = "block";
        } else {
            resetImageUpload();
        }
    }
    else if (activeMode === "pdf") {
        if (selectedPdfFile) {
            uploadAreaPdf.style.display = "none";
            previewAreaPdf.style.display = "block";
        } else {
            resetPdfUpload();
        }
    }
    // text tab needs no restore
}

function hideAllShared() {
    loadingSection.style.display = "none";
    resultSection.style.display = "none";
    errorSection.style.display = "none";
}

// ===== Image Tab =====
uploadAreaImage.addEventListener("click", function () { fileInputImage.click(); });
fileInputImage.addEventListener("change", function (e) { handleImageFile(e.target.files[0]); });

uploadAreaImage.addEventListener("dragover", function (e) { e.preventDefault(); uploadAreaImage.classList.add("drag-over"); });
uploadAreaImage.addEventListener("dragleave", function () { uploadAreaImage.classList.remove("drag-over"); });
uploadAreaImage.addEventListener("drop", function (e) {
    e.preventDefault();
    uploadAreaImage.classList.remove("drag-over");
    if (e.dataTransfer.files[0]) handleImageFile(e.dataTransfer.files[0]);
});

btnReselectImage.addEventListener("click", resetImageUpload);
btnAuditImage.addEventListener("click", function () { submitFile(selectedImageFile, "image"); });

function handleImageFile(file) {
    if (!file) return;
    var ext = file.name.split(".").pop().toLowerCase();
    var validExts = ["jpg", "jpeg", "png"];
    var validTypes = ["image/jpeg", "image/jpg", "image/png"];
    var typeOk = validTypes.indexOf(file.type) !== -1 || validExts.indexOf(ext) !== -1;
    if (!typeOk) { showError("仅支持 JPG、JPEG、PNG 格式"); fileInputImage.value = ""; return; }
    // 10MB 与后端 MAX_CONTENT_LENGTH 保持一致，超出会被服务端 413 拒绝
    if (file.size > 10 * 1024 * 1024) { showError("文件大小不能超过 10MB"); fileInputImage.value = ""; return; }
    selectedImageFile = file;
    var reader = new FileReader();
    reader.onload = function (e) {
        if (selectedImageFile !== file) return;
        previewImage.src = e.target.result;
        uploadAreaImage.style.display = "none";
        previewAreaImage.style.display = "block";
        errorSection.style.display = "none";
    };
    reader.readAsDataURL(file);
}

function resetImageUpload() {
    selectedImageFile = null;
    fileInputImage.value = "";
    uploadAreaImage.style.display = "block";
    previewAreaImage.style.display = "none";
}

// ===== Text Tab =====
btnClearText.addEventListener("click", function () {
    textInput.value = "";
    document.getElementById("ocrRawText").textContent = "";
    document.getElementById("resultBody").innerHTML = "";
    document.getElementById("fixSection").style.display = "none";
    document.getElementById("fixResult").style.display = "none";
    // 不清掉的话会留着一张空的"审核报告"卡片，里面的导出按钮还点不动
    resultSection.style.display = "none";
    errorSection.style.display = "none";
    btnAuditText.disabled = false;
    currentAuditResult = "";
    _currentOriginalText = "";
});
btnAuditText.addEventListener("click", submitText);

function submitText() {
    if (btnAuditText.disabled) return;
    var text = textInput.value.trim();
    if (!text) { showError("请先粘贴单证文字内容"); return; }
    btnAuditText.disabled = true;
    showLoading("text");
    stepOcr.className = "step done";
    stepOcr.querySelector(".step-label").textContent = "跳过OCR";
    stepAi.className = "step active";
    loadingText.textContent = "正在 AI 智能审核中...";

    var payload = { text: text };
    var lc = getLcTerms();
    if (hasLcTerms(lc)) payload.lc_terms = lc;

    fetch("/api/audit-text", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            // 成功和失败都要把按钮放开，否则审完一份就永久变灰，只能刷新页面
            btnAuditText.disabled = false;
            if (data.success) {
                stepAi.className = "step done";
                loadingText.textContent = "审核完成";
                setTimeout(function () { showResult(data); }, 400);
            } else {
                throw new Error(data.error || "未知错误");
            }
        })
        .catch(function (err) {
            btnAuditText.disabled = false;
            loadingSection.style.display = "none";
            showError(err.message);
        });
}

// ===== PDF Tab =====
uploadAreaPdf.addEventListener("click", function () { fileInputPdf.click(); });
fileInputPdf.addEventListener("change", function (e) { handlePdfFile(e.target.files[0]); });

uploadAreaPdf.addEventListener("dragover", function (e) { e.preventDefault(); uploadAreaPdf.classList.add("drag-over"); });
uploadAreaPdf.addEventListener("dragleave", function () { uploadAreaPdf.classList.remove("drag-over"); });
uploadAreaPdf.addEventListener("drop", function (e) {
    e.preventDefault();
    uploadAreaPdf.classList.remove("drag-over");
    if (e.dataTransfer.files[0]) handlePdfFile(e.dataTransfer.files[0]);
});

btnReselectPdf.addEventListener("click", resetPdfUpload);
btnAuditPdf.addEventListener("click", function () { submitFile(selectedPdfFile, "pdf"); });

function handlePdfFile(file) {
    if (!file) return;
    if (file.type !== "application/pdf" && file.name.toLowerCase().indexOf(".pdf") === -1) {
        showError("仅支持 PDF 格式"); fileInputPdf.value = ""; return;
    }
    if (file.size > 10 * 1024 * 1024) { showError("文件大小不能超过 10MB"); fileInputPdf.value = ""; return; }
    selectedPdfFile = file;
    pdfFileName.textContent = file.name;
    uploadAreaPdf.style.display = "none";
    previewAreaPdf.style.display = "block";
    errorSection.style.display = "none";
}

function resetPdfUpload() {
    selectedPdfFile = null;
    fileInputPdf.value = "";
    uploadAreaPdf.style.display = "block";
    previewAreaPdf.style.display = "none";
}

// ===== Shared — File Upload (Image / PDF) =====
var _fileSubmitting = false;

function submitFile(file, mode) {
    if (!file) return;
    // 双击 = 两次 OCR + 两次审核 + 两条历史记录，全都是要花钱的
    if (_fileSubmitting) return;
    _fileSubmitting = true;
    showLoading(mode);
    stepOcr.className = "step active";
    stepOcr.querySelector(".step-label").textContent = "OCR 文字识别";
    stepAi.className = "step";
    loadingText.textContent = "正在 OCR 识别中...";

    var formData = new FormData();
    formData.append("file", file);

    // Append LC terms if filled
    var lc = getLcTerms();
    if (hasLcTerms(lc)) {
        formData.append("lc_terms", JSON.stringify(lc));
    }

    fetch("/api/audit", {
        method: "POST",
        body: formData,
    })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            _fileSubmitting = false;
            if (data.success) {
                stepOcr.className = "step done";
                stepAi.className = "step active";
                loadingText.textContent = "正在 AI 智能审核中...";
                setTimeout(function () {
                    stepAi.className = "step done";
                    loadingText.textContent = "审核完成";
                    setTimeout(function () { showResult(data); }, 400);
                }, 600);
            } else {
                throw new Error(data.error || "未知错误");
            }
        })
        .catch(function (err) {
            _fileSubmitting = false;
            loadingSection.style.display = "none";
            showError(err.message);
        });
}

// ===== Shared — UI Helpers =====
function showLoading() {
    hideAllTabs();
    hideAllShared();
    loadingSection.style.display = "block";
    stepOcr.querySelector(".step-label").textContent = "OCR 文字识别";
    // 生成流程会把这一步改成"AI审核中"且不复位，会泄漏到下一次图片/文字审核
    stepAi.querySelector(".step-label").textContent = "AI 智能审核";
}

function showResult(data) {
    loadingSection.style.display = "none";
    resultSection.style.display = "block";
    resultBody.innerHTML = renderMarkdown(data.audit_result);
    ocrRawText.textContent = data.ocr_text;
    _auditResult = data.audit_result;
    currentAuditResult = data.audit_result;
    checkAndShowFix(data.audit_result, data.ocr_text);
}

function showError(msg) {
    errorText.textContent = msg;
    errorSection.style.display = "block";
    resultSection.style.display = "none";
    loadingSection.style.display = "none";
}

function hideAllTabs() {
    uploadAreaImage.style.display = "none";
    previewAreaImage.style.display = "none";
    uploadAreaPdf.style.display = "none";
    previewAreaPdf.style.display = "none";
}

// ===== New Audit =====
btnNewAudit.addEventListener("click", function () {
    hideAllShared();
    // Restore current tab's upload UI
    if (activeMode === "image") resetImageUpload();
    if (activeMode === "pdf") resetPdfUpload();
});

// ===== PDF Export =====
var btnExportPdf = document.getElementById("btnExportPdf");
var btnHistoryExportPdf = document.getElementById("btnHistoryExportPdf");
var currentAuditResult = "";
var _auditResult = "";        // text/image/pdf audit
var _genAuditResult = "";     // generate
var _compareAuditResult = ""; // compare
var _genInvoiceText = "";     // 后端排好版的纯文本，导出 PDF 用这个，不要用 HTML 的 textContent
var _genPlText = "";
var _genSubmitting = false;

function exportPdf(auditResult, title, filePrefix) {
    fetch("/api/export-pdf", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ audit_result: auditResult, title: title || "" }),
    })
        .then(function (r) {
            if (!r.ok) throw new Error("导出失败");
            return r.blob();
        })
        .then(function (blob) {
            var url = window.URL.createObjectURL(blob);
            var a = document.createElement("a");
            a.href = url;
            var now = new Date();
            a.download = (filePrefix || "审核报告") + "_" +
                now.getFullYear() +
                ("0" + (now.getMonth() + 1)).slice(-2) +
                ("0" + now.getDate()).slice(-2) + "_" +
                ("0" + now.getHours()).slice(-2) +
                ("0" + now.getMinutes()).slice(-2) +
                ("0" + now.getSeconds()).slice(-2) + ".pdf";
            document.body.appendChild(a);
            a.click();
            a.remove();
            window.URL.revokeObjectURL(url);
        })
        .catch(function (err) { alert("PDF导出失败: " + err.message); });
}

btnExportPdf.addEventListener("click", function () {
    if (currentAuditResult) exportPdf(currentAuditResult);
});

btnHistoryExportPdf.addEventListener("click", function () {
    if (currentAuditResult) exportPdf(currentAuditResult);
});

// ---- 不符点清单（银行交单格式）----
function downloadBlob(blob, fileName) {
    var url = window.URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = fileName;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
}

function timestamp() {
    var n = new Date();
    return n.getFullYear() +
        ("0" + (n.getMonth() + 1)).slice(-2) +
        ("0" + n.getDate()).slice(-2) + "_" +
        ("0" + n.getHours()).slice(-2) +
        ("0" + n.getMinutes()).slice(-2) +
        ("0" + n.getSeconds()).slice(-2);
}

function exportDiscrepancy(auditResult, ocrText) {
    fetch("/api/export-discrepancy", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ audit_result: auditResult, ocr_text: ocrText || "" }),
    })
        .then(function (r) {
            if (r.ok) return r.blob();
            // 后端会把"报告里没有不符点条目"讲清楚，原样透给用户，
            // 别吞掉换成笼统的"导出失败"
            return r.json().then(
                function (d) { throw new Error(d.error || "导出失败"); },
                function () { throw new Error("导出失败"); }
            );
        })
        .then(function (blob) {
            downloadBlob(blob, "不符点清单_" + timestamp() + ".pdf");
        })
        .catch(function (err) { alert("导出不符点清单失败：" + err.message); });
}

document.getElementById("btnExportDiscrepancy").addEventListener("click", function () {
    if (currentAuditResult) exportDiscrepancy(currentAuditResult, ocrRawText.textContent);
});

document.getElementById("btnHistoryExportDiscrepancy").addEventListener("click", function () {
    if (currentAuditResult) exportDiscrepancy(currentAuditResult, historyOcrText.textContent);
});

// ===== Smart Document Generation Tab =====
var btnAddRow = document.getElementById("btnAddRow");
var btnGenerate = document.getElementById("btnGenerate");
var genResult = document.getElementById("genResult");
var btnGenExportPdf = document.getElementById("btnGenExportPdf");
var btnGenNew = document.getElementById("btnGenNew");
var genInvoiceDisplay = document.getElementById("genInvoiceDisplay");
var genPLDisplay = document.getElementById("genPLDisplay");
var genAuditDisplay = document.getElementById("genAuditDisplay");
var _genCombinedText = "";

function addGoodsRow() {
    var tr = document.createElement("tr");
    tr.className = "goods-row";
    tr.innerHTML =
        '<td><input type="text" class="goods-name" placeholder="品名"></td>' +
        '<td><input type="number" class="goods-qty" value="0" min="0" onchange="recalcAll()"></td>' +
        '<td><input type="text" class="goods-unit" value="PCS" style="width:60px"></td>' +
        '<td><input type="number" class="goods-price" value="0.00" step="0.01" min="0" onchange="recalcAll()"></td>' +
        '<td><span class="goods-amount">0.00</span></td>' +
        '<td><input type="number" class="goods-pkgs" value="0" min="0" style="width:64px"></td>' +
        '<td><input type="number" class="goods-gw" value="0" step="0.1" min="0" style="width:72px"></td>' +
        '<td><input type="number" class="goods-nw" value="0" step="0.1" min="0" style="width:72px"></td>' +
        '<td><input type="number" class="goods-cbm" value="0" step="0.01" min="0" style="width:72px"></td>' +
        '<td><button class="btn btn-secondary btn-sm btn-del-row" onclick="removeGoodsRow(this)" aria-label="删除此行" title="删除此行"><svg viewBox="0 0 12 12" width="10" height="10" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="square" aria-hidden="true"><path d="M2.5 2.5l7 7M9.5 2.5l-7 7"/></svg></button></td>';
    document.getElementById("goodsTbody").appendChild(tr);
    recalcAll();
}

function removeGoodsRow(btn) {
    var rows = document.querySelectorAll("#goodsTbody .goods-row");
    if (rows.length <= 1) return;
    btn.closest("tr").remove();
    recalcAll();
}

function recalcAll() {
    var rows = document.querySelectorAll("#goodsTbody .goods-row");
    var subTotal = 0;
    rows.forEach(function (row) {
        var qty = parseFloat(row.querySelector(".goods-qty").value) || 0;
        var price = parseFloat(row.querySelector(".goods-price").value) || 0;
        var amount = Math.round(qty * price * 100) / 100;
        row.querySelector(".goods-amount").textContent = amount.toFixed(2);
        subTotal += amount;
    });
    subTotal = Math.round(subTotal * 100) / 100;
    document.getElementById("genSubTotal").textContent = subTotal.toFixed(2);

    var freight = parseFloat(document.getElementById("genFreight").value) || 0;
    var grandTotal = Math.round((subTotal + freight) * 100) / 100;
    document.getElementById("genGrandTotal").value = "USD " + grandTotal.toFixed(2);
}

btnAddRow.addEventListener("click", addGoodsRow);

function todayStr() {
    var t = new Date();
    return t.getFullYear() + "-" + ("0" + (t.getMonth() + 1)).slice(-2) + "-" + ("0" + t.getDate()).slice(-2);
}

// 发票日期默认开单当天，留空是最常见的漏填
(function () {
    var genDate = document.getElementById("genDate");
    if (genDate && !genDate.value) genDate.value = todayStr();
})();

// 这张表单以前没有任何校验（标签上的 * 只是装饰）：全空白点一下也会拼出一张
// 空单证、真调一次 AI 审核、再写一条档案记录，白花钱还留脏数据。
function validateGenForm(payload, goods) {
    if (!payload.invoice_no.trim()) return { msg: "请填写发票号 Invoice No", sel: "#genInvoiceNo" };
    if (!payload.date) return { msg: "请选择日期 Date", sel: "#genDate" };

    function isComplete(g) {
        return !!(g.name.trim() && parseFloat(g.qty) > 0 && parseFloat(g.price) > 0);
    }
    function hasAnyInput(g) {
        return !!(g.name.trim() || parseFloat(g.qty) > 0 || parseFloat(g.price) > 0 ||
                  parseInt(g.pkgs, 10) > 0 || parseFloat(g.gw) > 0 ||
                  parseFloat(g.nw) > 0 || parseFloat(g.cbm) > 0);
    }

    var complete = 0;
    var firstBad = 0;
    goods.forEach(function (g, i) {
        if (isComplete(g)) { complete++; return; }
        if (hasAnyInput(g) && !firstBad) firstBad = i + 1;
    });

    if (firstBad) {
        return { msg: "货物明细第 " + firstBad + " 行不完整：品名、数量、单价都要填（数量和单价要大于 0）", sel: null };
    }
    if (!complete) {
        return { msg: "请在货物明细里至少填写一行：品名 + 数量 + 单价", sel: "#goodsTbody .goods-name" };
    }
    return null;
}

btnGenerate.addEventListener("click", function () {
    // 双击会生成两份、写两条档案、调两次 AI
    if (_genSubmitting) return;
    var goods = [];
    document.querySelectorAll("#goodsTbody .goods-row").forEach(function (row) {
        goods.push({
            name: row.querySelector(".goods-name").value,
            qty: row.querySelector(".goods-qty").value,
            unit: row.querySelector(".goods-unit").value,
            price: row.querySelector(".goods-price").value,
            pkgs: row.querySelector(".goods-pkgs").value,
            gw: row.querySelector(".goods-gw").value,
            nw: row.querySelector(".goods-nw").value,
            cbm: row.querySelector(".goods-cbm").value,
        });
    });

    var payload = {
        invoice_no: document.getElementById("genInvoiceNo").value,
        date: document.getElementById("genDate").value,
        trade_terms: document.getElementById("genTradeTerms").value,
        payment: document.getElementById("genPayment").value,
        shipper_name: document.getElementById("genShipperName").value,
        shipper_addr: document.getElementById("genShipperAddr").value,
        consignee_name: document.getElementById("genConsigneeName").value,
        consignee_addr: document.getElementById("genConsigneeAddr").value,
        port_loading: document.getElementById("genPortLoading").value,
        port_discharge: document.getElementById("genPortDischarge").value,
        shipping_mark: document.getElementById("genShippingMark").value || document.getElementById("genInvoiceNo").value,
        invoice_remarks: document.getElementById("genInvoiceRemarks").value,
        pl_remarks: document.getElementById("genPlRemarks").value,
        freight: document.getElementById("genFreight").value,
        goods: JSON.stringify(goods),
    };

    var invalid = validateGenForm(payload, goods);
    if (invalid) {
        alert(invalid.msg);
        if (invalid.sel) {
            var el = document.querySelector(invalid.sel);
            if (el) el.focus();
        }
        return;   // 校验都过了才上锁，否则一次 alert 就把按钮永久锁死
    }
    _genSubmitting = true;

    // Show loading
    var genForm = document.querySelector(".gen-form");
    genForm.style.display = "none";
    genResult.style.display = "none";
    loadingSection.style.display = "block";
    loadingText.textContent = "正在生成单证并审核...";
    stepOcr.className = "step active";
    stepOcr.querySelector(".step-label").textContent = "生成单证中";
    stepAi.className = "step";

    fetch("/api/generate-docs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            _genSubmitting = false;
            if (data.success) {
                stepOcr.className = "step done";
                stepAi.className = "step active";
                stepAi.querySelector(".step-label").textContent = "AI审核中";
                setTimeout(function () {
                    stepAi.className = "step done";
                    loadingText.textContent = "完成";
                    setTimeout(function () {
                        loadingSection.style.display = "none";
                        genResult.style.display = "block";
                        genInvoiceDisplay.innerHTML = data.invoice_html || ('<pre>' + escapeHtml(data.invoice_text) + '</pre>');
                        genPLDisplay.innerHTML = data.pl_html || ('<pre>' + escapeHtml(data.pl_text) + '</pre>');
                        genAuditDisplay.innerHTML = renderMarkdown(data.audit_result);
                        _genCombinedText = data.combined_text;
                        _genInvoiceText = data.invoice_text || "";
                        _genPlText = data.pl_text || "";
                        _genAuditResult = data.audit_result;
                        currentAuditResult = data.audit_result;
                        if (data.amount_words) {
                            document.getElementById("genAmountWords").value = data.amount_words;
                        }
                        checkAndShowFix(data.audit_result, data.combined_text);
                    }, 400);
                }, 500);
            } else {
                throw new Error(data.error || "未知错误");
            }
        })
        .catch(function (err) {
            _genSubmitting = false;
            loadingSection.style.display = "none";
            genForm.style.display = "block";
            alert(err.message);
        });
});

btnGenNew.addEventListener("click", function () {
    genResult.style.display = "none";
    document.querySelector(".gen-form").style.display = "block";
});

document.getElementById("btnGenReset").addEventListener("click", function () {
    // Reset all gen form fields to defaults
    document.getElementById("genInvoiceNo").value = "";
    document.getElementById("genDate").value = todayStr();
    document.getElementById("genTradeTerms").value = "CIF";
    document.getElementById("genPayment").value = "T/T";
    document.getElementById("genShipperName").value = "";
    document.getElementById("genShipperAddr").value = "";
    document.getElementById("genConsigneeName").value = "";
    document.getElementById("genConsigneeAddr").value = "";
    document.getElementById("genPortLoading").value = "";
    document.getElementById("genPortDischarge").value = "";
    document.getElementById("genShippingMark").value = "";
    document.getElementById("genInvoiceRemarks").value = "";
    document.getElementById("genPlRemarks").value = "";
    document.getElementById("genFreight").value = "0.00";
    // 大写金额是只读框，不手动清会一直显示上一单的金额
    document.getElementById("genAmountWords").value = "";
    // Reset goods table to 1 empty row
    var tbody = document.getElementById("goodsTbody");
    tbody.innerHTML = "";
    addGoodsRow();
    // Hide result
    genResult.style.display = "none";
    document.querySelector(".gen-form").style.display = "block";
});

btnGenExportPdf.addEventListener("click", function () {
    if (!_genCombinedText) return;
    fetch("/api/export-docs-pdf", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            // 必须发后端排好版的纯文本：genInvoiceDisplay 的 textContent 会把
            // label 与值、序号与品名粘成 "Invoice NoINV-2026-001"、"1WIDGET"
            invoice_text: _genInvoiceText,
            pl_text: _genPlText,
            invoice_no: document.getElementById("genInvoiceNo").value || "单证",
        }),
    })
        .then(function (r) {
            if (!r.ok) throw new Error("导出失败");
            return r.blob();
        })
        .then(function (blob) {
            var url = window.URL.createObjectURL(blob);
            var a = document.createElement("a");
            a.href = url;
            var now = new Date();
            a.download = (document.getElementById("genInvoiceNo").value || "单证") + "_" +
                now.getFullYear() + ("0"+(now.getMonth()+1)).slice(-2) + ("0"+now.getDate()).slice(-2) + "_" +
                ("0"+now.getHours()).slice(-2) + ("0"+now.getMinutes()).slice(-2) + ("0"+now.getSeconds()).slice(-2) + ".pdf";
            document.body.appendChild(a);
            a.click();
            a.remove();
            window.URL.revokeObjectURL(url);
        })
        .catch(function (err) { alert("PDF导出失败: " + err.message); });
});

// ===== Archive Tab =====
var _archiveSortBy = "created_at";
var _archiveSortDir = "DESC";
var _archiveFilters = {};
var _currentArchiveId = null;

function loadArchive() {
    _archiveFilters = {};
    var inv = document.getElementById("archiveSearch").value.trim();
    if (inv) _archiveFilters.invoice_no = inv;
    var sh = document.getElementById("archiveShipper").value.trim();
    if (sh) _archiveFilters.shipper = sh;
    var co = document.getElementById("archiveConsignee").value.trim();
    if (co) _archiveFilters.consignee = co;
    var df = document.getElementById("archiveDateFrom").value;
    if (df) _archiveFilters.date_from = df;
    var dt = document.getElementById("archiveDateTo").value;
    if (dt) _archiveFilters.date_to = dt;
    var op = document.getElementById("archiveOpType").value;
    if (op) _archiveFilters.operation_type = op;

    var params = new URLSearchParams(_archiveFilters);
    params.set("sort_by", _archiveSortBy);
    params.set("sort_dir", _archiveSortDir);

    fetch("/api/archive?" + params.toString())
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (!data || !data.success) throw new Error((data && data.error) || "加载失败");
            renderArchiveTable(data.items || []);
        })
        .catch(function (err) {
            console.error("Archive load failed:", err);
            renderArchiveTable([]);
        });

    fetch("/api/archive/stats")
        .then(function (r) { return r.json(); })
        .then(function (data) {
            var s = (data && data.stats) || {};
            document.getElementById("statMonthCount").textContent = s.month_count || 0;
            document.getElementById("statMonthErrors").textContent = s.month_errors || 0;
            document.getElementById("statTotalCount").textContent = s.total_count || 0;
            document.getElementById("statTotalAmount").textContent = (s.total_amount || 0).toLocaleString();
        })
        .catch(function (err) { console.error("Archive stats failed:", err); });
}

function renderArchiveTable(rows) {
    var tbody = document.getElementById("archiveTbody");
    if (!Array.isArray(rows)) rows = [];
    if (rows.length === 0) {
        tbody.innerHTML = '<tr><td colspan="9" class="archive-empty">暂无档案记录</td></tr>';
        return;
    }
    tbody.innerHTML = rows.map(function (r) {
        // 结论只对"上传审核"有意义；智能制单生成的单据没有审核结论
        var verdict = r.operation_type === "上传审核"
            ? (r.has_issue ? '<span class="ar-chip is-fail">有问题</span>' : '<span class="ar-chip is-pass">通过</span>')
            : '<span class="ar-chip is-none">未审核</span>';
        var t = String(r.created_at || "").replace(/:\d{2}$/, "");
        return '<tr onclick="showArchiveDetail(' + r.id + ')">' +
            '<td class="ar-no">' + escapeHtml(r.invoice_no || "—") + '</td>' +
            '<td>' + verdict + '</td>' +
            '<td>' + escapeHtml(r.doc_type) + '</td>' +
            '<td>' + escapeHtml(r.shipper_name || '') + '</td>' +
            '<td>' + escapeHtml(r.consignee_name || '') + '</td>' +
            '<td>' + escapeHtml(r.goods_name || '') + '</td>' +
            '<td>' + (r.total_amount ? r.total_amount.toLocaleString() : '') + '</td>' +
            '<td class="ar-time">' + escapeHtml(t) + '</td>' +
            '<td>' + escapeHtml(r.operation_type || '') + '</td></tr>';
    }).join("");
}

function showArchiveDetail(id) {
    _currentArchiveId = id;
    fetch("/api/archive/" + id)
        .then(function (r) {
            if (!r.ok) throw new Error("记录不存在");
            return r.json();
        })
        .then(function (data) {
            if (data.error) { alert(data.error); return; }
            document.querySelector(".archive-table-wrap").style.display = "none";
            document.querySelector(".archive-filters").style.display = "none";
            document.querySelector(".archive-stats").style.display = "none";
            document.getElementById("archiveDetail").style.display = "block";
            var body = '<p><strong>发票号：</strong>' + escapeHtml(data.invoice_no || '') + '</p>';
            body += '<p><strong>单证类型：</strong>' + escapeHtml(data.doc_type || '') + '</p>';
            body += '<p><strong>发货人：</strong>' + escapeHtml(data.shipper_name || '') + '</p>';
            body += '<p><strong>收货人：</strong>' + escapeHtml(data.consignee_name || '') + '</p>';
            body += '<p><strong>货物品名：</strong>' + escapeHtml(data.goods_name || '') + '</p>';
            body += '<p><strong>总金额：</strong>USD ' + (data.total_amount ? data.total_amount.toLocaleString() : '0') + '</p>';
            body += '<p><strong>操作时间：</strong>' + (data.created_at || '') + '</p>';
            body += '<p><strong>操作类型：</strong>' + escapeHtml(data.operation_type || '') + '</p>';
            if (data.audit_result) {
                body += '<hr><h3>审核结果</h3><div>' + renderMarkdown(data.audit_result) + '</div>';
            }
            document.getElementById("archiveDetailBody").innerHTML = body;
            document.getElementById("archiveOcrText").textContent = data.ocr_text || "";
        })
        .catch(function (err) { alert("加载档案详情失败: " + err.message); });
}

function backToArchiveList() {
    document.getElementById("archiveDetail").style.display = "none";
    document.querySelector(".archive-table-wrap").style.display = "block";
    document.querySelector(".archive-filters").style.display = "flex";
    document.querySelector(".archive-stats").style.display = "grid";
    _currentArchiveId = null;
}

document.getElementById("btnArchiveBack").addEventListener("click", backToArchiveList);

document.getElementById("btnArchiveDelete").addEventListener("click", function () {
    if (!_currentArchiveId) return;
    if (!confirm("确定要删除这条档案吗？")) return;
    var btn = this;
    btn.disabled = true;
    fetch("/api/archive/" + _currentArchiveId, { method: "DELETE" })
        .then(function (r) { return r.json(); })
        .then(function (d) {
            btn.disabled = false;
            if (d.error) { alert("删除失败: " + d.error); return; }
            backToArchiveList(); loadArchive();
        })
        .catch(function (err) { btn.disabled = false; alert("网络错误，删除失败"); });
});

document.getElementById("btnArchiveReExport").addEventListener("click", function () {
    if (!_currentArchiveId) return;
    fetch("/api/archive/" + _currentArchiveId)
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (data.audit_result) {
                exportPdf(data.audit_result);
            } else {
                alert("该档案无可导出内容");
            }
        });
});

document.getElementById("btnArchiveExport").addEventListener("click", function () {
    var params = new URLSearchParams(_archiveFilters);
    var url = "/api/archive/export-excel?" + params.toString();
    fetch(url)
        .then(function (r) {
            if (!r.ok) return r.json().then(function (d) { throw new Error(d.error); });
            return r.blob();
        })
        .then(function (blob) {
            var a = document.createElement("a");
            a.href = URL.createObjectURL(blob);
            a.download = "档案报表_" + new Date().toISOString().substring(0, 7).replace("-", "") + ".xlsx";
            document.body.appendChild(a);
            a.click();
            a.remove();
            URL.revokeObjectURL(a.href);
        })
        .catch(function (err) { alert(err.message); });
});

document.getElementById("btnArchiveClear").addEventListener("click", function () {
    if (!confirm("确定要清空全部档案记录吗？此操作不可撤销。")) return;
    var btn = this;
    btn.disabled = true;
    fetch("/api/archive", { method: "DELETE" })
        .then(function (r) { return r.json(); })
        .then(function (d) {
            btn.disabled = false;
            if (d.error) { alert("清空失败: " + d.error); return; }
            backToArchiveList();
            loadArchive();
        })
        .catch(function (err) { btn.disabled = false; alert("网络错误，清空失败"); });
});

// Sortable columns
document.querySelectorAll(".archive-table th.sortable").forEach(function (th) {
    th.addEventListener("click", function (e) {
        e.stopPropagation();
        var field = this.dataset.sort;
        if (_archiveSortBy === field) {
            _archiveSortDir = _archiveSortDir === "ASC" ? "DESC" : "ASC";
        } else {
            _archiveSortBy = field;
            _archiveSortDir = "DESC";
        }
        loadArchive();
    });
});

// ===== Compare Tab =====
var miniTabs = document.querySelectorAll(".mini-tab");
var textA = document.getElementById("textA");
var textB = document.getElementById("textB");
var fileInputA = document.getElementById("fileInputA");
var fileInputB = document.getElementById("fileInputB");
var uploadAreaA = document.getElementById("uploadAreaA");
var uploadAreaB = document.getElementById("uploadAreaB");
var previewA = document.getElementById("previewA");
var previewB = document.getElementById("previewB");
var previewNameA = document.getElementById("previewNameA");
var previewNameB = document.getElementById("previewNameB");
var btnResetA = document.getElementById("btnResetA");
var btnResetB = document.getElementById("btnResetB");
var btnCompare = document.getElementById("btnCompare");
var compareResult = document.getElementById("compareResult");
var compareResultBody = document.getElementById("compareResultBody");
var compareRawText = document.getElementById("compareRawText");
var btnCompareNew = document.getElementById("btnCompareNew");
var btnCompareExportPdf = document.getElementById("btnCompareExportPdf");

var selectedFileA = null;
var selectedFileB = null;
var compareModes = { a: "text", b: "text" };

// Mini-tab switching
miniTabs.forEach(function (mt) {
    mt.addEventListener("click", function () {
        var side = this.dataset.side;
        var mode = this.dataset.mode;
        compareModes[side] = mode;
        // Update mini-tab styles
        this.parentElement.querySelectorAll(".mini-tab").forEach(function (t) { t.classList.remove("active"); });
        this.classList.add("active");
        // Show/hide input areas
        var capSide = side.toUpperCase();
        document.getElementById("compare" + capSide + "Text").classList.toggle("active", mode === "text");
        document.getElementById("compare" + capSide + "Image").classList.toggle("active", mode === "image");
        // Clear selection when switching mode
        if (side === "a") { selectedFileA = null; resetCompareFileUI("a"); }
        if (side === "b") { selectedFileB = null; resetCompareFileUI("b"); }
    });
});

// File upload helpers
function setupCompareUpload(side) {
    var fileInput = side === "a" ? fileInputA : fileInputB;
    var uploadArea = side === "a" ? uploadAreaA : uploadAreaB;
    var previewEl = side === "a" ? previewA : previewB;
    var nameEl = side === "a" ? previewNameA : previewNameB;

    uploadArea.addEventListener("click", function () { fileInput.click(); });
    fileInput.addEventListener("change", function (e) { handleCompareFile(side, e.target.files[0]); });

    uploadArea.addEventListener("dragover", function (e) { e.preventDefault(); uploadArea.classList.add("drag-over"); });
    uploadArea.addEventListener("dragleave", function () { uploadArea.classList.remove("drag-over"); });
    uploadArea.addEventListener("drop", function (e) {
        e.preventDefault();
        uploadArea.classList.remove("drag-over");
        if (e.dataTransfer.files[0]) handleCompareFile(side, e.dataTransfer.files[0]);
    });
}

function handleCompareFile(side, file) {
    if (!file) return;
    var validExts = ["jpg", "jpeg", "png", "pdf"];
    var ext = file.name.split(".").pop().toLowerCase();
    if (validExts.indexOf(ext) === -1) {
        alert("仅支持 JPG、PNG、PDF 格式");
        (side === "a" ? fileInputA : fileInputB).value = "";
        return;
    }
    if (file.size > 10 * 1024 * 1024) {
        alert("文件大小不能超过 10MB");
        (side === "a" ? fileInputA : fileInputB).value = "";
        return;
    }
    var uploadArea = side === "a" ? uploadAreaA : uploadAreaB;
    var previewEl = side === "a" ? previewA : previewB;
    var nameEl = side === "a" ? previewNameA : previewNameB;
    if (side === "a") selectedFileA = file; else selectedFileB = file;
    nameEl.textContent = file.name;
    uploadArea.style.display = "none";
    previewEl.style.display = "flex";
}

function resetCompareFileUI(side) {
    var uploadArea = side === "a" ? uploadAreaA : uploadAreaB;
    var previewEl = side === "a" ? previewA : previewB;
    var fileInput = side === "a" ? fileInputA : fileInputB;
    fileInput.value = "";
    uploadArea.style.display = "block";
    previewEl.style.display = "none";
}

setupCompareUpload("a");
setupCompareUpload("b");

btnResetA.addEventListener("click", function () { selectedFileA = null; resetCompareFileUI("a"); });
btnResetB.addEventListener("click", function () { selectedFileB = null; resetCompareFileUI("b"); });

var _compareSubmitting = false;

btnCompare.addEventListener("click", function () {
    // 双击 = 两次 OCR + 两次对比，翻倍计费
    if (_compareSubmitting) return;
    var formData = new FormData();

    if (compareModes.a === "text") {
        var ta = textA.value.trim();
        if (!ta) { alert("请先填写单证A的内容"); return; }
        formData.append("text_a", ta);
    } else {
        if (!selectedFileA) { alert("请先上传单证A的文件"); return; }
        formData.append("file_a", selectedFileA);
    }

    if (compareModes.b === "text") {
        var tb = textB.value.trim();
        if (!tb) { alert("请先填写单证B的内容"); return; }
        formData.append("text_b", tb);
    } else {
        if (!selectedFileB) { alert("请先上传单证B的文件"); return; }
        formData.append("file_b", selectedFileB);
    }

    // 校验都过了才上锁，否则上面任何一次 alert 返回都会把按钮永久锁死
    _compareSubmitting = true;

    // Show loading
    document.querySelector(".compare-container").style.display = "none";
    document.querySelector(".compare-actions").style.display = "none";
    compareResult.style.display = "none";
    loadingSection.style.display = "block";
    stepOcr.className = "step active";
    stepOcr.querySelector(".step-label").textContent = "OCR 识别中...";
    stepAi.className = "step";
    loadingText.textContent = "正在处理中...";

    fetch("/api/compare", { method: "POST", body: formData })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            _compareSubmitting = false;
            if (data.success) {
                stepOcr.className = "step done";
                stepAi.className = "step active";
                loadingText.textContent = "正在 AI 对比审核中...";
                setTimeout(function () {
                    stepAi.className = "step done";
                    loadingText.textContent = "对比完成";
                    setTimeout(function () {
                        loadingSection.style.display = "none";
                        compareResult.style.display = "block";
                        compareResultBody.innerHTML = renderMarkdown(data.audit_result);
                        compareRawText.textContent = "=== 单证A ===\n" + data.text_a + "\n\n=== 单证B ===\n" + data.text_b;
                        _compareAuditResult = data.audit_result;
                        currentAuditResult = data.audit_result;
                    }, 400);
                }, 600);
            } else {
                throw new Error(data.error || "未知错误");
            }
        })
        .catch(function (err) {
            _compareSubmitting = false;
            loadingSection.style.display = "none";
            document.querySelector(".compare-container").style.display = "flex";
            document.querySelector(".compare-actions").style.display = "flex";
            alert(err.message);
        });
});

btnCompareNew.addEventListener("click", function () {
    compareResult.style.display = "none";
    document.querySelector(".compare-container").style.display = "flex";
    document.querySelector(".compare-actions").style.display = "flex";
    textA.value = "";
    textB.value = "";
    selectedFileA = null; selectedFileB = null;
    resetCompareFileUI("a"); resetCompareFileUI("b");
});

btnCompareExportPdf.addEventListener("click", function () {
    if (currentAuditResult) exportPdf(currentAuditResult);
});

// ===== One-Click Fix =====
var fixSection = document.getElementById("fixSection");
var btnFixDoc = document.getElementById("btnFixDoc");
var fixResult = document.getElementById("fixResult");
var fixResultBody = document.getElementById("fixResultBody");
var btnFixExportPdf = document.getElementById("btnFixExportPdf");
var _currentOriginalText = "";

function checkAndShowFix(auditResult, originalText) {
    _currentOriginalText = originalText || "";
    var hasIssues = auditResult &&
        auditResult.indexOf("未发现明显错误") === -1 &&
        (auditResult.indexOf("【发现问题】") !== -1 || auditResult.indexOf("需修改") !== -1);
    fixSection.style.display = hasIssues ? "block" : "none";
    fixResult.style.display = "none";
}

btnFixDoc.addEventListener("click", function () {
    var origText = _currentOriginalText || document.getElementById("ocrRawText").textContent || "";
    btnFixDoc.disabled = true;
    btnFixDoc.textContent = "修复中...";

    fetch("/api/fix-doc", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ original: origText, audit_result: currentAuditResult }),
    })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            btnFixDoc.disabled = false;
            btnFixDoc.textContent = "一键修复";
            if (data.success) {
                fixResult.style.display = "block";
                fixResultBody.innerHTML = renderMarkdown(data.fixed_text);
            } else {
                alert("修复失败: " + (data.error || "未知错误"));
            }
        })
        .catch(function (err) {
            btnFixDoc.disabled = false;
            btnFixDoc.textContent = "一键修复";
            alert("修复请求失败: " + err.message);
        });
});

btnFixExportPdf.addEventListener("click", function () {
    if (fixResultBody.textContent) {
        var fixedText = fixResultBody.textContent.trim();
        var invoiceNo = document.getElementById("genInvoiceNo") ? document.getElementById("genInvoiceNo").value : "";
        fetch("/api/export-fixed-pdf", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ fixed_text: fixedText, invoice_no: invoiceNo }),
        })
            .then(function (r) {
                if (!r.ok) throw new Error("导出失败");
                return r.blob();
            })
            .then(function (blob) {
                var url = window.URL.createObjectURL(blob);
                var a = document.createElement("a");
                a.href = url;
                var now = new Date();
                a.download = "修复后单证_" +
                    (invoiceNo || "单证") + "_" +
                    now.getFullYear() +
                    ("0" + (now.getMonth() + 1)).slice(-2) +
                    ("0" + now.getDate()).slice(-2) + "_" +
                    ("0" + now.getHours()).slice(-2) +
                    ("0" + now.getMinutes()).slice(-2) +
                    ("0" + now.getSeconds()).slice(-2) + ".pdf";
                document.body.appendChild(a);
                a.click();
                a.remove();
                window.URL.revokeObjectURL(url);
            })
            .catch(function (err) { alert("PDF导出失败: " + err.message); });
    }
});

// ===== History Tab =====
var historyList = document.getElementById("historyList");
var historyEmpty = document.getElementById("historyEmpty");
var historyDetail = document.getElementById("historyDetail");
var historyDetailBody = document.getElementById("historyDetailBody");
var historyOcrText = document.getElementById("historyOcrText");
var btnHistoryBack = document.getElementById("btnHistoryBack");
var btnHistoryDelete = document.getElementById("btnHistoryDelete");
var currentHistoryId = null;
var _allHistoryRecords = [];

var _historyPage = 1;
var _historyTotal = 0;
var _historyPerPage = 20;

function loadHistory(page) {
    if (!page) page = _historyPage;
    var q = (document.getElementById("historySearch") || {}).value || "";
    var url = "/api/history?page=" + page + "&per_page=" + _historyPerPage;
    if (q) url += "&q=" + encodeURIComponent(q);
    // 页面上一直有这两个日期框，但以前既不读值、后端也没这个参数，选了完全没反应
    var dateFrom = (document.getElementById("historyDateFrom") || {}).value;
    if (dateFrom) url += "&date_from=" + encodeURIComponent(dateFrom);
    var dateTo = (document.getElementById("historyDateTo") || {}).value;
    if (dateTo) url += "&date_to=" + encodeURIComponent(dateTo);
    fetch(url)
        .then(function (r) { return r.json(); })
        .then(function (data) {
            _allHistoryRecords = data.items || [];
            _historyPage = data.page || 1;
            _historyTotal = data.total || 0;
            renderHistory(_allHistoryRecords);
            renderHistoryPager();
        })
        .catch(function (err) { console.error(err); });
}

function renderHistoryPager() {
    var totalPages = Math.ceil(_historyTotal / _historyPerPage) || 1;
    var pager = document.getElementById("historyPager");
    if (!pager) return;
    // 详情视图下分页器属于列表那一套，不能露出来。它写着"第 1 / 2 页，共 30 条"，
    // 挂在一单记录的详情上方，看着就像页面串了
    if (currentHistoryId) { pager.style.display = "none"; return; }
    if (totalPages <= 1) { pager.style.display = "none"; return; }
    pager.style.display = "flex";
    document.getElementById("pagerInfo").textContent =
        "第 " + _historyPage + " / " + totalPages + " 页，共 " + _historyTotal + " 条";
    document.getElementById("pagerPrev").disabled = _historyPage <= 1;
    document.getElementById("pagerNext").disabled = _historyPage >= totalPages;
}

function filterHistory() {
    _historyPage = 1;
    loadHistory(1);
}

function clearHistorySearch() {
    document.getElementById("historySearch").value = "";
    document.getElementById("historyDateFrom").value = "";
    document.getElementById("historyDateTo").value = "";
    _historyPage = 1;
    loadHistory(1);
}

function renderHistory(records) {
    historyList.innerHTML = "";
    if (records.length === 0) {
        historyList.innerHTML = '<p class="history-empty">暂无匹配记录</p>';
        return;
    }
    var badgeMap = { image: "badge-image", text: "badge-text", pdf: "badge-pdf", lc: "badge-lc" };
    var labelMap = { image: "图片", text: "文字", pdf: "PDF", lc: "信用证" };
    records.forEach(function (rec) {
        var div = document.createElement("div");
        div.className = "history-item";
        div.onclick = function () { showHistoryDetail(rec.id); };
        // 结论速览：后端按报告算好的。没有判定（信用证体检等结构不同的报告）就只显示类型。
        var status;
        if (rec.verdict === "fail") {
            status = '<span class="hi-status hi-fail">' + (rec.issue_count ? rec.issue_count + " 处问题" : "需修改") + "</span>";
        } else if (rec.verdict === "pass") {
            status = '<span class="hi-status hi-pass">通过</span>';
        } else {
            status = '<span class="hi-status hi-none">' + (labelMap[rec.input_type] || "记录") + "</span>";
        }
        var title = rec.doc_type || (rec.input_type === "lc" ? "信用证体检" : "审核记录");
        // 2026-09-22 19:30:52 → 09-22 19:30（年份和秒在列表里是噪音，悬停仍能看到完整时间）
        var shortTime = String(rec.created_at || "").replace(/^\d{4}-/, "").replace(/:\d{2}$/, "");
        var summary = String(rec.input_summary || "").replace(/\s+/g, " ").trim();
        div.innerHTML =
            status +
            '<div class="history-item-meta">' +
            '<div class="hi-title">' + escapeHtml(title) +
            (rec.ref ? '<span class="hi-ref">' + escapeHtml(rec.ref) + "</span>" : "") + "</div>" +
            '<div class="history-item-summary">' + escapeHtml(summary) + "</div>" +
            "</div>" +
            '<div class="hi-side"><time title="' + escapeHtml(rec.created_at || "") + '">' + escapeHtml(shortTime) + "</time>" +
            // 没有判定时左边的胶囊已经是类型了，右边不再重复一个
            (rec.verdict
                ? '<span class="history-item-badge ' + (badgeMap[rec.input_type] || "") + '">' + (labelMap[rec.input_type] || rec.input_type) + "</span>"
                : "") + "</div>" +
            '<span class="history-item-arrow">&gt;</span>';
        historyList.appendChild(div);
    });
}

// 历史页有两种形态：列表（搜索条 + 记录列表 + 分页器）和详情。
// 进详情时列表那一整套要一起收起 —— 旧版只藏了列表本身，搜索条和分页器
// 留在原地，详情页顶上就挂着"第 1 / 2 页，共 30 条"。
var historySearchBar = document.querySelector(".history-search");

function applyHistoryDetailLayout() {
    if (historySearchBar) historySearchBar.style.display = "none";
    historyList.style.display = "none";
    var pager = document.getElementById("historyPager");
    if (pager) pager.style.display = "none";
    historyDetail.style.display = "block";
}

function showHistoryDetail(id) {
    fetch("/api/history/" + id)
        .then(function (r) { return r.json(); })
        .then(function (data) {
            // 记录已被删除时后端返回的是 JSON 错误体，旧代码不检查就直接渲染，
            // 结果列表已隐藏、详情面板空白，只剩控制台里一行报错
            if (!data || data.error) {
                alert("打开失败: " + ((data && data.error) || "记录不存在"));
                return;
            }
            // 打开成功才认这是"在详情里"：失败时提前置位会让列表的分页器
            // 一直藏着（分页器看 currentHistoryId 决定显不显示）
            currentHistoryId = id;
            applyHistoryDetailLayout();
            historyDetailBody.innerHTML = renderMarkdown(data.audit_result);
            historyOcrText.textContent = data.ocr_text || "";
            currentAuditResult = data.audit_result;
        })
        .catch(function (err) {
            console.error(err);
            alert("网络错误，无法打开该记录");
        });
}

function backToHistoryList() {
    if (historySearchBar) historySearchBar.style.display = "";
    historyList.style.display = "flex";
    historyDetail.style.display = "none";
    currentHistoryId = null;
    renderHistoryPager();  // 回到列表，分页器按当前真实条数决定要不要出现
}

btnHistoryBack.addEventListener("click", backToHistoryList);

document.getElementById("btnHistoryClearAll").addEventListener("click", function () {
    if (!confirm("确定要清空全部历史记录吗？此操作不可撤销。")) return;
    var btn = this;
    btn.disabled = true;
    fetch("/api/history", { method: "DELETE" })
        .then(function (r) { return r.json(); })
        .then(function (d) {
            btn.disabled = false;
            if (d.error) { alert("清空失败: " + d.error); return; }
            _allHistoryRecords = [];
            _historyPage = 1; _historyTotal = 0;
            renderHistory([]);
            renderHistoryPager();
            historyDetail.style.display = "none";
            historyList.style.display = "flex";
            currentHistoryId = null;
        })
        .catch(function (err) { btn.disabled = false; alert("网络错误，清空失败"); });
});

btnHistoryDelete.addEventListener("click", function () {
    if (!currentHistoryId) return;
    if (!confirm("确定要删除这条记录吗？")) return;
    var btn = this;
    btn.disabled = true;
    fetch("/api/history/" + currentHistoryId, { method: "DELETE" })
        .then(function (r) { return r.json(); })
        .then(function (d) {
            btn.disabled = false;
            if (d.error) { alert("删除失败: " + d.error); return; }
            backToHistoryList();
            loadHistory();
        })
        .catch(function (err) { btn.disabled = false; alert("网络错误，删除失败"); });
});

function escapeHtml(str) {
    var div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

var _RPT_SECTION_CLASS = {
    "单证类型": "rpt-sec-type",
    "发现问题": "rpt-sec-issue",
    "数学验算": "rpt-sec-math",
    "风险提示": "rpt-sec-risk",
    "审核结论": "rpt-sec-conclusion",
    // 多单证对比页用另一套小节名
    "对比结论": "rpt-sec-conclusion",
    "差异项": "rpt-sec-issue",
    // 信用证体检报告的小节。配色沿用同一套指路规则，不另起炉灶
    "信用证概要": "rpt-sec-type",
    "风险条款": "rpt-sec-issue",
    "时间安排": "rpt-sec-math",
    "单据要求清单": "rpt-sec-math"
};

// 需要按"问题条目"渲染的小节（加粗 + 竖条 + 编号徽标）
var _RPT_ISSUE_SECTIONS = { "发现问题": 1, "差异项": 1, "风险条款": 1 };

// 严重度标签文案：审核报告里写的是英文枚举，界面上给中文
var _SEVERITY_LABEL = { critical: "严重", error: "需改", warning: "提示" };

// 把 [R01] 规则编号和 [critical] 严重度渲染成小标签
function stampTags(el) {
    // R = 审核规则，L = 审证规则（信用证体检）。
    // 规则编号的方括号可选：模型有时会把提示词里的 "[规则编号]" 当成"这里填编号"，
    // 只写 L11 不带括号（严重度那半边却照写了括号）。
    // 严重度仍要求带方括号 —— 裸的英文 error/warning 有可能是正文里的词，
    // 误加徽标比漏加更难看。
    var re = /\[(R\d{2}|L\d{2}|critical|error|warning)\]|\b([RL]\d{2})\b/g;
    var walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null);
    var nodes = [], n;
    while ((n = walker.nextNode())) nodes.push(n);
    nodes.forEach(function (node) {
        var text = node.nodeValue;
        re.lastIndex = 0;
        if (!re.test(text)) return;
        re.lastIndex = 0;
        var frag = document.createDocumentFragment();
        var last = 0, m;
        while ((m = re.exec(text))) {
            if (m.index > last) frag.appendChild(document.createTextNode(text.slice(last, m.index)));
            var tok = m[1] || m[2];
            var span = document.createElement("span");
            // 认严重度要认关键字，不能靠"是不是 R 开头"——那样 L 开头的审证规则
            // 会被当成严重度，套上 rpt-sev 的样式（L 编号刚加进来时就是这么错的）
            if (/^(critical|error|warning)$/.test(tok)) {
                span.className = "rpt-tag rpt-sev rpt-sev-" + tok;
                span.textContent = _SEVERITY_LABEL[tok] || tok;
            } else {
                // 规则编号做成可点的：点一下跳到「审核规则」页并筛到那一条。
                // 指导老师的演示稿要的就是这个 ——「每一个结论，都不是黑箱」，
                // 光靠旁白说不算，得让观众看见编号真的能查回条款。
                span.className = "rpt-tag rpt-rule rpt-rule-link";
                span.textContent = tok;
                span.dataset.ruleId = tok;
                span.setAttribute("role", "button");
                span.setAttribute("tabindex", "0");
                span.title = "查看这条规则的依据";
            }
            frag.appendChild(span);
            last = m.index + m[0].length;
        }
        if (last < text.length) frag.appendChild(document.createTextNode(text.slice(last)));
        node.parentNode.replaceChild(frag, node);
    });
}

// 【小节】前后补空行：模型常把"【审核结论】需修改 【发现问题】…"写成一整段，
// 拆成独立段落后才能按小节分别上色。
// 注意不能见【】就拆 —— 正文里会写"少量待补项见【风险提示】。"这种行内提及，
// 拆了就会凭空多出一个假标题，还把句子截断。
function normalizeReportText(text) {
    return String(text)
        // 「**【参考答案】**」这种加粗小标题：先剥掉外层 **，否则下面拆行会把 ** 留成两行孤零零的星号
        .replace(/\*\*\s*(【[^】\n]{1,20}】[^*\n]*?)\s*\*\*/g, "$1")
        .replace(/(.)?[ \t]*【([^】\n]{1,20})】[ \t]*/g, function (whole, before, name) {
            // 前面紧跟着文字/数字 = 行内提及，原样保留
            if (before && /[一-鿿㐀-䶿A-Za-z0-9]/.test(before)) return whole;
            return (before || "") + "\n\n【" + name + "】\n\n";
        })
        .replace(/\n{3,}/g, "\n\n");
}

// 把"问题1："这个前缀单独拎出来加粗上色
function stampIssueNumber(el) {
    var walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null);
    var node = walker.nextNode();
    if (!node) return;
    var m = node.nodeValue.match(/^\s*(问题\s*\d+)\s*([：:])/);
    if (!m) return;
    var span = document.createElement("span");
    span.className = "rpt-no";
    span.textContent = m[1] + m[2];
    var rest = document.createTextNode(node.nodeValue.slice(m[0].length));
    node.parentNode.insertBefore(span, node);
    node.parentNode.insertBefore(rest, node);
    node.parentNode.removeChild(node);
}

// 结论是"通过"还是"需修改"：先把否定式（未发现明显错误…）换成肯定语，
// 否则"未发现明显错误"里的"错误"会被当成负面词
function conclusionState(text) {
    // 结论开头写明了判定词就以它为准，后半句里的"风险""需修改项"不能把它翻过来：
    // "通过（…）：…未发现需修改项；仅日期时效需人工复核" 原来会被判成红色（实测 #67 #86）。
    // 与 services/archive.py 的 _VERDICT_HEAD_RE 同一个口径
    var head = String(text || "").replace(/\*\*/g, "").match(/^[\s\-#>]*(不通过|需修改|需修正|建议改证|通过|可接受)/);
    if (head) return (head[1] === "通过" || head[1] === "可接受") ? "is-ok" : "is-bad";
    var t = text
        .replace(/未发现明显(错误|问题|异常|不利条款)/g, "○通过")
        .replace(/未发现(任何)?(错误|问题|异常|不利条款)/g, "○通过")
        .replace(/不存在(明显)?(错误|问题)/g, "○通过")
        .replace(/没有发现(任何)?(错误|问题)/g, "○通过");
    // 信用证体检的判定词是"可接受"，不是"通过"
    if (/^可接受|可接受[：:]/.test(t.trim())) return "is-ok";
    if (/需修改|需修正|需核查|需补充|需补|不通过|不符|风险|错误|问题|不完整|不一致|缺失|拒付|改证/.test(t)) {
        return "is-bad";
    }
    if (/通过|无异常|无误|一致|符合|正常|可接受/.test(t)) return "is-ok";
    return "";
}

// 按小节上色。配色规则见 app.css：颜色只给小节标题"指路"，正文一律深色，
// 正文里只有问题条目和审核结论两个例外（它们本身就是状态，不是叙述）。
function decorateReport(box) {
    var blocks = box.querySelectorAll("p, li, h1, h2, h3, h4, h5, h6");
    var section = "";
    var conclusionHead = null;
    var conclusionCls = "";
    Array.prototype.forEach.call(blocks, function (el) {
        var text = (el.textContent || "").trim();
        if (!text) return;
        var head = text.match(/^【(.+?)】$/);
        if (head) {
            section = head[1];
            // 【本轮执行】是附在报告末尾的执行情况说明，按附录压低处理
            if (section === "本轮执行") {
                el.classList.add("rpt-sec", "rpt-appendix");
                return;
            }
            el.classList.add("rpt-sec");
            el.classList.add(_RPT_SECTION_CLASS[section] || "rpt-sec-other");
            if (section === "审核结论" || section === "对比结论") conclusionHead = el;
            return;
        }
        // 末尾的"附：16项规则速查表"是固定附录，不属于上一节，
        // 否则会被当成【审核结论】的延续，整段变成大号粗体
        if (/^附[：:]/.test(text)) {
            section = "";
            el.classList.add("rpt-appendix");
            return;
        }
        if (_RPT_ISSUE_SECTIONS[section]) {
            el.classList.add("rpt-item-issue");
            stampIssueNumber(el);
            stampTags(el);
        } else if (section === "审核结论" || section === "对比结论") {
            var state = conclusionState(text);
            el.classList.add("rpt-conclusion");
            if (state) {
                el.classList.add(state);
                if (!conclusionCls) conclusionCls = state;
            }
        } else if (section === "本轮执行") {
            el.classList.add("rpt-appendix");
        }
    });
    // 标题跟着结论走：结论是"需修改"，这一节的标题也变红，整节统一
    if (conclusionHead && conclusionCls) conclusionHead.classList.add(conclusionCls);
}

// AI 返回的报告和单证原文都会落库，又在多处用 innerHTML 渲染；
// marked v15 已经移除了 sanitize 选项（原始 HTML 会原样透传），
// 所以先转义再交给 marked：markdown 排版照常，脚本注入挡在门外。
function renderMarkdown(text) {
    if (text === null || text === undefined) return "";
    // 标准审核报告走结构化视图（结论横幅 + 问题卡片）；认不出格式就退回下面的 markdown 渲染
    var normalized = normalizeReportText(text);
    if (window.DZTReport) {
        try {
            var view = window.DZTReport.build(normalized);
            if (view) return view;
        } catch (e) { /* 解析出错不能让报告打不开，退回旧渲染 */ }
    }
    var box = document.createElement("div");
    // 中文里「**要求：**找出」这种写法，按 CommonMark 规则结束符前是标点、后面紧跟文字，不算加粗，
    // 会原样露出星号。先在转义后的文本上把成对的 ** 换成 <strong>（此时已无用户 HTML，插入的标签是安全的）
    var safe = escapeHtml(normalized).replace(/\*\*([^*\n]+?)\*\*/g, "<strong>$1</strong>");
    box.innerHTML = marked.parse(safe);
    decorateReport(box);
    return box.innerHTML;
}

// Override tab switching to auto-load history
tabs.forEach(function (tab) {
    if (tab.dataset.tab === "history") {
        // 直接绑 loadHistory 会把 MouseEvent 当页码传进来（永远 truthy），
        // 每次点这个 tab 都静默重置回第 1 页
        tab.addEventListener("click", function () { loadHistory(); });
    }
    if (tab.dataset.tab === "archive") {
        // archive already loaded in restoreCurrentTabUI
    }
});

// ===== Retry =====
btnRetry.addEventListener("click", function () {
    if (activeMode === "text") submitText();
    else if (activeMode === "pdf" && selectedPdfFile) submitFile(selectedPdfFile, "pdf");
    else if (activeMode === "image" && selectedImageFile) submitFile(selectedImageFile, "image");
});

// ===== Workbench: topbar module name + mobile drawer =====
(function () {
    // 每个页签在顶栏显示的名字。漏了哪个，点它顶栏就只剩"当前："，
    // 所以新增页签时必须一起加进来
    var MODULE_NAMES = {
        home: "首页",
        generate: "智能制单",
        image: "上传图片",
        text: "粘贴文字",
        pdf: "上传 PDF",
        lcreview: "信用证体检",
        compare: "多单证对比",
        graph: "一致性图",
        practice: "实训练习",
        history: "历史记录",
        archive: "档案管理",
        help: "功能说明",
        rules: "审核规则",
        settings: "设置"
    };
    var topbarModule = document.getElementById("topbarModule");
    var menuBtn = document.getElementById("menuBtn");
    var backdrop = document.getElementById("sidebarBackdrop");

    tabs.forEach(function (tab) {
        tab.addEventListener("click", function () {
            topbarModule.textContent = "当前：" + (MODULE_NAMES[this.dataset.tab] || "");
            // 浏览器标签页标题跟着变：多开几个标签页、或从历史里找回时分得清
            document.title = (MODULE_NAMES[this.dataset.tab] ? MODULE_NAMES[this.dataset.tab] + " - " : "") + "单智通";
            document.body.classList.remove("nav-open");
        });
    });

    menuBtn.addEventListener("click", function () {
        document.body.classList.toggle("nav-open");
    });

    backdrop.addEventListener("click", function () {
        document.body.classList.remove("nav-open");
    });

    document.addEventListener("keydown", function (e) {
        if (e.key === "Escape") document.body.classList.remove("nav-open");
    });
})();

// ===== 教学案例：一键载入练习单证 =====
(function () {
    var caseBtns = document.querySelectorAll(".case-btn");
    if (!caseBtns.length || !window.TEACHING_CASES) return;
    caseBtns.forEach(function (btn) {
        btn.addEventListener("click", function () {
            var idx = parseInt(btn.dataset.case, 10) || 0;
            var item = window.TEACHING_CASES[idx];
            if (!item) return;
            textInput.value = item.text;
            var auditBtn = document.getElementById("btnAuditText");
            if (auditBtn) auditBtn.focus();
        });
    });
})();

// ===== Home tab: 总控智能助手（对话） =====
(function () {
    var chatScroll = document.getElementById("chatScroll");
    var chatList = document.getElementById("chatList");
    var chatEmpty = document.getElementById("chatEmpty");
    var chatThreads = document.getElementById("chatThreads");
    var homeForm = document.getElementById("homeComposer");
    var homeInput = document.getElementById("homeInput");
    var btnChatNew = document.getElementById("btnChatNew");
    var btnChatClear = document.getElementById("btnChatClear");
    if (!chatScroll || !chatList || !homeForm || !homeInput || !chatThreads) return;

    var composerSlot = homeForm.parentElement;
    var homeSub = document.getElementById("homeSub");
    var homeTitle = document.getElementById("homeTitle");

    var sending = false;
    var loadingEl = null;
    var chatBusyStop = null;
    var currentThreadId = null; // null = 新对话（尚未创建）

    function scrollBottom() { chatScroll.scrollTop = chatScroll.scrollHeight; }

    function updateEmpty() {
        var empty = !chatList.children.length;
        // 空状态不写内联 display，交给样式表的 flex 居中规则生效
        chatEmpty.style.display = empty ? "" : "none";
        chatScroll.classList.toggle("is-empty", empty);
        // 空状态：输入条居中放在大字下方；有消息后移回底部
        if (empty) {
            chatEmpty.insertBefore(homeForm, homeSub);
        } else if (homeForm.parentElement !== composerSlot) {
            // 搬动已聚焦的节点会触发 blur，用户得再点一下才能接着输入
            var hadFocus = document.activeElement === homeInput;
            composerSlot.appendChild(homeForm);
            if (hadFocus) homeInput.focus();
        }
    }

    function addUserBubble(text) {
        var wrap = document.createElement("div");
        wrap.className = "chat-msg user";
        var bubble = document.createElement("div");
        bubble.className = "chat-bubble";
        bubble.textContent = text;
        wrap.appendChild(bubble);
        chatList.appendChild(wrap);
        updateEmpty();
        scrollBottom();
    }

    function addAssistantBubble(markdown, kind) {
        var wrap = document.createElement("div");
        wrap.className = "chat-msg assistant";
        var bubble = document.createElement("div");
        bubble.className = "chat-bubble";
        if (kind === "audit") {
            var tag = document.createElement("div");
            tag.className = "chat-kind";
            tag.textContent = "审核报告";
            bubble.appendChild(tag);
        }
        var body = document.createElement("div");
        body.className = "result-body chat-body";
        body.innerHTML = renderMarkdown(markdown || "");
        bubble.appendChild(body);
        wrap.appendChild(bubble);
        chatList.appendChild(wrap);
        updateEmpty();
        scrollBottom();
    }

    function showLoading(label) {
        loadingEl = document.createElement("div");
        loadingEl.className = "chat-msg assistant";
        var bubble = document.createElement("div");
        bubble.className = "chat-bubble chat-loading";
        bubble.innerHTML = '<span class="busy-glyph-wrap">' + DZTBusy.glyph() + '</span>'
            + '<span class="busy-verb"></span><span class="busy-time"></span>';
        chatBusyStop = DZTBusy.run(bubble.querySelector(".busy-verb"), bubble.querySelector(".busy-time"),
            { verbs: DZTBusy.verbsFor("chat") });
        loadingEl.appendChild(bubble);
        chatList.appendChild(loadingEl);
        updateEmpty();
        scrollBottom();
    }

    function hideLoading() {
        if (chatBusyStop) { chatBusyStop(); chatBusyStop = null; }
        if (loadingEl) { loadingEl.remove(); loadingEl = null; }
    }

    function autosize() {
        homeInput.style.height = "auto";
        homeInput.style.height = Math.min(homeInput.scrollHeight, 160) + "px";
    }

    function fetchThreads() {
        return fetch("/api/assistant/threads")
            .then(function (r) { return r.json(); })
            .catch(function () { return null; });
    }

    function renderThreads(threads) {
        chatThreads.innerHTML = "";
        if (!threads || !threads.length) {
            var hint = document.createElement("p");
            hint.className = "thread-empty-hint";
            hint.textContent = "还没有历史对话";
            chatThreads.appendChild(hint);
            return;
        }
        threads.forEach(function (t) {
            var item = document.createElement("button");
            item.type = "button";
            item.className = "thread-item" + (t.id === currentThreadId ? " active" : "");
            var title = document.createElement("div");
            title.className = "thread-title";
            title.textContent = t.title || "新对话";
            var meta = document.createElement("div");
            meta.className = "thread-meta";
            meta.textContent = (t.msg_count || 0) + " 条 · " + (t.updated_at || "").slice(5, 16);
            item.appendChild(title);
            item.appendChild(meta);
            item.addEventListener("click", function () { openThread(t.id); });
            chatThreads.appendChild(item);
        });
    }

    function loadThreads() {
        fetchThreads().then(function (data) {
            if (data && data.success) renderThreads(data.threads || []);
        });
    }

    function clearBubbles() {
        chatList.innerHTML = "";
        updateEmpty();
    }

    function openThread(id) {
        if (sending) return;
        currentThreadId = id;
        clearBubbles();
        loadThreads();
        fetch("/api/assistant/history?thread_id=" + id)
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (!data.success || currentThreadId !== id) return;
                (data.messages || []).forEach(function (m) {
                    if (m.kind === "summary") return; // 摘要只做上下文，不在界面显示
                    if (m.role === "user") addUserBubble(m.content);
                    else addAssistantBubble(m.content, m.kind);
                });
                scrollBottom();
            })
            .catch(function () {});
    }

    function newChat() {
        if (sending) return;
        currentThreadId = null;
        clearBubbles();
        loadThreads();
        homeInput.focus();
    }

    function send() {
        if (sending) return;
        var text = homeInput.value.trim();
        if (!text) return;
        sending = true;
        addUserBubble(text);
        homeInput.value = "";
        autosize();
        showLoading("正在思考…");

        var payload = { message: text };
        if (currentThreadId !== null) payload.thread_id = currentThreadId;

        fetch("/api/assistant", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                hideLoading();
                sending = false;
                if (data.success) {
                    currentThreadId = data.thread_id;
                    addAssistantBubble(data.reply, data.kind);
                    loadThreads();
                } else {
                    addAssistantBubble("出错了：" + (data.error || "未知错误"), "chat");
                }
            })
            .catch(function () {
                hideLoading();
                sending = false;
                addAssistantBubble("网络错误，请重试。", "chat");
            });
    }

    homeForm.addEventListener("submit", function (e) {
        e.preventDefault();
        send();
    });

    homeInput.addEventListener("keydown", function (e) {
        if (e.key !== "Enter" || e.shiftKey) return;
        if (e.isComposing || e.keyCode === 229) return; // 中文输入法组字中，不发送
        e.preventDefault();
        send();
    });

    homeInput.addEventListener("input", autosize);

    btnChatNew.addEventListener("click", newChat);

    btnChatClear.addEventListener("click", function () {
        if (currentThreadId === null) {
            // 新会话还没落库时按钮点了没反应，用户会以为坏了：至少清掉界面上的气泡
            if (!chatList.children.length) return;
            if (!confirm("确定清空当前对话？")) return;
            clearBubbles();
            return;
        }
        if (!confirm("确定清空当前对话？")) return;
        fetch("/api/assistant/history?thread_id=" + currentThreadId, { method: "DELETE" })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data && data.success) {
                    currentThreadId = null;
                    clearBubbles();
                    loadThreads();
                } else {
                    alert("清空失败：" + ((data && data.error) || "未知错误"));
                }
            })
            .catch(function () { alert("清空失败，请重试"); });
    });

    updateEmpty(); // 初始空状态：把输入条摆进中央

    // 初始化：只把左侧会话列表拉出来，不自动打开最近一条。
    // 每次进工作台都该停在打招呼的空状态，想接着聊再点左边那一列。
    loadThreads();
})();

// ===== 信用证体检 Tab（审证）=====
(function () {
    var lcReviewInput = document.getElementById("lcReviewInput");
    if (!lcReviewInput) return;

    var lcReviewFile = document.getElementById("lcReviewFile");
    var fileInfo = document.getElementById("lcReviewFileInfo");
    var fileNameEl = document.getElementById("lcReviewFileName");
    var resultSectionEl = document.getElementById("lcReviewResult");
    var resultBodyEl = document.getElementById("lcReviewBody");
    var rawTextEl = document.getElementById("lcReviewRawText");
    var deadlineBox = document.getElementById("lcDeadlineResult");
    var dlShipment = document.getElementById("dlShipment");
    var dlExpiry = document.getElementById("dlExpiry");
    var dlDays = document.getElementById("dlDays");
    var dlMailing = document.getElementById("dlMailing");
    var btnRun = document.getElementById("btnLcReviewRun");

    // 抽出字段的键名 → 审单表单里那 14 个 input 的 id
    var _LC_FIELD_DOM_ID = {
        lc_amount: "lcAmount", lc_expiry: "lcExpiry", lc_applicant: "lcApplicant",
        lc_partial: "lcPartial", lc_transship: "lcTransship",
        lc_shipment_date: "lcShipmentDate", lc_freight_terms: "lcFreightTerms",
        lc_originals: "lcOriginals", lc_consignee: "lcConsignee",
        lc_description: "lcDescription", lc_measurement: "lcMeasurement",
        lc_base_qty: "lcBaseQty", lc_tolerance_pct: "lcTolerancePct",
        lc_tolerance_clause: "lcToleranceClause"
    };

    var _submitting = false;
    var _lcText = "";      // 体检用的信用证原文，回填/导出时复用
    var _reviewText = "";  // 体检报告全文

    // ---- 交单时间表（本地算，不花 AI 额度）----
    var _dlTimer = null;

    function deadlinePayload() {
        var p = {
            shipment_date: dlShipment.value.trim(),
            expiry: dlExpiry.value.trim(),
            days: parseInt(dlDays.value, 10) || 21,
            mailing_days: parseInt(dlMailing.value, 10) || 0
        };
        if (!p.shipment_date && !p.expiry) return null;
        return p;
    }

    function scheduleDeadline() {
        clearTimeout(_dlTimer);
        _dlTimer = setTimeout(fetchDeadline, 350);
    }

    function fetchDeadline() {
        var payload = deadlinePayload();
        if (!payload) {
            deadlineBox.innerHTML =
                '<p class="lc-deadline-empty">填写装运日或效期，自动算出最迟交单日</p>';
            return;
        }
        fetch("/api/lc-deadline", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                renderDeadline(d);
                // 后端认得更多日期写法（260915、15 SEP 2026），把归一化结果写回输入框
                if (d && d.ok) {
                    if (d.shipment_date) dlShipment.value = d.shipment_date;
                    if (d.expiry) dlExpiry.value = d.expiry;
                }
            })
            .catch(function () {
                deadlineBox.innerHTML =
                    '<p class="lc-deadline-empty">时间计算失败，请检查日期格式</p>';
            });
    }

    function renderDeadline(d) {
        if (!d || !d.ok) {
            deadlineBox.innerHTML = '<p class="lc-deadline-empty">' +
                escapeHtml((d && d.error) || "填写装运日或效期，自动算出最迟交单日") + "</p>";
            return;
        }
        var leftCls = d.days_left < 0 ? "is-over" : (d.days_left <= 7 ? "is-tight" : "");
        var leftText = d.days_left < 0
            ? "已过期 " + (-d.days_left) + " 天"
            : "还剩 " + d.days_left + " 天";

        var html = '<div class="lc-dl-headline">' +
            '<div class="lc-dl-main">' +
            '<span class="lc-dl-label">最迟交单日</span>' +
            '<span class="lc-dl-date">' + escapeHtml(d.deadline) + '</span>' +
            '</div>' +
            '<div class="lc-dl-side">' +
            '<span class="lc-dl-left ' + leftCls + '">' + escapeHtml(leftText) + '</span>' +
            '<span class="lc-dl-src">依据：' + escapeHtml(d.deadline_source) + '</span>' +
            '</div></div>';

        html += '<div class="lc-dl-schedule">';
        (d.schedule || []).forEach(function (s) {
            html += '<div class="lc-dl-item is-' + escapeHtml(s.tone) + '">' +
                '<span class="lc-dl-item-label">' + escapeHtml(s.label) + '</span>' +
                '<span class="lc-dl-item-date">' + escapeHtml(s.date) + '</span>' +
                '<span class="lc-dl-item-note">' + escapeHtml(s.note) + '</span>' +
                '</div>';
        });
        html += '</div>';

        if (d.warnings && d.warnings.length) {
            html += '<ul class="lc-dl-warn">';
            d.warnings.forEach(function (w) {
                html += '<li>' + escapeHtml(w) + '</li>';
            });
            html += '</ul>';
        }
        deadlineBox.innerHTML = html;
    }

    [dlDays, dlMailing].forEach(function (el) {
        el.addEventListener("input", scheduleDeadline);
        el.addEventListener("change", scheduleDeadline);
    });

    // 粘贴信用证时，顺手把两个日期抓出来预填，省得再手敲一遍。
    //
    // 这两个字段是不是"自动抓来的"要记着：换一张信用证来体检时，旧日期必须能被
    // 新抓到的覆盖。否则框里留着上一张证的效期，它又会作为"系统已计算的交单时间"
    // 注入提示词，把新证的真实效期盖掉——模型只能凭空多出一条"双到期"。
    // 用户手敲的值则不覆盖，那是他自己的判断。
    var _dlAutoFilled = { dlShipment: false, dlExpiry: false };
    var _prefillTimer = null;

    [dlShipment, dlExpiry].forEach(function (el) {
        el.addEventListener("input", function () {
            _dlAutoFilled[el.id] = false;  // 手填了，之后不再被自动覆盖
            scheduleDeadline();
        });
        el.addEventListener("change", scheduleDeadline);
    });

    function setAutoDate(el, value) {
        if (el.value.trim() && !_dlAutoFilled[el.id]) return false;
        el.value = value;
        _dlAutoFilled[el.id] = true;
        return true;
    }

    function prefillDates() {
        var raw = lcReviewInput.value;
        if (!raw) {
            // 清空输入时，把自动抓来的日期也清掉，别留下上一张证的痕迹
            ["dlShipment", "dlExpiry"].forEach(function (id) {
                if (_dlAutoFilled[id]) {
                    document.getElementById(id).value = "";
                    _dlAutoFilled[id] = false;
                }
            });
            scheduleDeadline();
            return;
        }
        var dateRe = "([0-9]{4}[-/.][0-9]{1,2}[-/.][0-9]{1,2}|[0-9]{8}|[0-9]{6})";
        // MT700 的 44C 写的是 "LATEST DATE OF SHIPMENT"，不是 "LATEST SHIPMENT DATE"
        var m = raw.match(new RegExp(
            "(?:LATEST\\s+DATE\\s+OF\\s+SHIPMENT|LATEST\\s+SHIPMENT(?:\\s+DATE)?|" +
            "SHIPMENT\\s+DATE|LATEST\\s+DATE|最迟装运日|最迟装船日)\\s*[:：]?\\s*" + dateRe, "i"));
        if (m) setAutoDate(dlShipment, m[1]);
        var m2 = raw.match(new RegExp(
            "(?:EXPIRY(?:\\s+DATE)?|VALID(?:ITY)?\\s+(?:UNTIL|THRU|TO)|" +
            "LATEST\\s+DATE\\s+OF\\s+PRESENTATION|效期|最迟交单日)\\s*[:：]?\\s*" + dateRe, "i"));
        if (m2) setAutoDate(dlExpiry, m2[1]);
        scheduleDeadline();
    }

    lcReviewInput.addEventListener("input", function () {
        clearTimeout(_prefillTimer);
        _prefillTimer = setTimeout(prefillDates, 500);
    });

    // ---- 上传 LC 文件 ----
    document.getElementById("btnLcReviewUpload").addEventListener("click", function () {
        lcReviewFile.click();
    });

    lcReviewFile.addEventListener("change", function () {
        if (lcReviewFile.files && lcReviewFile.files[0]) {
            fileNameEl.textContent = lcReviewFile.files[0].name;
            fileInfo.style.display = "flex";
        }
    });

    document.getElementById("btnLcReviewFileClear").addEventListener("click", function () {
        lcReviewFile.value = "";
        fileInfo.style.display = "none";
        fileNameEl.textContent = "";
    });

    document.getElementById("btnLcReviewClear").addEventListener("click", function () {
        lcReviewInput.value = "";
        lcReviewFile.value = "";
        fileInfo.style.display = "none";
        resultSectionEl.style.display = "none";
        _lcText = "";
        _reviewText = "";
        // 日期也一起清掉：这是"换一张信用证重新来过"的入口，
        // 留着上一张证的日期会污染下一次体检
        ["dlShipment", "dlExpiry"].forEach(function (id) {
            document.getElementById(id).value = "";
            _dlAutoFilled[id] = false;
        });
        scheduleDeadline();
    });

    // ---- 提交体检 ----
    function startLoading(hasFile) {
        showLoading(); // 会顺带 hideAllTabs()，完成后要靠 lcShowTab() 把自己切回来
        stepOcr.className = hasFile ? "step active" : "step done";
        stepOcr.querySelector(".step-label").textContent = hasFile ? "识别信用证" : "跳过识别";
        stepAi.className = "step active";
        stepAi.querySelector(".step-label").textContent = "审证分析中";
        loadingText.textContent = hasFile ? "正在识别并分析信用证…" : "正在分析信用证…";
    }

    function finishLoading() {
        stepOcr.className = "step done";
        stepAi.className = "step done";
        loadingSection.style.display = "none";
    }

    function lcShowTab() {
        tabs.forEach(function (t) {
            t.classList.toggle("active", t.dataset.tab === "lcreview");
        });
        tabContents.forEach(function (c) {
            c.classList.toggle("active", c.id === "tabLcreview");
        });
        activeMode = "lcreview";
        hideAllShared();
        restoreCurrentTabUI();
    }

    btnRun.addEventListener("click", function () {
        if (_submitting) return;
        var text = lcReviewInput.value.trim();
        var file = lcReviewFile.files && lcReviewFile.files[0];
        if (!text && !file) {
            alert("请粘贴信用证原文，或上传 LC 文件");
            return;
        }
        _submitting = true;
        startLoading(!!file);

        var req;
        if (file) {
            var fd = new FormData();
            fd.append("file", file);
            var dp = deadlinePayload();
            if (dp) fd.append("deadline", JSON.stringify(dp));
            req = fetch("/api/lc-review", { method: "POST", body: fd });
        } else {
            req = fetch("/api/lc-review", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ text: text, deadline: deadlinePayload() })
            });
        }

        req.then(function (r) {
            return r.json().then(function (d) { return { ok: r.ok, data: d }; });
        })
            .then(function (res) {
                finishLoading();
                if (!res.ok || !res.data.success) {
                    throw new Error((res.data && res.data.error) || "体检失败");
                }
                showReview(res.data);
            })
            .catch(function (err) {
                finishLoading();
                lcShowTab();
                alert("体检失败：" + err.message);
            })
            .then(function () { _submitting = false; });
    });

    function showReview(d) {
        _lcText = d.lc_text || "";
        _reviewText = d.audit_result || "";
        rawTextEl.textContent = _lcText;
        resultBodyEl.innerHTML = renderMarkdown(_reviewText);
        resultSectionEl.style.display = "block";
        lcShowTab();
        resultSectionEl.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    // ---- 一键回填到审单表单 ----
    document.getElementById("btnLcFillForm").addEventListener("click", function () {
        if (!_lcText) return;
        var btn = this;
        var oldText = btn.textContent;
        btn.disabled = true;
        btn.textContent = "抽取中...";

        fetch("/api/lc-fields", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text: _lcText })
        })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (!d.success) throw new Error(d.error || "抽取失败");
                var n = applyLcFields(d.fields || {});
                if (!n) {
                    alert("没能从这段信用证里认出可填的字段，请手动填写。");
                    return;
                }
                // 切到「粘贴文字」页并展开信用证卡片 —— 回填的字段在那里
                var textTab = document.querySelector('.tab[data-tab="text"]');
                if (textTab) textTab.click();
                lcExpanded = true;
                lcBody.style.display = "block";
                lcChevron.style.transform = "rotate(90deg)";
                updateLcHeaderBadge();
                alert("已填入 " + n + " 个字段，请核对后用于审单。");
            })
            .catch(function (err) {
                alert("抽取失败：" + err.message);
            })
            .then(function () {
                btn.disabled = false;
                btn.textContent = oldText;
            });
    });

    function applyLcFields(fields) {
        var n = 0;
        Object.keys(fields).forEach(function (key) {
            var domId = _LC_FIELD_DOM_ID[key];
            if (!domId) return;
            var el = document.getElementById(domId);
            if (!el) return;
            var val = String(fields[key]).trim();
            if (!val) return;
            if (el.tagName === "SELECT") {
                var upper = val.toUpperCase();
                upper = _LC_SELECT_ALIASES[upper] || upper;
                for (var i = 0; i < el.options.length; i++) {
                    var optVal = el.options[i].value.toUpperCase();
                    var optTxt = el.options[i].text.toUpperCase();
                    if ((optVal && optVal === upper) || (optVal && optTxt.indexOf(upper) !== -1)) {
                        el.value = el.options[i].value;
                        n++;
                        break;
                    }
                }
            } else {
                el.value = val;
                n++;
            }
        });
        return n;
    }

    // ---- 导出体检报告 ----
    document.getElementById("btnLcReviewPdf").addEventListener("click", function () {
        if (_reviewText) exportPdf(_reviewText, "信用证体检报告", "信用证体检报告");
    });
})();


// ===== 设置页：导航选中样式 =====
// 两档（色块 / 竖条）都符合视觉规范，做成可切换而不是直接改，用户自己挑。
// 选择存 localStorage；真正生效靠 <html data-nav-style>，
// base.html 的 <head> 里已经在首次绘制前设好了，所以刷新不会闪。
(function () {
    var KEY = "dzt_nav_style";
    var switchBox = document.getElementById("navStyleSwitch");
    if (!switchBox) return;
    var btns = switchBox.querySelectorAll(".seg-btn");

    function current() {
        try {
            return localStorage.getItem(KEY) === "bar" ? "bar" : "block";
        } catch (e) {
            return "block";  // 隐私模式下 localStorage 会抛，用默认档
        }
    }

    function apply(style) {
        if (style === "bar") {
            document.documentElement.setAttribute("data-nav-style", "bar");
        } else {
            document.documentElement.removeAttribute("data-nav-style");
        }
        btns.forEach(function (b) {
            var on = b.dataset.style === style;
            b.classList.toggle("active", on);
            b.setAttribute("aria-pressed", on ? "true" : "false");
        });
    }

    btns.forEach(function (b) {
        b.addEventListener("click", function () {
            var style = b.dataset.style;
            try {
                localStorage.setItem(KEY, style);
            } catch (e) {
                // 存不下就只当次生效，不报错
            }
            apply(style);
        });
    });

    apply(current());
})();

// ===== 审核规则页：按关键词筛选 =====
(function () {
    var input = document.getElementById("rulesFilter");
    if (!input) return;
    var items = Array.prototype.slice.call(document.querySelectorAll("#tabRules .rule-item"));
    var groups = Array.prototype.slice.call(document.querySelectorAll("#tabRules .rules-group"));
    var empty = document.getElementById("rulesEmpty");
    var count = document.getElementById("rulesCount");
    if (!items.length) return;

    function update() {
        var q = input.value.trim().toLowerCase();
        var shown = 0;
        items.forEach(function (el) {
            var hit = !q || (el.dataset.ruleText || "").toLowerCase().indexOf(q) !== -1;
            el.style.display = hit ? "" : "none";
            if (hit) shown++;
        });
        // 整组都被筛掉就把分类标题也收起来，否则满页只剩一堆空标题
        groups.forEach(function (g) {
            var anyVisible = Array.prototype.some.call(
                g.querySelectorAll(".rule-item"),
                function (el) { return el.style.display !== "none"; }
            );
            g.style.display = anyVisible ? "" : "none";
        });
        count.textContent = q
            ? "匹配 " + shown + " / " + items.length + " 条"
            : "共 " + items.length + " 条";
        if (empty) empty.style.display = shown ? "none" : "";
    }

    input.addEventListener("input", update);
    update();
})();


// ===== 实训练习 Tab（仅教育版）=====
// 标准答案不在前端：列表和详情接口都不返回它，判卷在服务端做。
// 这里只管收集勾选、发请求、把结果画出来。
(function () {
    var root = document.getElementById("tabPractice");
    if (!root) return;   // 标准版没有这个页签，直接跳过（app.js 不过 Jinja，只能靠这个守卫）

    var viewList = document.getElementById("practiceListView");
    var viewAnswer = document.getElementById("practiceAnswerView");
    var viewResult = document.getElementById("practiceResultView");
    var viewCreate = document.getElementById("practiceCreateView");

    var caseListEl = document.getElementById("practiceCaseList");
    var emptyEl = document.getElementById("practiceEmpty");
    var titleEl = document.getElementById("practiceCaseTitle");
    var hintEl = document.getElementById("practiceCaseHint");
    var docEl = document.getElementById("practiceDocText");
    var countEl = document.getElementById("practiceAnswerCount");

    var pickerEl = document.getElementById("practiceRulePicker");
    var answerPickerEl = document.getElementById("practiceAnswerPicker");
    var filterEl = document.getElementById("practiceFilter");
    var filterCountEl = document.getElementById("practiceFilterCount");
    var ruleEmptyEl = document.getElementById("practiceRuleEmpty");
    var submitBtn = document.getElementById("btnPracticeSubmit");

    var current = null;        // 当前打开的题目
    var _submitting = false;

    function show(which) {
        viewList.style.display = which === "list" ? "" : "none";
        viewAnswer.style.display = which === "answer" ? "" : "none";
        viewResult.style.display = which === "result" ? "" : "none";
        viewCreate.style.display = which === "create" ? "" : "none";
        window.scrollTo(0, 0);
    }

    function pickedIn(container) {
        var out = [];
        container.querySelectorAll(".practice-check").forEach(function (c) {
            if (c.checked) out.push(c.value);
        });
        return out;
    }

    function clearPicked(container) {
        container.querySelectorAll(".practice-check").forEach(function (c) { c.checked = false; });
    }

    // 只保留本题用得上的规则：没给信用证就收起 lc 类，单份单证就收起 pair 类。
    // 口径与后端 rule_available() 一致 —— 学生看到的就是审核引擎能查的那些。
    function applyScope(container, hasLc, docCount) {
        container.querySelectorAll(".practice-pick").forEach(function (el) {
            var scope = el.dataset.scope || "";
            var hide = (!hasLc && scope.indexOf("lc") !== -1)
                    || (docCount < 2 && scope.indexOf("pair") !== -1);
            el.dataset.scopeHidden = hide ? "1" : "";
            el.querySelectorAll("[data-scope-when]").forEach(function (tag) {
                var need = tag.dataset.scopeWhen;
                var off = (need === "lc" && !hasLc) || (need === "pair" && docCount < 2);
                tag.style.display = off ? "none" : "";
            });
        });
    }

    // ---------- 题目列表 ----------
    function loadCases() {
        fetch("/api/practice/cases")
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (!data.success) throw new Error(data.error || "读取失败");
                renderCases(data.items || []);
            })
            .catch(function (err) {
                caseListEl.innerHTML = '<p class="practice-empty">读取题目失败：'
                    + escapeHtml(err.message) + "</p>";
            });
    }

    function renderCases(items) {
        caseListEl.innerHTML = "";
        emptyEl.style.display = items.length ? "none" : "";
        items.forEach(function (c) {
            var card = document.createElement("div");
            card.className = "practice-case";
            var score;
            if (c.attempts) {
                score = '<span class="practice-case-score">做过 ' + c.attempts + " 次"
                      + (c.best_score !== null ? " · 最高 " + c.best_score + " 分" : "")
                      + (c.last_score !== null ? " · 最近 " + c.last_score + " 分" : "")
                      + "</span>";
            } else {
                score = '<span class="practice-case-score practice-case-new">未作答</span>';
            }
            card.innerHTML =
                '<div class="practice-case-main">' +
                '<span class="practice-case-title">' + escapeHtml(c.title) + "</span>" +
                '<span class="practice-case-meta">共 ' + c.answer_count + " 处问题 · "
                + escapeHtml(c.doc_count > 1 ? "多单证" : "单份单证") + "</span>" +
                score +
                "</div>" +
                '<div class="practice-case-actions">' +
                '<button type="button" class="btn btn-primary btn-sm practice-start">开始作答</button>' +
                (c.is_builtin ? "" :
                    '<button type="button" class="btn btn-danger btn-sm practice-del">删除</button>') +
                "</div>";
            card.querySelector(".practice-start").addEventListener("click", function () {
                openCase(c.id);
            });
            var del = card.querySelector(".practice-del");
            if (del) {
                del.addEventListener("click", function () {
                    if (!confirm("确定删除这道题？作答记录也会一并删除。")) return;
                    fetch("/api/practice/cases/" + c.id, { method: "DELETE" })
                        .then(function (r) { return r.json(); })
                        .then(function (d) {
                            if (!d.success) throw new Error(d.error || "删除失败");
                            loadCases();
                        })
                        .catch(function (e) { alert(e.message); });
                });
            }
            caseListEl.appendChild(card);
        });
    }

    // ---------- 作答 ----------
    function openCase(id) {
        fetch("/api/practice/cases/" + id)
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (!data.success) throw new Error(data.error || "打开失败");
                current = data.case;
                titleEl.textContent = current.title;
                hintEl.textContent = current.hint || "";
                hintEl.style.display = current.hint ? "" : "none";
                docEl.textContent = current.doc_text;
                countEl.textContent = "本题共 " + current.answer_count + " 处问题";
                clearPicked(pickerEl);
                applyScope(pickerEl, !!current.lc_text, current.doc_count);
                if (filterEl) filterEl.value = "";
                filterPicker();
                show("answer");
            })
            .catch(function (err) { alert(err.message); });
    }

    function filterPicker() {
        if (!filterEl || !pickerEl) return;
        var q = filterEl.value.trim().toLowerCase();
        var shown = 0;
        pickerEl.querySelectorAll(".practice-pick").forEach(function (el) {
            // 先过范围：本题用不上的规则，不因为关键词命中就冒出来
            var hit = !el.dataset.scopeHidden
                   && (!q || (el.dataset.ruleText || "").toLowerCase().indexOf(q) !== -1);
            el.style.display = hit ? "" : "none";
            if (hit) shown++;
        });
        // 整组都被筛掉就把分类标题也收起来，否则满页只剩空标题
        pickerEl.querySelectorAll(".rules-group").forEach(function (g) {
            var any = Array.prototype.some.call(
                g.querySelectorAll(".practice-pick"),
                function (el) { return el.style.display !== "none"; });
            g.style.display = any ? "" : "none";
        });
        if (filterCountEl) {
            filterCountEl.textContent = q ? "匹配 " + shown + " 条" : "共 " + shown + " 条可选";
        }
        if (ruleEmptyEl) ruleEmptyEl.style.display = shown ? "none" : "";
    }

    if (filterEl) filterEl.addEventListener("input", filterPicker);

    submitBtn.addEventListener("click", function () {
        if (_submitting || !current) return;
        var picked = pickedIn(pickerEl);
        if (!picked.length && !confirm("你一条都没勾。确定按「未发现问题」提交吗？")) return;
        _submitting = true;
        submitBtn.disabled = true;
        submitBtn.textContent = "判卷中…";

        fetch("/api/practice/grade", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ case_id: current.id, picked: picked })
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (!data.success) throw new Error(data.error || "判卷失败");
                renderResult(data);
                show("result");
            })
            .catch(function (err) { alert("判卷失败：" + err.message); })
            .then(function () {       // 放在 catch 之后 = finally，成败都会解锁
                _submitting = false;
                submitBtn.disabled = false;
                submitBtn.textContent = "提交作答";
            });
    });

    // ---------- 判卷结果 ----------
    function tallyBlock(label, ids, cls) {
        var chips = ids.map(function (id) {
            return '<button type="button" class="practice-chip practice-chip-' + cls
                 + '" data-rule="' + escapeHtml(id) + '">' + escapeHtml(id) + "</button>";
        }).join("");
        return '<div class="practice-tally-col"><p class="practice-tally-label practice-tally-'
             + cls + '">' + label + " " + ids.length
             + '</p><div class="practice-chips">'
             + (chips || '<span class="practice-tally-none">—</span>') + "</div></div>";
    }

    function renderResult(d) {
        document.getElementById("practiceScore").textContent = d.score;
        var words = d.score >= 90 ? "很好" : d.score >= 60 ? "基本掌握" : "还需要再看一遍";
        document.getElementById("practiceScoreLine").textContent =
            "找对 " + d.hit.length + " 处 · 漏了 " + d.missed.length + " 处 · 多报 "
            + d.wrong.length + " 处（应找 " + d.answer_count + " 处）—— " + words;

        var tally = document.getElementById("practiceTally");
        tally.innerHTML =
            tallyBlock("找对", d.hit, "ok") +
            tallyBlock("漏报", d.missed, "miss") +
            tallyBlock("多报", d.wrong, "wrong");
        tally.querySelectorAll("[data-rule]").forEach(function (chip) {
            chip.addEventListener("click", function () {
                var box = document.getElementById("explain-" + this.dataset.rule);
                if (box) box.scrollIntoView({ behavior: "smooth", block: "center" });
            });
        });

        var box = document.getElementById("practiceExplain");
        box.innerHTML = "";
        var order = d.missed.concat(d.hit, d.wrong);
        if (!order.length) {
            box.innerHTML = '<p class="practice-empty">这道题一处问题都没有，你也一条没勾——判断正确。</p>';
            return;
        }
        order.forEach(function (rid) {
            var r = d.rules[rid];
            if (!r) return;
            var kind = d.missed.indexOf(rid) !== -1 ? "漏"
                     : d.wrong.indexOf(rid) !== -1 ? "多" : "对";
            var cls = kind === "漏" ? "miss" : kind === "多" ? "wrong" : "ok";
            var div = document.createElement("div");
            div.className = "practice-explain-item";
            div.id = "explain-" + rid;
            div.innerHTML =
                '<div class="practice-explain-head">' +
                '<span class="practice-verdict practice-verdict-' + cls + '">' + kind + "</span>" +
                '<span class="rpt-tag rpt-rule">' + escapeHtml(rid) + "</span>" +
                '<span class="rule-name">' + escapeHtml(r.name) + "</span>" +
                '<span class="rpt-tag rpt-sev rpt-sev-' + escapeHtml(r.severity) + '">'
                + escapeHtml(r.severity_cn || r.severity) + "</span>" +
                '<span class="rule-scope">' + escapeHtml(r.category) + "</span>" +
                "</div>" +
                '<p class="rule-line"><span class="rule-label">依据</span>' + escapeHtml(r.basis) + "</p>" +
                '<p class="rule-line"><span class="rule-label">查</span>' + escapeHtml(r.check) + "</p>" +
                '<p class="rule-line"><span class="rule-label">改</span>' + escapeHtml(r.fix) + "</p>";
            box.appendChild(div);
        });
    }

    // ---------- 出题 ----------
    document.getElementById("btnPracticeNew").addEventListener("click", function () {
        document.getElementById("practiceNewTitle").value = "";
        document.getElementById("practiceNewHint").value = "";
        document.getElementById("practiceNewDoc").value = "";
        clearPicked(answerPickerEl);
        applyScope(answerPickerEl, false, 1);
        document.getElementById("practiceDraftNote").textContent = "勾选本题的正确答案，可随时增删";
        show("create");
    });

    document.getElementById("btnPracticeCreateCancel").addEventListener("click", function () {
        show("list");
    });

    document.getElementById("btnPracticeDraft").addEventListener("click", function () {
        var doc = document.getElementById("practiceNewDoc").value.trim();
        if (!doc) { alert("请先粘贴单据原文"); return; }
        var btn = this;
        btn.disabled = true;
        btn.textContent = "审核中…";
        fetch("/api/practice/draft", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ doc_text: doc })
        })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (!d.success) throw new Error(d.error || "生成失败");
                clearPicked(answerPickerEl);
                (d.suggested_rules || []).forEach(function (rid) {
                    var box = answerPickerEl.querySelector('.practice-check[value="' + rid + '"]');
                    if (box) box.checked = true;
                });
                document.getElementById("practiceDraftNote").textContent =
                    "初稿勾中 " + (d.suggested_rules || []).length
                    + " 条 —— 模型会漏报也会误报，请对着「审核规则」页核对后再保存";
            })
            .catch(function (err) { alert("生成失败：" + err.message); })
            .then(function () {
                btn.disabled = false;
                btn.textContent = "生成答案初稿";
            });
    });

    document.getElementById("btnPracticeSave").addEventListener("click", function () {
        var title = document.getElementById("practiceNewTitle").value.trim();
        var doc = document.getElementById("practiceNewDoc").value.trim();
        if (!title) { alert("请填写题目标题"); return; }
        if (!doc) { alert("请粘贴单据原文"); return; }
        var rules = pickedIn(answerPickerEl);
        var btn = this;
        btn.disabled = true;
        fetch("/api/practice/cases", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                title: title,
                doc_text: doc,
                hint: document.getElementById("practiceNewHint").value.trim(),
                answer_rules: rules
            })
        })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (!d.success) throw new Error(d.error || "保存失败");
                show("list");
                loadCases();
            })
            .catch(function (err) { alert("保存失败：" + err.message); })
            .then(function () { btn.disabled = false; });
    });

    // ---------- 返回 / 重做 ----------
    document.getElementById("btnPracticeBack").addEventListener("click", function () {
        show("list");
        loadCases();
    });
    document.getElementById("btnPracticeResultBack").addEventListener("click", function () {
        show("list");
        loadCases();
    });
    document.getElementById("btnPracticeRetry").addEventListener("click", function () {
        clearPicked(pickerEl);
        show("answer");
    });
    document.getElementById("btnPracticeClear").addEventListener("click", function () {
        clearPicked(pickerEl);
    });

    // 切到本页签时刷新列表。
    // 注意别把 loadCases 直接当 handler —— 事件对象会被当参数传进去。
    tabs.forEach(function (t) {
        if (t.dataset.tab === "practice") {
            t.addEventListener("click", function () {
                if (viewList.style.display !== "none") loadCases();
            });
        }
    });

    loadCases();
})();

// ===== 首页工作台：统一投放区 + 快捷入口 + 最近审核 =====
(function () {
    var drop = document.getElementById("homeDrop");
    var fileInput = document.getElementById("homeFile");
    var links = document.getElementById("homeLinks");
    var recent = document.getElementById("homeRecent");
    var recentList = document.getElementById("homeRecentList");
    if (!drop || !links) return;

    // 快捷入口只是侧栏页签的快捷方式：点哪个就等于点侧栏里对应那一项，
    // 这样页签切换、恢复上次状态等逻辑都不用再写一遍
    function goTab(name) {
        var tab = document.querySelector('.tab[data-tab="' + name + '"]');
        if (tab) tab.click();
    }
    document.getElementById("homeRecent").addEventListener("click", function (e) {
        var btn = e.target.closest("[data-go]");
        if (btn) goTab(btn.dataset.go);
    });
    links.addEventListener("click", function (e) {
        var btn = e.target.closest("[data-go]");
        if (btn) goTab(btn.dataset.go);
    });

    // 一个投放区收图片和 PDF：按类型分流到原来的两个上传页，复用它们的校验与预览。
    // 先切页签（会复位上传区），再交文件，顺序不能反。
    function route(file) {
        if (!file) return;
        var isPdf = file.type === "application/pdf" || /\.pdf$/i.test(file.name);
        if (isPdf) { goTab("pdf"); handlePdfFile(file); }
        else { goTab("image"); handleImageFile(file); }
    }
    drop.addEventListener("click", function () { fileInput.click(); });
    drop.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInput.click(); }
    });
    fileInput.addEventListener("change", function () { route(fileInput.files[0]); fileInput.value = ""; });
    drop.addEventListener("dragover", function (e) { e.preventDefault(); drop.classList.add("drag-over"); });
    drop.addEventListener("dragleave", function () { drop.classList.remove("drag-over"); });
    drop.addEventListener("drop", function (e) {
        e.preventDefault();
        drop.classList.remove("drag-over");
        route(e.dataTransfer.files[0]);
    });

    // 没有单据的人（评委、新用户）最需要这个：一键把样例填进「粘贴文字」
    var sampleBtn = document.getElementById("btnTrySample");
    if (sampleBtn) {
        sampleBtn.addEventListener("click", function () {
            goTab("text");
            var item = window.TEACHING_CASES && window.TEACHING_CASES[0];
            if (item && textInput) textInput.value = item.text;
            var auditBtn = document.getElementById("btnAuditText");
            if (auditBtn) auditBtn.focus();
        });
    }

    // 最近审核：直接读真实记录。没有记录就整块不显示，不放占位假数据。
    function loadRecent() {
        if (!recent || !recentList) return;
        fetch("/api/history?per_page=5")
            .then(function (r) { return r.json(); })
            .then(function (d) {
                var items = (d && d.items) || [];
                if (!items.length) { recent.hidden = true; return; }
                recentList.innerHTML = items.map(function (rec) {
                    var st = rec.verdict === "fail"
                        ? '<span class="hr-st is-fail">' + (rec.issue_count ? rec.issue_count + " 处问题" : "需修改") + "</span>"
                        : rec.verdict === "pass"
                            ? '<span class="hr-st is-pass">通过</span>'
                            : '<span class="hr-st is-none">' + (rec.input_type === "lc" ? "信用证体检" : "记录") + "</span>";
                    var title = rec.doc_type || (rec.input_type === "lc" ? "信用证体检" : "审核记录");
                    var time = String(rec.created_at || "").replace(/^\d{4}-/, "").replace(/:\d{2}$/, "");
                    return '<li class="hr-item" tabindex="0" data-id="' + rec.id + '">' + st +
                        '<span class="hr-title">' + escapeHtml(title) +
                        (rec.ref ? '<span class="hr-ref">' + escapeHtml(rec.ref) + "</span>" : "") + "</span>" +
                        '<span class="hr-time">' + escapeHtml(time) + "</span></li>";
                }).join("");
                recent.hidden = false;
            })
            .catch(function () { recent.hidden = true; });
    }
    function openRecord(li) {
        if (!li) return;
        goTab("history");
        showHistoryDetail(parseInt(li.dataset.id, 10));
    }
    recentList.addEventListener("click", function (e) { openRecord(e.target.closest(".hr-item")); });
    recentList.addEventListener("keydown", function (e) {
        if (e.key === "Enter") openRecord(e.target.closest(".hr-item"));
    });
    loadRecent();
})();

// ===== 设置页：配色主题 =====
// 与导航样式同一套机制：选择存 localStorage，<html data-theme> 由 base.html 头部在首次绘制前设好。
// 这里只负责点击切换、同步按钮的选中态。
(function () {
    var KEY = "dzt_theme";
    var box = document.getElementById("themePicker");
    if (!box) return;
    var opts = box.querySelectorAll(".theme-opt");

    function current() {
        try { return localStorage.getItem(KEY) === "warm" ? "warm" : "cool"; }
        catch (e) { return "cool"; }       // 隐私模式下 localStorage 会抛，用默认主题
    }
    function apply(theme) {
        if (theme === "warm") document.documentElement.setAttribute("data-theme", "warm");
        else document.documentElement.removeAttribute("data-theme");
        opts.forEach(function (o) {
            o.setAttribute("aria-pressed", o.dataset.themeValue === theme ? "true" : "false");
        });
    }
    opts.forEach(function (o) {
        o.addEventListener("click", function () {
            var theme = o.dataset.themeValue;
            try { localStorage.setItem(KEY, theme); } catch (e) { /* 存不下就只当次生效 */ }
            apply(theme);
        });
    });
    apply(current());
})();

// ===== 交单方式切换（图片 / PDF / 文字）：侧栏页签的快捷方式 =====
document.addEventListener("click", function (e) {
    var btn = e.target.closest && e.target.closest(".intake-switch [data-go]");
    if (!btn || btn.classList.contains("is-on")) return;
    var tab = document.querySelector('.tab[data-tab="' + btn.dataset.go + '"]');
    if (tab) tab.click();
});


// ===== 首页问候语 + 设置里的「称呼」=====
// 按时段说一句，不猜用户的状态（不写"还在盯单子？"这类）。
// 填了称呼就接在后面："晚上好，小王"。称呼只存 localStorage，不上传。
(function () {
    var KEY = "dzt_name";
    var greetEl = document.getElementById("homeGreeting");
    var nameInput = document.getElementById("userNameInput");

    function getName() {
        try { return (localStorage.getItem(KEY) || "").trim(); } catch (e) { return ""; }
    }
    function timeWord() {
        var h = new Date().getHours();
        if (h >= 5 && h < 11) return "早上好";
        if (h >= 11 && h < 13) return "中午好";
        if (h >= 13 && h < 18) return "下午好";
        if (h >= 18 && h < 23) return "晚上好";
        return "夜深了";
    }
    function render() {
        if (!greetEl) return;
        var name = getName();
        greetEl.textContent = timeWord() + (name ? "，" + name : "");   // textContent：称呼里有尖括号也不会被当 HTML
    }
    render();

    if (nameInput) {
        nameInput.value = getName();
        nameInput.addEventListener("input", function () {
            try { localStorage.setItem(KEY, nameInput.value.trim()); } catch (e) { /* 存不下就只当次生效 */ }
            render();
        });
    }
})();
