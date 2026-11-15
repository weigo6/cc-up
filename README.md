# CC-Up

用于多台 Windows 设备的 CC-Switch 用量同步工具。本地只读 SQLite，Cloudflare Workers 接收数据，D1 保存最近 **90 天**的请求日志，**按日 Token 用量长期持久化**。

客户端只依赖 Python 标准库，无需 pip 安装第三方库。设置窗口使用原生 Tk，定时同步交给 Windows 任务计划程序；关闭设置窗口后没有常驻进程。

当前版本 **0.3.0**。变更见 [CHANGELOG.md](CHANGELOG.md)，开发检查与打包步骤见下方「验证与打包」。Git 仓库只保存源码，便携源码包和静态网页包放在 Release 附件中。

## 已实现

- 原生中文设置窗口，手动立即同步、每日多个固定时间同步。
- 按 `created_at` 增量上传，按 `(created_at, request_id)` 分页；每轮重读最后一秒。
- 按 `(device_id, request_id)` 幂等入库，断网后从最后确认批次恢复。
- 本地按 CC-Switch 的跨来源去重和 Token 归一化规则，计算今天、最近 7 个自然日、最近 30 个自然日用量，按设备完整覆盖云端快照。
- 保留全部源请求表字段，包括四类 Token、费用、请求模型、计价模型、会话 ID、状态、错误、耗时；不包含源表本来没有保存的请求正文或响应正文。
- 云端两台设备用量汇总、最近请求分页浏览、请求完整字段详情。
- 独立的 `usage_daily` 表长期保存逐设备、逐日的四类 Token、请求数、成功数、费用和应用分组。近期 30 日完整覆盖，较早日期保留最后上报值，不随请求日志过期而删除。
- 每小时自动分批清理 90 天前日志；查询立即排除超期数据，不必等待清理任务完成。
- 两台电脑使用同一份同步密钥，设备 ID 自动生成；Windows DPAPI 加密保存本地密钥。网页可另配只读密钥（Worker `VIEWER_TOKENS`），只能查询、不能上传。
- 自动避免手动同步与定时同步重叠。失败后 Windows 每 5 分钟重试，最多 3 次。
- 独立静态网页工作台：用量和费用概览、年度热力图、趋势、设备与应用筛选、请求搜索、日用量查询和 CSV 导出，无前端框架依赖。

## 目录结构

```text
cc_up/        采集器、SQLite 只读查询、Tk 设置窗口（仅标准库）
cloudflare/   Worker 源码、D1 迁移与网页控制台建表脚本
frontend/     静态网页工作台（无依赖、无需构建）
docs/         只用网页配置 Cloudflare 的完整步骤
tests/        Python 自动化测试与夹具
tools/        基准测试、打包、网页预览与运维脚本
dist/         打包产物，已被 Git 忽略，发布时作为 Release 附件
```

## 两台电脑怎么用

每台电脑安装 Python 3.11 或更新版本，保留安装选项 **Tcl/Tk** 和 **Python Launcher**。Python 3.14 已在本机验证。把整个项目解压到固定目录，启用定时后不要移动该目录。

首次使用先完成下面的 Cloudflare 部署。然后在两台电脑上分别：

1. 双击 `CC-Up.pyw`（或运行 `python cc_up_launcher.py settings`）。
2. 在两台电脑填写相同的同步密钥。首次可在第一台点“生成 / 复制”，并将同一份值设为 Worker 的 `SYNC_TOKEN`。
3. 填写部署后得到的相同 Worker 地址，例如 `https://cc-up.<子域>.workers.dev`；设备名称分别改成“台式机”“笔记本”等。
4. 检查 CC-Switch 数据库路径，默认 `%USERPROFILE%\.cc-switch\cc-switch.db`。
5. 点击“保存设置”，再点击“立即同步”。
6. 如需定时，填入 `09:00, 13:00, 18:00, 23:00` 等每日时间，点击“启用 / 更新定时”。
7. 在“用量与请求”页查看云端汇总、请求日志或长期历史用量。“本机预览”可在没有云端连接的情况下使用。

定时任务使用当前 Windows 登录账户，不需要账户密码，不要求管理员权限，不弹控制台。只有用户登录时才运行；设备睡眠或离线错过触发后，Windows 在条件允许时补执行。它不会主动唤醒设备。设置里的时间按 Windows 本地时区解释。

修改定时时间后，须再点“启用 / 更新定时”。点击“停用定时”会移除本工具对应的任务。更改源数据库或云端地址后，采集器为新来源或新目标重新开始扫描仍存在的近 90 天日志。

## Cloudflare 网页部署（推荐）

按 [网页控制台配置指南](docs/CLOUDFLARE-DASHBOARD.md) 完成。只需 Cloudflare 账户，无需 Node.js 或命令行：

1. 网页创建 D1，执行 `cloudflare/dashboard-schema.sql`。
2. 创建 Worker，把 `cloudflare/src/worker.mjs` 的全部内容粘贴到代码编辑器并部署。
3. 添加 D1 绑定，变量名为 `DB`。
4. 添加 Secret `SYNC_TOKEN`，两台电脑填写同一值。
5. 添加 Cron `17 * * * *`，清理超期请求。

