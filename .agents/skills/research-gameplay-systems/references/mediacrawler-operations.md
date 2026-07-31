# 使用当前 Fork 采集研究材料

本文对应仓库 `TongYOuO/MediaCrawler`，核对基线为 2026-07-29。运行前先检查当前提交和 `uv run main.py --help`，平台接口可能随时变化。七平台本机实抓结果见 [platform-smoke-test-2026-07-29.md](platform-smoke-test-2026-07-29.md)。

## 目录

1. 能力和限制
2. 环境准备
3. 研究型安全配置
4. 搜索、详情与作者模式
5. 平台差异
6. 输出和归档
7. 常见故障

## 1. 能力和限制

当前支持 `xhs/dy/ks/bili/wb/tieba/zhihu`，七个平台都存在 `search/detail/creator` 运行路径，也都有一级和二级评论采集逻辑；登录方式为 `qrcode/phone/cookie`。这表示当前代码具备相应能力，不表示平台接口长期稳定或任何查询都一定返回数据。小黑盒没有适配器。

对于深度玩法研究，MediaCrawler 的搜索结果、标题、简介、互动量和评论属于 `D0 候选发现`。B站必须继续获取完整字幕/ASR，知乎必须获取完整回答/文章正文，才形成可供论证的 `L0 原始内容`。采集成功不等于研究证据充分。

2026-07-29 按“搜索内容落盘＋一级评论落盘＋单条详情复抓”严格测试，小红书、抖音、B站和微博通过，状态为 `4/7 PASS`。知乎随后在标准 Playwright＋人工登录下完成“搜索全文落盘→L0 分段”，记为 `PARTIAL-DEEP-TEXT`，但尚未按严格标准复测评论＋详情；快手、贴吧未通过。

这个 Fork 的重要差异：

- 默认 `SAVE_DATA_OPTION = "jsonl"`。
- CLI 支持关键词、指定内容、指定作者、评论数量、并发和输出目录覆盖。
- `--creator_id` 能覆盖小红书、抖音、快手、B站、微博、贴吧和知乎的作者列表。
- `--enable_cdp_mode yes/no` 可在 CDP 与标准 Playwright 浏览器之间切换，便于平台兼容性对照。
- 小红书、抖音、B站作者 ID 在内容和评论存储时转为匿名哈希，昵称脱敏。
- 教学版不持久化创作者完整画像、粉丝/关注关系，避免不必要的个人信息收集。
- 数据库模式首次运行自动建表。

许可证只允许非商业学习研究，不允许商业用途或大规模采集。公司使用前先取得授权或换用获准接口。

## 2. 环境准备

仓库声明 Python 3.11，推荐使用锁定环境：

```powershell
uv sync
node --version
uv run python --version
```

如果仓库默认的清华 PyPI 镜像对某个锁定包返回 `403 Forbidden`，先不要删除 `uv.lock`。可在当前 PowerShell 会话临时切换官方源：

```powershell
$env:UV_DEFAULT_INDEX = "https://pypi.org/simple"
uv sync
```

新版 `uv` 可能顺带更新 lock revision，并把锁文件中的下载源改成官方 PyPI。若本次目的只是创建本地环境，不要把大面积 `uv.lock` 源地址变化误当成依赖升级；提交前逐项检查该 diff。

抖音相关签名处理需要 Node.js，README 要求 Node >= 16。

默认启用 CDP 并连接现有 Chrome：

```python
ENABLE_CDP_MODE = True
CDP_CONNECT_EXISTING = True
CDP_DEBUG_PORT = 9222
```

在 Chrome `chrome://inspect/#remote-debugging` 中允许远程调试。程序弹出连接确认时，在 60 秒内接受。使用默认 CDP 模式无需安装 Playwright 浏览器；将 `ENABLE_CDP_MODE` 设为 `False` 后才需要：

```powershell
uv run playwright install
```

不要把 Cookie 写入文档、命令历史或 Git。优先二维码/人工登录和本地登录态。

## 3. 研究型安全配置

