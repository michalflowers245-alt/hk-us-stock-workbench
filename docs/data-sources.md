# 行情与交易日历来源核验

- 核验日期：2026-11-22
- 当前运行：`DEMO`，无真实行情供应商连接、无 API Key、无登录凭证。
- 当前样本：港股和美股各 15 个合成证券，代码均以 `SYN-` 开头；证券名称和K线由固定算法生成。

## 候选日线来源

| 来源 | 市场覆盖与历史 | 授权、限额与费用 | 结论 |
|---|---|---|---|
| Futu OpenAPI | 官方文档列出香港与美国行情、历史K线、交易日历；调整方式和历史分页由端点参数确定。 | OAuth 2.1 PKCE；报价读取需 `quote:read`，可用权限及行情级别取决于用户授权和产品权限。令牌须安全保存。 | 技术覆盖较合适，但须连接 Futu 授权。当前没有授权；本项目暂不接入。 |
| Twelve Data | 官方覆盖目录列出 XHKG 港交所和美国市场，并提供日线端点；每个具体证券历史长度仍需逐符号确认。 | Basic 标价为 `$0`、8 credits/min 和 800/day，但只有 3 个市场；官方定价页列出 Grow `$29/月`、20+ 市场、internal display。Basic 对 XHKG 的可用性、公司行动完整度及本机缓存许可需以账号条款再核。 | 可能适合小规模日终验证；需要注册 API Key，免费覆盖与再分发权未证实。当前没有注册或接入。 |
| Alpha Vantage | 官方 API 文档描述全球日线序列与 25+ 年历史；调整日线是单独的 premium 接口。官方示例含上海、深圳代码，未在本轮确认港交所符号覆盖。 | 使用 API Key。免费配额、香港覆盖、调整历史的实际权限及工作台缓存/派生数据的适用条款，需在注册前再次确认。 | 不能据“全球覆盖”推定满足港股要求。当前没有注册或接入。 |

上述来源及范围依据：[Futu 开发入门](https://open.futunn.com/api/overview/getting-started)、[Futu API 分类](https://open.futunn.com/api/overview/api-reference)、[Twelve Data 价格](https://twelvedata.com/pricing)、[Twelve Data XHKG 目录](https://support.twelvedata.com/en/articles/12682324-end-of-day-eod-pricing-market-data)、[Alpha Vantage API 文档](https://www.alphavantage.co/documentation/)和[使用条款](https://www.alphavantage.co/terms_of_service/)。本表是初步比对，不构成对具体账号权限或法律许可的认定。

## 交易日历

- 使用 `exchange_calendars==4.13.3` 的 `XHKG` 和 `XNYS` 会话表，保留开盘、收盘时刻并显示半日市。
- 香港交易时段和公众假期以[港交所证券市场时段](https://www.hkex.com.hk/Services/Trading-hours-and-Severe-Weather-Arrangements/Trading-Hours/Securities-Market?sc_lang=en)及[香港证券市场 2026 假期表](https://www.hkex.com.hk/-/media/HKEX-Market/Services/Circulars-and-Notices/Participant-and-Members-Circulars/SEHK/2025/ce_SEHK_CT_075_2025.pdf)作核对入口。
- 美国假期及提前收市以[NYSE 官方交易时段和假期日历](https://www.nyse.com/trade/hours-calendars)作核对入口。
- 库内日历适用于本机演示和逐日计算。正式接入真实行情前，应对照当年两地交易所日历复核；若交易所修订日历，须升级日历数据版本并保留记录。

## 接入决策

在获得明确授权、确认市场覆盖、费用、个人使用和本机缓存许可之前，不启用真实行情 Provider。`HKUS_DATA_MODE` 只能设为 `DEMO`；将其设为其他值时服务会停止启动，避免把演示结果显示为真实数据。
