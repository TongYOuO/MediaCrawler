# 使用当前 Fork 采集研究材料

本文对应仓库 `TongYOuO/MediaCrawler`，核对基线为 2026-07-29、提交 `17f6612`。运行前先检查当前代码和 `uv run main.py --help`，平台接口可能随时变化。

## 目录

1. 能力和限制
2. 环境准备
3. 研究型安全配置
4. 搜索、详情与作者模式
5. 平台差异
6. 输出和归档
7. 常见故障

## 1. 能力和限制

当前支持 `xhs/dy/ks/bili/wb/tieba/zhihu`，运行模式为 `search/detail/creator`，登录方式为 `qrcode/phone/cookie`。研究流程主要使用小红书、抖音和 B站；小黑盒没有适配器。

这个 Fork 的重要差异：

- 默认 `SAVE_DATA_OPTION = "jsonl"`。
- CLI 支持关键词、指定内容、指定作者、评论数量、并发和输出目录覆盖。
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

将 `--platform` 改为 `dy` 或 `bili` 分批运行。不要混用平台指标；每次运行记录平台、查询、排序和采集时间。

### 4.2 指定内容深挖

```powershell
uv run main.py --platform bili --lt qrcode --type detail `
  --specified_id "BV号或完整URL" `
  --get_comment yes `
  --get_sub_comment yes `
  --max_comments_count_singlenotes 50 `
  --save_data_path "research-cases/游戏名/raw"
```

`--specified_id` 支持逗号分隔列表。小红书详情 URL 必须包含有效的 `xsec_token` 和 `xsec_source`；从当前搜索结果复制完整 URL，不要只保存 note ID。

### 4.3 指定作者

```powershell
uv run main.py --platform dy --lt qrcode --type creator `
  --creator_id "作者主页URL或平台ID" `
  --crawler_max_notes_count 20 `
  --save_data_path "research-cases/游戏名/raw"
```

本 Fork 会停止落库创作者完整画像，因此作者模式应服务于“定位其公开作品”，而不是建立个人画像。

## 5. 平台差异

### 5.1 小红书

- 排序由 `config/xhs_config.py` 的 `SORT_TYPE` 控制；默认是 `popularity_descending`。
- 热门扫描后应再用其他排序或人工补充最新/中长尾样本。
- 指定笔记和作者 URL 依赖 `xsec_token`；过期或缺失会导致详情为空或 JSON 解析错误。
- 图文攻略的关键步骤可能只在图片中；结构化文本抓取成功不代表证据完整。

### 5.2 抖音

- 发布时间筛选由 `config/dy_config.py` 的 `PUBLISH_TIME_TYPE` 控制。
- 指定内容支持完整 URL、带 `modal_id` URL、短链和纯作品 ID。
- 短视频常缺少前置条件；下载/转写只对深挖样本进行。
- 扫码后仍可能出现手机验证，应由用户在可见浏览器中人工完成，不自动绕过。

### 5.3 B站

- `BILI_SEARCH_MODE="normal"` 时不使用 `START_DAY/END_DAY`。
- 时间范围模式为 `all_in_time_range` 或 `daily_limit_in_time_range`。
- `MAX_NOTES_PER_DAY` 默认只有 1；切换时间范围模式却忘记调整，会误以为搜索漏数据。
- 普通搜索内部页面大小固定为 20；即使 CLI 把 `crawler_max_notes_count` 设为小于 20，也会提升到至少 20。
- 标题和简介不能替代视频内容；深挖样本需要字幕、转写或逐帧记录。

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
| 只得到内容没有评论 | `--get_comment`、评论上限、平台返回权限 | 先以一个公开内容做 detail 冒烟测试 |
| 二级评论缺失 | 默认关闭，或一级评论无回复 | 深挖阶段显式 `--get_sub_comment yes`，控制单帖上限 |
| 输出目录找不到 | `SAVE_DATA_PATH` 后仍按平台/格式分层 | 从指定目录递归查找当天 JSONL |
| 重复数据 | JSONL 是追加写入 | 每次实验使用独立案例目录；分析阶段按平台业务 ID 去重 |
| 命令参数看似无效 | 平台专属参数仍在配置文件 | 运行 `uv run main.py --help`，再检查对应 `config/*_config.py` |
| 接口突然失败 | 平台页面/API 变化、Cookie 失效或项目版本变化 | 小样本冒烟测试；记录提交号；不要用加并发掩盖适配故障 |
| `uv sync` 下载包返回 403 | 默认清华镜像缺包、缓存路径失效或镜像拒绝 | 当前会话临时设 `UV_DEFAULT_INDEX=https://pypi.org/simple`；保留锁文件并检查是否产生纯源地址改写 |
| Windows 上 `test_no_user_info.py` 调用 `grep` 失败或扫描到仓库根目录 | 测试依赖 GNU grep，MSYS 对 `G:\...` 参数的路径解释也可能偏离 `store/` | 将其视为测试可移植性问题；不要误判为业务回归，改在 Git Bash/WSL 复验或后续把测试改为 Python/`rg` 实现 |
| Skill 工具读取中文报 GBK 错误 | Windows 默认编码不是 UTF-8 | 在当前 PowerShell 命令设置 `$env:PYTHONUTF8='1'` 后重跑，不修改全局环境 |
