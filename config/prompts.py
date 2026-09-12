# -*- coding: utf-8 -*-
"""审核规则表与提示词。

**规则表是全项目唯一事实来源**：提示词、速查表、本次可执行范围全部由它生成，
不要再往提示词里手抄一份（以前就是手抄的，两边早就对不上了）。

字段说明：
  id       规则编号，稳定不变，报告里标的就是它
  severity critical=构成不符点或直接造成损失 / error=必须修改 / warning=建议人工核查
  scope    执行条件：single=单份单证即可 / pair=需两份以上单证 / lc=需信用证条款
           两个条件都要时写成 "pair+lc"
  basis    依据（UCP600 条款 / ISBP / WCO 等），用来支撑"为什么这是错的"
"""
import re

AUDIT_RULES = [
    # ================= A 组 · 数学与金额 =================
    {
        "id": "R01", "name": "金额数学验算", "category": "数学与金额",
        "severity": "critical", "scope": "single", "basis": "发票基本要求",
        "check": "逐项验算 单价×数量=行金额；各行金额之和=Sub Total；(Sub Total+运费)=Grand Total。"
                 "发现不一致时算出正确值，并指出到底是哪个数字错了。",
        "fix": "按正确单价或数量重算，并同步修改 Sub Total、Grand Total 与英文大写金额",
    },
    {
        "id": "R02", "name": "金额大小写一致性", "category": "数学与金额",
        "severity": "critical", "scope": "single", "basis": "ISBP 发票条款",
        "check": "英文大写金额必须等于 Grand Total（含运费），不是 Sub Total；结尾须有 ONLY，"
                 "币别须与金额栏一致。",
        "fix": "按 Grand Total 重写大写金额",
    },
    {
        "id": "R03", "name": "单证内币别一致性", "category": "数学与金额",
        "severity": "critical", "scope": "single", "basis": "内部一致性",
        "check": "同一份单证内所有金额必须使用同一种币别；金额栏与大写栏币别不一致即为错误。"
                 "（与信用证币别的比对见 R12）",
        "fix": "统一币别",
    },
    {
        "id": "R04", "name": "净重毛重逻辑", "category": "数学与金额",
        "severity": "error", "scope": "single", "basis": "内部一致性",
        "check": "净重必须小于等于毛重；各行重量之和须等于重量合计栏；毛净重与件数应成合理比例。",
        "fix": "核对是否写反或漏改",
    },
    {
        "id": "R05", "name": "数量单位合理性", "category": "数学与金额",
        "severity": "warning", "scope": "single", "basis": "单证惯例",
        "check": "数量单位须与货物属性和计价方式自洽：液体/粉末按 KG、L，不应按 PCS；"
                 "成套货物按 SET；同一货物在同一单证内的单位须统一。",
        "fix": "按实际计价单位修正",
    },

    # ================= B 组 · 信用证 =================
    {
        "id": "R11", "name": "LC 金额占用", "category": "信用证",
        "severity": "critical", "scope": "lc", "basis": "UCP600 Art.30(a)",
        "check": "信用证无 about / approximately / circa 等措辞时：发票金额不得【超过】信用证金额，"
                 "低于信用证金额不构成不符；有该措辞时：允许增减 10%。",
        "fix": "超出时减少支取金额，或改证、改分批支取",
    },
    {
        "id": "R12", "name": "LC 币别一致性", "category": "信用证",
        "severity": "critical", "scope": "lc", "basis": "UCP600 Art.18(a)(iii)",
        "check": "商业发票的币别必须与信用证币别完全相同，不同即为不符点。",
        "fix": "改用信用证币别出票",
    },
    {
        "id": "R13", "name": "LC 数量容差", "category": "信用证",
        "severity": "critical", "scope": "lc", "basis": "UCP600 Art.30(b)",
        "check": "数量允许 5% 增减，但两个前提：一是信用证未把数量规定为包装单位或个数"
                 "（如 500 CARTONS、1000 PCS 属于个数计价，不适用 5% 容差）；"
                 "二是支取总额不得超过信用证金额。",
        "fix": "超出容差时改证或调整发运数量",
    },
    {
        "id": "R14", "name": "LC 最迟装运日", "category": "信用证",
        "severity": "critical", "scope": "lc", "basis": "UCP600 Art.20(a)(ii)",
        "check": "装运日不得晚于信用证规定的最迟装运日。装运日的认定：提单有 on board 批注时以批注日期为准，"
                 "没有批注时以提单签发日为准。",
        "fix": "超期须改证或调整发运批次",
    },
    {
        "id": "R15", "name": "LC 交单期", "category": "信用证",
        "severity": "critical", "scope": "lc", "basis": "UCP600 Art.14(c)",
        "check": "交单日必须不迟于信用证效期和最迟交单日；信用证未规定交单期时，"
                 "须在装运日后 21 个日历日内交单。注意：效期约束的是【交单日】，"
                 "不是单据的出具日期 —— 一份日期较早的发票在有效期内交单完全合规。",
        "fix": "临期时优先交单，或申请改证展期",
    },
    {
        "id": "R16", "name": "LC 运费条款", "category": "信用证",
        "severity": "error", "scope": "lc", "basis": "UCP600 / Incoterms",
        "check": "提单运费批注须与信用证规定逐字一致（FREIGHT PREPAID / FREIGHT COLLECT / AS ARRANGED）；"
                 "并须与贸易术语匹配：CIF、CFR、CPT、CIP 通常为 PREPAID，FOB、FCA 通常为 COLLECT。",
        "fix": "按信用证措辞更正运费批注",
    },
    {
        "id": "R17", "name": "LC 正本份数", "category": "信用证",
        "severity": "error", "scope": "lc", "basis": "UCP600 Art.20",
        "check": "提单签发的正本份数须与信用证要求一致（如 3/3、2/3）。",
        "fix": "补签不足的份数",
    },
    {
        "id": "R18", "name": "LC 收货人措辞", "category": "信用证",
        "severity": "critical", "scope": "lc", "basis": "UCP600 严格相符原则",
        "check": "提单收货人措辞须与信用证规定逐字一致，包括 THE 这类冠词，不得增减、改写或缩写。",
        "fix": "照抄信用证措辞重出提单",
    },
    {
        "id": "R19", "name": "LC 货描必含字句", "category": "信用证",
        "severity": "critical", "scope": "lc", "basis": "UCP600 Art.18(c)",
        "check": "信用证规定货描必须包含的字句（如 PI 号、合同号、产地），须逐一出现在发票货描中，"
                 "缺任何一项都构成不符点。",
        "fix": "在货描中补入信用证规定字句",
    },
    {
        "id": "R20", "name": "LC 分批装运与转运", "category": "信用证",
        "severity": "critical", "scope": "lc", "basis": "UCP600 Art.31",
        "check": "信用证禁止分批装运时，出现多套运输单据或分批发运即为不符点；"
                 "禁止转运时须核查运输单据上的转运批注。",
        "fix": "改证，或调整发运安排",
    },
    {
        "id": "R21", "name": "LC 港口一致性", "category": "信用证",
        "severity": "error", "scope": "lc", "basis": "UCP600 Art.20(a)(iii)",
        "check": "装运港与卸货港须在信用证规定的范围内，不得擅自更改、增删港口。",
        "fix": "按信用证规定的港口出运",
    },

    # ================= C 组 · 当事人 =================
    {
        "id": "R31", "name": "发票抬头（申请人）", "category": "当事人",
        "severity": "critical", "scope": "lc", "basis": "UCP600 Art.18(a)(ii)",
        "check": "商业发票必须出具给信用证申请人（转让信用证除外）。抬头写成第三方，"
                 "是实务中最高频的拒付原因之一。",
        "fix": "把发票抬头改为信用证申请人的名称",
    },
    {
        "id": "R32", "name": "发票出具人（受益人）", "category": "当事人",
        "severity": "error", "scope": "lc", "basis": "UCP600 Art.18(a)(i)",
        "check": "商业发票须由信用证受益人出具（转让信用证除外）。",
        "fix": "改为受益人出具",
    },
    {
        "id": "R33", "name": "提单收货人一致性", "category": "当事人",
        "severity": "error", "scope": "pair+lc", "basis": "UCP600 Art.20",
        "check": "提单收货人须按信用证规定填写（TO ORDER / TO ORDER OF XX BANK / 具名公司），"
                 "并与其它单据上的收货人相互印证。",
        "fix": "按信用证要求重新出具提单",
    },
    {
        "id": "R34", "name": "提单通知方", "category": "当事人",
        "severity": "error", "scope": "pair+lc", "basis": "UCP600 严格相符原则",
        "check": "提单通知方的名称与地址须符合信用证或合同要求，并与其他单据一致。",
        "fix": "更正通知方信息",
    },
    {
        "id": "R35", "name": "收货人地址完整性", "category": "当事人",
        "severity": "warning", "scope": "single", "basis": "实务惯例",
        "check": "收货人地址至少应含城市与国别；仅有信箱号（P.O.BOX）在信用证项下常被认为不完整。",
        "fix": "补全街道、城市、国别",
    },
    {
        "id": "R36", "name": "三方名称地址跨单据一致", "category": "当事人",
        "severity": "error", "scope": "pair", "basis": "UCP600 数据不矛盾原则",
        "check": "发货人、收货人、通知方的名称与地址，在发票、装箱单、提单之间必须一致。",
        "fix": "以信用证规定为准统一各单据",
    },

    # ================= D 组 · 运输单据 =================
    {
        "id": "R41", "name": "提单签发人", "category": "运输单据",
        "severity": "error", "scope": "single", "basis": "UCP600 Art.20(a)(i)",
        "check": "提单必须表明承运人名称，并由承运人或其具名代理签署；由代理签署时须注明代表谁签署。",
        "fix": "补齐承运人名称或签署方信息",
    },
    {
        "id": "R42", "name": "提单性质与流通性", "category": "运输单据",
        "severity": "error", "scope": "single", "basis": "UCP600 Art.20-22",
        "check": "提单标题（ORIGINAL / NON-NEGOTIABLE / COPY）、收货人形式（TO ORDER / 具名）"
                 "与正本份数三者须相互自洽；NON-NEGOTIABLE 不能与 TO ORDER 并存。",
        "fix": "按单据性质修正标题、收货人或份数",
    },
    {
        "id": "R43", "name": "唛头与件数", "category": "运输单据",
        "severity": "error", "scope": "single", "basis": "实务惯例",
        "check": "唛头中 C/No. 区间推算的箱数（结束号-起始号+1，多组相加）须等于件数栏 TOTAL PKGS。",
        "fix": "核对唛头区间或件数栏",
    },
    {
        "id": "R44", "name": "集装箱类型与温控", "category": "运输单据",
        "severity": "warning", "scope": "single", "basis": "实务惯例",
        "check": "冷冻/冷藏货物应使用 REEFER 箱；普通货物使用 REEFER 箱需说明必要性；"
                 "危险品须核对是否使用对应专用箱。",
        "fix": "核对箱型与货物属性",
    },
    {
        "id": "R45", "name": "签发地与装运港", "category": "运输单据",
        "severity": "warning", "scope": "single", "basis": "实务惯例",
        "check": "提单签发地通常应与装运港同国；不同国时须有转船、货代签发或多式联运等合理解释。",
        "fix": "确认签发主体与运输方式",
    },

    # ================= E 组 · 货描与编码 =================
    {
        "id": "R51", "name": "HS 编码格式与归类", "category": "货描与编码",
        "severity": "error", "scope": "single", "basis": "WCO 协调制度",
        "check": "HS 编码前 6 位为国际统一编码（WCO 协调制度），超过 6 位为各国细分"
                 "（中国报关用 10 位）。书写形式不限：6911.10、6911.10.00、6911100000 都是规范写法，"
                 "带分隔点不算错。只有【归类与货描的材质或用途明显不符】才算错误；"
                 "位数不足报关要求的，只在风险提示里建议补足，不要当作错误。",
        "fix": "按实际货物归类；报关用时补足到 10 位",
    },
    {
        "id": "R52", "name": "货描比对分工", "category": "货描与编码",
        "severity": "critical", "scope": "lc", "basis": "UCP600 Art.18(c)",
        "check": "只对【商业发票】做与信用证货描的逐字比对（空格、大小写、标点、缩写都要一致）；"
                 "装箱单、提单等其他单据可以用不矛盾的概括性描述，"
                 "不得因为描述比发票简略就判为不符点。",
        "fix": "发票货描照抄信用证",
    },
    {
        "id": "R53", "name": "包装与货物属性匹配", "category": "货描与编码",
        "severity": "warning", "scope": "single", "basis": "实务惯例",
        "check": "包装方式须与货物属性相符：易碎品应有防震包装或 FRAGILE 标识；"
                 "危险品须有 UN 编号与危险品标识；食品须标注保质期与储存条件。",
        "fix": "补充相应的包装标识",
    },

    # ================= F 组 · 日期逻辑 =================
    {
        "id": "R61", "name": "单据日期链", "category": "日期逻辑",
        "severity": "warning", "scope": "single", "basis": "实务惯例",
        "check": "发票、装箱单、提单之间的日期先后【没有强制顺序】（装箱单常早于发票，"
                 "两者也常同日出具），仅在明显异常时作提示，不得判为错误。",
        "fix": "核实是否存在笔误",
    },
    {
        "id": "R62", "name": "单据日期与交单日", "category": "日期逻辑",
        "severity": "error", "scope": "single", "basis": "UCP600 Art.14(e)",
        "check": "除运输单据外，其他单据的出具日期不得晚于交单日；"
                 "单据日期早于信用证开立日原则上可以接受。",
        "fix": "核对出具日期",
    },
    {
        "id": "R63", "name": "单据时效", "category": "日期逻辑",
        "severity": "warning", "scope": "single", "basis": "实务惯例",
        "check": "单据日期距审核基准日过久（如超过一年）时，提示核实是否为旧单再利用。",
        "fix": "确认为本次实际交易所用单据",
    },

    # ================= G 组 · 字符与格式 =================
    {
        "id": "R71", "name": "纯数字字段格式", "category": "字符与格式",
        "severity": "warning", "scope": "single", "basis": "OCR 风险控制",
        "check": "邮编、电话号码、传真、提单号、封条号等纯数字字段中出现字母（尤其 O/0、I/1/l），"
                 "属于高风险混淆，须提示人工逐字核对原单。",
        "fix": "人工核对原单后更正",
    },
    {
        "id": "R72", "name": "集装箱号校验位", "category": "字符与格式",
        "severity": "warning", "scope": "single", "basis": "ISO 6346",
        "check": "集装箱号应为 4 位字母（箱主代号+设备识别码）+ 6 位数字 + 1 位校验位；"
                 "末位校验位可用 ISO 6346 算法验算，对不上即为错号。",
        "fix": "核对箱号后更正",
    },
    {
        "id": "R73", "name": "金额分位符格式", "category": "字符与格式",
        "severity": "warning", "scope": "single", "basis": "内部一致性",
        "check": "千分位与小数点格式须统一（USD 1,234.56 与欧洲记法 1.234,56 不得混用）。",
        "fix": "统一记账格式",
    },
]


