# VideoHub — Project Context

> 归档用开发上下文。对应本机原型仓库收口状态（约 2026-09-16）。  
> 对话可 archive；后续接手以本文 + `README.md` + `docs/` 为准。

---

## 1. 项目定位

**VideoHub** 是音视频链接解析 / 预览 / 下载的 MVP 原型，用于本地演示与面试展示。

产品原则（对话中定稿）：

1. **下载载体**：第一版把文件交给浏览器下载栏，不自建应用内下载队列 UI。
2. **Cookie**：不做「用户导出 cookies.txt」的产品步骤；B 站公开视频尽量免登录。可选 `backend/cookies.txt` 仅作 YouTube 增强，已 gitignore。
3. **改动红线**：修某一平台 / 功能时，不得打挂已正常的 B 站、抖音、YouTube（及已稳定的 X）路径。
4. **演示边界**：首页**不展示** X 示例芯片（避免面试演示联想到 NSFW）；后端仍支持解析下载 X 公开原生视频。

---

## 2. 当前状态（可视为 MVP 完结）

| 模块 | 状态 | 备注 |
|------|------|------|
| B 站单稿 / 多分页 合集 | 可用 | `pagelist` ；未登录约 ≤720p |
| 抖音短链 / 分享文案抽链 | 可用 | `__ac_nonce` + jingxuan `RENDER_DATA` 为主路径 |
| YouTube 解析 / 预览 / 下载 | 可用 | `android_vr`/`android`；预览与下载均走本地临时文件 |
| X 公开视频 | 可用 | 首页无入口；syndication tombstone 会落到 fxtwitter |
| 合集勾选 / 批量下载 | 可用 | 至少 1 条；取消全选保留当前详情项 |
| 导航 / 刷新 / 返回 | 可用 | `sessionStorage` + `history`；返回不中断下载 |
| 账号 / 支付 / 公网部署 | 未做 | 见 P1 |

---

## 3. 架构

```
浏览器 (Vue @5173)
    │  Vite proxy /api → :8000
    ▼
FastAPI (backend.main)
    ├─ bilibili.parse      ← B 站官方 JSON
    ├─ douyin.parse        ← 短链 / SSR / 回退
    ├─ twitter.parse       ← syndication → 镜像 → yt-dlp
    └─ ytdlp_engine        ← YouTube（及兜底）
         │
         ├─ /api/parse        元数据 + 清晰度列表
         ├─ /api/resolve-item 合集某一集
         ├─ /api/stream       预览（Range；YT 本地文件）
         └─ /api/download     附件下载
```

**关键约定**：平台解析模块彼此隔离；新增平台只加模块 + `main._parse_url` / `SUPPORTED_HOSTS` 分支，不改其它平台内部逻辑。

---

## 4. 前端要点

| 文件 | 职责 |
|------|------|
| `src/App.vue` | 首页 ↔ 媒体页；`sessionStorage` 键 `videohub.session`；`#/` / `#/media` |
| `src/views/HomeView.vue` | URL 输入；示例芯片（无 X）；抖音提示 |
| `src/views/MediaView.vue` | 预览、清晰度、下载、音频；合集面板 |
| `src/components/CollectionPanel.vue` | 分页、勾选、全选规则 |
| `src/api.js` | `parseUrlApi` / `streamJobUrl` / `downloadJobUrl` / `resolveItemApi` |
| `src/mock.js` | DEMO 链接、分页常量；残留 mock 数据供离线参考，主路径走真实 API |

合集验收口径（必须保持）：

- 至少勾选 1 条；最后一条不能取消。
- 全选 → 全勾；再点取消全选 → **只勾当前正在看详情的那一集**。
- N 选下载 → 浏览器栏出现 N 个任务。

---

## 5. 后端要点（按平台）

### 5.1 Bilibili — `backend/bilibili.py`

- 短链 `b23.tv` 解析；`view` + `pagelist`（避免 pages 截断）。
- `playurl` 取渐进 MP4；代理时带 Referer。
- 合集 `kind: collection`，单项可 `resolve-item`。

### 5.2 Douyin — `backend/douyin.py`

