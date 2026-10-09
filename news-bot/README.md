# 🗞️ Telegram × GitHub 每小時中文新聞推送 Bot

用 **GitHub Actions** 每小時自動上網抓取**香港 + 國際**新聞，篩走曬英文同垃圾內容，
合成一份**純中文**快報推送去 Telegram 頻道／群組／個人。

> 唔使租伺服器、唔使俾錢、唔使識 Deploy —— GitHub Actions 免費額度已經夠用（每次約 30 秒）。

---

## ✨ 實際做到啲咩

| 功能 | 說明 |
|---|---|
| ⏰ 每小時自動推送 | GitHub Actions cron，香港時間每小時 08 分自動跑 |
| 🇭🇰 香港 + 🌍 國際 | 兩個版塊分開，可開關；另有財經／科技版塊可選 |
| 🈶 只推中文 | 用中日韓字比例檢測，英文報道自動濾走 |
| 🧹 智能去重 | 同一單新聞有 10 間媒體報道，只出一次，並標示「另見：XXX」 |
| 🚫 反洗版 | 同一版塊內同一媒體最多 2 單；已推送過嘅下一小時唔會再出 |
| 🔗 原連結 | 每條都附上原文連結，一撳即睇 |
| 📱 支援指令 | 附 `bot.py`，可 `/news`、`/hk`、`/world` 即時問新聞（可選） |

---

## 🚀 5 分鐘設定（GitHub Actions 方案）

### 1️⃣ 開一個 Telegram Bot

