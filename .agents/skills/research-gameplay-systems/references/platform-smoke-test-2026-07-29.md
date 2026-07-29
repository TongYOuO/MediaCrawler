# 七平台实抓冒烟测试记录（2026-07-29）

> 这是一次环境快照，不是长期兼容性承诺。结论只适用于下述代码、账号、网络和浏览器组合；复用前应重新运行冒烟测试。

## 1. 测试目标和通过标准

目标：验证 `xhs/dy/ks/bili/wb/tieba/zhihu` 不只是“代码里有适配器”，而是在当前环境能完成研究所需的最小闭环。

全链路通过需要同时满足：

1. 浏览器启动或连接成功。
2. 登录态通过平台客户端校验。
3. 关键词搜索至少产生一条内容 JSONL。
4. 至少产生一条一级评论 JSONL。
5. 从搜索结果选择一条公开内容，`detail` 再次产生内容和评论 JSONL。

仅能打开页面、出现二维码或存在 `search/detail/creator` 代码路径，不算通过。

## 2. 测试环境

| 项目 | 值 |
|---|---|
| 仓库 | `TongYOuO/MediaCrawler` |
| 应用代码基线 | `ba41c95`（测试期间仅临时改浏览器连接/Profile 配置，结束后已恢复） |
| 日期 | 2026-07-29 |
| 系统 | Windows / PowerShell 7.6.4 |
| Python | 3.11.14 |
| Node.js | 22.22.3 |
| 浏览器 | 第一轮：Google Chrome 150.0.7871.187，CDP；隔离复测：Playwright Chromium 149，标准模式 |
| 查询 | `原神 攻略` |
| 输出 | JSONL、媒体下载关闭、二级评论关闭 |
| 低频参数 | `crawler_max_notes_count=1`、`max_comments_count_singlenotes=1`、`max_concurrency_num=1` |

原始结果保存在仓库外的本地目录 `G:\GDC\.smoke-tests\MediaCrawler-20260729`，不提交平台内容、Cookie 或浏览器 Profile。

## 3. 结果

| 平台 | 关键词搜索 | 一级评论 | 单条详情＋评论 | 最终状态 | 关键证据/失败点 |
|---|---|---|---|---|---|
| 小红书 | 成功 | 成功 | 成功 | **PASS** | 搜索测试因两个外层进程被中止但子 Python 继续运行，共追加 60 行、23 个唯一内容 ID；详情为 1 内容＋1 评论 |
| B站 | 成功 | 成功 | 成功 | **PASS** | 搜索为 20 内容＋20 评论；BV 详情为 1 内容＋1 评论 |
| 微博 | 成功 | 成功 | 成功 | **PASS** | 搜索为 16 内容＋10 评论；详情为 1 内容＋1 评论；全文补抓成功 |
| 抖音 | 成功 | 成功 | 成功 | **PASS（标准模式）** | Chrome 150/CDP 导航失败；Playwright Chromium 149＋人工登录后为 14 内容＋14 评论，详情为 1 内容＋1 评论 |
| 快手 | 返回空 | 未执行 | 未执行 | **FAIL** | CDP 首页超时；标准模式登录成功，但 `原神 攻略` 和 `原神` 都返回 `not found data`，无 JSONL |
| 贴吧 | 未执行到搜索 | 未执行 | 未执行 | **FAIL/暂停** | CDP 导航失败；标准模式可从百度进入贴吧，但触发百度安全验证，旧二维码选择器失效，按用户要求暂停 |
| 知乎 | 未执行到搜索 | 未执行 | 未执行 | **FAIL/未隔离复测** | Chrome 150/CDP 已连接，但 `browser_context.new_page()` 报 `TargetClosedError`；尚未用标准模式复测 |

结论：当前环境有小红书、抖音、B站和微博完成研究全链路，状态为 **4/7 PASS**。其中抖音必须改用 Playwright Chromium 标准模式并人工完成登录；快手、贴吧和知乎不能写成“当前可正常抓取”。

## 4. 复现命令骨架

每个平台使用独立输出目录，避免 JSONL 追加结果互相污染：