# ============================================================================
# 审证规则（信用证体检用）
# ============================================================================
# 与 AUDIT_RULES 同构，但不带 scope —— 体检的输入就是信用证本身，每条规则
# 都一定可执行，不需要按输入条件裁剪。
#
# L1x 软条款是这套规则的核心：这些条款的杀伤力在于「单证做得再完美也没用」，
# 审单规则一条都发现不了，只能从信用证原文本身看出来。
LC_RULES = [
    # ================= L1 组 · 软条款 =================
    {
        "id": "L11", "name": "客检条款", "category": "软条款",
        "severity": "critical", "basis": "常见软条款（UCP600 未规定，实务公认高风险）",
        "check": "要求品质/检验/分析证书由开证申请人或其授权人签发，或要求开证行核对签字、"
                 "印鉴与留存记录相符，或规定以买方国检验标准为准。"
                 "买方不签发或不及时签发，受益人即无法交单，信用证形同虚设。",
        "fix": "要求改为由独立第三方检验机构（如 SGS、BV、CCIC）签发，或删除申请人签发要求",
    },
    {
        "id": "L12", "name": "正本提单直寄申请人", "category": "软条款",
        "severity": "critical", "basis": "物权凭证风险",
        "check": "要求将 1/3 或 2/3 正本提单（甚至全套正本）在装运后直接寄交开证申请人或买方，"
                 "而不随单据交银行。买方可能凭此先行提货，受益人货款两空。",
        "fix": "要求删除直寄条款；如买方坚持，至少改为全套正本提单径交银行",
    },
    {
        "id": "L13", "name": "暂不生效条款", "category": "软条款",
        "severity": "critical", "basis": "常见软条款",
        "check": "信用证载明暂不生效或待条件满足后生效：待进口许可证签发、待样品经申请人确认、"
                 "待申请人另行通知、待进口国当局审批等。生效时点完全不受受益人控制。",
        "fix": "要求删除生效条件，改为开证即生效",
    },
    {
        "id": "L14", "name": "装运由买方控制", "category": "软条款",
        "severity": "error", "basis": "常见软条款",
        "check": "装运须待申请人指定船名、船公司或发出装运通知后才能进行；"
                 "或由申请人指定货代，或限制船龄、船籍、船公司、航线。"
                 "买方不发通知即可让受益人无法按期装运。",
        "fix": "要求在证内预先规定船名，或改为由双方认可的独立第三方安排装运",
    },
    {
        "id": "L15", "name": "付款以买方收货或检验为条件", "category": "软条款",
        "severity": "critical", "basis": "常见软条款",
        "check": "付款以货物运抵目的港、经买方检验合格、完成清关、或经外管核准为条件。"
                 "信用证的付款义务被挂到单据以外的、受益人无法控制的事件上。",
        "fix": "要求删除该条件，付款义务应仅取决于单据是否相符",
    },
    {
        "id": "L16", "name": "收货收据由申请人签发", "category": "软条款",
        "severity": "critical", "basis": "常见软条款",
        "check": "要求提交由开证申请人签发或核实的收货收据、验收证明、货物收讫证明等作为付款单据之一。",
        "fix": "要求改为受益人可自行取得的凭证，或从单据清单中删除",
    },
    {
        "id": "L17", "name": "要求受益人无法自行取得的单据", "category": "软条款",
        "severity": "error", "basis": "单据可获得性",
        "check": "要求提交受益人无法独立取得的单据：须由买方国特定机构出具、须买方配合才能获得的文件、"
                 "进口国官方许可、或申请人所在地商会签发的证明。",
        "fix": "要求明确可替代的单据，或改为受益人可自行申领的签发机构",
    },
    {
        "id": "L18", "name": "条款自相矛盾", "category": "软条款",
        "severity": "error", "basis": "UCP600 单据一致性原则",
        "check": "信用证内部条款相互矛盾：允许提交联运提单又禁止转运、既要求 FREIGHT PREPAID "
                 "又指定 FOB 类术语、金额栏与溢短装措辞冲突、要求的单据类型与货描不符。"
                 "矛盾条款会让银行审单时无所适从，成为拒付借口。",
        "fix": "要求删除矛盾条款之一，明确以哪条为准",
    },
    {
        "id": "L19", "name": "到期地点在开证行所在国", "category": "软条款",
        "severity": "warning", "basis": "UCP600 Art.6(d)(ii)",
        "check": "信用证规定在开证行柜台到期（而非受益人所在国柜台），"
                 "交单在途时间与邮寄风险全部由受益人承担。",
        "fix": "争取修改为在受益人所在国到期",
    },
    {
        "id": "L20", "name": "记名提单与空运单的物权风险", "category": "软条款",
        "severity": "warning", "basis": "物权凭证性质",
        "check": "要求提单做成记名收货人（直接交给收货人，非 TO ORDER），"
                 "或要求提交空运单、运输行收据、邮包收据等不具有物权凭证功能的单据。"
                 "此类单据项下买方无须凭提单即可提货。",
        "fix": "争取改为 TO ORDER 或做成指示提单；如无法修改，须另行安排收汇保障",
    },

    # ================= L2 组 · 时间三要素 =================
    {
        "id": "L21", "name": "双到期", "category": "时间三要素",
        "severity": "error", "basis": "UCP600 Art.14(c)；实务制单寄单周期",
        "check": "最迟装运日与信用证效期同一天或间隔过短，装运后来不及制单、寄单、交单。"
                 "实务上应留出至少 10 天缓冲（制单 3 至 5 天、寄单 3 至 5 天）。",
        "fix": "要求将效期适当延后，或相应提前装运日期",
    },
    {
        "id": "L22", "name": "交单期不足或缺省", "category": "时间三要素",
        "severity": "error", "basis": "UCP600 Art.14(c)",
        "check": "信用证规定的交单期短于 21 天；或未规定交单期（此时默认适用装运日后 21 个日历日，"
                 "但须确认效期能覆盖该期限）。交单期过短极易导致迟交单。",
        "fix": "争取交单期不少于 21 天；缺省时在内部按 21 天管理并留意效期",
    },
    {
        "id": "L23", "name": "装运期过紧", "category": "时间三要素",
        "severity": "warning", "basis": "备货与订舱周期",
        "check": "从信用证开出日到最迟装运日的可用时间过短，扣除备货、订舱、内陆运输所需时间后余量不足；"
                 "或最迟装运日已临近、已过、甚至早于信用证开出日。",
        "fix": "核实能否按期装运，不能则立即申请展延装运期",
    },
    {
        "id": "L24", "name": "效期与交单期衔接不合理", "category": "时间三要素",
        "severity": "warning", "basis": "UCP600 Art.14(c)",
        "check": "信用证效期早于「最迟装运日 + 交单期」，使规定的交单期实际不可用；或效期本身已过。",
        "fix": "要求展延效期至覆盖完整交单期",
    },

    # ================= L3 组 · 单据要求 =================
    {
        "id": "L31", "name": "单据清单不完整或不明确", "category": "单据要求",
        "severity": "warning", "basis": "UCP600 Art.14；46A 所需单据栏",
        "check": "要求的单据名称、份数、正副本、签发人未明确（如只写 invoice 未写份数），"
                 "或要求的单据类型与交易实际不符，导致无法确定该提交什么。",
        "fix": "要求开证行澄清或修改单据条款",
    },
    {
        "id": "L32", "name": "非单据化条件", "category": "单据要求",
        "severity": "warning", "basis": "UCP600 Art.14(h)",
        "check": "信用证含不要求提交对应单据的软性条件（如货物须为当年新产、包装须符合某标准、"
                 "须提供某证明而未列入单据清单）。银行依法不予理会，但申请人可能借此拒付。",
        "fix": "知悉风险并留痕；必要时要求删除或改为单据化条件",
    },
    {
        "id": "L33", "name": "单据签发人要求不合理", "category": "单据要求",
        "severity": "warning", "basis": "单据可获得性",
        "check": "要求的签发人受益人难以取得（如要求申请人所在国商会签发产地证、"
                 "要求特定海外机构出证、要求使领馆认证而该国无相应机构）。",
        "fix": "要求改为受益人能够获得的签发人",
    },
    {
        "id": "L34", "name": "附加条款含额外限制", "category": "单据要求",
        "severity": "warning", "basis": "47A 附加条件栏",
        "check": "附加条款栏含额外单据、额外费用、额外限制等容易被忽略的要求，"
                 "实务中拒付常来自这一栏而非单据清单栏。",
        "fix": "逐条评估可执行性，无法执行的立即要求修改",
    },

    # ================= L4 组 · 金额与费用 =================
    {
        "id": "L41", "name": "金额与溢短装措辞不清晰", "category": "金额与费用",
        "severity": "warning", "basis": "UCP600 Art.30(a)",
        "check": "金额未标明币别、大小写金额不一致；溢短装措辞含糊（既没写 ABOUT 之类的容差措辞，"
                 "又未明确比例），发票金额极易被认定不符。",
        "fix": "要求明确币别、大小写一致，并写清溢短装比例",
    },
    {
        "id": "L42", "name": "银行费用由受益人承担", "category": "金额与费用",
        "severity": "warning", "basis": "费用条款（实务惯例为各自承担本国费用）",
        "check": "信用证规定开证行或进口国银行费用由受益人承担，或完全未约定费用归属。",
        "fix": "争取改为开证行费用由申请人承担、各自承担本国银行费用",
    },
    {
        "id": "L43", "name": "佣金与折扣条款", "category": "金额与费用",
        "severity": "warning", "basis": "发票金额口径",
        "check": "信用证含佣金、折扣扣减条款，或规定金额已扣佣，发票金额须相应体现。"
                 "若制单时按未扣佣金额出票，即构成不符。",
        "fix": "确认发票金额与佣扣口径一致",
    },

    # ================= L5 组 · 信用证性质 =================
    {
        "id": "L51", "name": "未注明不可撤销或未适用 UCP600", "category": "信用证性质",
        "severity": "error", "basis": "UCP600 Art.1、Art.3",
        "check": "信用证未载明是否不可撤销，或未注明适用 UCP600（或适用规则的表述模糊、"
                 "指向已失效的旧版本）。",
        "fix": "要求明确载明 IRREVOCABLE，并注明适用 UCP600 最新版本",
    },
    {
        "id": "L52", "name": "可转让与保兑要求不明", "category": "信用证性质",
        "severity": "warning", "basis": "信用证性质",
        "check": "信用证性质（可转让、保兑、循环、远期/即期）未明确；"
                 "或为远期信用证而未要求加具保兑，受益人须自行承担开证行到期不付的风险。",
        "fix": "按合同要求明确信用证性质，远期证争取加具保兑",
    },
    {
        "id": "L53", "name": "开证行资信与国别风险", "category": "信用证性质",
        "severity": "warning", "basis": "开证行信用风险",
        "check": "开证行名称未载明或资信不明；开证行所在国存在外汇管制、政治风险或惯常付款延迟。",
        "fix": "核实开证行资信；必要时要求由一流银行开证或加具保兑。本系统不对具体国家作评级结论",
    },
]

