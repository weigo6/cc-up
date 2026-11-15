# 只使用网页配置 Cloudflare

这份流程使用一份共享同步密钥。两台电脑填写同一 Worker 地址和密钥，设备 ID 由采集器自动生成，无需配对文件。整个 Cloudflare 部署过程不需要命令行。

## 1. 创建数据库并建表

1. 登录 [Cloudflare 控制台](https://dash.cloudflare.com/)，进入 **Storage & databases → D1 SQL database**（存储和数据库 → D1）。
2. 点击 **Create Database / 创建数据库**，名称填写 `cc-up`。
3. 打开刚创建的数据库，进入 **Console / 控制台**。
4. 打开项目的 `cloudflare/dashboard-schema.sql`，复制全部内容，粘贴到 SQL 输入框，点击 **Execute / 执行**。
5. 在 Tables 中应看到 `devices`、`request_logs`、`usage_snapshots`、`usage_daily` 四张表。这个文件只创建缺少的表和索引，不删除现有数据。

## 2. 创建 Worker 并放入代码

1. 回到 **Workers & Pages**，点击 **Create application / 创建应用**。
2. 选择 **Start with Hello World / 从 Hello World 开始**，名称可填 `cc-up`，点击 **Deploy / 部署**。
3. 打开该 Worker，点击 **Edit code / 编辑代码**。
4. 打开项目的 `cloudflare/src/worker.mjs`，复制全部内容，替换网页编辑器里的默认代码。
5. 点击 **Deploy / 部署**。

这份 Worker 是单文件 JavaScript，支持直接粘贴到 Cloudflare 编辑器，不需要安装依赖或上传整个项目。

## 3. 把数据库绑定到 Worker

1. 在 Worker 页面进入 **Bindings / 绑定**。
2. 点击 **Add binding / 添加绑定 → D1 database**。
3. **Variable name / 变量名必须填 `DB`**，注意大写。
4. 数据库选择第一步创建的 `cc-up`，保存绑定；如果控制台提示部署，点击部署。

数据库名称可以自定义，但代码中的绑定名固定为 `DB`。

## 4. 设置一份同步密钥

1. 在电脑上双击项目里的 `CC-Up.pyw`。
2. 在“同步密钥”旁点击 **生成**，再点击 **复制**。暂时保留这个窗口。
3. 回到 Cloudflare Worker 的 **Settings → Variables and Secrets → Add**。
4. 类型选择 **Secret / 密钥**，变量名填 **`SYNC_TOKEN`**，值粘贴刚才复制的同步密钥。
5. 点击 **Deploy / 部署** 保存。

密钥是你自己生成的一串随机字符，不是 Cloudflare 账户 API Token，也不是模型服务商的 API Key。不要把它写入公开网页代码或发到公开位置。

Worker 必须配置 `SYNC_TOKEN`；网页还能另配一把只读密钥（可选，见下）。

### 可选：网页使用只读密钥

共享密钥 `SYNC_TOKEN` 既能查询也能上传。网页建议单独使用只读密钥。只读密钥持有者可查询全部设备用量和请求详情，不能上传或覆盖数据；需要保密时，不要把它写入公开站点的 `config.json`。

用法和 `SYNC_TOKEN` 一样，Worker 与网页填同一串明文：

1. 生成密钥：

   ```powershell
   python tools/create_viewer.py
   ```

2. 回到 Worker → **Settings → Variables and Secrets → Add**，类型选 **Secret**，名称填 **`VIEWER_TOKENS`**，值就填这串明文；有多把时用英文逗号分隔（例如 `密钥A,密钥B`）。保存并部署。
3. 把同一串明文填到网页“连接我的数据”；用 Netlify 部署时设为环境变量 `CC_UP_TOKEN`。
4. 只读密钥只能 `GET`；`POST /v1/logs` 与 `POST /v1/snapshot` 返回 403。`SYNC_TOKEN` 权限不变，采集器继续用它上传。

撤销就是把那一串从 `VIEWER_TOKENS` 里删掉后重新部署。新增**采集器**不需要新密钥，填同一个 `SYNC_TOKEN` 即可。

没有配置 `VIEWER_TOKENS` 时行为与以前一致：只接受 `SYNC_TOKEN`。排错见文末「常见情况」。

## 5. 配置自动清理

1. 在 Worker 的 **Settings → Triggers → Cron Triggers** 中添加触发器。
2. 选择自定义 Cron 表达式，填入：

```text
17 * * * *
```

这表示每小时第 17 分钟检查并分批清理 90 天前的请求日志。按日 Token 和费用历史不会被这个清理任务删除。它与两台电脑的本地同步时间无关。

## 6. 两台电脑填写相同地址和密钥

从 Worker 页面复制 `https://cc-up.<你的子域>.workers.dev` 地址。在两台电脑的 `CC-Up.pyw` 中：

1. Worker 地址填写上面的完整 HTTPS 根地址。
2. 同步密钥填写第四步的同一份值。
3. 设备名称分别填写“台式机”“笔记本”等容易区分的名称。
4. 数据库路径通常保持自动填写的值。
5. 点击“保存设置”，再点击“立即同步”。

设备 ID、每批请求数、时区已经有默认值，位于“高级设置”中，无需修改。

浏览器访问 Worker 地址加 `/health`，看到 `{"service":"cc-up","version":1}` 表示代码能够访问。这个检查不验证数据库绑定和密钥；客户端“立即同步”成功才是完整验证。

## 7. 部署网页前端并允许跨域读取

把项目 `frontend` 目录作为静态站点根目录上传到你选择的平台，或上传 `dist/CC-Up-Web.zip`。压缩包根目录包含 `index.html` 和 `assets`，不需要构建命令，也不包含同步密钥。

如果使用 Netlify，可以在站点环境变量中设置 `CC_UP_ENDPOINT` 与 `CC_UP_TOKEN`，由构建阶段生成 `config.json`，让网页打开即连、不再要求填写密钥；步骤和风险说明见 [frontend/README.md](../frontend/README.md) 的「Netlify 构建时注入密钥」一节。

如果使用 Cloudflare Pages，可在 Workers & Pages 创建 Pages 项目，选择 **Direct Upload / 直接上传**，上传网页压缩包并部署。得到类似 `https://cc-up-dashboard.pages.dev` 的站点地址后：

1. 返回数据 Worker → **Settings → Variables and Secrets → Add**。
2. 类型选择普通 **Text / 文本**。
3. 名称填写 **`ALLOWED_ORIGINS`**。
4. 值填写网页的来源，例如 `https://cc-up-dashboard.pages.dev`，不带结尾 `/`，不带页面路径。
5. 如有多个来源，用英文逗号分隔。GitHub Pages 的来源填 `https://你的用户名.github.io`，不包含项目路径。
6. 保存并部署。
7. 打开网页，点击“连接我的数据”，填写 Worker 地址和密钥（同步密钥或只读密钥），即可看到真实用量。

静态网页使用浏览器发起读取请求，因此需要 `ALLOWED_ORIGINS`；Python 采集器无需这个设置。

网页填写的密钥可以是 `SYNC_TOKEN`（既能查询也能上传），也可以是第 4 节配置的只读密钥（只能查询）。公开站点的 `config.json` 里只应填只读密钥。

## 常见情况

- **客户端提示 401**：确认两台电脑的同步密钥与 Worker 的 `SYNC_TOKEN` 完全一致，且已部署保存。
- **客户端提示 503**：确认绑定名是 `DB`，并且四张表均已创建。
- **网页能打开，但连接失败**：确认使用最新版 Worker 代码，并将网页来源加入 `ALLOWED_ORIGINS`。
- **网页仍显示演示模式**：点击“连接我的数据”；展示站点不会自动包含任何真实账户凭据。
- **只读密钥上传返回 403**：预期行为，只读密钥只能 `GET`；上传必须用 `SYNC_TOKEN`。
- **配置 `VIEWER_TOKENS` 后网页仍提示密钥无效**：确认 Secret 里填的是明文密钥，和网页 / Netlify 里那一串完全一致；改完要重新部署 Worker。
- **`VIEWER_TOKENS` 报 503**：值须是明文密钥，多把用英文逗号分隔；每把 32～128 位字母、数字、下划线或短横线，且最多 32 把。
- **刚启用时没有 90 天请求**：云端只会收到 CC-Switch 当前仍保留的明细，之后持续累积，最多保留 90 天。

控制台按钮可能随界面更新略有变化，可对照官方说明：[Worker 网页创建](https://developers.cloudflare.com/workers/get-started/dashboard/)、[D1 创建、控制台和绑定](https://developers.cloudflare.com/d1/get-started/)、[网页设置密钥](https://developers.cloudflare.com/workers/configuration/secrets/)、[Cron 触发器](https://developers.cloudflare.com/workers/configuration/cron-triggers/)。
