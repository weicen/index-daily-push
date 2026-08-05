# 美股指数日报 · 云端自动推送（GitHub Actions + Server酱）

电脑关机也能每天 08:00 收到标普500 / 纳指100 的收盘涨幅、PE 和定投策略提示。

## 工作原理

```
每天 08:00（北京时间）
   │  GitHub Actions（免费云端，与你电脑无关）
   ▼
抓取数据 → 生成日报卡片 → Server酱 → 你的微信
```

| 数据 | 来源 | 说明 |
|---|---|---|
| 标普500 / 纳指100 行情 | CNBC 官方免费 API | 收盘点位、涨跌、涨跌幅 |
| 标普500 PE | multpl.com（Shiller 权威数据） | as-reported TTM 口径 |
| 纳指100 PE | FMP 免费 API 取 QQQ 的 PE | QQQ 完全跟踪纳指100，误差极小 |

周六/周日美股休市，自动跳过不推送。

---

## 部署步骤（约 10 分钟，只需做一次）

### ① 注册 GitHub 账号（免费）
- 打开 https://github.com 注册并登录（已有账号跳过）

### ② 获取 Server酱 SendKey（用于微信接收）
1. 打开 https://sct.ftqq.com ，用**微信扫码**登录
2. 进入「SendKey」页，复制你的 SendKey（形如 `SCTxxxxxxx...`）
3. 扫码关注 Server酱 公众号（不关注收不到推送）

### ③ 获取 FMP 免费 API Key（用于纳指100的PE）
1. 打开 https://financialmodelingprep.com/developer/docs 点 **Register** 注册（免费）
2. 注册后进 Dashboard → **API Key**，复制（形如一串字母数字）
   - 免费版每天 250 次请求，本任务每天只用 1 次，足够

### ④ 创建 GitHub 仓库并上传本目录文件
1. GitHub 右上角 **+ → New repository**
2. 名字随意（如 `index-daily-push`），选 **Private（私有）**
3. 创建后，把本目录的 **3 样东西**上传到仓库根目录：
   - `fetch_data.py`
   - `.github/workflows/daily-push.yml`（.github 是隐藏文件夹，上传时注意保留路径）
   - 本 `README.md`（可选）

> 不会传文件？GitHub 仓库页点 **Add file → Upload files**，把文件拖进去即可。

### ⑤ 配置两个密钥（Secrets）
1. 仓库页 → **Settings → Secrets and variables → Actions**
2. 点 **New repository secret**，添加两个：
   | Name | Value |
   |---|---|
   | `FMP_KEY` | ③ 拿到的 FMP API Key |
   | `SERVERCHAN_SENDKEY` | ② 拿到的 Server酱 SendKey |

### ⑥ 手动测试一次
1. 仓库页 → **Actions** → 左侧 `daily-index-push` → **Run workflow**
2. 等 1~2 分钟跑完，绿色对勾 = 成功
3. 打开微信，应收到 Server酱 推送的日报卡片 ✅

### ⑦ 完成
之后每天北京时间 08:00 自动执行，电脑关机也能收到。想临时手动推送一次，随时去 Actions 页点 Run workflow。

---

## 常见问题

**Q：没收到推送？**
- 确认 ⑥ 手动测试时 Actions 是绿色；红色则点进日志看报错
- 确认已扫码关注 Server酱 公众号
- 确认 Secrets 的两个名字拼写正确（`FMP_KEY` / `SERVERCHAN_SENDKEY`）

**Q：PE 数值和我之前看到的（24.34 / 28.93）不一样？**
正常。那是两个不同口径：本方案 SPX 用 multpl 的 as-reported 口径（约 29~30），
原来的 24.34 是指数 TTM 加权口径。判断"多投/少投"的方向通常一致，以同一口径连续跟踪即可。

**Q：周末会推送吗？**
不会，脚本自动跳过周六/周日（美股休市没有新数据）。

**Q：原来的本地自动化怎么办？**
云端跑通后建议把本地自动化暂停（避免每天收到两条不同口径的推送）。
暂停方法：WorkBuddy 自动化设置里把任务停用即可；如需恢复随时再开。
