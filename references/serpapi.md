# SerpApi 備忘

## 用到的兩個引擎

| 引擎 | 指令 | 重點參數 |
|---|---|---|
| `google_flights` | grid、insights、ticket | `departure_id`、`arrival_id`(機場代號可逗號隔開,也可以是國家的知識圖譜代號)、`outbound_date`、`return_date`、`type=1` 來回、`sort_by=2` 依價格 |
| `google_travel_explore` | explore | `departure_id`、`arrival_area_id`(國家 / 地區代號)、`month`、`travel_duration`(1 週末 / 2 一週 / 3 兩週) |

共用:`currency`、`hl`、`gl`(預設 TWD / zh-TW / tw)。

- 來回票的 `price` 是去回合計。要看回程班次,拿去程選項的 `departure_token` 再查一次(`ticket` 指令做的事)。
- `price_insights`(價格水準、平常區間、`price_history` = [Unix 秒, 價格])只在目的地是機場或城市時出現。
- `search_metadata.google_flights_url` 是同一組條件的 Google 航班網址,報表的「看航班」就是它。

文件:https://serpapi.com/google-flights-api 、 https://serpapi.com/google-travel-explore-api

## 額度

- 免費方案每月 250 次,每月 1 號重置;`account` 指令查剩幾次,本身不扣。
- 一次 `grid` 查詢 = 一個「出發日 × 天數」。兩個月 × 3 種天數 ≈ 183 次;要省就 `--step 2` 或少一種天數。
- 一小時內查太多會回 429,程式會自己等 5 分鐘再接著查。
- 查過的條件存在 `flight-scan-data/<種類>/…json`,再跑讀快取不扣額度。想要最新價格,把那個 json 移走再跑。

## 地點代號

`flights.py` 內建的代號(大小寫都可以):

| 代號 | 指到 | 代號 | 指到 |
|---|---|---|---|
| JP | 日本 `/m/03_3d` | US | 美國 `/m/09c7w0` |
| KR | 韓國 `/m/06qd3` | AU | 澳洲 `/m/0chghy` |
| TH | 泰國 `/m/07f1x` | NZ | 紐西蘭 `/m/0ctw_b` |
| VN | 越南 `/m/01crd5` | GB | 英國 `/m/07ssc` |
| SG | 新加坡 `/m/06t2t` | FR | 法國 `/m/0f8l9c` |
| MY | 馬來西亞 `/m/09pmkv` | DE | 德國 `/m/0345h` |
| PH | 菲律賓 `/m/05v8c` | ID | 印尼 `/m/03ryn` |
| TAIPEI | `TPE,TSA` | TOKYO | `NRT,HND` |
| OSAKA | `KIX,ITM` | SEOUL | `ICN,GMP` |
| BANGKOK | `BKK,DMK` | | |

香港、澳門直接用機場代號 `HKG`、`MFM`。

**其他國家**:國家代號就是 Wikidata 上那個國家的「Freebase ID」(屬性 P646)。例如土耳其:
`https://www.wikidata.org/wiki/Special:EntityData/Q43.json` 裡 `P646` 的值。查到後直接 `--to /m/xxxx`
(Windows 的 Git Bash 會把 `/m/…` 當成路徑亂改,這時改用 PowerShell,或把它加進 `flights.py` 的 `PLACES`)。