在 `config/base_config.py` 中保持低频小样本：

```python
SAVE_DATA_OPTION = "jsonl"
CRAWLER_MAX_NOTES_COUNT = 15
MAX_CONCURRENCY_NUM = 1
ENABLE_GET_COMMENTS = True
CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES = 10
ENABLE_GET_SUB_COMMENTS = False
ENABLE_GET_MEIDAS = False
CRAWLER_MAX_SLEEP_SEC = 2
```

原则：

- 全景阶段每个查询先抓少量内容，不默认下载媒体。
- `CRAWLER_MAX_NOTES_COUNT` 不是所有平台的严格条数截断；小红书、B站和微博的搜索可能处理完整首屏。最低风险冒烟应先 `--get_comment no`，再对一条结果用 `detail` 测评论。
- 深挖阶段再对已选内容使用 `detail`，按需开启二级评论或媒体。
- 不要为了“样本更多”立即启用代理池和高并发。
- `DISABLE_SSL_VERIFY=True` 只用于明确的本地中间人代理调试，会降低传输安全，不作为普通故障修复。

## 4. 搜索、详情与作者模式

### 4.1 搜索

PowerShell 示例：

```powershell
uv run main.py --platform xhs --lt qrcode --type search `
  --keywords "游戏名 攻略,游戏名 核心机制,游戏名 进阶误区" `
  --crawler_max_notes_count 15 `
  --max_comments_count_singlenotes 10 `
  --get_comment yes `
  --get_sub_comment no `
  --max_concurrency_num 1 `
  --save_data_option jsonl `
  --save_data_path "research-cases/游戏名/raw"
```

将 `--platform` 改为 `dy`、`ks`、`bili`、`wb`、`tieba` 或 `zhihu` 分批运行。不要混用平台指标；每次运行记录平台、查询、排序和采集时间。七个平台是候选来源池，应按问题和平台内容形态分配样本，不要求等量采集。

正式研究前不要一次并行启动七个平台。逐平台使用独立输出目录，并将“浏览器启动、登录、搜索内容、一级评论、详情内容、详情评论”六项分别记为通过或失败。

### 4.2 指定内容深挖

```powershell
uv run main.py --platform bili --lt qrcode --type detail `
  --specified_id "BV号或完整URL" `
  --get_comment yes `
  --get_sub_comment yes `
  --max_comments_count_singlenotes 50 `
  --save_data_path "research-cases/游戏名/raw"
```

`--specified_id` 支持逗号分隔列表，并能覆盖七个平台的详情配置。小红书详情 URL 必须包含有效的 `xsec_token` 和 `xsec_source`；从当前搜索结果复制完整 URL，不要只保存 note ID。

B站视频正文不要依赖 MediaCrawler 的标题/简介字段。对已入选的 BV 号生成完整时间戳 L0：

```powershell
python .agents/skills/research-gameplay-systems/scripts/extract_bilibili_l0.py `
  --video "BV号或URL" `
  --output "research-cases/游戏名/l0-private/bili/BV号" `
  --asr --asr-model small --language auto --beam-size 1 --device auto
```

先用 `small/auto/beam-size 1` 形成可审读稿；只有关键术语确实需要且 GPU 运行已验证时再用 `large-v3` 重转。脚本默认拒绝 `large-v3` 在 CPU 上运行，避免一条长视频占用数小时；确认接受成本后才显式传 `--allow-large-cpu`。

知乎 JSONL 只有在回答/文章记录包含完整 `content_text` 时才可升级为 L0：

```powershell
uv run python .agents/skills/research-gameplay-systems/scripts/build_zhihu_l0.py `
  --input "research-cases/游戏名/raw/zhihu/zhihu_contents.jsonl" `
  --output "research-cases/游戏名/l0-private/zhihu"
```

详细筛选、验收和证据升级规则见 [deep-evidence-workflow.md](deep-evidence-workflow.md)。

### 4.3 指定作者

