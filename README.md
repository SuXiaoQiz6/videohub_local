# VideoHub

路径：`D:\ai_tools\videohub-prototype`  
依赖都在本目录：`node_modules`、`.venv`（不写系统全局）。

## 启动（两个窗口）

**后端**

```bat
D:\ai_tools\videohub-prototype\backend\start.bat
```

**前端**

```bat
D:\ai_tools\videohub-prototype\start-frontend.bat
```

打开 http://127.0.0.1:5173  
健康检查：http://127.0.0.1:8000/api/health

## 真实解析说明

- 引擎：`yt-dlp`（只拉元数据，不落盘）
- API：`POST /api/parse` `{ "url": "..." }`
- YouTube：当前环境已验证可解析（如首页「YouTube 单视频」）
- B 站 / 抖音：常返回 412，需要登录态 Cookie

### 给 B 站 / 抖音准备 cookies（可选）

1. 浏览器安装扩展 **Get cookies.txt LOCALLY**
2. 打开 bilibili.com / douyin.com 并登录
3. 导出 Netscape 格式 cookies，保存为：

`D:\ai_tools\videohub-prototype\backend\cookies.txt`

4. 重启后端再解析

不要把 `cookies.txt` 提交到公开仓库。

## 目录

```
videohub-prototype/
  backend/          FastAPI + yt-dlp
  src/              Vue 前端
  .venv/            Python 虚拟环境（本地）
  node_modules/     npm 依赖（本地）
```