_LC_CATEGORY_ORDER = ["软条款", "时间三要素", "单据要求", "金额与费用", "信用证性质"]

# 规则编号里连续区间的简写，例如 R01、R02 → "R01、R02"；R01..R05 → "R01-R05"
_SCOPE_REASON = {
    "pair": "只有一份单证",
    "lc": "未提供信用证条款",
}
_CATEGORY_ORDER = ["数学与金额", "信用证", "当事人", "运输单据", "货描与编码", "日期逻辑", "字符与格式"]


def rules_by_category(rules, order=None):
    """按固定顺序分组，保证每次生成的提示词顺序稳定。

    order 不传就按审核规则的分类顺序；审证规则有自己的顺序（_LC_CATEGORY_ORDER）。
    """
    order = order or _CATEGORY_ORDER
    groups = []
    for cat in order:
        items = [r for r in rules if r["category"] == cat]
        if items:
            groups.append((cat, items))
    # 兜底：将来新增了没登记的分类也别丢
    for cat in sorted(set(r["category"] for r in rules) - set(order)):
        groups.append((cat, [r for r in rules if r["category"] == cat]))
    return groups


# 严重度英文枚举 → 界面中文。与 services/discrepancy.py 的 _SEV_LABEL 保持一致：
# 报告里显示"严重/需改/提示"，速查页必须显示同一套词，两边才对得上
_SEVERITY_CN = {"critical": "严重", "error": "需改", "warning": "提示"}