```powershell
uv run main.py --platform dy --lt qrcode --type creator `
  --creator_id "作者主页URL或平台ID" `
  --crawler_max_notes_count 20 `
  --save_data_path "research-cases/游戏名/raw"
```

本 Fork 会停止落库创作者完整画像，因此作者模式应服务于“定位其公开作品”，而不是建立个人画像。

知乎作者模式可直接传公开作者主页 URL：

```powershell
uv run main.py --platform zhihu --lt qrcode --type creator `
  --creator_id "https://www.zhihu.com/people/公开作者token" `
  --crawler_max_notes_count 20 `
  --save_data_path "research-cases/游戏名/raw"
```

## 5. 平台差异

### 5.1 小红书

- 排序由 `config/xhs_config.py` 的 `SORT_TYPE` 控制；默认是 `popularity_descending`。
- 热门扫描后应再用其他排序或人工补充最新/中长尾样本。
- 指定笔记和作者 URL 依赖 `xsec_token`；过期或缺失会导致详情为空或 JSON 解析错误。
- 图文攻略的关键步骤可能只在图片中；结构化文本抓取成功不代表证据完整。
- 实测即使 `crawler_max_notes_count=1`，搜索仍处理完整首屏；不要在首次冒烟时同时打开搜索评论。

### 5.2 抖音

- 发布时间筛选由 `config/dy_config.py` 的 `PUBLISH_TIME_TYPE` 控制。
- 指定内容支持完整 URL、带 `modal_id` URL、短链和纯作品 ID。
- 短视频常缺少前置条件；下载/转写只对深挖样本进行。
- 扫码后仍可能出现手机验证，应由用户在可见浏览器中人工完成，不自动绕过。
- 当前实测应将 `ENABLE_CDP_MODE=False` 并安装 Playwright Chromium；Chrome 150/CDP 首页导航失败。
- 自动登录使用的 DOM 已过期，可能被全屏登录层或 `uc-second-verify` 遮罩拦截。先人工保存登录态，再运行搜索；不要尝试绕过验证。

### 5.3 快手

- 指定作品和作者都支持完整 URL 或纯 ID；优先保存原始完整 URL，方便回溯来源语境。
- 研究价值集中在短视频操作示范和高频实用技巧，片段通常缺失模式、段位、配装或版本前置条件。
- 与抖音分开记录查询位置和互动指标，不跨平台相加或直接比较。

### 5.4 B站

- `BILI_SEARCH_MODE="normal"` 时不使用 `START_DAY/END_DAY`。
- 时间范围模式为 `all_in_time_range` 或 `daily_limit_in_time_range`。
- `MAX_NOTES_PER_DAY` 默认只有 1；切换时间范围模式却忘记调整，会误以为搜索漏数据。
- 普通搜索内部页面大小固定为 20；即使 CLI 把 `crawler_max_notes_count` 设为小于 20，也会提升到至少 20。
- 当前 Fork 在 API 返回 `bvid` 时保存标准 BV URL，便于将候选直接交给详情抓取和 L0 转写脚本；旧 JSONL 中的 `av<aid>` 仍可交给 L0 脚本解析。
- 标题和简介不能替代视频内容；深挖样本需要字幕、转写或逐帧记录。
- 同一平台、同一浏览器 Profile 的爬虫必须串行运行；并发连接会争用 Profile/Context，出现 `TargetClosedError`、Profile lock 或相互关闭浏览器。

### 5.5 微博

- `config/weibo_config.py` 的 `ENABLE_WEIBO_FULL_TEXT=True` 会让搜索结果逐条请求详情，正文更完整，但也会提高触发风控的概率。
- 全景冒烟阶段若只需发现话题，可临时关闭全文；深挖选定帖子后再用 `detail` 获取完整内容。
- 转发和重复表述不能当独立证据；按原帖 ID、URL 和文本相似度去重。
- 明确的“没有评论”响应当前会被当成错误反复重试；首屏 16 条内容的低频测试也可能运行数分钟。

### 5.6 贴吧

