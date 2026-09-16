# VideoHub

本机可运行的音视频解析 / 预览 / 下载 MVP。粘贴公开页面链接 → 后端解析 → 浏览器原生播放器预览 → 交给 Chrome / Edge / 夸克下载栏保存。

> 演示对齐常见「鱼皮式」路径：**平台专用解析或 yt-dlp 在服务端完成，浏览器只负责保存文件**。

## 功能概览

| 能力 | 说明 |
|------|------|
| 解析 | B 站、抖音、YouTube；另支持 X（Twitter）公开原生视频 |
| 预览 | `/api/stream` 代理，与下载分离；合集可切换分 P |
| 下载 | `/api/download`；合集多选一次最多 5 个浏览器任务 |
| 导航 | 返回首页写入历史；刷新可恢复当次解析；返回不中断已开始的下载 |

首页示例芯片仅展示：**B 站公开视频 / 抖音短链 / YouTube / 失败示例**。X 不在首页露出，但直接粘贴 `x.com` / `twitter.com` 含 `/status/` 的链接仍可解析下载。

## 技术栈

- **前端**：Vue 3 + Vite（`http://127.0.0.1:5173`，`/api` 代理到后端）
- **后端**：FastAPI + httpx + yt-dlp（`http://127.0.0.1:8000`）

## 快速启动

需已安装 Node.js 与 Python 3.9+。

```bash
# 依赖（首次）
python -m venv .venv
# Windows:
.venv\Scripts\pip install -r backend\requirements.txt
npm install

# 终端 1 — 后端
backend\start.bat
# 或: .venv\Scripts\uvicorn.exe backend.main:app --reload --host 127.0.0.1 --port 8000

# 终端 2 — 前端
start-frontend.bat
# 或: npm run dev -- --host 127.0.0.1 --port 5173
```

- 前端：http://127.0.0.1:5173  
- 健康检查：http://127.0.0.1:8000/api/health  

## 各平台说明

- **B 站**：官方 `view` / `pagelist` / `playurl`；公开视频一般无需 Cookie；未登录渐进 MP4 常见上限约 720p。
- **抖音**：优先 App「分享 → 复制链接」短链（`v.douyin.com`）；支持从整段分享文案中抽出 URL。
- **YouTube**：`yt-dlp`（优先 `android_vr` / `android` 客户端）。若本机风控较严，可把 Netscape 格式的 `cookies.txt` 放到 `backend/cookies.txt`（可选，已在 `.gitignore`）。预览与下载均走本机临时文件再流式输出，避免 CDN 直连 403。
- **X**：syndication → fxtwitter / vxtwitter → yt-dlp；敏感帖 syndication 可能 tombstone，会继续走镜像接口。仅公开含原生视频的帖子；外链、纯图文、已删内容会失败。

## API（摘要）

| 方法 | 路径 | 作用 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| POST | `/api/parse` | `{ "url": "..." }` 解析单条 / 合集 |
| POST | `/api/resolve-item` | 合集内某一集补全播放信息 |
| GET/HEAD | `/api/stream` | 预览（支持 Range） |
| GET/HEAD | `/api/download` | 附件下载 |

查询参数常见：`url`、`quality`；音频另加 `audio=true`、`format`。

## 目录结构

```
videohub-prototype/
  backend/
    main.py           # FastAPI 入口与路由
    bilibili.py       # B 站解析
    douyin.py         # 抖音解析
    twitter.py        # X 解析
    ytdlp_engine.py   # YouTube / 通用 yt-dlp
    httputil.py       # HTTP / 文案工具
    start.bat
    requirements.txt
  src/
    App.vue           # 首页 ↔ 媒体页导航与 session
    api.js            # 前端 API 客户端
    views/            # HomeView / MediaView
    components/       # CollectionPanel 等
  docs/               # PRD 与阶段性补充需求
  project_context.md  # 开发上下文（归档用）
  start-frontend.bat
```

## 文档

- [`docs/阶段性补充需求.md`](docs/阶段性补充需求.md) — 相对原 PRD 的增量约定与验收口径  
- [`docs/VideoHub产品需求文档.docx`](docs/VideoHub产品需求文档.docx) — 产品需求原文  
- [`project_context.md`](project_context.md) — 当前实现状态、架构决策与已知限制  

## 已知限制（MVP）

- 下载依赖浏览器下载栏，无应用内任务队列。
- B 站高码率 / 大会员档、音视频分轨合并为 P1。
- YouTube / X 受平台风控与内容类型影响，失败属预期；勿把失败提示写成「登录 VideoHub」。
- 公网部署需独立后端（GitHub Pages 只能托管静态前端）。

## License

个人 / 面试演示用原型。请遵守各平台服务条款与版权，仅解析你有权访问的公开内容。