# scope 翻成人话。速查页要标出来，否则用户不知道某条规则为什么没在自己的单子上生效
_SCOPE_NOTE = {
    "single": "",
    "pair": "需两份以上单证",
    "lc": "需提供信用证条款",
    "pair+lc": "需两份以上单证 + 信用证条款",
}

# 速查页的两大块：R 系列查单证，L 系列查信用证本身
RULE_SERIES = [
    ("单证审核规则", "R 系列", AUDIT_RULES, _CATEGORY_ORDER),
    ("信用证审证规则", "L 系列", LC_RULES, _LC_CATEGORY_ORDER),
]


def rules_catalog():
    """把两张规则表整理成模板直接能渲染的结构（「审核规则」页用）。

    内容一个字节都不复制：分组走 rules_by_category、严重度取自规则本身，
    这里只补展示层需要的中文标签和分组标题。规则表改了，速查页自动跟着改。
    """
    series = []
    for title, prefix, rules, order in RULE_SERIES:
        groups = []
        for category, items in rules_by_category(rules, order):
            groups.append({
                "category": category,
                "rules": [{
                    "id": r["id"],
                    "name": r["name"],
                    "severity": r["severity"],
                    "severity_cn": _SEVERITY_CN.get(r["severity"], r["severity"]),
                    "basis": r["basis"],
                    "check": r["check"],
                    "fix": r["fix"],
                    # scope 是原始取值（single / pair / lc / pair+lc），
                    # 实训练习页要靠它决定哪些规则在本题下不适用而收起；
                    # scope_note 是给人看的中文说明。
                    "scope": r.get("scope", ""),
                    "scope_note": _SCOPE_NOTE.get(r.get("scope", ""), ""),
                } for r in items],
            })
        series.append({
            "title": title,
            "prefix": prefix,
            "count": len(rules),
            "groups": groups,
        })
    return series


