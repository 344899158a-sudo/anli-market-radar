# ANLI Market Radar

独立的手机端 QQQ 大盘状态与未来四周事件雷达。

## 数据与边界

- QQQ 价格和日 K：Nasdaq.com 公开延时数据。
- 事件：美联储、BLS、BEA、公司投资者关系页面等官方来源人工核验。
- 页面展示的是决策辅助，不是券商实时行情，不执行自动交易。
- 数据更新失败时保留上一份真实快照，页面显示快照时间，不填充虚构金融数据。

## 本地检查

```powershell
npm test
npm run refresh
```

静态网页文件位于仓库根目录。GitHub Actions 会定时重新生成
`dashboard.json` 并部署到 GitHub Pages。
