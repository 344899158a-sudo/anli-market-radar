# ANLI Market Radar

独立的手机端 QQQ 大盘状态与未来四周事件雷达。

- 公开首页：<https://344899158a-sudo.github.io/anli-market-radar/>
- QQQ 技术详情：在首页点击第一张模块，进入 `#trendiq`。
- 首页与详情共用同一份 `public/data/dashboard.json`，不会复制交易规则。
- 浏览器每60秒检查云端快照，回到前台时也会立即复核。

## 数据与边界

- QQQ 价格和日 K：Nasdaq.com 公开延时数据。
- 事件：美联储、BLS、BEA、公司投资者关系页面等官方来源人工核验。
- GitHub Actions 在工作日配置为约每15分钟重新生成并部署，定时触发属于平台尽力而为；页面会标记偏旧快照。
- 未来四周事件是人工核验清单，自动构建只滚动展示窗口，不会自动发现或核验新事件。
- 页面展示的是决策辅助，不是券商实时行情，不执行自动交易。
- 数据更新失败时保留上一份真实快照，页面显示快照时间，不填充虚构金融数据。

## 本地检查

```powershell
npm test
npm run check
```

静态网页位于 `public/`。GitHub Actions 会重新生成
`public/data/dashboard.json`，通过新鲜度、历史行数、来源与结构闸门后再部署到
GitHub Pages；刷新失败时保留上一份真实部署，不填入虚构行情。