def rule_available(rule, has_lc=False, doc_count=1):
    """这条规则在本次输入条件下能不能执行。"""
    needs = set(rule["scope"].split("+"))
    if "single" in needs:
        return True
    if "pair" in needs and doc_count < 2:
        return False
    if "lc" in needs and not has_lc:
        return False
    return True


def _missing_reasons(skipped, has_lc, doc_count):
    """整体汇总本次没执行的原因。

    逐条去拼会重复（纯 pair 规则给"只有一份单证"，pair+lc 规则给"只有一份单证、未提供信用证条款"，
    拼一起就成一串车轱辘话，模型还会原样抄进报告）。
    """
    scopes = set()
    for r in skipped:
        scopes |= set(r["scope"].split("+"))
    reasons = []
    if "pair" in scopes and doc_count < 2:
        reasons.append(_SCOPE_REASON["pair"])
    if "lc" in scopes and not has_lc:
        reasons.append(_SCOPE_REASON["lc"])
    return "、".join(reasons) or "输入条件不满足"


def _digest(ids):
    """把编号压缩成 R01 R02 R03 → R01-R03，报告里不占地方。

    前缀不写死：审核规则是 R，审证规则是 L，按传入的编号自己认。
    """
    if not ids:
        return "无"
    prefix = ids[0][0].upper()
    nums = sorted(int(i[1:]) for i in ids)
    parts, start, prev = [], nums[0], nums[0]
    for n in nums[1:] + [None]:
        if n is not None and n == prev + 1:
            prev = n
            continue
        parts.append("%s%02d" % (prefix, start) if start == prev
                     else "%s%02d-%s%02d" % (prefix, start, prefix, prev))
        if n is not None:
            start = prev = n
    return " ".join(parts)


