# ANLI Market Radar

ANLI 原则驱动交易决策系统的公开隐私版。3.2 从浏览器本机持仓出发，匹配未来四个自然周的公司、产业链、行业和宏观事件；3.1、3.0、2.0、1.0 全部保留，电脑与手机使用同一套响应式页面和数据。

## 页面

- `index.html`：3.2 私人持仓事件与回归研究；公开版持仓只存在当前浏览器，不上传服务器，公开数据不足时不生成回归结论。
- `v3.1.html`：3.1 验证与风险闭环；公开版不接收或展示账户、持仓、成本和止损资料。
- `v3.html`：3.0 统一决策系统。
- `v1.html`：1.0 主看板，覆盖大盘、自然周事件、机会排序和 52 只股票。
- `playbooks.html`：2.0 剧本指挥台，展示环境、风险闸门、仓位上限和逐股行动剧本。
- `qqq_trendiq.html?symbol=NVDA`：任意观察池股票的 TrendIQ 多周期技术分析；QQQ 使用同一页面。

每只股票均包含 15 分钟、1 小时、4 小时、日线和周线分析（以真实数据可用性为准）、趋势指标、形态、支撑阻力、计划价位、风险收益和数据时效闸门。系统不会补造缺失行情，也不会自动下单。

## 数据与恢复

公开行情可能延时或被限流。生成端会保存最后一份通过校验的真实行情；临时断线或进程重启时，页面明确标记“最后有效缓存”，避免误报为实时数据，也避免整站空白。实际交易前仍须用券商实时 Bid/Ask 复核。

## 自动更新

GitHub Actions 在美股工作日定时生成公开快照。只有 Python、浏览器脚本、Cloudflare Worker、数据质量和发布物校验全部通过后才部署；失败时保留上一版站点。仓库内的 bootstrap 包提供经过验证的 52 股只读兜底快照。

## 本地验证

```bash
python -m unittest discover -s tests -v
node --test tests/public_adapter.test.mjs
node --test tests/v3_frontend.test.mjs tests/v31_frontend.test.mjs tests/v32_frontend.test.mjs
python tools/export_public_release.py .site --runtime .runtime --timeout-seconds 840
python tools/validate_public_release.py .site/data
python tools/build_v2_overlay.py .site
python tools/build_v31_overlay.py .site
```

公开发布物不包含 API 密钥、账户、审计库、私有任务、原始模型响应或内部错误详情。
