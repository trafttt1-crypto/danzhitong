/* 审核报告视图：把模型写的【小节】文本拆成结构化数据，再渲染成「结论横幅 + 问题卡片 + 折叠附录」。
 *
 * 为什么不直接靠 markdown 排版：模型的输出是一大段文字，结论在最底下，
 * 问题、风险、"没能核查"的项混在一起，用户得从头读到尾才知道这份单能不能放行。
 * 这里按报告的固定结构把它拆开，结论提到最上面，问题做成卡片。
 *
 * 容错是第一要务：
 *  - 解析不了就返回 null，调用方退回旧的 markdown 渲染，不会比以前更差；
 *  - 所有原文都会显示出来（折叠也算显示），绝不因为分类不准就丢内容 ——
 *    漏掉一条不符点，业务员就可能真的漏改一处（services/discrepancy.py 里也是这个原则）。
 *
 * 只处理标准审核报告（同时有【发现问题】和【审核结论】）。信用证体检、多单证对比
 * 用的是别的小节名，不在这里处理，仍走旧渲染。
 */
(function () {
    "use strict";

    var SEV_LABEL = { critical: "严重", error: "需改", warning: "提示" };
    var SEV_ALIAS = { "严重": "critical", "需改": "error", "提示": "warning", "错误": "error" };

    function esc(s) {
        return String(s === null || s === undefined ? "" : s)
            .replace(/&/g, "&amp;").replace(/</g, "&lt;")
            .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    }

    // 规则编号做成可点徽标（app.js 里有委托：点一下跳到「审核规则」页并筛到那一条）。
    // "R11-R21" 这种区间不做徽标，点哪个端点都不对。
    var RULE_INLINE_RE = /(?<![-–\w])([RL]\d{2})(?![\w])(?!\s*[-–]\s*[RL]\d{2})/g;

    function ruleBadge(id) {
        return '<span class="rpt-tag rpt-rule rpt-rule-link" data-rule-id="' + esc(id) +
            '" role="button" tabindex="0" title="查看这条规则的依据">' + esc(id) + "</span>";
    }

    function inlineRich(text) {
        return esc(text).replace(RULE_INLINE_RE, function (m, id) { return ruleBadge(id); });
    }

    function sevChip(sev) {
        if (!sev) return "";
        return '<span class="rv-sev rv-sev-' + sev + '">' + (SEV_LABEL[sev] || sev) + "</span>";
    }

    // ---------- 拆小节 ----------
    function splitSections(text) {
        var map = {}, order = [], cur = null;
        String(text).split(/\r?\n/).forEach(function (line) {
            var m = line.trim().match(/^【([^】]{1,20})】$/);
            if (m) { cur = m[1]; if (!map[cur]) { map[cur] = []; order.push(cur); } return; }
            if (cur) map[cur].push(line);
        });
        return { map: map, order: order };
    }

    function cleanLines(lines) {
        return (lines || []).map(function (l) { return l.replace(/\s+$/, ""); })
            .filter(function (l) { return l.trim() !== ""; });
    }

    function stripBullet(l) {
        return l.replace(/^\s*(?:[-*•·]|\d+[.、)）])\s*/, "").replace(/\*\*/g, "");
    }

    // ---------- 行首标签：[R01][critical] / R63（warning）： / R43 / R04（提示）： ----------
    function parseTags(s) {
        var rules = [], sev = "", other = "";
        var guard = 0;
        while (guard++ < 8) {
            var m = s.match(/^\s*[\[【(（]\s*([^\]】)）]{1,60}?)\s*[\]】)）]\s*/);
            if (m) {
                var tag = m[1].trim(), low = tag.toLowerCase();
                if (/^(critical|error|warning)$/.test(low)) sev = sev || low;
                else if (SEV_ALIAS[tag]) sev = sev || SEV_ALIAS[tag];
                else if (/^[RL]\d{2}/.test(tag)) {
                    (tag.match(/[RL]\d{2}/g) || []).forEach(function (r) { if (rules.indexOf(r) < 0) rules.push(r); });
                } else other = other || tag;       // 例如「无对应规则编号 — 单证内部条款自相矛盾」
                s = s.slice(m[0].length);
                continue;
            }
            var b = s.match(/^\s*([RL]\d{2}(?:\s*[\/、,，]\s*[RL]\d{2})*)(?![\d\w-])\s*/);
            if (b) {
                (b[1].match(/[RL]\d{2}/g) || []).forEach(function (r) { if (rules.indexOf(r) < 0) rules.push(r); });
                s = s.slice(b[0].length);
                continue;
            }
            break;
        }
        s = s.replace(/^\s*[：:]\s*/, "");
        return { rules: rules, sev: sev, other: other, rest: s };
    }

    // ---------- 问题 ----------
    var ISSUE_START_RE = /^\s*(?:[-*•]\s*)?(?:\*\*)?问题\s*(\d+)\s*(?:\*\*)?\s*[：:．.、]\s*/;
    var NONE_RE = /未发现|没有发现|无明显|不存在|无需修改|无问题/;

    function parseIssues(lines) {
        var issues = [], notes = [], cur = null;
        lines.forEach(function (raw) {
            var m = raw.match(ISSUE_START_RE);
            if (m) {
                cur = { n: parseInt(m[1], 10), raw: raw.slice(m[0].length) };
                issues.push(cur);
                return;
            }
            var t = raw.trim();
            // 括号起头的整行是模型的补充说明（"其余字段均自洽…"），不是问题
            if (/^[（(]/.test(t)) { notes.push(t.replace(/^[（(]\s*|\s*[）)]$/g, "")); cur = null; return; }
            if (cur) cur.raw += " " + t;
            else if (!NONE_RE.test(t)) notes.push(t);
        });
        issues.forEach(function (it) {
            var tg = parseTags(it.raw);
            it.rules = tg.rules; it.sev = tg.sev || "error"; it.other = tg.other;
            // 标签后面紧跟的短横线是"位置 - 描述"的分隔符漏到了开头（旧版提示词的写法）
            var body = tg.rest.replace(/^\s*[-—–]{1,2}\s+/, ""), fix = "", loc = "", desc = body;
            var ai = body.search(/\s*(?:→|->|=>|⇒)\s*/);
            if (ai >= 0) {
                desc = body.slice(0, ai);
                fix = body.slice(ai).replace(/^\s*(?:→|->|=>|⇒)\s*/, "");
            }
            // 早期版本写成"位置：… 描述：… 建议：…"的带标签格式
            var lab = desc.match(/位置[：:]\s*([\s\S]*?)\s*描述[：:]\s*([\s\S]*)$/);
            if (lab) { loc = lab[1]; desc = lab[2]; }
            if (!fix) {
                var sg = desc.match(/^([\s\S]*?)\s*(?:[-—–]\s*)?(?:修改)?建议[：:]\s*([\s\S]+)$/);
                if (sg && sg[1].trim()) { desc = sg[1]; fix = sg[2]; }
            }
            if (!loc) {
                var lm = desc.match(/^(.{1,30}?)\s+[-—–]{1,2}\s+([\s\S]+)$/);
                if (lm) { loc = lm[1]; desc = lm[2]; }
            }
            it.loc = loc.trim(); it.desc = desc.trim(); it.fix = fix.trim();
        });
        return { issues: issues, notes: notes };
    }

    // ---------- 风险提示 ----------
    var UNCHECKED_RE = /无法(?:执行|核查|核对|验证|比对|判断|确认|检查|评价)/;

    // "本次已核查，未发现问题"这类是在报告"没事"，不是风险；带"建议/须/需"的说明有动作，不算
    var PASSED_RE = /已核查|核查通过|未发现(?:问题|异常|错误)|无异常|均通过|验算通过/;
    var ACTION_RE = /建议|须|需|应当|请|但/;

    function parseRisks(lines) {
        var review = [], unchecked = [], passed = [];
        lines.forEach(function (raw) {
            var tg = parseTags(stripBullet(raw));
            var item = { rules: tg.rules, sev: tg.sev, text: tg.rest.trim() };
            if (!item.text) return;
            // 模型常把"无法执行"写进括号标签里：R01/R02（critical，无法执行）：…
            // 标签被当成 other，所以要把它和正文合起来判断
            var probe = tg.other + " " + item.text;
            if (!tg.sev && UNCHECKED_RE.test(probe)) unchecked.push(item);
            else if (!tg.sev && PASSED_RE.test(item.text) && !ACTION_RE.test(item.text)) passed.push(item);
            else review.push(item);
        });
        return { review: review, unchecked: unchecked, passed: passed };
    }

    // ---------- 结论 ----------
    function parseVerdict(lines, issueCount) {
        var text = lines.map(function (l) { return l.trim(); }).join(" ").replace(/\*\*/g, "").trim();
        var state = "";
        if (typeof window.conclusionState === "function") state = window.conclusionState(text);
        if (!state) state = issueCount ? "is-bad" : "is-ok";
        var head = "", summary = text;
        // 判定词后面常跟一层括号注释："通过（单证内部自查未发现问题）：数量…自洽"。
        // 整对括号一起拆：原来只吃掉左括号，右括号留在句中，横幅上显示成"…未发现问题）：数量…"
        var m = text.match(/^(不通过|需修改|需修正|需核查|需补充|建议改证|通过|可接受|有条件通过)\s*(?:[（(]([^（()）]*)[）)])?\s*[：:，,。.]?\s*/);
        if (m) {
            head = m[1];
            var inner = (m[2] || "").trim(), rest = text.slice(m[0].length).trim();
            summary = inner && rest ? inner + "：" + rest : (inner || rest);
        }
        // 列出了问题却写"通过"是模型自相矛盾，以问题条目为准（与后端 has_issue 同口径），
        // 否则横幅会出现"红底 + 通过章"或"3 处需修改 + 通过章"
        if (issueCount && state !== "is-bad") {
            state = "is-bad";
            if (head === "通过" || head === "可接受") head = "需修改";
        }
        if (!head) head = state === "is-bad" ? "需修改" : (state === "is-ok" ? "通过" : "审核完成");
        return { state: state, head: head, summary: summary.trim() };
    }

    // ---------- 渲染 ----------
    // 设计方向：审单员桌上的一份批注过的单据，而不是 SaaS 仪表盘。
    //  - 不做卡片：问题之间只用细线分隔（之前是"卡片里再套一个绿色建议框"）
    //  - 不做药丸胶囊：严重度是「小方块 + 文字」
    //  - 不做统计小方块：三个数字排成一行字
    //  - 结论用一枚"批注章"，章上的字是楷体（子集字体，见 static/fonts）
    var ICON_CHEV = '<svg class="rv-chev" viewBox="0 0 16 16" width="12" height="12" fill="none" ' +
        'stroke="currentColor" stroke-width="1.8" stroke-linecap="square" aria-hidden="true">' +
        '<path d="M6 3.5L10.5 8 6 12.5"/></svg>';

    function count(n, label) {
        return '<span class="rv-ct' + (n ? "" : " is-zero") + '"><b>' + n + "</b> " + label + "</span>";
    }

    function renderVerdict(v, docType, counts) {
        var bad = v.state === "is-bad";
        return '<header class="rv-verdict ' + (bad ? "is-bad" : "is-ok") + '">' +
            '<div class="rv-vmain">' +
            '<p class="rv-kicker">' + (docType ? esc(docType) + " · " : "") + "审核结论</p>" +
            (v.summary ? '<p class="rv-summary">' + inlineRich(v.summary) + "</p>" : "") +
            '<p class="rv-counts">' +
            count(counts.issues, "处需修改") + '<i class="rv-sep" aria-hidden="true"></i>' +
            count(counts.review, "项需复核") + '<i class="rv-sep" aria-hidden="true"></i>' +
            count(counts.unchecked, "项未能核查") + "</p>" +
            "</div>" +
            '<div class="rv-stamp" role="img" aria-label="' + esc(v.head) + '"><span>' + esc(v.head) + "</span></div>" +
            "</header>";
    }

    function renderIssues(issues, notes) {
        if (!issues.length) {
            return '<section class="rv-block"><h3 class="rv-h">发现的问题</h3>' +
                '<p class="rv-empty">本次审核未发现需要修改的问题。</p>' +
                renderNotes(notes) + "</section>";
        }
        var html = '<section class="rv-block"><h3 class="rv-h">发现的问题<span class="rv-count">' +
            issues.length + '</span></h3><ol class="rv-issues">';
        issues.forEach(function (it, i) {
            var rules = it.rules.map(ruleBadge).join("");
            if (!rules && it.other) rules = '<span class="rv-norule">' + esc(it.other) + "</span>";
            html += '<li class="rv-issue sev-' + it.sev + '">' +
                '<span class="rv-no">' + (i + 1 < 10 ? "0" : "") + (i + 1) + "</span>" +
                '<div class="rv-issue-body">' +
                '<div class="rv-issue-head">' + sevChip(it.sev) + rules +
                (it.loc ? '<span class="rv-loc">' + esc(it.loc) + "</span>" : "") + "</div>" +
                '<p class="rv-desc">' + inlineRich(it.desc) + "</p>" +
                (it.fix ? '<p class="rv-fix"><span class="rv-fix-label">修改</span><span>' + inlineRich(it.fix) + "</span></p>" : "") +
                "</div></li>";
        });
        return html + "</ol>" + renderNotes(notes) + "</section>";
    }

    function renderNotes(notes) {
        if (!notes || !notes.length) return "";
        return '<p class="rv-note">' + notes.map(inlineRich).join("<br>") + "</p>";
    }

    function fold(title, badge, inner, open, cls) {
        return '<details class="rv-fold ' + (cls || "") + '"' + (open ? " open" : "") + ">" +
            "<summary>" + ICON_CHEV + '<span class="rv-fold-title">' + title + "</span>" +
            (badge ? '<span class="rv-fold-badge">' + badge + "</span>" : "") + "</summary>" +
            '<div class="rv-fold-body">' + inner + "</div></details>";
    }

    function renderMath(lines) {
        var items = lines.map(stripBullet).filter(Boolean);
        if (!items.length) return "";
        var last = items[items.length - 1], badge = "", open = false;
        var conclusion = items.filter(function (l) { return /^结论[：:]/.test(l); })[0] || last;
        if (/不通过|不一致|不符|错误|差异/.test(conclusion) && !/无差异|无数字错误|未发现/.test(conclusion)) {
            badge = '<span class="rv-flag is-bad">验算不通过</span>'; open = true;
        } else if (/通过|一致|无误/.test(conclusion)) {
            badge = '<span class="rv-flag is-ok">验算通过</span>';
        }
        var inner = '<ul class="rv-list">' + items.map(function (l) {
            return "<li>" + inlineRich(l) + "</li>";
        }).join("") + "</ul>";
        return fold("数学验算", badge, inner, open);
    }

    function renderRiskItem(it) {
        var rules = it.rules.map(ruleBadge).join("");
        return "<li>" + sevChip(it.sev) + rules + "<span>" + inlineRich(it.text) + "</span></li>";
    }

    function renderRisks(r) {
        var html = "";
        if (r.review.length) {
            html += fold("需人工复核", r.review.length + " 项",
                '<ul class="rv-list rv-risks">' + r.review.map(renderRiskItem).join("") + "</ul>", true);
        }
        if (r.passed.length) {
            html += fold("已核查、未见异常", r.passed.length + " 项",
                '<ul class="rv-list rv-risks">' + r.passed.map(renderRiskItem).join("") + "</ul>", false, "is-quiet");
        }
        if (r.unchecked.length) {
            html += fold("因资料不全未能核查", r.unchecked.length + " 项",
                '<ul class="rv-list rv-risks">' + r.unchecked.map(renderRiskItem).join("") + "</ul>", false, "is-quiet");
        }
        return html;
    }

    function renderExec(lines) {
        var items = cleanLines(lines);
        if (!items.length) return "";
        var inner = '<ul class="rv-list">' + items.map(function (l) {
            var m = l.match(/^\s*(执行|未执行)\s*[：:]\s*([\s\S]*)$/);
            if (!m) return "<li>" + inlineRich(l) + "</li>";
            return '<li><b class="rv-exec-k">' + m[1] + "</b>" + inlineRich(m[2]) + "</li>";
        }).join("") + "</ul>";
        return fold("本轮核查范围", "", inner, false, "is-quiet");
    }

    function build(text) {
        if (!text) return null;
        var sec = splitSections(text);
        if (!sec.map["发现问题"] || !sec.map["审核结论"]) return null;

        var parsed = parseIssues(cleanLines(sec.map["发现问题"]));
        // 有内容却一条问题也没解析出来，又不是"未发现…"：格式认不出，交还给旧渲染
        var rawIssueText = cleanLines(sec.map["发现问题"]).join(" ");
        if (!parsed.issues.length && rawIssueText && !NONE_RE.test(rawIssueText)) return null;

        var risks = parseRisks(cleanLines(sec.map["风险提示"] || []));
        var verdict = parseVerdict(cleanLines(sec.map["审核结论"]), parsed.issues.length);
        if (!verdict.summary && !parsed.issues.length && verdict.head === "审核完成") return null;
        var docType = cleanLines(sec.map["单证类型"] || [])[0] || "";
        // 只取类型本身："商业发票（COMMERCIAL INVOICE，发票号 …）" → 商业发票
        docType = docType.replace(/\*\*/g, "").split(/[（(，,]/)[0].trim();

        var html = '<div class="rv">' +
            renderVerdict(verdict, docType, {
                issues: parsed.issues.length, review: risks.review.length, unchecked: risks.unchecked.length
            }) +
            renderIssues(parsed.issues, parsed.notes) +
            '<div class="rv-folds">' +
            renderMath(cleanLines(sec.map["数学验算"] || [])) +
            renderRisks(risks) +
            renderExec(sec.map["本轮执行"] || []) +
            "</div></div>";
        return html;
    }

    // 规则徽标是 role=button 的 span，键盘也要能点（Enter / 空格）
    document.addEventListener("keydown", function (e) {
        if (e.key !== "Enter" && e.key !== " ") return;
        var t = e.target;
        if (t && t.classList && t.classList.contains("rpt-rule-link")) {
            e.preventDefault();
            t.click();
        }
    });

    window.DZTReport = { build: build, _parse: { issues: parseIssues, risks: parseRisks, verdict: parseVerdict, tags: parseTags } };
})();