网页前端单独上传 `dist/CC-Up-Web.zip` 到静态托管平台，再在 Worker 设置普通文本变量 `ALLOWED_ORIGINS` 为网页来源。详细前端说明见 [frontend/README.md](frontend/README.md)。用 Netlify 部署时可以让构建阶段注入密钥、打开网页即连，见该文档的「Netlify 构建时注入密钥」一节。

## 可选：命令行部署

只需在一台电脑上部署一次。要求 Cloudflare 账户、Node.js 22 或更新版本和可连接 npm / Cloudflare 的网络。账户使用 Workers Free 即可，是否能一直处于免费额度内取决于日志数量和大小。

以下命令在项目根目录的 PowerShell 执行：

```powershell
cd cloudflare
npm ci
npx wrangler login
npx wrangler d1 create cc-up
```

`npm ci` 按 `package-lock.json` 安装 Wrangler 4.162.0。`wrangler d1 create` 会输出数据库 ID，把 `cloudflare/wrangler.jsonc` 中的 `REPLACE_WITH_YOUR_D1_DATABASE_ID` 替换为该 ID。然后在 `cloudflare` 目录继续：

```powershell
npx wrangler d1 migrations apply cc-up --remote
npx wrangler secret put SYNC_TOKEN
npx wrangler deploy
```

`d1 migrations apply` 依次执行 `migrations/` 下的 `0001_initial.sql` 和 `0002_usage_history.sql`；`secret put` 时粘贴设置窗口“生成 / 复制”得到的同步密钥，两台电脑使用同一份值。部署完成后记录命令输出的 `https://...workers.dev` 地址，填入两台设备设置窗口。

`wrangler.jsonc` 已绑定 `DB`，并配置每小时第 17 分钟执行清理任务，无需再手动添加。如果已有名为 `cc-up` 的 D1 数据库，直接把它的 ID 填入配置，不必重复创建。如果 Worker 名称已被占用，可修改配置中的 `name`，客户端使用新的部署地址即可。

网页前端仍需按 [frontend/README.md](frontend/README.md) 单独部署，并设置 `ALLOWED_ORIGINS`。

