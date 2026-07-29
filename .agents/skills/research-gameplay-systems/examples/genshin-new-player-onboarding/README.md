# 《原神》新手开荒认知负荷调研示例

这是 `research-gameplay-systems` Skill 的完整示例，演示怎样用“两阶段：快速全景扫描 → 关键玩法深拆”处理一批真实社区材料，并把 GDC 分享作为分析透镜。

## 本例包含

- [research.md](research.md)：完成版调研文档。
- [collection-summary.md](collection-summary.md)：采集数量、启发式编码与偏差说明。
- [source-register.csv](source-register.csv)：本例实际使用的来源登记。
- [evidence-ledger.csv](evidence-ledger.csv)：核心证据及其支持边界。
- [keyword-matrix.csv](keyword-matrix.csv)：已执行与待补查询。
- [collection-log.csv](collection-log.csv)：四个平台的实际采集方式与结果。
- [case.json](case.json)：案例元数据。

## 数据边界

- 社区快照采集于 2026-07-29，查询词只有 `原神 攻略`，使用平台默认搜索排序。
- 去重后包含 73 条公开内容和 67 条一级评论；评论采集上限很低，不能代表总体玩家分布。
- 原始 JSONL、Cookie、登录态、作者昵称、媒体文件和带访问令牌的 URL 不进入 Git。
- 本例没有直接游玩、录像观察、官方规则核对或玩家访谈，因此关于实际新手体验的结论最高为“中等置信度”，主要价值是展示研究方法。
- 社区样本中的版本名称和未来内容没有独立核验；本例不据此判断游戏当前版本事实。

## 如何复用

先复制 Skill 的 [方法说明＋空白模板](../../assets/gameplay-research-template.md)，再根据自己的研究问题建立独立案例。不要把本例的《原神》结论直接套到其他游戏。
