# 常用說法 → 指令

使用者的原話不一定長這樣,意思對到就用。`<skill>` 是 skill 資料夾。

## 1. 大範圍掃最便宜的來回

> 兩個月內想去日本玩 4 到 6 天,幫我找最便宜的來回,日本所有機場都算

```bash
python <skill>/scripts/flights.py grid --from TPE --to JP --start <明天起算> --end <兩個月後> --days 4,5,6 --dry-run
# 報次數、確認後
python <skill>/scripts/flights.py grid ... --max-calls <同意的次數>
python <skill>/scripts/flights.py analyze --from TPE --to JP
python <skill>/scripts/flights.py report  --from TPE --to JP
```

回報:最便宜那張 + 前三個最便宜的機場 + 報表路徑。

## 2. 先看預算,再決定去哪

> 預算 8,000,能飛日本哪些城市?

```bash
python <skill>/scripts/flights.py explore --from TPE --to JP --months 11,12 --budget 8000
```

Google 探索給的是「每個城市一週內來回」的最低價,同一個機場附近的城市會一起列(京都、奈良都是飛關西)。
回報時按價格排,點出幾個使用者可能沒想到的(離島、溫泉區)。

## 3. 這張票現在該不該買

> 這張票現在算便宜還是貴?給我價格紀錄

```bash
python <skill>/scripts/flights.py insights --from TPE --to OKA --depart 2026-11-01 --return 2026-11-05
```

目的地要用單一機場或城市代號(`OKA`、`TOKYO`),用整個國家 Google 不給價格分析。
回報:價格水準(偏低 / 一般 / 偏高)、平常區間、價格紀錄的最高最低和現在。偏低又接近紀錄最低,就說現在是好時機。

## 4. 同一班飛機,挑對日子

> 這一班飛東京的飛機,哪天出發最便宜、哪天最貴?

```bash
python <skill>/scripts/flights.py flight --from TPE --to JP --flight "TR 866" --days 4
```

讀第 1 步 grid 的結果,不扣額度。班次要寫成航班號(航空代碼 + 數字),不知道就先看 analyze 的輸出。
回報:最便宜和最貴的出發日、差多少。

## 5. 整理成一頁

> 把結果整理成一頁報表給我

```bash
python <skill>/scripts/flights.py report --from TPE --to JP --budget 8000
```

報表是單一 HTML 檔,可以直接用瀏覽器打開、傳給旅伴。有跑過 explore 就會多一區「還能飛哪裡」。

## 其他

- 這張票去回程是哪兩班:`ticket --to JP --depart ... --return ...`(多 1 次查回程)
- 換出發地:`--from KHH`(高雄)、`--from TAIPEI`(桃園 + 松山)
- 換幣別:`--currency USD --hl en --gl us`
