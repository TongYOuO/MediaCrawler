# 《原神》玩法研究证据升级示例

这是 `research-gameplay-systems` Skill 的真实案例，专门演示一次重要纠错：搜索结果、标题、互动量和评论只能形成 D0 候选发现，不能冒充高阶玩家或策划的深度分析。原有报告保留为“待验证研究假设”，新增 B站/知乎完整内容的 L0 升级记录。

## 本例包含

- [research.md](research.md)：由 D0 社区材料形成的两阶段研究假设，不是完成的深度结论。
- [deep-evidence-upgrade.md](deep-evidence-upgrade.md)：D0→L0→L1/L2 的真实升级过程、原始证据位置与筛选结论。
- [deep-source-register.csv](deep-source-register.csv)：B站/知乎深度候选评分和纳入决定。
- [l0-manifest.csv](l0-manifest.csv)：本地完整原文/转写的 URL、定位和哈希；全文不进 Git。
- [collection-summary.md](collection-summary.md)：采集数量、启发式编码与偏差说明。
- [source-register.csv](source-register.csv)：本例实际使用的来源登记。
- [evidence-ledger.csv](evidence-ledger.csv)：旧版 D0 假设账本；其中评论条目不能升级为机制/设计 L0。
- [keyword-matrix.csv](keyword-matrix.csv)：已执行与待补查询。
- [collection-log.csv](collection-log.csv)：四个平台的实际采集方式与结果。
- [case.json](case.json)：案例元数据。

## 数据边界

- 社区快照采集于 2026-07-29，查询词只有 `原神 攻略`，使用平台默认搜索排序。
- 去重后包含 73 条公开内容和 67 条一级评论；评论采集上限很低，不能代表总体玩家分布。
- 原始 JSONL、Cookie、登录态、作者昵称、媒体文件和带访问令牌的 URL 不进入 Git。
- 原先 73 条内容＋67 条评论全部降为 D0；它们可以发现问题和反例，不能证明玩法机制、设计意图或高阶玩家共识。
- 2026-07-29 的知乎实抓已取得回答/文章全文，并转成带原始 JSONL 行号、段落 ID 和 SHA256 的本地 L0；完整正文位于 `G:\GDC\.deep-evidence\genshin\zhihu-l0-run2`，不进入 Git。
- B站 L0 使用完整字幕/ASR 和时间戳；Git 只保存必要的短切片、释义、定位与哈希，不保存视频或全文转写。
- 本例仍没有直接游玩、官方规则核对或玩家访谈，因此正文中的玩法结论保持为待验证假设。
- 社区样本中的版本名称和未来内容没有独立核验；本例不据此判断游戏当前版本事实。

## 如何复用

先读 [深度证据工作流](../../references/deep-evidence-workflow.md)，再复制 [方法说明＋空白模板](../../assets/gameplay-research-template.md)。不要把本例的《原神》假设直接套到其他游戏，也不要把“长文/长视频”自动等同于“专家材料”。
