---
name: flight-scan
description: 讓 Claude 幫你大範圍掃機票:透過 SerpApi 讀 Google 航班,把「一段日期的每一天出發 × 玩幾天 × 整個國家的機場」一次比完,找出最便宜的來回票,再做成一頁價格日曆報表。也能查預算內能飛哪些城市、這張票現在算便宜還是貴(Google 價格紀錄)、同一班飛機哪天出發最便宜。只要使用者說「找便宜機票」「機票比價」「幫我掃機票」「最便宜什麼時候飛」「飛日本 / 韓國 / 泰國多少錢」「預算多少能飛哪」「這張票該不該買」「Google Flights」「SerpApi」,或任何要比較很多日期、很多機場票價的需求,都要用這個 skill,即使沒有說出「掃」這個字。Use for scanning many dates × trip lengths × airports on Google Flights via SerpApi to find the cheapest round trip.
---

# flight-scan:讓 AI 幫你掃機票

以前找機票是一個日期一個日期換著查;這個 skill 讓 Claude 一次把整段日期、幾種天數、整個國家的機場全部查完、排好,
最後交一頁報表。所有查詢都走 `scripts/flights.py`(只用 Python 標準函式庫),結果存在使用者的資料夾,同樣條件再問不會重查。

## 開工前:金鑰

1. 跑 `python <skill>/scripts/flights.py account`。印出方案和剩餘次數就可以開始。
2. 說找不到金鑰,就請使用者:
   - 到 https://serpapi.com/users/sign_up 免費註冊(免費方案每月 250 次)
   - 登入後在 Dashboard 的「Your Private API Key」複製金鑰,貼給你
3. 拿到金鑰後寫進 `<skill>/.env`,只寫一行 `SERPAPI_KEY=金鑰`。**不要在回覆裡重貼金鑰,不要寫進任何會被 commit 的檔案**(skill 自帶的 `.gitignore` 已排除 `.env`)。

`<skill>` 是這個 SKILL.md 所在的資料夾。查詢結果預設存在目前資料夾的 `flight-scan-data/`。

## 流程

### 1. 問清楚條件

使用者沒講的才問(AskUserQuestion 一次問完,第一個選項標 Recommended):

| 條件 | 參數 | 預設 |
|---|---|---|
| 從哪出發 | `--from` | TPE(桃園) |
| 去哪 | `--to` | 國家代號 JP / KR / TH…、城市代號 TOKYO / OSAKA…,或機場代號(`OKA`、`NRT,HND`) |
| 哪段日期出發 | `--start` `--end` | 接下來兩個月 |
| 玩幾天 | `--days` | 4,5,6(來回玩 5 天 = 第 1 天去、第 5 天回) |
| 預算 | 報表的 `--budget` | 沒有就不篩 |

代號對照、怎麼查新的國家代號在 `references/serpapi.md`。

### 2. 先算要查幾次,再開跑

```bash
python <skill>/scripts/flights.py grid --from TPE --to JP --start 2026-11-01 --end 2026-12-31 --days 4,5,6 --dry-run
```

一個「出發日 × 天數」就是一次查詢(兩個月 × 3 種天數 ≈ 183 次)。把次數跟 `account` 的剩餘次數一起告訴使用者:

- 次數超過剩餘額度,或使用者想省:提議 `--step 2`(隔天查一次)或少一種天數
- 使用者同意後才真的跑,`--max-calls` 設成同意的次數。超過 30 次就在背景跑(每次約 2–4 秒)
- 中途停了(到上限、一小時內查太多會自動等 5 分鐘),同一行指令再跑一次會從斷的地方接著查,查過的不扣額度

### 3. 整理、做報表、回報

```bash
python <skill>/scripts/flights.py analyze --from TPE --to JP          # 最便宜排行、每個機場最低價、價格日曆
python <skill>/scripts/flights.py report  --from TPE --to JP          # 一頁 HTML:價格日曆、前 10 名、各機場長條
```

回報時先講結論:最便宜那張(價格、日期、玩幾天、哪個機場、航空公司、班次、直飛或轉機),再講第二、三便宜的機場,
最後附報表路徑和那張票的 Google 航班連結。說明查詢時間,票價以 Google 航班當下為準。

### 4. 使用者追問時

| 使用者問 | 指令 | 額度 |
|---|---|---|
| 預算 8,000 能去哪些城市? | `explore --to JP --months 11,12 --budget 8000` | 一個月 1 次 |
| 這張票現在算便宜還是貴? | `insights --to OKA --depart 2026-11-01 --return 2026-11-05` | 1 次;目的地用單一機場才有價格紀錄 |
| 這班飛機哪天出發最便宜、哪天最貴? | `flight --to JP --flight "TR 866" --days 4` | 0 次(讀 grid 結果) |
| 這張票去回程是哪兩班? | `ticket --to JP --depart 2026-11-01 --return 2026-11-05` | 1 次(查回程) |
| 報表加上預算城市 | 先跑 explore,再 `report --budget 8000` | 0 次 |

`insights` 會說價格水準(偏低 / 一般 / 偏高)、平常區間和近兩個月的價格紀錄;回答時用這三個數字講「該不該現在買」。
常用的說法和它們對到的指令,在 `references/prompts.md`。

## 規則

- **只查不訂**:這個 skill 不下單、不付款、不填乘客資料。要訂就給 Google 航班連結,讓使用者自己去訂。
- **額度要先講**:任何一次會新查超過 10 次的動作,先說要用幾次、還剩幾次,得到同意才跑。
- **數字要同一輪**:同一份回報裡的票價都來自同一輪查詢;使用者隔天再問,建議重查最關鍵的那幾組(把 `flight-scan-data/` 裡對應的 json 移走再跑)。
- 價格是 SerpApi 讀到的 Google 航班經濟艙來回價(含稅、`--currency` 預設台幣),行李、選位另計,依航空公司為準。
- 金鑰只放 `.env`,不印出、不 commit、不貼進報表。
