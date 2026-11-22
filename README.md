# 港美股日终研究工作台

本机单用户、日终数据、只读研究。包含港股/美股概览、规则机会池、日K与均线、自选和逐日历史回放。

> 当前全部数据均为 DEMO 合成数据。示例证券、K线、信号、成交额和模拟结果都不代表真实行情或真实收益。项目不连接券商、不接受订单、不公开监听。

## macOS 快速开始

前置条件：Python 3.12、Node.js 20.19+ 或 22.12+、npm、uv。首次双击 **设置环境.command** 安装锁定依赖并构建。之后双击 **启动港美股工作台.command**，浏览器会打开 `http://127.0.0.1:8740`。双击 **停止港美股工作台.command** 可停止本机服务。Mac 睡眠或关机期间服务会暂停。

也可在终端手动运行：

```bash
uv sync --python 3.12
npm ci
npm run build
.venv/bin/python ops/local_runtime.py start
```

打开 [http://127.0.0.1:8740](http://127.0.0.1:8740)。停止：

```bash
.venv/bin/python ops/local_runtime.py stop
```

## Windows

安装 Python 3.12、Node.js 20.19+ 或 22.12+、npm 和 uv。使用 PowerShell 在项目根目录运行：

```powershell
uv sync --python 3.12
npm ci
npm run build
uv run uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8740
```

打开 `http://127.0.0.1:8740`；按 `Ctrl+C` 停止服务。仅监听回环地址，不要改为 `0.0.0.0`。

## 页面与数据

- **市场全景：** 港美两市分别显示最近完整交易日、预期交易日、计算时间、数据覆盖和规则观察。
- **机会池：** 按市场切换，可搜索、排序、筛选和打开个股；支持导出带 DEMO 来源和规则版本的 CSV；白名单是 30 个合成样本。
- **个股分析：** 最多 500 根合成日K、成交量、MA5/13/21/34/55、规则标记与逐条理由；日期回放截止后不会读取未来K线。支持深浅主题及主题记忆。
- **我的自选：** 添加、移除、备注和本机持久化。
- **历史回放：** 单一标的逐日模拟，列出规则信号、下一日开盘执行、费用/滑点假设、资金曲线和最大回撤。

行情和模拟响应会附上 `data_mode=DEMO`、来源、交易日、计算时间、规则版本、输入指纹、数据修订和数据警告。成交额使用“收盘价×成交量”的合成估算值。涨跌颜色默认港股红涨绿跌、美股绿涨红跌，顶栏可切换。重复刷新在输入未变化时沿用同一快照，不制造重复记录。

交易日历来自 `exchange_calendars` 的 `XHKG` / `XNYS` 会话表，处理各自时区、休市日和半日市，并在 API 返回当地开收盘时间。准确性核对入口见 [`docs/data-sources.md`](docs/data-sources.md)。

策略参数由 [`config/strategy.json`](config/strategy.json) 提供；规则定义、边界与费用假设见 [`docs/strategy.md`](docs/strategy.md)。

## 真实行情状态

尚未接入任何真实行情供应商。初步核验结果、官方出处、报价/配额和待确认的许可边界记录在 [`docs/data-sources.md`](docs/data-sources.md)。获得明确授权并完成逐市场覆盖、费用、缓存与个人研究许可确认前，服务只运行合成数据；把 `HKUS_DATA_MODE` 改为非 `DEMO` 会阻止启动。

## 配置与本机数据

- 默认地址：`127.0.0.1:8740`。现有港股工作台使用 `8738`，两者独立。
- 可复制 `.env.example` 为 `.env` 并修改本机端口；监听地址必须保持 `127.0.0.1`，不能设置为 `0.0.0.0`。
- SQLite：`data/market.sqlite3`。运行日志：`data/logs/web.log`。均已排除在 Git 外。
- 备份：先停止服务，再复制 `data/market.sqlite3`；恢复时停止服务后替换数据库文件。
- 清空演示数据：停止服务后删除 `data/market.sqlite3` 与 `data/market.sqlite3-wal`、`data/market.sqlite3-shm`，下次启动会重新生成合成库。真实行情接入后不要使用此命令。

## 开发和验收

```bash
uv run pytest
npm run build
npm run test:e2e
```

pytest 覆盖指标/信号边界、下一日成交与待执行、未来数据不改写过去、日历半日市、前导零代码、自选去重、快照幂等、CSV 演示标识、跨源写入拦截和公司行动阻断。Playwright 覆盖主题记忆、机会池 CSV 导出、搜索与个股、自选、回放、筛选排序和窄屏溢出。

本轮具体验收结果与运行边界见 [`docs/验收记录.md`](docs/验收记录.md)。

Windows 首次运行浏览器验收前，执行 `npx playwright install chromium`。

项目源码适用 MIT；第三方库按各自许可使用。数据供应商条款和 Lightweight Charts 署名范围见 [`LICENSE-SCOPE.md`](LICENSE-SCOPE.md)。