- 主路径：短链 → `aweme_id` → bootstrap Cookie → jingxuan SSR `RENDER_DATA` → CDN。
- 回退：iesdouyin iteminfo / 分享页 / yt-dlp。
- 输入可含整段分享文案（`httputil.extract_http_url`）。

### 5.3 YouTube — `backend/ytdlp_engine.py` + `main.py`

- Player client 实测：`tv`/默认易「page needs to be reloaded」；优先 `android_vr` → `android`。
- googlevideo CDN 经服务端代拉易 403 → **预览与下载都先 `download_to_file` 再 FileResponse / Range**（仅 YouTube）。
- 可选 `backend/cookies.txt`（Netscape）。

### 5.4 X — `backend/twitter.py`

- 支持 `/user/status/ID`、`/i/status/ID`、`/i/web/status/ID`、短链等。
- 主：cdn.syndication.twimg.com tweet-result。
- **敏感帖**：syndication 常为 `TweetTombstone` → **不要硬失败**，记 notes 后继续 fxtwitter / vxtwitter / yt-dlp。
- 仅原生 progressive MP4；无视频 / 已删 / 纯外链 → 422 类失败属预期。
- 与 B 站 / 抖音 / YouTube 代码路径隔离。

### 5.5 公共

- `backend/httputil.py`：浏览器头、抽 URL、时长/计数格式化。
- `main.py`：`_PICK_CACHE`（约 180s）、YouTube 文件缓存（约 600s）、`Content-Disposition` 中文文件名。

---

## 6. 关键决策（勿轻易推翻）

1. **浏览器下载栏**，不是站内任务机（P1 再议）。
2. **预览与下载接口分离**；失败仍应能下。
3. **平台专用优先，yt-dlp 兜底**（YouTube 主用 yt-dlp）。
5. **首页不宣传 X**；能力保留。
6. **改 X / YouTube 流式策略时只动对应分支**，禁止「统一改所有 CDN 代理」导致 B 站/抖音回归。

---

## 7. 已知坑与回归清单

接手改动后建议快速点验：

1. B 站公开单稿：解析 → 预览 → 下载。
2. B 站多分 P：分 P 数量、勾选规则、多选多个下载任务、文件名。
3. 抖音 `v.douyin.com` 短链：解析 + 预览/下载。
4. YouTube：解析成功；预览能播（非 403）；下载能保存。
5. X（可选）：粘贴含 `/status/` 的公开视频链接；含敏感标记的帖应走镜像而非直接 422。
6. 返回首页：预览取消，下载不中断；刷新媒体页能恢复并重新拉预览。

历史已修问题摘要：

| 现象 | 根因方向 |
|------|----------|
| 抖音 422 | 旧 iteminfo 空；需 SSR + ac_signature |
| YouTube 解析「reload」 | player client 过时 |
| YouTube 预览 403 | CDN 代拉被拒 → 本地文件再流 |
| X 500 | 未定义正则等实现 bug |
| X 部分 422 | 无视频 / 删帖 / tombstone 未回退镜像 |
| 合集只下一个 | 浏览器拦连点；需受控并发触发 |

---

## 8. P1 / 未做

- 登录态更高清晰度与音视频分轨合并。
- 应用内下载任务状态机。
- 账号、Stripe、去水印等原 PRD 商业能力。
- 公网：静态前端 + 独立 API。
- 预览跨刷新二进制缓存。
- B 站跨多个 BV 的「季节/系列」目录。

---

## 9. 本地与仓库卫生

- 依赖目录：`.venv`、`node_modules`（gitignore）。
- 勿提交：`backend/cookies.txt`、`backend/_tmp_cookies.txt`、`__pycache__`、诊断临时文件。
- 启动：`backend/start.bat` + `start-frontend.bat`。
- Python 包以仓库根为 cwd：`uvicorn backend.main:app`。

---

## 10. 归档说明

本文件由收口对话整理，用于：

- 把长对话 archive 后仍能恢复「做到哪、为什么、别踩什么」；
- 开新对话时把 `project_context.md` + `README.md` 当作首要上下文。

若实现与本文冲突，以代码为准，代码相关功能改变约一天内同步至此文档。