def build_system_prompt(has_lc=False, doc_count=1, intro=None):
    """按"本次实际能查什么"生成系统提示词。

    只注入可执行的规则，查不了的规则不进提示词（省 token，也免得模型对着
    查不了的规则瞎编），改为在末尾列一份"本次未执行"的清单。
    """
    available = [r for r in AUDIT_RULES if rule_available(r, has_lc, doc_count)]
    skipped = [r for r in AUDIT_RULES if not rule_available(r, has_lc, doc_count)]

    lines = []
    lines.append("你是一名专业的外贸单证审核专家，熟悉 UCP600、ISBP 与贸易术语，"
                 "拥有丰富的国际贸易单证审核经验。")
    lines.append("")
    lines.append("【本次审核范围】")
    lines.append("- 收到：%d 份单证%s" % (doc_count, "；已提供信用证条款" if has_lc else "；未提供信用证条款"))
    lines.append("- 本次可执行的规则共 %d 条（见下）" % len(available))
    if skipped:
        lines.append("- 本次【无法执行】的规则：%s（原因：%s）"
                     % (_digest([r["id"] for r in skipped]),
                        _missing_reasons(skipped, has_lc, doc_count)))
        lines.append("  这些规则本次一律不要下结论，也不要凭空推测没有提供的单证或信用证内容。"
                     "如果相关风险重要，只写在【风险提示】里。")

    lines.append("")
    lines.append("【审核规则】每条都标了编号，发现问题时必须标出命中的编号。")
    for cat, items in rules_by_category(available):
        lines.append("")
        lines.append("### " + cat)
        for r in items:
            lines.append("%s %s（%s）" % (r["id"], r["name"], r["severity"]))
            lines.append("  查：%s" % r["check"])
            lines.append("  改：%s" % r["fix"])

    lines.append("")
    lines.append("【输出格式】严格按照以下结构，不要增删小节：")
    lines.append("")
    lines.append("【单证类型】")
    lines.append("识别出的单证种类")
    lines.append("")
    lines.append("【发现问题】")
    lines.append("只写需要修改的项：严重度 critical 和 error 的规则命中，以及单证本身存在的"
                 "错误、不一致和字段缺失。")
    lines.append("warning 级别的命中、以及因缺少配套单证或信用证条款而无法核查的项，"
                 "一律不要写进本节，只写在【风险提示】里。")
    lines.append("问题1：[规则编号][严重度] 位置 - 问题描述 → 建议修改方式")
    lines.append("问题2：...")
    lines.append("（单证本身没问题就写\"未发现明显错误\"）")
    lines.append("")
    lines.append("【数学验算】")
    lines.append("逐项验算单价×数量是否等于金额、各项合计是否等于总金额。"
                 "如有差异，列出正确计算结果并指出哪个数字错。"
                 "（如无差异则写\"验算通过，各项金额一致\"）")
    lines.append("")
    lines.append("【风险提示】")
    lines.append("列出需要人工复核的项：warning 级别的命中、以及因资料不全而没能完成的核查"
                 "（例如未提供信用证、未提供配套单证导致哪些规则无法执行）。")
    lines.append("")
    lines.append("【审核结论】")
    lines.append("一句话总结对本次单证本身的审核结果，开头给出明确判定词：")
    lines.append("- 单证本身没查出错误，即使缺少配套资料，也写\"通过（单证内部自查未发现问题）\"，"
                 "不要因为资料不全就判为\"需修改\"")
    lines.append("- 单证本身有错，写\"需修改：...\"")
    lines.append("")
    lines.append("【本轮执行】")
    lines.append("执行：本次实际命中的规则编号（没有命中就写\"无命中\"）")
    lines.append("未执行：%s（%s）"
                 % (_digest([r["id"] for r in skipped]),
                    _missing_reasons(skipped, has_lc, doc_count) if skipped else "无"))

    if intro:
        lines.append("")
        lines.append(intro)
    return "\n".join(lines)


