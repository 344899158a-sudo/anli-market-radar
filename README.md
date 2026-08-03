# ANLI Market Radar 2.1

ANLI 原则驱动交易决策看板的公开只读版本。电脑版与手机版读取同一份已校验快照和同一套 2.1 决策结果，只通过响应式布局适配不同屏幕。

## 页面内容

- 五层指挥栈：数据、市场、行业、个股剧本、执行确认
- 四套互斥剧本：强势龙头回踩、买预期、财报后确认、超跌修复
- 六阶段事件生命周期、买预期卖事实证据链、进场触发与退出失效条件
- 大盘环境、未来四周事件、QQQ 决策雷达与板块广度
- 48 只重点股票的独立决策卡和详细技术分析
- 公开行情仅用于研究；任何执行都必须由券商实时行情再次确认

## 自动更新

GitHub Actions 在美股工作日每 15 分钟生成一次公开快照，周末每日校验一次。旧版数据层继续负责行情抓取、哈希校验、不可变快照和失败降级；2.1 决策层只读取通过验证的发布物。只有旧数据层、2.1 规则、48 个技术分片和 Pages 发布物全部通过时才部署。

实时刷新失败时，系统只允许复用上一份已验证行情并单独更新仍在核验窗口内的事件日历；页面会保留原始行情时间并标记 `PARTIAL` 或 `BLOCKED`，不会把旧数据伪装成最新行情。

公开快照不包含 API 密钥、账户、审计库、私有任务、原始模型响应或内部错误。系统不会自动下单，也不承诺盈利。

## 本地验证

```bash
python -m unittest discover -s tests -v
python -m compileall -q src tools
node --test tests/public_adapter.test.mjs
python tools/export_public_release.py .site --runtime .runtime --timeout-seconds 840
python tools/validate_public_release.py .site/data
python tools/build_v2_overlay.py .site
```
