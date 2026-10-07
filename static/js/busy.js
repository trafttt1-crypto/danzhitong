/* 等待状态：一枚线条星芒 + 会流光的动词 + 已用时间。
 * 做法：不假装有进度条，只如实告诉用户"还在做、做了多久"，
 * 动词是对本次任务工作范围的描述，随时间轮换，不代表严格的先后步骤。
 * 对外：window.DZTBusy = { glyph(), verbsFor(kind), run(verbEl, timeEl, opts) -> stop }
 */
(function () {
    "use strict";

    var VERBS = {
        audit: ["通读单据", "核对金额与币种", "比对数量与重量", "对照信用证条款", "检查日期与装运期",
                "核验当事人名称", "复算数学关系", "翻查 UCP600", "核对港口与唛头", "整理审核意见"],
        lc: ["通读信用证条款", "查看 46A 单据要求", "推算交单期限", "检查软条款风险",
             "核对 UCP600 相关条款", "整理体检结论"],
        generate: ["整理货物明细", "套用单证格式", "填写金额与日期", "核对单证之间的数据", "自检生成结果"],
        compare: ["逐份读取单证", "比对当事人名称", "比对金额与数量", "核对日期与港口", "找出单单不符"],
        chat: ["思考", "翻查系统里的审核数据", "整理回答"],
    };

    // 四条线穿过中心 = 八个尖的星芒；线端点直接写屏幕坐标，这样 CSS 缩放不会被旋转带歪
    var SPOKES = [
        [10, 2, 10, 18], [2, 10, 18, 10], [4.3, 4.3, 15.7, 15.7], [15.7, 4.3, 4.3, 15.7],
    ];

    function glyph() {
        var s = '<svg class="busy-glyph" viewBox="0 0 20 20" width="18" height="18" aria-hidden="true" focusable="false">';
        for (var i = 0; i < SPOKES.length; i++) {
            var p = SPOKES[i];
            s += '<line class="busy-spoke" style="animation-delay:' + (i * 0.15).toFixed(2) + 's"'
               + ' x1="' + p[0] + '" y1="' + p[1] + '" x2="' + p[2] + '" y2="' + p[3] + '"/>';
        }
        return s + '</svg>';
    }

    function verbsFor(kind) { return VERBS[kind] || VERBS.audit; }

    function fmt(sec) {
        if (sec < 60) return sec + " 秒";
        return Math.floor(sec / 60) + " 分 " + (sec % 60) + " 秒";
    }

    function order(list) {
        // 第一个固定（最贴合"刚开始"），其余打乱，避免每次都是同一个顺序
        var rest = list.slice(1);
        for (var i = rest.length - 1; i > 0; i--) {
            var j = Math.floor(Math.random() * (i + 1));
            var t = rest[i]; rest[i] = rest[j]; rest[j] = t;
        }
        return [list[0]].concat(rest);
    }

    /* verbEl 显示动词，timeEl 显示用时。返回 stop()。 */
    function run(verbEl, timeEl, opts) {
        opts = opts || {};
        var list = order(opts.verbs || VERBS.audit);
        var slowAfter = opts.slowAfter || 45;
        var started = Date.now();
        var idx = 0;
        var tick = 0;

        function paint() {
            var sec = Math.floor((Date.now() - started) / 1000);
            var txt = fmt(sec);
            if (sec >= slowAfter) txt += " · 比平时慢一些，请稍候";
            timeEl.textContent = txt;
        }
        verbEl.textContent = list[0] + "…";
        paint();

        var timer = setInterval(function () {
            tick++;
            paint();
            if (tick % 3 === 0) {           // 每 3 秒换一个动词
                idx = (idx + 1) % list.length;
                verbEl.textContent = list[idx] + "…";
            }
        }, 1000);
        return function stop() { clearInterval(timer); };
    }

    window.DZTBusy = { glyph: glyph, verbsFor: verbsFor, run: run };

    // ---- 主审核等待区：各个流程都是改 #loadingSection 的 display，这里统一监听，不改每个调用点 ----
    var section = document.getElementById("loadingSection");
    var verbEl = document.getElementById("busyVerb");
    var timeEl = document.getElementById("busyTime");
    var glyphEl = document.getElementById("busyGlyph");
    if (!section || !verbEl || !timeEl) return;
    if (glyphEl) glyphEl.innerHTML = glyph();

    function kindNow() {
        var t = document.querySelector(".tab.active");
        var name = t ? t.getAttribute("data-tab") : "";
        if (name === "lcreview") return "lc";
        if (name === "generate") return "generate";
        if (name === "compare") return "compare";
        return "audit";
    }

    var stop = null;
    function sync() {
        var visible = section.style.display !== "none";
        if (visible && !stop) {
            stop = run(verbEl, timeEl, { verbs: verbsFor(kindNow()) });
            // 文字审核页的表单还留在上面，等待行在下方，要带到视野里，否则像是没反应
            if (section.scrollIntoView) section.scrollIntoView({ block: "nearest", behavior: "smooth" });
        } else if (!visible && stop) {
            stop(); stop = null;
        }
    }
    new MutationObserver(sync).observe(section, { attributes: true, attributeFilter: ["style"] });
    sync();
})();
