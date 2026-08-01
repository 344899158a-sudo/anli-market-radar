# ANLI Market Radar

ANLI 原则驱动交易决策看板的公开只读版本。电脑版与手机版使用同一套 HTML、JavaScript、规则引擎和快照数据，只通过响应式布局适配不同屏幕。

## 页面内容

- 大盘环境、未来四周事件、QQQ 多周期决策雷达
- 板块广度、机会排序、48 只重点股票
- 个股多周期技术分析、形态、支撑阻力与情景计划
- 已脱敏的 AI、新闻与 SEC 证据快照
- 本机持仓标记；不会写回服务器，也不会自动下单

## 自动更新

GitHub Actions 在美股工作日每 15 分钟生成一次公开快照，周末每日校验一次。只有测试、数据质量和发布物校验全部通过后才部署；失败时保留上一版网站。

公开快照不包含 API 密钥、账户、审计库、私有任务、原始模型响应或内部错误。公开行情可能延时或限流，所有静态快照均标记为不可直接执行，实际交易前必须用券商实时行情复核。

## 本地验证

```bash
python -m unittest -v tests.test_public_release tests.test_public_snapshot tests.test_public_snapshot_quality
node --test tests/public_adapter.test.mjs
python tools/export_public_release.py .site --runtime .runtime --timeout-seconds 840
python tools/validate_public_release.py .site/data
```
