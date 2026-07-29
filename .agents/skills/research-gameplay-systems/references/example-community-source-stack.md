# 示例：玩家攻略数据源与开源方案评估

> 这是 2026-07-29 的技术选型快照，用来示范怎样记录候选、边界和决策。Stars 和最近提交会变化，复用前重新查询 GitHub。

## 1. 研究问题

怎样采集小红书、抖音、B站和小黑盒上的公开游戏攻略，为游戏系统与核心玩法研究建立可追溯语料？

## 2. 候选项目快照

| 项目 | 当时能力 | 当时活跃度 | 判断 |
|---|---|---|---|
| `NanmiCoder/MediaCrawler` | 小红书、抖音、B站等关键词、详情、作者和评论 | 约 5.9 万 Stars；2026-07-24 有推送 | 研究型 MVP 主入口 |
| `apify/crawlee-python` | 通用队列、重试、浏览器和结构化抓取 | 约 9400 Stars；持续更新 | 自建长期适配器底座 |
| `g1879/DrissionPage` | 浏览器与请求协同 | 约 1.2 万 Stars；持续更新 | 小黑盒半自动适配候选 |
| `Evil0ctal/Douyin_TikTok_Download_API` | 抖音/快手/TikTok/B站解析下载 | 约 1.9 万 Stars；主要提交停在 2025-10 | 只作已知 URL 媒体补充 |
| `yt-dlp/yt-dlp` | 多站音视频下载 | 约 18 万 Stars；持续更新 | 视频深挖阶段的下载器 |
| `ReaJason/xhs` | 小红书 Web 请求封装 | 约 2200 Stars；主要提交停在 2025-07 | 参考实现，不作为唯一底座 |
| `Nemo2011/bilibili-api` | B站常用 API SDK | 约 4200 Stars；检查时已归档 | 不再作为新系统主依赖 |

重新核验示例：

```powershell
$repos = @(
  'NanmiCoder/MediaCrawler',
  'apify/crawlee-python',
  'g1879/DrissionPage',
  'yt-dlp/yt-dlp'
)

foreach ($repo in $repos) {
  Invoke-RestMethod "https://api.github.com/repos/$repo" `
    -Headers @{ 'User-Agent' = 'gameplay-research' } |
    Select-Object full_name, stargazers_count, pushed_at, archived, license
}
```

不要只看 Stars。至少检查最近推送、归档状态、开放 Issue、许可证、是否抓“搜索＋详情＋评论”，以及项目只是下载器还是完整采集器。

## 3. 小黑盒结论

GitHub 上当时只有零散小项目：

- `gehongyan/HeyBox.Net`：小规模的非官方 .NET API 实现，不是成熟攻略语料采集系统。
- `LSM2016/HeyBox_Bilibili_spider`：2019 年小型专项爬虫。
- `half-ghost/steam_crawler_bot`：2022 年归档，面向游戏搜索和折扣。

没有找到同时满足热门、活跃、社区攻略搜索和评论采集的通用项目。因此不应把小黑盒强行塞进 MediaCrawler；先用人工检索＋URL登记＋半自动提取，确有持续需求后再单独实现 `HeyboxAdapter`。

## 4. 最终架构决策

```text
XiaohongshuAdapter ─┐
DouyinAdapter ──────┤
BilibiliAdapter ────┼→ 原始 JSONL → 规范化证据库 → OCR/ASR → 玩法编码 → 调研文档
HeyboxAdapter ──────┘
```

- 小红书、抖音、B站：用当前 MediaCrawler 验证研究流程。
- 小黑盒：保持半自动，避免依赖无人维护的项目。
- 视频：只对深挖样本用 yt-dlp/faster-whisper。
- 图片：只对关键图文用 PaddleOCR。
- 分析：作者可信度与观点证据强度分开，不用纯词频或情感分析替代玩法推理。

## 5. 为什么不做“一键抓完后直接让 LLM 总结”

1. 平台推荐和搜索结果不是随机样本。
2. 热门内容代表传播成功，不等于玩法主张正确。
3. 视频关键条件常不在标题和简介中。
4. 同一攻略会跨平台转载，不能算多条独立证据。
5. 旧版本攻略可能在新版本继续获得流量。
6. LLM 能编码主张，但无法替代版本核对、复现和反例检查。

## 6. 本次决策的适用边界

这个方案面向低频、公开、小样本的个人学习研究。MediaCrawler 的非商业许可证不适合作为未授权的商业生产底座；正式公司系统应优先使用获准开放接口、合法数据供应商、用户授权导出或自建合规适配器。
