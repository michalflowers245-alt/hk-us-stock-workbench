# 行情与交易日历来源核验

- 核验日期：2026-11-22
- 研究/回放模式：`DEMO`；实时行情连接器：Futu OpenAPI OAuth 2.1 + PKCE，授权状态由本机钥匙串决定。本轮未完成用户授权，当前没有真实报价。
- 当前样本：港股和美股各 15 个合成证券，代码均以 `SYN-` 开头；证券名称和K线由固定算法生成。

## 实时港股报价接入

| 项目 | 已实现内容 | 仍需实测或边界 |
|---|---|---|
| 标的 | `HK.800000` 恒生指数、`HK.800700` 恒生科技、`HK.800100` 恒生中国企业指数、`HK.00700` 腾讯、`HK.09988` 阿里、`HK.01810` 小米、`HK.03690` 美团 | 代码能被 API 解析不代表该账号拥有报价权限；需要授权后逐项检查返回结果。 |
| 授权 | 动态注册本机 OAuth 公共客户端，PKCE + state；只请求 `quote:read`。OAuth 令牌仅保存在 macOS 钥匙串。 | 本人需在富途官方页面登录并批准只读行情权限；授权令牌默认 14 天有效，之后需要重新授权。 |
| 实时连接 | WebSocket 订阅基础报价；断线后指数退避重连、重新鉴权和订阅；REST 快照在每次连接时补齐当前值；每 5 分钟刷新推送会话。 | 富途官方明确订阅是否成功还受市场/品类权限、权限级别和订阅配额影响。没有完成账号授权前不能宣称实时通路可用。 |
| 历史记录 | 独立 SQLite 表保存源行情时间、接收时间；港股连续交易时段按分钟采样，可从页面导出 CSV。 | Mac 睡眠/关机时无法采集；行情源中断期间会形成可见缺口。分钟快照只在服务运行且港股日历处于连续交易时段时生成。 |
| 费用 | 富途文档称 API 调用没有额外 API 费；部分行情品种需购买行情卡。文档列出国际客户港股证券 LV1 免费。 | 指数权限、账号地区身份及代码可用范围仍以该账号的授权/订阅结果为准，不推定为免费或可用。 |

官方依据：[OAuth 与权限范围](https://open.futunn.com/api/overview/getting-started)、[市场行情权限与配额](https://open.futunn.com/api/overview/api-authority)、[API 费用](https://open.futunn.com/api/overview/api-fee)、[实时快照字段](https://open.futunn.com/api/quote/realtime/stock-quote)、[WebSocket 鉴权与会话刷新](https://open.futunn.com/api/quote/push/auth)、[WebSocket 报价订阅格式](https://open.futunn.com/api/quote/push/subscribe)、[WebSocket 行情字段](https://open.futunn.com/api/quote/push/data-format)。以上文档在 2026-11-22 核验；实时授权范围和代码权限尚未通过用户账号验证。

## 候选日线来源

| 来源 | 市场覆盖与历史 | 授权、限额与费用 | 结论 |
|---|---|---|---|
| Futu OpenAPI | 本项目已实现香港关注标的的 REST 快照与 WebSocket 实时报价连接器。官方文档另列历史K线和交易日历接口。 | OAuth 2.1 PKCE；报价读取只请求 `quote:read`，令牌保存在 macOS 钥匙串。可用权限及行情级别取决于用户授权和产品权限。 | 连接代码已集成；截至核验时本人尚未完成官方登录授权，因此没有真实报价。授权后仍需确认各个指数、证券代码和行情权限。 |
| Twelve Data | 官方覆盖目录列出 XHKG 港交所和美国市场，并提供日线端点；每个具体证券历史长度仍需逐符号确认。 | Basic 标价为 `$0`、8 credits/min 和 800/day，但只有 3 个市场；官方定价页列出 Grow `$29/月`、20+ 市场、internal display。Basic 对 XHKG 的可用性、公司行动完整度及本机缓存许可需以账号条款再核。 | 可能适合小规模日终验证；需要注册 API Key，免费覆盖与再分发权未证实。当前没有注册或接入。 |
| Alpha Vantage | 官方 API 文档描述全球日线序列与 25+ 年历史；调整日线是单独的 premium 接口。官方示例含上海、深圳代码，未在本轮确认港交所符号覆盖。 | 使用 API Key。免费配额、香港覆盖、调整历史的实际权限及工作台缓存/派生数据的适用条款，需在注册前再次确认。 | 不能据“全球覆盖”推定满足港股要求。当前没有注册或接入。 |

上述来源及范围依据：[Futu 开发入门](https://open.futunn.com/api/overview/getting-started)、[Futu API 分类](https://open.futunn.com/api/overview/api-reference)、[Twelve Data 价格](https://twelvedata.com/pricing)、[Twelve Data XHKG 目录](https://support.twelvedata.com/en/articles/12682324-end-of-day-eod-pricing-market-data)、[Alpha Vantage API 文档](https://www.alphavantage.co/documentation/)和[使用条款](https://www.alphavantage.co/terms_of_service/)。本表是初步比对，不构成对具体账号权限或法律许可的认定。

## 交易日历

- 使用 `exchange_calendars==4.13.3` 的 `XHKG` 和 `XNYS` 会话表，保留开盘、收盘时刻并显示半日市。
- 香港交易时段和公众假期以[港交所证券市场时段](https://www.hkex.com.hk/Services/Trading-hours-and-Severe-Weather-Arrangements/Trading-Hours/Securities-Market?sc_lang=en)及[香港证券市场 2026 假期表](https://www.hkex.com.hk/-/media/HKEX-Market/Services/Circulars-and-Notices/Participant-and-Members-Circulars/SEHK/2025/ce_SEHK_CT_075_2025.pdf)作核对入口。
- 美国假期及提前收市以[NYSE 官方交易时段和假期日历](https://www.nyse.com/trade/hours-calendars)作核对入口。
- 库内日历适用于本机演示和逐日计算。正式接入真实行情前，应对照当年两地交易所日历复核；若交易所修订日历，须升级日历数据版本并保留记录。

## 数据隔离决策

研究/回放模块继续使用 `HKUS_DATA_MODE=DEMO`；Futu 实时报价使用独立的 `/api/realtime/*` 接口和独立 SQLite 表，不会进入 DEMO 快照或策略模拟。服务将 `HKUS_DATA_MODE` 设成其他值时仍会停止启动。页面会显示行情数据时间、接收时间、连接状态、具体不可用代码和历史缺口。
