# CC-Up 静态网页工作台

纯 HTML / CSS / JavaScript，可部署到 Cloudflare Pages、GitHub Pages、Netlify 或其他静态托管平台。没有前端 npm 依赖，无需构建。

## 网页部署

1. 上传 `dist/CC-Up-Web.zip`，或把本目录作为站点根目录。根目录应直接包含 `index.html` 和 `assets`。
2. 使用 Cloudflare Pages 时，可在网页控制台选择 **Create application → Get started → Drag and drop your files**，上传压缩包，再点击 **Deploy site**。
3. 在数据 Worker 的 Settings → Variables and Secrets 中增加普通文本变量 `ALLOWED_ORIGINS`，值为前端来源，例如 `https://cc-up-dashboard.pages.dev`。多个来源用英文逗号分隔，不带结尾 `/` 或页面路径。
4. 确保 Worker 已更新为同一版本的 `cloudflare/src/worker.mjs`。
5. 打开网页，点击“连接我的数据”，填写 Worker 根地址及访问密钥（推荐独立只读密钥）。

完整 Cloudflare 网页配置见 [网页控制台指南](../docs/CLOUDFLARE-DASHBOARD.md)。不需要把任何 `*.private.json` 文件上传到静态站点。

## Netlify 构建时注入密钥（可选）

不想每次打开网页都填密钥时，可以让站点在构建阶段把密钥写成 `config.json`，页面启动后自动连接。

1. Netlify → **Site configuration → Environment variables**，新增 `CC_UP_ENDPOINT`（Worker 根地址，如 `https://cc-up.example.workers.dev`）和 `CC_UP_TOKEN`（**建议填只读密钥**，见下方“访问密钥”）。
2. 构建命令填 `node tools/build_web_config.mjs`，发布目录填 `frontend`——仓库根目录的 `netlify.toml` 已写好这两项，直接连接 Git 仓库即可。
3. 构建成功后会生成 `frontend/config.json`（已被 `.gitignore` 忽略，不会进仓库）。页面读取它并自动连接，提示“已按站点配置自动连接”；文件缺失或内容无效时，仍显示“连接我的数据”手动入口。
4. 轮换只读密钥时：改 `CC_UP_TOKEN` 重新部署站点，同时在 Worker 的 `VIEWER_TOKENS` 里删掉旧条目并重新部署，两边保持同步。
5. 移除这两个环境变量并重新构建，会删除上一次生成的 `config.json`，恢复手动连接。配置不完整或无效时构建失败，同时移除旧配置。

**公开配置的访问范围**：`config.json` 是站点上的公开静态文件，任何能打开网站的人都能读到 `CC_UP_TOKEN`，进而查询全部设备用量及请求详情，包括模型、会话标识和错误信息。这里只应填**只读密钥**；若填共享同步密钥，拿到的人还能上传和覆盖数据。需要保密时使用手动连接，或在站点前配置访问控制。`_headers` 已对该文件设置 `Cache-Control: no-store` 与 `noindex`，它们不能限制读取权限。

## 可视化与查询

- 概览：真实消耗 Token、请求数、估算费用、缓存命中率。
- 自定义日期范围，单次最多 36,600 个自然日；支持全部历史、设备和应用筛选。
- 每日趋势可切换 Token、请求数和费用；未上报日期保留空缺。
- 年度热力图支持七项指标，点击一天查看设备和应用明细；键盘方向键可移动。
- 热力图明确区分“未上报”“已上报零用量”和“未来日期”。
- 最近 90 天请求可按日期、设备、应用、状态、模型、请求 ID、会话或供应商搜索，支持前后翻页、完整字段和单条 JSON 下载。
- 长期每日用量表与 CSV 导出；请求 CSV 明确仅导出当前页。
- 手机窄屏支持折叠菜单，表格和全年热力图可横向滚动。

默认展示明确标注的合成示例数据；连接成功后才显示真实云端数据。长期历史来自 `usage_daily`，不会从 90 天请求日志重算。费用沿用采集器上报结果，不是订阅实际扣款。

## 访问密钥

网页只需要一把密钥，按用途选一种：

- **共享同步密钥 `SYNC_TOKEN`**：最省事，能查询也能上传。只在自己的浏览器里临时填写，不要放进公开站点或公开仓库。
- **只读密钥**：用 `python tools/create_viewer.py` 生成一串明文，Worker 的 Secret `VIEWER_TOKENS` 和网页填同一串。它只能 `GET`，上传会返回 403；持有者可读取所有设备的用量和请求详情。配置步骤见 [网页控制台指南](../docs/CLOUDFLARE-DASHBOARD.md#可选网页使用只读密钥)。

没有配置 `VIEWER_TOKENS` 时，Worker 只接受 `SYNC_TOKEN`。

默认只在页面内存中保存访问密钥；勾选“记住本次会话”后保存到当前来源的 `sessionStorage`，不写入 `localStorage`。Worker 地址会保存到 `localStorage` 便于下次填写。退出连接会清除当前密钥。使用共享电脑时不要勾选记住会话。

## 本地预览与验证

在项目根目录执行 `python tools/preview_web.py`，打开它输出的本机地址。直接用 `file://` 打开页面无法可靠加载 JavaScript 模块，连接云端时也无法提供正常网页来源，因此请使用 HTTP 预览或静态托管。

测试命令：`node --test frontend/test/*.test.mjs`。端点每次读取完整所选范围的日聚合数据，最多 36,600 天，并在页面内缓存 60 秒；没有后台轮询，点击“刷新”可立即重新读取。历史跨度较大时，响应大小、查询耗时及浏览器内存会随记录数增加。

`_headers` 适用于 Cloudflare Pages 等支持该格式的平台，其他平台可按需要设置等效响应头。页面不使用外部 CDN、字体、分析脚本或图表库。