```powershell
uv run main.py --platform <platform> --lt qrcode --type search `
  --keywords "原神 攻略" `
  --crawler_max_notes_count 1 `
  --max_comments_count_singlenotes 1 `
  --get_comment yes `
  --get_sub_comment no `
  --max_concurrency_num 1 `
  --save_data_option jsonl `
  --save_data_path "<smoke-root>/<platform>-search"
```

从搜索 JSONL 选择一条公开内容后运行：

```powershell
uv run main.py --platform <platform> --lt qrcode --type detail `
  --specified_id "<平台要求的 ID 或 URL>" `
  --max_comments_count_singlenotes 1 `
  --get_comment yes `
  --get_sub_comment no `
  --max_concurrency_num 1 `
  --save_data_option jsonl `
  --save_data_path "<smoke-root>/<platform>-detail"
```

## 5. 已确认的非显然问题

### 5.1 内容上限不是严格条数上限

小红书和 B站即使设置 `crawler_max_notes_count=1`，仍会处理搜索接口的完整首屏，约 20 条内容，并逐条抓评论。微博本次首屏处理 16 条。做低频测试时应先关闭搜索评论，再选择单条 `detail` 开启评论，避免意外放大请求量。

### 5.2 B站搜索输出与详情输入不闭合

搜索落盘只保留 aid，并生成 `https://www.bilibili.com/video/av<aid>`；当前详情解析器只接受 BV 号或含 BV 的 URL。纯 aid 和落盘的 `av...` URL 都被拒绝。测试中通过官方 view API把 aid 换成 BV 后，详情和评论成功。

### 5.3 抖音 CDP 与登录自动化不可靠

系统 Chrome 150/CDP 下首页导航连续出现 `ERR_ABORTED` 或等待 `load` 超时。Playwright Chromium 149 标准模式能打开页面，但当前自动登录仍等待旧的 `#login-panel-new`，随后点击“登录”时会被新的全屏登录层或 `uc-second-verify` 遮罩拦截。

测试采用只保持窗口、检测 `HasUserLogin/LOGIN_STATUS` 的手动登录程序保存登录态；随后 MediaCrawler 搜索和详情均成功。这说明搜索适配器可用，故障集中在默认 CDP/登录入口，而不是搜索接口整体封禁。

### 5.4 微博“没有评论”被当成错误重试

评论接口返回“还没有人评论”或“快来发表你的评论吧”时，当前客户端将其当作 `DataFetchError`，每帖重试多次。结果仍能完成，但首屏小样本耗时接近 5 分钟。研究脚本应把明确的空评论响应视为有效空集。

### 5.5 不要用第二个 Playwright 连接调用 `browser.close()` 做诊断

对正在运行的 CDP 浏览器再次 `connect_over_cdp()` 后调用 `browser.close()`，会关闭主测试的 BrowserContext，使主进程报 `TargetClosedError`。只读诊断应使用 CDP HTTP 元数据，或确保额外客户端只断开自身连接而不关闭浏览器。

### 5.6 停止外层 PowerShell 不一定停止子 Python

桌面工具中止外层命令后，MediaCrawler 的 Python 子进程可能继续抓取并向 JSONL 追加。终止测试前应按完整命令行定位仅属于该冒烟测试的 Python 和独立 Chrome Profile 进程；分析时按平台业务 ID 去重。

## 6. 后续修复候选（本次未实现）

1. 为各平台统一封装可重试导航，优先 `domcontentloaded`，对长连接页面避免强等 `load`。
2. 抖音默认改用已验证的标准 Chromium 路径，或修复 Chrome 150/CDP 导航；更新登录 DOM 与二次验证等待，允许用户完成后再继续。
3. 快手检查 GraphQL 搜索响应结构和请求参数；登录成功不等于搜索通过。
4. 贴吧更新百度安全验证后的二维码/登录选择器；知乎用标准模式隔离复测并检查 CDP Context 生命周期。
5. 让 B站详情解析器接受纯 aid 与 `av...` URL，或在搜索落盘中同时保存 BV。
6. 让搜索层严格截断到 `CRAWLER_MAX_NOTES_COUNT`，评论任务只接收截断后的 ID。
7. 把微博明确的“无评论”响应映射为空列表，停止无意义重试。

修复后必须重新执行本文件第 1 节的全链路标准；单元测试或接口方法存在不能替代实抓验证。