- `TIEBA_SPECIFIED_ID_LIST` 接受帖子 ID；CLI 也会把常见帖子 URL 规范化为 ID。
- 作者模式接受主页 URL或 portrait ID；CLI 会规范化后写入 `TIEBA_CREATOR_URL_LIST`。
- 楼中楼是理解争论和反例的关键，但默认不开启二级评论；只在深挖帖上显式启用并保留父子关系。
- 长期帖子容易混合多个版本，必须同时记录主帖、楼层和回复发布时间。

### 5.7 知乎

- 指定内容支持回答、专栏文章和 `zvideo` URL；保存内容类型，避免把不同媒介结构强行统一。
- 作者模式可用 CLI `--creator_id` 覆盖 `ZHIHU_CREATOR_URL_LIST`，建议优先跟踪已筛选的公开专业作者，而不是无边界全站搜索。
- 当前 Fork 会把知乎固定 20 条的 API 首屏按 `--crawler_max_notes_count` 截断后再落盘和抓评论，低频小样本不再被强制扩大到整页。
- 知乎一级评论会严格遵守 `--max_comments_count_singlenotes`，不会因 API 页大小默认为 10 而意外抓完整页。
- 知乎日志只打印候选数量、内容 ID、类型和正文长度，不再把整篇文章输出到终端；全文只进入本地 JSONL/L0 包。
- 落盘的 `content_text` 是 `extract_text_from_html` 的产物，正则删除全部标签，**配图、动图和公式的 URL 在写入前就已丢失**；知乎适配器没有 media 分支，`ENABLE_GET_MEIDAS` 对知乎无效。深度材料须用 `scripts/extract_zhihu_media.py` 重新打开原页、从 `js-initialData` 取原始正文 HTML 后恢复，详见 [deep-evidence-workflow.md](deep-evidence-workflow.md) 第 5.1 节。
- 搜索接口返回的回答/文章记录已含完整 `content`，因此一次 `search` 就能同时得到点赞数和全文；不必为了拿正文再跑一遍 `detail`，`detail` 主要用于补评论。
- 互动量在部分题材上与分析深度负相关。舆情型问题（争议、差评风波）会把高赞位占满，机制拆解和源码分析常年停在个位数赞。只按点赞阈值筛选会系统性漏掉深度材料，应同时用正文长度或标题命中做并集。
- 问题与回答可能跨越多年；发布日期、编辑时间和适用游戏版本分别核对。
- 长文逻辑完整仍只是观点证据，关键机制主张应回到录像、规则、补丁或可复现实验验证。

## 6. 输出和归档

设置 `--save_data_path <case>/raw` 后，文件位于：

```text
<case>/raw/<platform>/<format>/<crawler_type>_<item_type>_<date>.<format>
```

实际平台目录可能是 `xhs`、`douyin`、`bili` 等存储实现名称。JSONL 每行一条记录，便于追加、流式处理和保留原始快照。

内容记录已包含平台业务 ID、标题/正文、匿名作者、互动量、来源关键词和 URL；评论记录通过内容 ID 与正文关联。仍需在研究案例中另存：

- 运行命令或配置快照。
- 搜索排序与结果位置。
- 游戏版本与研究者判断。
- 视频/图片转写的时间戳或画面位置。

不要提交：

- Cookie、`.env`、浏览器用户目录。
- 原始手机号、身份或关系链。
- 未经授权的大体量视频、图片和完整转载正文。

## 7. 常见故障

