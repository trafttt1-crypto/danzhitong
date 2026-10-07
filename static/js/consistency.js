/* 单证一致性图（页签 #tabGraph）。
 *
 * 版式：每份单证是一列"单据"，同一个字段在各列里排在同一行，
 * 相邻两份都有这个字段的，中间连一条线：绿=对得上，黄=近似（疑似拼写差异），红=对不上。
 * 某份单证没抽到的字段显示灰色的"—"，不连线。
 *
 * 后端（services/consistency.py）全程确定性比对，不调用大模型。
 * 这里只负责画：所有文字都走 textContent / setAttribute，不拼 HTML 字符串，
 * 单证原文里有 <script> 之类的东西也只会被当成普通文字显示。
 */
(function () {
    "use strict";

    var root = document.getElementById("tabGraph");
    if (!root) return;

    var slotsEl = document.getElementById("cgSlots");
    var btnRun = document.getElementById("cgRun");
    var btnAdd = document.getElementById("cgAdd");
    var btnSample = document.getElementById("cgSample");
    var btnClear = document.getElementById("cgClear");
    var errEl = document.getElementById("cgError");
    var resultEl = document.getElementById("cgResult");
    var scrollEl = document.getElementById("cgScroll");
    var summaryEl = document.getElementById("cgSummary");
    var issuesEl = document.getElementById("cgIssues");
    var coverageEl = document.getElementById("cgCoverage");

    var MIN_SLOTS = 2, MAX_SLOTS = 5;
    var SVGNS = "http://www.w3.org/2000/svg";

    // 版式常量
    var PAD = 16, COL_W = 200, GAP = 84, HEAD_H = 50, ROW_H = 48;

    var STATUS_TEXT = { ok: "一致", near: "近似", conflict: "不一致", unknown: "未提取" };
    var STATUS_MARK = { ok: "=", near: "≈", conflict: "≠" };

    // ---------- 输入槽 ----------
    function slotCount() { return slotsEl.querySelectorAll(".cg-slot").length; }

    function renumber() {
        Array.prototype.forEach.call(slotsEl.querySelectorAll(".cg-slot"), function (slot, i) {
            slot.querySelector(".cg-slot-name").textContent = "单证 " + (i + 1);
            var rm = slot.querySelector(".cg-slot-remove");
            rm.hidden = slotCount() <= MIN_SLOTS;
        });
        btnAdd.disabled = slotCount() >= MAX_SLOTS;
    }

    function addSlot(text) {
        if (slotCount() >= MAX_SLOTS) return;
        var slot = document.createElement("div");
        slot.className = "cg-slot";

        var head = document.createElement("div");
        head.className = "cg-slot-head";
        var name = document.createElement("span");
        name.className = "cg-slot-name";
        var rm = document.createElement("button");
        rm.type = "button";
        rm.className = "cg-slot-remove";
        rm.textContent = "移除";
        rm.addEventListener("click", function () {
            if (slotCount() <= MIN_SLOTS) return;
            slot.parentNode.removeChild(slot);
            renumber();
        });
        head.appendChild(name);
        head.appendChild(rm);

        var ta = document.createElement("textarea");
        ta.className = "cg-textarea";
        ta.placeholder = "粘贴信用证、商业发票、装箱单或提单的文字。\n系统会自己判断这是哪种单证。";
        ta.spellcheck = false;
        ta.value = text || "";

        slot.appendChild(head);
        slot.appendChild(ta);
        slotsEl.appendChild(slot);
        renumber();
    }

    function setSlots(texts) {
        slotsEl.innerHTML = "";
        texts.forEach(function (t) { addSlot(t); });
        while (slotCount() < MIN_SLOTS) addSlot("");
    }

    // ---------- SVG 小工具 ----------
    function svg(name, attrs, text) {
        var e = document.createElementNS(SVGNS, name);
        Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, attrs[k]); });
        if (text !== undefined) e.textContent = text;
        return e;
    }

    function clip(s, n) {
        s = String(s || "");
        return s.length > n ? s.slice(0, n - 1) + "…" : s;
    }

    // ---------- 画图 ----------
    var RANK = { conflict: 3, near: 2, ok: 1 };

    function drawGraph(g) {
        var n = g.docs.length, rows = g.rows;
        var W = PAD * 2 + n * COL_W + (n - 1) * GAP;
        var H = PAD * 2 + HEAD_H + rows.length * ROW_H;
        var colX = function (i) { return PAD + i * (COL_W + GAP); };
        var rowY = function (r) { return PAD + HEAD_H + r * ROW_H; };

        // 每个单元格的最差状态：用来给值上色
        var cellState = {};
        g.edges.forEach(function (e) {
            [e.a, e.b].forEach(function (d) {
                var k = e.key + "|" + d;
                if ((RANK[e.status] || 0) > (RANK[cellState[k]] || 0)) cellState[k] = e.status;
            });
        });
        var rowIndex = {};
        rows.forEach(function (r, i) { rowIndex[r.key] = i; });

        var s = svg("svg", { width: W, height: H, viewBox: "0 0 " + W + " " + H, role: "img",
            "aria-label": "单证一致性图：" + g.docs.map(function (d) { return d.label; }).join("、") });

        // 1) 连线先画，单据列盖在上面 —— 线跨过中间的列时会"从后面穿过去"，只在列间隙里可见
        var edgeLayer = svg("g", { class: "cg-edges" });
        g.edges.forEach(function (e) {
            var r = rowIndex[e.key];
            var y = rowY(r) + ROW_H / 2 + 6;
            var x1 = colX(e.a) + COL_W, x2 = colX(e.b);
            var grp = svg("g", { class: "cg-edge is-" + e.status, "data-row": e.key });
            var tip = e.label + "：" + e.a_label + " " + e.a_raw + "  " + (STATUS_MARK[e.status] || "?") + "  " +
                e.b_label + " " + e.b_raw + (e.note ? "（" + e.note + "）" : "");
            grp.appendChild(svg("title", {}, tip));
            grp.appendChild(svg("line", { x1: x1, y1: y, x2: x2, y2: y }));
            // 标记放在第一个间隙的中间
            var mx = x1 + GAP / 2;
            grp.appendChild(svg("rect", { x: mx - 10, y: y - 10, width: 20, height: 20, rx: 3, class: "cg-mark-bg" }));
            grp.appendChild(svg("text", { x: mx, y: y + 5, "text-anchor": "middle", class: "cg-mark" }, STATUS_MARK[e.status] || "?"));
            edgeLayer.appendChild(grp);
        });
        s.appendChild(edgeLayer);

        // 2) 单据列
        g.docs.forEach(function (d, di) {
            var x = colX(di), y0 = PAD, h = HEAD_H + rows.length * ROW_H;
            var col = svg("g", { class: "cg-doc" });
            col.appendChild(svg("rect", { x: x, y: y0, width: COL_W, height: h, rx: 4, class: "cg-sheet" }));
            col.appendChild(svg("text", { x: x + 12, y: y0 + 22, class: "cg-doc-name" }, d.label));
            var have = Object.keys(d.fields).length;
            col.appendChild(svg("text", { x: x + 12, y: y0 + 40, class: "cg-doc-sub" },
                d.type === "unknown" ? "没认出是哪种单证" : "抽到 " + have + " 个字段"));
            col.appendChild(svg("line", { x1: x, y1: y0 + HEAD_H, x2: x + COL_W, y2: y0 + HEAD_H, class: "cg-rule-strong" }));

            rows.forEach(function (r, ri) {
                var ry = rowY(ri);
                var cell = r.cells[di];
                var st = cellState[r.key + "|" + di] || "";
                var rowG = svg("g", { class: "cg-row", "data-row": r.key });
                if (ri > 0) rowG.appendChild(svg("line", { x1: x + 10, y1: ry, x2: x + COL_W - 10, y2: ry, class: "cg-rule" }));
                rowG.appendChild(svg("text", { x: x + 12, y: ry + 17, class: "cg-field" }, r.label));
                var val = svg("text", { x: x + 12, y: ry + 37, class: "cg-val" + (cell.raw ? (st ? " is-" + st : "") : " is-none") },
                    cell.raw ? clip(cell.raw, 25) : "—");
                if (cell.raw) val.appendChild(svg("title", {}, cell.raw));
                rowG.appendChild(val);
                col.appendChild(rowG);
            });
            s.appendChild(col);
        });

        scrollEl.innerHTML = "";
        scrollEl.appendChild(s);
    }

    // ---------- 摘要与清单 ----------
    function ruleBadge(id) {
        var b = document.createElement("span");
        b.className = "rpt-tag rpt-rule rpt-rule-link";
        b.textContent = id;
        b.dataset.ruleId = id;
        b.setAttribute("role", "button");
        b.setAttribute("tabindex", "0");
        b.title = "查看这条规则的依据";
        return b;
    }

    function drawSummary(g) {
        var sm = g.summary;
        summaryEl.innerHTML = "";
        [["conflict", sm.conflict, "处不一致"], ["near", sm.near, "处近似"], ["ok", sm.ok, "处一致"]].forEach(function (it) {
            var span = document.createElement("span");
            span.className = "cg-sum is-" + it[0] + (it[1] ? "" : " is-zero");
            var b = document.createElement("b");
            b.textContent = it[1];
            span.appendChild(b);
            span.appendChild(document.createTextNode(" " + it[2]));
            summaryEl.appendChild(span);
        });
    }

    function drawIssues(g) {
        issuesEl.innerHTML = "";
        var bad = g.edges.filter(function (e) { return e.status === "conflict" || e.status === "near"; });
        bad.sort(function (a, b) { return (RANK[b.status] - RANK[a.status]); });

        var h = document.createElement("h3");
        h.className = "cg-h";
        h.textContent = bad.length ? "需要你看的地方" : "结论";
        issuesEl.appendChild(h);

        if (!bad.length) {
            var p = document.createElement("p");
            p.className = "cg-empty";
            p.textContent = g.summary.ok
                ? "所有能比对的字段都对得上。灰色的「—」是没抽到，不代表没有问题，请对着原件再核一遍。"
                : "没有找到可以比对的共同字段。请确认粘贴的是完整的单证文字，并且包含「发票号」「金额」这类带标签的栏目。";
            issuesEl.appendChild(p);
            return;
        }
        var ol = document.createElement("ol");
        ol.className = "cg-issue-list";
        bad.forEach(function (e) {
            var li = document.createElement("li");
            li.className = "cg-issue is-" + e.status;
            li.dataset.row = e.key;

            var head = document.createElement("div");
            head.className = "cg-issue-head";
            var st = document.createElement("span");
            st.className = "cg-st";
            st.textContent = STATUS_TEXT[e.status];
            var name = document.createElement("b");
            name.textContent = e.label;
            head.appendChild(st);
            head.appendChild(name);
            if (e.rule) head.appendChild(ruleBadge(e.rule));
            li.appendChild(head);

            var body = document.createElement("p");
            body.className = "cg-issue-body";
            body.textContent = e.a_label + "：" + e.a_raw + "　" + STATUS_MARK[e.status] + "　" + e.b_label + "：" + e.b_raw;
            li.appendChild(body);
            if (e.note) {
                var note = document.createElement("p");
                note.className = "cg-issue-note";
                note.textContent = e.note;
                li.appendChild(note);
            }
            ol.appendChild(li);
        });
        issuesEl.appendChild(ol);
    }

    function drawCoverage(g) {
        coverageEl.innerHTML = "";
        var weak = g.docs.filter(function (d) { return d.type === "unknown" || Object.keys(d.fields).length < 4; });
        if (!weak.length) return;
        var p = document.createElement("p");
        p.className = "cg-note";
        p.textContent = "提示：" + weak.map(function (d) {
            return d.label + (d.type === "unknown" ? "没认出类型" : "只抽到 " + Object.keys(d.fields).length + " 个字段");
        }).join("；") + "。字段抽得少，图上能比对的就少。请确认粘贴的是完整文字、并且带着「发票号」「金额」这样的栏目标签。";
        coverageEl.appendChild(p);
    }

    // 鼠标移到清单的某一条，图里对应的行高亮
    issuesEl.addEventListener("mouseover", function (ev) {
        var li = ev.target.closest && ev.target.closest(".cg-issue");
        var key = li ? li.dataset.row : "";
        Array.prototype.forEach.call(scrollEl.querySelectorAll(".cg-row, .cg-edge"), function (g) {
            g.classList.toggle("is-hl", !!key && g.getAttribute("data-row") === key);
        });
    });
    issuesEl.addEventListener("mouseleave", function () {
        Array.prototype.forEach.call(scrollEl.querySelectorAll(".is-hl"), function (g) { g.classList.remove("is-hl"); });
    });

    // ---------- 动作 ----------
    function showError(msg) {
        errEl.textContent = msg;
        errEl.hidden = !msg;
    }

    function run() {
        showError("");
        var texts = Array.prototype.map.call(slotsEl.querySelectorAll(".cg-textarea"), function (t) { return t.value.trim(); })
            .filter(Boolean);
        if (texts.length < MIN_SLOTS) {
            showError("至少需要粘贴两份单证的文字。");
            return;
        }
        btnRun.disabled = true;
        fetch("/api/consistency", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ docs: texts })
        })
            .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
            .then(function (res) {
                btnRun.disabled = false;
                if (!res.ok) { showError(res.d.error || "生成失败，请重试"); return; }
                drawGraph(res.d);
                drawSummary(res.d);
                drawIssues(res.d);
                drawCoverage(res.d);
                resultEl.hidden = false;
                resultEl.scrollIntoView({ behavior: "smooth", block: "start" });
            })
            .catch(function () {
                btnRun.disabled = false;
                showError("网络错误，请重试");
            });
    }

    btnRun.addEventListener("click", run);
    btnAdd.addEventListener("click", function () { addSlot(""); });
    btnClear.addEventListener("click", function () {
        setSlots(["", "", ""]);
        resultEl.hidden = true;
        showError("");
    });
    btnSample.addEventListener("click", function () {
        showError("");
        fetch("/api/consistency/sample")
            .then(function (r) { return r.json(); })
            .then(function (d) { setSlots(d.docs || []); run(); })
            .catch(function () { showError("样例加载失败，请重试"); });
    });

    setSlots(["", "", ""]);
})();