官方命令说明：[D1](https://developers.cloudflare.com/d1/wrangler-commands/)、[Workers Secrets](https://developers.cloudflare.com/workers/configuration/secrets/)。

## 手动命令行

```powershell
# 打开设置
python cc_up_launcher.py settings

# 同步一次，结束后退出
python cc_up_launcher.py sync

# 只读本地统计，不上传
python cc_up_launcher.py preview

# 查看云端设备状态
python cc_up_launcher.py status

# 安装或移除每日定时任务
python cc_up_launcher.py install-schedule
python cc_up_launcher.py remove-schedule
```

也可以双击 `立即同步.cmd`。使用自定义配置时，在命令最后加 `--config D:\路径\config.json`。

辅助脚本，同样在项目根目录执行：

- `python tools/backfill_history.py --apply`：把源数据库里仍保留、但早于最近 30 天的历史汇总一次性补传到 `usage_daily`，只写日用量、不重传旧请求，可安全重跑。
- `python tools/preview_web.py`：在本机回环地址预览网页工作台。
- `python tools/create_viewer.py`：生成网页用的只读密钥；把同一串明文填进 Worker 的 `VIEWER_TOKENS` 和网页 / Netlify。
- `python tools/verify_windows_schedule.py`：创建、查询并立即删除一个临时定时任务，验证任务计划程序权限，不执行同步。

默认配置、进度和运行日志位于 `%LOCALAPPDATA%\CC-Up\`：

- `config.json`：连接和每日时间；密钥经过当前账户 DPAPI 加密。
- `config.state.json`：已确认时间游标、快照序号、最后成功时间与本机统计。
- `sync.log`：小型滚动日志，每份最多 128 KiB，最多 3 份。
- `scheduled-task.xml`：系统定时任务定义，无设备密钥。

不要把本地配置直接复制到另一台电脑：DPAPI 绑定 Windows 账户与电脑，设备 ID 也必须不同。在两台电脑分别填写相同同步地址和密钥即可，设备 ID 会各自生成；“高级设置”中可以查看或修改设备 ID、每批请求数和统计时区。

## 统计与同步边界

实现参考 CC-Switch `27e2cffa91c091469d8106e679cae2772d47c8dd`，并在本机 schema 26 数据库上进行只读验证。新旧语义的区别保留在 `input_token_semantics` 中；Claude Desktop 在统计展示中合并到 Claude。

“7 天”和“30 天”指包含今天的自然日范围，默认使用 UTC+8。两台设备须设置相同统计时区，CC-Switch 的旧每日汇总也应使用这一时区。汇总结果同时考虑仍存在的请求明细和 CC-Switch 已生成的完整日期汇总；采集器不会重读 Agent JSONL 或触发 CC-Switch 扫描。

本地和云端的缓存命中率均按四类计数重算，不平均各设备的百分比。云端不把请求日志再次加到用量快照中。

历史日用量与近期快照在同一个服务端事务中提交。每次只计算源数据库中近 30 个自然日的现状，覆盖对应日期，云端更早的日期不删除。启用后持续积累长期历史，首次不会恢复源端已不存在的历史数据。日志的 90 天清理只操作 `request_logs`，不操作 `usage_daily`。

历史接口为 `GET /v1/history`，支持 `start=YYYY-MM-DD`、`end=YYYY-MM-DD`、`device_id` 和分页参数 `cursor`，每页 50 个设备日，响应中的 `next_cursor` 用于读取下一页。鉴权与日志接口一致。按日记录包含全部四类 Token 及应用分组，方便后续导出或绘图。

费用以 CC-Switch 已写入的四类费用字段和 `total_cost_usd` 为准。日志保留原值；日用量和近期汇总在去重后累加总费用，跨设备继续求和，不重新查询模型价格，不再次乘供应商倍率。`model`、`request_model`、`pricing_model`、`cost_multiplier` 都随原始请求上传。缺失定价导致的零费用保持为零，没有独立补价或历史重新计费。聚合费用保留 8 位小数，不代表订阅套餐实际扣款。

增量协议有意不处理游标之前的会话补录，也不传播已上传日志的更新和删除。近期快照来自每次读到的本地完整现状，可能上升或下降；云端请求列表保存首次采集值，因此请求列表与用量概览不保证逐条对账。两台电脑不要分别导入同一批会话文件，否则会被当作两份设备用量。

超过一小时没有上报的设备显示最后上报时间并提示。跨日未上报或统计规则 / 时区不同的设备会被明确列为暂未计入，避免把不同日期的“今天”直接相加。

首次连接可上传源数据库当前仍存在的近 90 天明细。但 CC-Switch 自己通常只保留约 30 天明细：云端 90 天是持续运行后积累的保留期限，不能恢复源端已经删除的请求。长期离线导致源端先清理明细时，该部分明细无法补传。

## 内存与免费容量

采集器默认每批 80 条，最多可设为 100 条。数据库页面缓存限制 512 KiB，禁用 mmap，SQL 临时数据允许落盘；不会把请求表或整个数据库载入内存。无界面同步不会导入 Tkinter。

本机 Windows / Python 3.14 的 10 万条合成记录测试：峰值工作集约 **31 MiB**，同步计算约 **8.4 秒**，包含逐批 JSON 编码和本地进度持久化，接收端使用不保留记录的模拟确认接口，耗时不包括公网往返。内存数字包括 Python 运行时与数据库生成阶段，实际随 Python 版本、单条记录大小和系统环境变化。

按 2026-11-15 核对的官方限制，Cloudflare D1 Free 单库最多 500 MB，每日 10 万写入行、500 万读取行；主键和索引也占空间，索引维护也计入写入。90 天保留期不等于无限容量：如果平均每条日志连同索引约 1.5 KiB，两台设备合计每天 2,000 条，90 天约 264 MiB。请以 D1 控制台实际大小为准，保留容量余量。达到免费额度时采集器保留进度并显示失败，不跳过未确认批次。

服务端每小时最多物理清理 2,000 条超期记录，避免清理积压用尽当天写入额度；接口始终只返回最近 90 天。短时间首次导入大量记录可能先触及每日写入限额，次日继续同一进度即可。

官方限制：[D1 容量](https://developers.cloudflare.com/d1/platform/limits/)、[读写额度](https://developers.cloudflare.com/d1/platform/pricing/)。

## 验证与打包

开发检查需要 Python 3.11 或更新版本、Node.js 24 和 Git。以下检查不连接真实数据库、云端服务或账户；Worker 接口测试使用 Node 内置 SQLite，与 Cloudflare D1 的线上运行环境仍有区别。

```powershell
python tools/check_release.py
```

该命令统一检查语法、文档链接、版本、Python 与 JavaScript 测试，再生成并检查发布包、SHA-256 校验值和重复构建结果。提交到 GitHub 后，[自动检查配置](.github/workflows/ci.yml) 在 Windows / Python 3.11 与 3.14、Node.js 24 上运行相同流程，不会自动发布或部署。

按需单独运行：

```powershell
python -m unittest discover -s tests -v
node --test frontend/test/*.test.mjs cloudflare/test/*.test.mjs tools/test/*.test.mjs
python tools/benchmark.py --rows 100000
python tools/build_release.py
```

`tools/benchmark.py` 仅支持 Windows，只在本机临时目录生成合成记录并统计峰值内存。`tools/build_release.py` 从程序版本读取包名，生成 `dist/CC-Up-0.3.0.zip`、`dist/CC-Up-Web.zip` 和 `dist/SHA256SUMS.txt`；`dist/` 已被 Git 忽略，发布时作为 Release 附件上传。

包内不包含任何密钥、配置、真实数据库、`node_modules` 或开发缓存。客户端仍需 Python，不是内嵌运行时的 exe。

## 许可证

本项目以 MIT 许可证发布，见 [LICENSE](LICENSE)。`cc_up/rules.py` 和 `cc_up/database.py` 中迁自 [CC-Switch](https://github.com/farion1231/cc-switch) 的聚合规则同样使用 MIT 许可，完整声明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