| 现象 | 先检查 | 处理 |
|---|---|---|
| CDP 连接超时 | Chrome 是否允许远程调试、9222 是否监听、是否确认弹窗 | 保持浏览器可见并人工确认；必要时改用项目自动启动浏览器 |
| 扫码成功但仍失败 | 是否有滑块、手机号验证或登录态失效 | 关闭无头，人工完成验证；不要自动绕过 |
| 小红书详情为空/JSON 错误 | URL 是否带当前有效 `xsec_token/xsec_source` | 从同一登录态下的搜索结果复制完整 URL |
| B站时间搜索结果过少 | `BILI_SEARCH_MODE`、日期范围、`MAX_NOTES_PER_DAY` | 明确选择模式并提高每日上限；记录该配置 |
| B站旧搜索结果只有 `av...` URL | 旧记录生成于标准 BV URL 修复之前 | 直接把 `av...` 交给 L0 脚本，或从 view API/页面补得 BV 后再跑 MediaCrawler detail |
| B站 ASR 报 `cublas64_12.dll`/cuDNN 缺失 | Windows 未搜索 pip 安装的 `site-packages/nvidia/*/bin` | L0 脚本会注册 DLL 目录并在失败时回退 CPU；检查 `metadata.json` 的设备与回退原因 |
| B站媒体 CDN 在 TLS 握手时报超时 | 临时网络/CDN 节点不稳定，元数据 API 仍可能正常 | L0 脚本有限重试 3 次并清理残片；仍失败就换时段重跑，不把空目录或半截媒体登记为 L0 |
| B站视频页面 35 分钟，但 ASR 只到 11 分钟 | CDN 返回了可正常结束、但时长不足的媒体文件 | 当前脚本在 ASR 前用 `ffprobe` 对照页面时长，低于 90% 直接失败；重新取得播放 URL，不登记旧包 |
| B站标题或 ASR 出现 `ã€...` / `´ó¼Ò...` | UTF-8 或 GBK 字节被按 Latin-1 解码 | 当前脚本按中文可读性修复常见模式；仍要抽查角色名、数值、否定词，不把自动修复当内容校对 |
| 英文访谈被转成“通顺的繁体中文”且时长覆盖正常 | 强制 `--language zh` 会让 ASR 在错误语言上幻听；覆盖率只证明媒体完整 | 默认使用 `--language auto`，或已知语言显式传 `en/zh`；抽查开头、中段、结尾并记录 detected language |
| `large-v3` 转写长视频数小时无输出 | CUDA 运行时失败后落到 CPU，模型和 beam 过重 | 默认已禁止 large-v3 CPU；先用 `small --beam-size 1` 审读，只有关键样本再在已验证 GPU 上升级；显式 `--allow-large-cpu` 表示接受成本 |
| 同平台第二条爬虫报 Profile lock/`TargetClosedError` | 两个任务复用同一个 Playwright/CDP Profile | 停止第二条任务并串行运行；不同输出目录不能隔离浏览器 Profile |
| 停止二维码爬虫后相册/WPS 也被关闭 | 临时二维码 PNG 由系统关联程序打开，可能成为爬虫进程树子进程 | 只精确停止已核对命令行的爬虫进程；清理进程树前先列出子进程，避免误关用户正在使用的查看器 |
| 微博搜索很快触发验证或失败 | `ENABLE_WEIBO_FULL_TEXT=True` 导致逐帖详情请求 | 全景阶段按需关闭全文，小样本运行；选中内容后再 detail |
| 微博无评论帖子重复报错、运行很慢 | “无评论”文本被当成 `DataFetchError` 重试 | 测试时选择已知有评论内容；后续把明确空响应改为空列表 |
| 贴吧只看到主楼或一级回复 | 二级评论默认关闭 | 深挖阶段显式 `--get_sub_comment yes`，并保留父回复 ID |
| 知乎 CDP 在创建页面前 `TargetClosedError` | Chrome/CDP Context 生命周期或版本兼容 | 用 `--enable_cdp_mode no` 切换标准 Playwright 浏览器对照，并保留独立本地登录态 |
| 知乎已有登录态却突然进入扫码、随后找不到二维码 | `pong` 可能因 `ReadTimeout` 被当作未登录；登录页二维码 DOM 也可能已变化 | 先把网络超时与明确未登录响应分开；不要因一次超时清空登录结论，更新 `canvas.Qrcode-qrcode` 选择器后再复测 |
| 只得到内容没有评论 | `--get_comment`、评论上限、平台返回权限 | 先以一个公开内容做 detail 冒烟测试 |
| 二级评论缺失 | 默认关闭，或一级评论无回复 | 深挖阶段显式 `--get_sub_comment yes`，控制单帖上限 |
| 输出目录找不到 | `SAVE_DATA_PATH` 后仍按平台/格式分层 | 从指定目录递归查找当天 JSONL |
| 重复数据 | JSONL 是追加写入 | 每次实验使用独立案例目录；分析阶段按平台业务 ID 去重 |
| 命令参数看似无效 | 平台专属参数仍在配置文件 | 运行 `uv run main.py --help`，再检查对应 `config/*_config.py` |
| 接口突然失败 | 平台页面/API 变化、Cookie 失效或项目版本变化 | 小样本冒烟测试；记录提交号；不要用加并发掩盖适配故障 |
| `uv sync` 下载包返回 403 | 默认清华镜像缺包、缓存路径失效或镜像拒绝 | 当前会话临时设 `UV_DEFAULT_INDEX=https://pypi.org/simple`；保留锁文件并检查是否产生纯源地址改写 |
| 旧提交在 Windows 上 `test_no_user_info.py` 调用 `grep` 失败 | 测试依赖 GNU grep | 当前 Fork 已改为纯 Python 扫描；旧提交可在 Git Bash/WSL 复验 |
| Skill 工具读取中文报 GBK 错误 | Windows 默认编码不是 UTF-8 | 在当前 PowerShell 命令设置 `$env:PYTHONUTF8='1'` 后重跑，不修改全局环境 |
| 知乎 L0 里一张配图都没有 | `content_text` 是删标签后的纯文字，不是缺陷而是设计 | 用 `extract_zhihu_media.py` 从原页 `js-initialData` 恢复；不要去改 `extract_text_from_html`，其他平台依赖它 |
| 恢复出的知乎配图数量刚好翻倍 | 知乎为每张图额外输出一份 `<noscript>` 副本 | 当前脚本已剥离 `<noscript>`；自建解析时必须同样处理，否则体量和引用都会翻倍 |
| 知乎配图下载得到模糊小图 | 取了 `src`（懒加载缩略图）而不是 `data-original` | 按 `data-original` → `data-actualsrc` → `src` 的顺序取全分辨率 |
| 解析知乎 JSONL 报 `Unterminated string` | 正文含 U+2028/U+0085，`str.splitlines()` 会在这些字符处切断记录 | 按 `\n` 迭代文件句柄，不要用 `splitlines()` |
| 抖音/快手首页 `Page.goto` 报 `ERR_ABORTED` 或 30 秒超时 | Chrome 150/CDP 导航兼容问题 | 安装 Playwright Chromium，临时设 `ENABLE_CDP_MODE=False` 对照；抖音已在该路径通过，快手搜索仍为空 |
| 抖音登录按钮点击超时 | 页面 DOM 已变化，登录遮罩或 `uc-second-verify` 拦截旧选择器 | 保持可见窗口人工完成验证并保存登录态；不绕过验证；更新登录选择器后再自动化 |
| 快手登录成功但搜索无输出 | GraphQL 搜索返回无数据 | 用宽/窄两个关键词复验；当前测试保持 FAIL，检查响应结构和参数后再启用 |
| 贴吧百度入口和直连都超时 | 访问路径或当前网络/CDP 环境异常 | 分别记录百度入口和贴吧直连错误；修复前保持 FAIL |
| 知乎 `browser_context.new_page()` 报 `TargetClosedError` | CDP 浏览器/Context 在创建页前退出 | 检查 Context 生命周期和浏览器进程；修复后重跑完整闭环 |
| 额外诊断后主爬虫报 `TargetClosedError` | 第二个 Playwright CDP 客户端调用了 `browser.close()` | 不对共享测试浏览器调用 `browser.close()`；只读诊断不要改变 Context 生命周期 |
| 中止桌面命令后 JSONL 仍追加 | 只停止了外层 PowerShell，子 Python 仍在运行 | 用完整命令行和独立 Profile 精确定位测试进程；按业务 ID 去重 |