# 兼容旧引用：默认按"单份单证、无信用证"生成。
# 真正审核时请用 build_system_prompt(has_lc, doc_count)，不要直接用这个常量。
SYSTEM_PROMPT = build_system_prompt()


def build_lc_review_prompt(deadline_facts=None):
    """审证（信用证体检）的系统提示词。

    与 build_system_prompt 同一套路：规则从 LC_RULES 生成，速查表不手抄。

    deadline_facts 是 services/lc_deadline.py 算好的交单时间结论。传进来就作为
    「已核实事实」注入 —— 日期不让模型自己算，这是跟 OpenNER「验证过才返回」
    学的做法：能算的本地算完，模型只负责解释。模型心算日期经常错一天，
    而交单日晚一天就是真金白银的拒付。
    """
    lines = []
    lines.append("你是一名资深的国际贸易结算专家，精通 UCP600、ISBP 与信用证实务，"
                 "长期为出口企业做审证（审信用证）与改证建议，尤其擅长识别软条款。")
    lines.append("")
    lines.append("【本次任务】")
    lines.append("用户提供的是**信用证原文**（可能是 MT700 报文、银行开证格式或复印件 OCR 文本）。")
    lines.append("请对照下列规则逐条审证，找出对受益人不利的条款并给出改证建议。")
    lines.append("注意：本次审核的对象是信用证本身，不是单据。不要评价货物，也不要要求用户提交单据。")

    lines.append("")
    lines.append("【审证规则】每条都标了编号，发现风险时必须标出命中的编号。")
    for cat, items in rules_by_category(LC_RULES, _LC_CATEGORY_ORDER):
        lines.append("")
        lines.append("### " + cat)
        for r in items:
            lines.append("%s %s（%s）" % (r["id"], r["name"], r["severity"]))
            lines.append("  查：%s" % r["check"])
            lines.append("  改：%s" % r["fix"])

    if deadline_facts:
        lines.append("")
        lines.append("【系统已计算的交单时间】")
        lines.append(deadline_facts)
        lines.append("以上日期结果以系统计算为准，不要重新推算，直接采用。")
        lines.append("但若信用证原文里的日期与上面输入的不一致（例如原文 31D 载明的效期"
                     "与这里用的效期对不上），一律以原文为准，并在报告中明确指出这处"
                     "不一致、提醒用户核对——不要不动声色地按系统输入下结论。")

    lines.append("")
    lines.append("【输出格式】严格按照以下结构，不要增删小节：")
    lines.append("")
    lines.append("【信用证概要】")
    lines.append("逐项列出：开证行 / 申请人 / 受益人 / 金额与币别 / 信用证效期 / 最迟装运日 / "
                 "交单期 / 信用证性质。原文未载明的写\"原文未载明\"，不要猜。")
    lines.append("")
    lines.append("【风险条款】")
    lines.append("只写需要改证的项，即 critical 与 error 级的命中，按严重程度从高到低排列。")
    lines.append("warning 级的命中一律不要写进本节，只写在【风险提示】里。")
    lines.append("问题1：[规则编号][严重度] 信用证位置 - 条款问题说明 → 改证建议")
    lines.append("问题2：...")
    lines.append("（方括号是格式的一部分，照原样写：编号和严重度各自套一层方括号，"
                 "例如 [L12][critical]、[L21][error]；不要写成 L12[critical] 或 L12 critical。"
                 "位置、说明、建议写在同一行，之间用 - 和 → 分隔。）")
    lines.append("（没有风险条款就写\"未发现明显不利条款\"）")
    lines.append("")
    lines.append("【时间安排】")
    lines.append("核查最迟装运日、交单期、效期三者是否衔接合理，是否存在双到期。")
    lines.append("系统已提供计算结果的，直接采用该结果说明，不要自行重算日期。")
    lines.append("")
    lines.append("【单据要求清单】")
    lines.append("把信用证要求的单据逐条列成清单，每条一行，包含：单据名称 / 份数 / 特殊要求 / "
                 "受益人能否满足。这一节是给用户照着准备单据用的，要完整，不要只列有问题的。")
    lines.append("")
    lines.append("【风险提示】")
    lines.append("warning 级条款、以及需要人工向银行或客户核实的项（如开证行资信）。")
    lines.append("")
    lines.append("【审核结论】")
    lines.append("一句话总结，开头给出明确判定词：")
    lines.append("- 没查出需要改证的条款，写\"可接受：未发现明显不利条款\"")
    lines.append("- 有需要改证的条款，写\"建议改证：...\"，并点明最要紧的一两条")
    lines.append("")
    lines.append("【本轮执行】")
    lines.append("执行：本次实际命中的规则编号（没有命中就写\"无命中\"）")
    return "\n".join(lines)