1. Telegram 搜尋 **[@BotFather](https://t.me/BotFather)** → 傳 `/newbot`
2. 改個名（例如 `HK News Bot`）、改個 username（例如 `my_hk_news_bot`，一定要 `_bot` 結尾）
3. 佢會俾一條 **HTTP API token** 你 → 抄低佢

### 2️⃣ 準備推送目標（三揀一）

| 目標 | 做法 | `TELEGRAM_CHAT_IDS` 填 |
|---|---|---|
| **頻道**（推薦） | 開個 Channel → 加 Bot 做 **Admin**（要有 Post 權限） | `@你的頻道username` |
| **群組** | 加 Bot 入群 | `-1001234567890` |
| **自己** | 直接 PM 個 bot | `987654321` |

> **點搵數字 ID？** 先隨便傳句嘢畀 bot／群組，然後開瀏覽器：
> `https://api.telegram.org/bot<你的TOKEN>/getUpdates`
> 入面 `chat` → `id` 就係。（群組 ID 一定係負數，前面要有 `-`）

### 3️⃣ 放上 GitHub

```bash
# 方法一：直接 Upload
#   GitHub 開新 repo → Add file → Upload files → 拖成個資料夾入去

# 方法二：用 git
cd news-bot
git init
git add .
git commit -m "feat: hourly Chinese news bot"
git branch -M main
git remote add origin https://github.com/<你的名>/<repo名>.git
git push -u origin main
```

### 4️⃣ 設定 Secrets（**最重要**）

去 repo → **Settings → Secrets and variables → Actions → New repository secret**，加兩個：

| Name | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | BotFather 俾你嗰條 token |
| `TELEGRAM_CHAT_IDS` | `@你的頻道` 或數字 ID（多個用逗號分隔） |

想改設定而唔改程式碼，可以喺 **Variables** 頁加（唔係 Secrets）：
`MAX_TOTAL`、`MAX_AGE_HOURS`、`SECTIONS`、`MODE`、`QUIET_HOURS`、`DISABLE_PREVIEW`

### 5️⃣ 開 Actions 同試跑

repo → **Actions** 頁 → 撳「I understand my workflows, go ahead and enable them」
→ 左邊揀 **每小時中文新聞推送** → **Run workflow**（可以剔 `dry_run` 先睇效果）

✅ 搞掂！之後每小時會自動推。想即刻睇效果就手動 Run 一次。

---

## 🧪 本機試跑（唔使 token 都睇到效果）

```bash
cd news-bot
pip install -r requirements.txt

# 預覽：print 出嚟，唔會真發送
python main.py --dry-run

# 出一個靚靚嘅 HTML 預覽檔（用瀏覽器開）
python main.py --dry-run --save-sample out/sample.html
```

真推送：開個 `.env`（參考 `.env.example`）之後 `python main.py`

---

## ⚙️ 點改設定

全部喺 `config.yaml`，改完 push 上 GitHub 就生效。

```yaml
settings:
  max_total: 14          # 每次最多推幾單（全部版塊加埋）
  max_age_hours: 12      # 只推 12 小時內嘅新聞
  max_per_source: 2      # 同一版塊內，同一媒體最多 2 單
  dupe_threshold: 0.42   # 標題相似度 ≥ 呢個值就當同一單（想少啲合併就調大）
  cjk_min_ratio: 0.25    # 標題要有 25% 中文字先當中文

sections:                # 版塊開關同數量
  - key: hk
    title: "🇭🇰 香港"
    limit: 6
    enabled: true
  - key: world
    title: "🌍 國際"
    limit: 6
    enabled: true
  - key: finance
    title: "💰 財經"
    limit: 3
    enabled: false       # 想要就改 true
```

### 加減新聞來源

```yaml
sources:
  - name: "My News"
    url: "https://example.com/rss"
    category: hk         # hk / world / finance / tech
```

### 過濾垃圾內容

- `block_keywords:` — 標題有呢啲字就丟（副刊、星座、開箱文…）
- `block_sources:` — 成個媒體跳過（財經數據頁、海外華人社區門戶…）
- `classify:` — 決定「呢單係香港定國際」（按來源名／標題關鍵字判斷）

---

## 🤖 可選：常駐 Bot（支援對話指令）

GitHub Actions 淨係識定時推。想用戶可以隨時 `/news` 問，就跑 `bot.py`
（Render / Railway / 自己部機都得，最簡單係 Render 開個 Background Worker）：

```bash
# .env 入面要有 TELEGRAM_BOT_TOKEN
python bot.py
```

| 指令 | 作用 |
|---|---|
| `/start` | 訂閱每小時自動推送 |
| `/news` | 即刻攞一次最新（港聞＋國際＋財經＋科技） |
| `/hk` | 淨係香港 |
| `/world` | 淨係國際 |
| `/finance` `/tech` | 財經／科技 |
| `/stop` | 取消訂閱 |

> bot.py 同 GitHub Actions 可以同時用，兩邊共用同一份去重記錄，唔會推重複。
> 怕麻煩嘅話，**淨用 GitHub Actions 已經夠**。

---

## 📂 檔案結構

```
news-bot/
├── .github/workflows/hourly-news.yml   # 每小時自動跑嘅 workflow
├── config.yaml                          # ⭐ 所有設定：新聞源、版塊、過濾規則
├── main.py                              # GitHub Actions 入口
├── bot.py                               # （可選）常駐 bot，支援指令
├── newsbot/
│   ├── config.py      # 讀 config.yaml ＋ 環境變數
│   ├── fetcher.py     # 並發抓 RSS、清理標題
│   ├── filters.py     # 中文檢測、新鮮度、黑名單
│   ├── classify.py    # 判斷香港／國際
│   ├── cluster.py     # 合併同一單新聞、排序
│   ├── dedupe.py      # 已推送記錄（state/sent.json）
│   ├── formatter.py   # 排版成 Telegram HTML、自動拆訊息
│   └── telegram.py    # Bot API（含限速重試）
├── state/sent.json    # 去重記錄，workflow 會自動 commit 返
└── out/sample.html    # 效果預覽
```

## 📰 新聞來源（全部實測可用）

**香港**：Google 新聞（香港頭條／港聞／突發）、香港 01、香港電台、星島頭條、明報
**國際**：Google 新聞（國際／兩岸）、BBC 中文、德國之聲、RFI 中文、美國之音、中央社
**其他**：ETtoday、自由時報、公視（財經／科技版塊另有港股、中央社財經科技等）

---

## ⏰ 加埋 cron-job.org（建議・可選）

GitHub Actions 內置 cron 有兩個缺點：**繁忙時會延遲 5–30 分鐘**，同埋
**repo 60 日冇活動會自動停用排程**。加埋 cron-job.org 就可以解決：

```
cron-job.org  →  POST  →  GitHub Actions workflow_dispatch  →  推送新聞
   （準點到分鐘）              （免費運算 + 存放 Secrets）
```

設定步驟睇 **`cron-job-setup.html`**（圖文教學），簡單講：

1. 開一條 **Fine-grained Personal Access Token**，只開 `Actions: Read and write`
2. cron-job.org 開 cronjob：
   - URL：`https://api.github.com/repos/<OWNER>/<REPO>/actions/workflows/hourly-news.yml/dispatches`
   - Method：`POST`
   - Headers：`Authorization: Bearer <PAT>`（另加 `Accept` / `X-GitHub-Api-Version` / `Content-Type`）
   - Body：`{"ref":"main"}`
   - 排程：每小時第 0 分
3. 撳 TEST RUN，見到 **204** 就成功

**唔使驚重複推送**：程式內置「最短推送間隔鎖」（`min_interval_minutes`，預設 45）。
兩個 trigger 邊個先到邊個推，另一個會自動跳過；一邊死機另一邊就頂上。

---

## ❓ 常見問題

**Q：點解唔係正點收到？**
GitHub Actions 嘅 cron 喺繁忙時間會延遲 5–30 分鐘，屬正常現象。想準時就用 `bot.py` 常駐方案。

**Q：Token 放 GitHub 會唔會洩漏？**
放喺 **Secrets** 係加密嘅，log 入面會自動變 `***`，安全。千祈唔好直接寫喺 `config.yaml` 入面（尤其 public repo）。

**Q：想深夜唔好嘈？**
喺 Variables 加 `QUIET_HOURS=0-6`（香港時間凌晨 0 到 6 點唔推）。

**Q：想一單新聞一條訊息，唔想打包？**
Variables 加 `MODE=individual`。

**Q：淨係想要香港新聞？**
Variables 加 `SECTIONS=hk`。

**Q：推送內容有啲唔啱心水？**
改 `config.yaml` 嘅 `block_keywords` / `block_sources` / `source_priority`，push 上 GitHub 即刻生效。

**Q：免費額度夠唔夠？**
每次跑約 30–60 秒，每小時一次一個月約 30 分鐘。Public repo 無限免費；private repo 免費 2000 分鐘／月，都綽綽有餘。

---

Made in Hong Kong 🇭🇰 · 有問題隨時開 issue 或者問我