# 从信用证原文抽取那 14 个结构化字段（体检完一键回填到审单表单用）。
# 输出必须是纯 JSON，所以单独一次调用，和体检报告分开 —— 混在一起会让模型
# 在正文里夹一段 JSON，解析起来很脆。
LC_FIELD_KEYS = [
    "lc_amount", "lc_expiry", "lc_applicant", "lc_partial", "lc_transship",
    "lc_shipment_date", "lc_freight_terms", "lc_originals", "lc_consignee",
    "lc_description", "lc_measurement", "lc_base_qty", "lc_tolerance_pct",
    "lc_tolerance_clause",
]

LC_FIELDS_PROMPT = """你是一名信用证信息抽取助手。请从用户提供的信用证原文中抽取下列字段，只输出一个 JSON 对象，不要输出任何解释文字、不要用代码块包裹。

字段说明：
- lc_amount：信用证金额，含币别，照抄原文（例如 "USD 100,000.00"；原文写了 ABOUT 等措辞也照抄）
- lc_expiry：信用证效期或最迟交单日，统一转成 YYYY-MM-DD
- lc_applicant：申请人名称与地址
- lc_partial：分批装运，只填 "允许" 或 "禁止"（ALLOWED/PERMITTED 对应允许，NOT ALLOWED/PROHIBITED 对应禁止）
- lc_transship：转运，只填 "允许" 或 "禁止"，同上
- lc_shipment_date：最迟装运日，统一转成 YYYY-MM-DD
- lc_freight_terms：只填 "FREIGHT PREPAID" 或 "FREIGHT COLLECT"
- lc_originals：要求的正本份数，只填数字
- lc_consignee：提单收货人措辞，照抄原文（例如 "TO ORDER OF ABC BANK"）
- lc_description：信用证规定货物描述中必须包含的字句，照抄原文
- lc_measurement：计量单位，只填 "CBM" 或 "CFT"
- lc_base_qty：信用证规定的基准数量，只填数字（不要单位）
- lc_tolerance_pct：溢短装比例，只填数字（10% 填 "10"）
- lc_tolerance_clause：溢短装条款原文

任何一项在原文中找不到或无法确定，该字段填空字符串 ""，不要编造。
原文中跨行的字段值请用单个空格连成一行（同一行内原本的换行位置不要粘连成
"PCSPI" 这样的词）。
日期的写法可能五花八门（15 SEP 2026、20260915、26 年 9 月 15 日等），一律归一化成 YYYY-MM-DD。

必须输出的 14 个键：""" + "、".join(LC_FIELD_KEYS)


COMPARE_PROMPT = """你是一名专业的外贸单证审核专家。请对比以下两份单证内容，找出差异和不一致之处。

对比时请重点检查：
1. 货物品名是否一致
2. 数量是否一致
3. 金额是否一致
4. 收发货人信息是否一致
5. 其他关键字段是否匹配（日期、贸易术语、运输方式、启运港/目的港、唛头、包装方式等）

输出格式严格按照以下结构：

【对比结论】
一致 / 不一致（如果一致，后面各节无需列出差异项）

【差异项】
差异1：[字段名] - 单证A显示：XXX - 单证B显示：XXX - 建议核查
差异2：...

【风险提示】
列出因数据不一致可能导致的清关、收付款、退税等风险

【建议】
给出具体修改建议"""
