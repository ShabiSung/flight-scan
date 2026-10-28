"""flight-scan:透過 SerpApi 讀 Google 航班,把「一段日期 × 玩幾天 × 整個國家的機場」一次比完。

只用 Python 標準函式庫(3.9 以上)。每一次查詢的原始結果都存進資料夾,同樣的條件再跑就讀快取、不扣額度。
金鑰:環境變數 SERPAPI_KEY,或目前資料夾 / skill 資料夾裡的 .env(一行 SERPAPI_KEY=你的金鑰)。

  python flights.py account                                                           剩幾次(不扣額度)
  python flights.py grid     --from TPE --to JP --start 2026-11-01 --end 2026-12-31 --days 4,5,6
  python flights.py analyze  --from TPE --to JP                                       整理成最便宜排行、各機場、日曆
  python flights.py report   --from TPE --to JP                                       做成一頁 HTML 報表
  python flights.py explore  --from TPE --to JP --months 11,12 --budget 8000          預算內能飛哪些城市
  python flights.py insights --from TPE --to OKA --depart 2026-11-01 --return 2026-11-05   便宜還是貴 + 價格紀錄
  python flights.py flight   --from TPE --to JP --flight "TR 866" --days 4            同一班飛機哪天最便宜
  python flights.py ticket   --from TPE --to JP --depart 2026-11-01 --return 2026-11-05     最便宜那張的去回程班次
"""
import argparse
import html
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

API = "https://serpapi.com/search.json"
SKILL = Path(__file__).resolve().parents[1]
# 國家用 Google 知識圖譜代號(= Wikidata 的 Freebase ID,P646);城市用機場代號,逗號隔開
PLACES = {
    "JP": "/m/03_3d", "KR": "/m/06qd3", "TH": "/m/07f1x", "VN": "/m/01crd5", "SG": "/m/06t2t",
    "MY": "/m/09pmkv", "PH": "/m/05v8c", "ID": "/m/03ryn", "US": "/m/09c7w0", "AU": "/m/0chghy",
    "NZ": "/m/0ctw_b", "GB": "/m/07ssc", "FR": "/m/0f8l9c", "DE": "/m/0345h",
    "TAIPEI": "TPE,TSA", "TOKYO": "NRT,HND", "OSAKA": "KIX,ITM", "SEOUL": "ICN,GMP", "BANGKOK": "BKK,DMK",
}
LEVEL = {"low": "偏低", "typical": "一般", "high": "偏高"}


class G:  # main() 填好的全域設定
    data = Path("flight-scan-data")
    locale = {}


# ---------- 查詢 ----------

def load_key():
    key = os.environ.get("SERPAPI_KEY")
    for env in (Path.cwd() / ".env", SKILL / ".env"):
        if key:
            break
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("SERPAPI_KEY="):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not key:
        sys.exit(f"找不到 SerpApi 金鑰:在 {SKILL / '.env'} 寫一行 SERPAPI_KEY=你的金鑰"
                 "(免費申請:https://serpapi.com/users/sign_up)")
    return key


def call(url, params, tries=12):
    q = urllib.parse.urlencode(dict(params, api_key=load_key()))
    for i in range(tries):
        try:
            with urllib.request.urlopen(f"{url}?{q}", timeout=120) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:300]
            if "run out of searches" in body:
                sys.exit("這個月的額度用完了(SerpApi 每月 1 號重置)")
            if e.code == 429 and i < tries - 1:
                print("  一小時內查太多次,等 5 分鐘再繼續…", flush=True)
                time.sleep(300)
                continue
            sys.exit(f"SerpApi 回傳 HTTP {e.code}:{body}")
        except urllib.error.URLError as e:
            if i < 2:
                time.sleep(5)
                continue
            sys.exit(f"連不上 SerpApi:{e.reason}")
    sys.exit("重試太多次,先停下來")


def place(x):
    if x.startswith("/"):          # 知識圖譜代號分大小寫,原樣傳
        return x
    return PLACES.get(x.upper(), x.upper())


def slug(x):
    return x.upper().replace(",", "-").replace("/", "_")


def cache(kind, name):
    return G.data / kind / f"{name}.json"


def search(kind, name, params):
    """有快取讀快取,沒有才打 API。回傳 (結果, 是不是新查的)。查不到航班也會存,其他錯誤不存。"""
    path = cache(kind, name)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8")), False
    res = call(API, dict(params, **G.locale))
    err = res.get("error")
    if err and "returned any results" not in err:
        sys.exit(f"SerpApi:{err}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    with open(G.data / "calls.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"at": datetime.now().isoformat(timespec="seconds"), "kind": kind, "name": name},
                           ensure_ascii=False) + "\n")
    return res, True


def flights_params(frm, to, dep, ret):
    return dict(engine="google_flights", departure_id=place(frm), arrival_id=place(to), type=1,
                outbound_date=dep.isoformat(), return_date=ret.isoformat(), sort_by=2)


def options(res):
    opts = [o for o in (res.get("best_flights") or []) + (res.get("other_flights") or []) if o.get("price")]
    return sorted(opts, key=lambda o: o["price"])


def describe(o):
    f = o["flights"]
    return dict(price=o["price"], airline=f[0].get("airline", ""),
                flight=" / ".join(s.get("flight_number", "") for s in f),
                dep=f[0]["departure_airport"].get("time", ""), arr=f[-1]["arrival_airport"].get("time", ""),
                ap=f[-1]["arrival_airport"].get("id", ""), ap_name=f[-1]["arrival_airport"].get("name", ""),
                stops=len(f) - 1)


def remaining():
    acc = call("https://serpapi.com/account.json", {})
    return acc.get("total_searches_left", acc.get("plan_searches_left"))


def money(p):
    return f"{p:,}"


# ---------- 指令 ----------

def cmd_account(_):
    acc = call("https://serpapi.com/account.json", {})
    for k, label in (("plan_name", "方案"), ("searches_per_month", "每月次數"), ("this_month_usage", "這個月用了"),
                     ("total_searches_left", "還剩"), ("account_rate_limit_per_hour", "每小時上限")):
        print(f"{label:8} {acc.get(k)}")


def grid_cells(a):
    d, end = date.fromisoformat(a.start), date.fromisoformat(a.end)
    days = [int(x) for x in a.days.split(",")]
    cells = []
    while d <= end:
        cells += [(d, n) for n in days]
        d += timedelta(days=a.step)
    return cells


def grid_dir(frm, to):
    return f"grid/{slug(frm)}-{slug(to)}"


def cmd_grid(a):
    folder = grid_dir(a.frm, a.to)
    cells = grid_cells(a)
    todo = [c for c in cells if not cache(folder, f"{c[0]}_{c[1]}d").exists()]
    print(f"{a.frm} → {a.to}:{len(cells)} 組(出發日 × 天數),快取 {len(cells) - len(todo)} 組,要新查 {len(todo)} 次")
    if a.dry_run or not todo:
        return
    left = remaining()
    print(f"帳號還剩 {left} 次;這次最多查 {a.max_calls} 次")
    limit = min(a.max_calls, left if isinstance(left, int) else a.max_calls)
    made = 0
    for d, n in cells:
        name = f"{d}_{n}d"
        if not cache(folder, name).exists() and made >= limit:
            print(f"到上限了,停在 {name};同一行指令再跑一次會從這裡接著查")
            break
        res, fresh = search(folder, name, flights_params(a.frm, a.to, d, d + timedelta(days=n - 1)))
        made += fresh
        opts = options(res)
        tag = "新" if fresh else "快"
        if not opts:
            print(f"[{tag}] {d} {n}天  沒有結果", flush=True)
        else:
            c = describe(opts[0])
            print(f"[{tag}] {d} {n}天  {money(c['price']):>7}  {c['ap']}  {c['airline']} {c['flight']}"
                  f"  比了 {len(opts)} 個航班", flush=True)
    print(f"這次新查 {made} 次")


def analyze(frm, to):
    folder = G.data / grid_dir(frm, to)
    files = sorted(folder.glob("*.json"))
    if not files:
        sys.exit(f"{folder} 沒有資料,先跑 grid")
    rows, per_ap = [], defaultdict(list)
    for p in files:
        res = json.loads(p.read_text(encoding="utf-8"))
        d, n = p.stem.split("_")
        opts = options(res)
        if not opts:
            continue
        best = {}
        for o in opts:
            r = dict(describe(o), date=d, days=int(n[:-1]))
            if r["ap"] not in best or r["price"] < best[r["ap"]]["price"]:
                best[r["ap"]] = r
        for r in best.values():
            per_ap[r["ap"]].append(r)
        meta = res.get("search_metadata", {})
        rows.append(dict(describe(opts[0]), date=d, days=int(n[:-1]), n_options=len(opts),
                         url=meta.get("google_flights_url", ""), at=meta.get("created_at", "")))
    rows.sort(key=lambda r: r["price"])
    ap_best = {}
    for ap, rs in per_ap.items():
        ap_best[ap] = dict(best=min(rs, key=lambda r: r["price"]), worst=max(rs, key=lambda r: r["price"]), n=len(rs))
    cal = defaultdict(dict)
    for r in rows:
        cal[r["date"]][r["days"]] = r["price"]
    out = dict(frm=frm.upper(), to=to.upper(), rows=rows, ap_best=ap_best, calendar=cal,
               searched=[min(r["at"] for r in rows), max(r["at"] for r in rows)] if rows else [])
    path = G.data / f"analysis-{slug(frm)}-{slug(to)}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out, path


def cmd_analyze(a):
    out, path = analyze(a.frm, a.to)
    rows = out["rows"]
    print(f"{len(rows)} 組有結果,查詢時間 {' ~ '.join(out['searched'])}")
    print(f"== 最便宜 {a.top} 組")
    for r in rows[:a.top]:
        print(f"  {money(r['price']):>7}  {r['date']} 玩{r['days']}天  {r['ap']} {r['ap_name']}  "
              f"{r['airline']} {r['flight']}  {r['dep'][11:]} 出發  {'直飛' if not r['stops'] else str(r['stops']) + ' 次轉機'}")
    print("== 最貴 3 組")
    for r in rows[-3:]:
        print(f"  {money(r['price']):>7}  {r['date']} 玩{r['days']}天  {r['ap']}  {r['airline']}")
    print("== 每個機場的最低價")
    for ap, v in sorted(out["ap_best"].items(), key=lambda kv: kv[1]["best"]["price"]):
        b, w = v["best"], v["worst"]
        print(f"  {ap} {b['ap_name'][:12]:12}  最低 {money(b['price']):>7}({b['date']} 玩{b['days']}天 {b['airline']})"
              f"  最高 {money(w['price']):>7}")
    print("寫出", path)


def cmd_explore(a):
    to = place(a.to)
    key = "arrival_area_id" if to.startswith(("/m/", "/g/")) else "arrival_id"
    for m in [int(x) for x in a.months.split(",")]:
        res, fresh = search("explore", f"{slug(a.frm)}-{slug(a.to)}-m{m:02d}-d{a.duration}", {
            "engine": "google_travel_explore", "departure_id": place(a.frm), key: to,
            "month": m, "travel_duration": a.duration, "type": 1})
        dests = sorted([d for d in res.get("destinations", []) if d.get("flight_price")],
                       key=lambda d: d["flight_price"])
        if a.budget:
            dests = [d for d in dests if d["flight_price"] <= a.budget]
        head = f"預算 {money(a.budget)} 以內" if a.budget else "全部"
        print(f"\n== {m} 月{head}:{len(dests)} 個城市 {'(新查)' if fresh else '(快取)'}")
        for d in dests:
            print(f"  {money(d['flight_price']):>7}  {d.get('name')}({(d.get('destination_airport') or {}).get('code')})"
                  f"  {d.get('start_date')} → {d.get('end_date')}  {d.get('airline')}"
                  f"  {'直飛' if not d.get('number_of_stops') else str(d['number_of_stops']) + ' 次轉機'}")


def one_search(a, kind):
    """指定去回日期的那一次查詢;grid 查過同樣條件就直接用。"""
    dep, ret = date.fromisoformat(a.depart), date.fromisoformat(getattr(a, "return"))
    n = (ret - dep).days + 1
    g = cache(grid_dir(a.frm, a.to), f"{dep}_{n}d")
    if g.exists():
        return json.loads(g.read_text(encoding="utf-8")), dep, ret
    res, _ = search(kind, f"{slug(a.frm)}-{slug(a.to)}-{dep}-{ret}", flights_params(a.frm, a.to, dep, ret))
    return res, dep, ret


def cmd_insights(a):
    res, dep, ret = one_search(a, "insights")
    pi = res.get("price_insights")
    opts = options(res)
    if opts:
        c = describe(opts[0])
        print(f"{a.frm} → {a.to}  {dep} 去、{ret} 回:最便宜 {money(c['price'])}({c['airline']} {c['flight']})")
    if not pi:
        print("Google 這組條件沒有給價格分析。目的地改成單一機場(例如 OKA、NRT,HND)再查一次通常就會有")
        return
    lo, hi = (pi.get("typical_price_range") or [None, None])[:2]
    print(f"目前價格水準:{LEVEL.get(pi.get('price_level'), pi.get('price_level'))}")
    if lo:
        print(f"平常價格:{money(lo)} ~ {money(hi)}")
    hist = pi.get("price_history") or []
    if hist:
        day = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%m/%d")
        ps = [p for _, p in hist]
        print(f"價格紀錄 {day(hist[0][0])} ~ {day(hist[-1][0])}:最高 {money(max(ps))}、最低 {money(min(ps))}、"
              f"現在 {money(ps[-1])}")
        step = max(1, len(hist) // 10)
        print("  " + "  ".join(f"{day(t)} {money(p)}" for t, p in hist[::step]))


def norm(x):
    return x.replace(" ", "").upper()


def cmd_flight(a):
    folder = G.data / grid_dir(a.frm, a.to)
    want = norm(a.flight)
    pts = []
    for p in sorted(folder.glob("*.json")):
        d, n = p.stem.split("_")
        if a.days and int(n[:-1]) != a.days:
            continue
        for o in options(json.loads(p.read_text(encoding="utf-8"))):
            if any(norm(s.get("flight_number", "")) == want for s in o["flights"]):
                pts.append((d, int(n[:-1]), o["price"]))
                break
    if not pts:
        sys.exit(f"grid 結果裡找不到 {a.flight};先跑 grid,或用 analyze 看有哪些航班")
    for d, n, p in pts:
        print(f"  {d} 玩{n}天  {money(p):>7}")
    lo, hi = min(pts, key=lambda x: x[2]), max(pts, key=lambda x: x[2])
    print(f"{a.flight}:最便宜 {lo[0]} 出發 {money(lo[2])},最貴 {hi[0]} 出發 {money(hi[2])},差 {money(hi[2] - lo[2])}")


def cmd_ticket(a):
    res, dep, ret = one_search(a, "insights")
    opts = options(res)
    if a.flight:
        opts = [o for o in opts if any(norm(s.get("flight_number", "")) == norm(a.flight) for s in o["flights"])]
    if not opts:
        sys.exit("這組日期沒有符合的航班")
    go = opts[0]
    print(f"來回 {money(go['price'])}")
    for s in go["flights"]:
        print(f"  去程 {s.get('flight_number')}  {s['departure_airport']['id']} {s['departure_airport']['time']}"
              f" → {s['arrival_airport']['id']} {s['arrival_airport']['time']}  {s.get('airline')}")
    token = go.get("departure_token")
    if not token:
        return
    back, _ = search("ticket", f"{slug(a.frm)}-{slug(a.to)}-{dep}-{ret}-{norm(go['flights'][0]['flight_number'])}",
                     dict(flights_params(a.frm, a.to, dep, ret), departure_token=token))
    bo = options(back)
    if bo:
        for s in bo[0]["flights"]:
            print(f"  回程 {s.get('flight_number')}  {s['departure_airport']['id']} {s['departure_airport']['time']}"
                  f" → {s['arrival_airport']['id']} {s['arrival_airport']['time']}  {s.get('airline')}")
    url = back.get("search_metadata", {}).get("google_flights_url") or res.get("search_metadata", {}).get("google_flights_url")
    print("在 Google 航班打開:", url)


# ---------- 報表 ----------

def heat(p, lo, hi):
    """便宜綠 → 中間黃 → 貴紅。"""
    t = 0 if hi == lo else (p - lo) / (hi - lo)
    hue = 140 - 140 * min(1, max(0, t)) ** 0.8
    return f"hsl({hue:.0f} 70% 42%)"


def cmd_report(a):
    out, _ = analyze(a.frm, a.to)
    rows, e = out["rows"], html.escape
    best = rows[0]
    prices = sorted(r["price"] for r in rows)
    lo, hi = prices[0], prices[int(len(prices) * 0.9) - 1] if len(prices) > 10 else prices[-1]
    days_set = sorted({r["days"] for r in rows})
    dates = sorted(out["calendar"])
    d0, d1 = date.fromisoformat(dates[0]), date.fromisoformat(dates[-1])

    # 日曆:一週一列,星期一開頭;格子放那天出發最便宜的價格
    cells, d = [], d0 - timedelta(days=d0.weekday())
    by_date = defaultdict(list)
    for r in rows:
        by_date[r["date"]].append(r)
    while d <= d1:
        k = d.isoformat()
        if k in out["calendar"]:
            r = min(by_date[k], key=lambda r: r["price"])
            tip = "、".join(f"玩{n}天 {money(p)}" for n, p in sorted(out["calendar"][k].items()))
            mark = " best" if r is best else ""
            cells.append(f'<a class="day{mark}" href="{e(r["url"])}" target="_blank" rel="noopener" '
                         f'style="--c:{heat(r["price"], lo, hi)}" title="{e(k)}:{e(tip)}">'
                         f'<i>{d.month}/{d.day}</i><b>{money(r["price"])}</b><s>{e(r["ap"])}</s></a>')
        else:
            cells.append('<span class="day off"></span>')
        d += timedelta(days=1)

    top = "".join(
        f'<tr><td class="num">{money(r["price"])}</td><td>{e(r["date"][5:])}</td><td>{r["days"]} 天</td>'
        f'<td>{e(r["ap_name"])}<small>{e(r["ap"])}</small></td><td>{e(r["airline"])}<small>{e(r["flight"])}</small></td>'
        f'<td>{"直飛" if not r["stops"] else str(r["stops"]) + " 轉"}</td>'
        f'<td><a href="{e(r["url"])}" target="_blank" rel="noopener">看航班</a></td></tr>' for r in rows[:a.top])

    aps = sorted(out["ap_best"].values(), key=lambda v: v["best"]["price"])
    amin, amax = aps[0]["best"]["price"], aps[-1]["best"]["price"]
    bars = "".join(
        f'<div class="bar"><span>{e(v["best"]["ap_name"])} <small>{e(v["best"]["ap"])}</small></span>'
        f'<div><i style="width:{v["best"]["price"] / amax * 100:.1f}%;--c:{heat(v["best"]["price"], amin, amax)}"></i></div>'
        f'<b>{money(v["best"]["price"])}</b></div>' for v in aps)

    budget = ""
    for p in sorted((G.data / "explore").glob(f"{slug(a.frm)}-{slug(a.to)}-m*.json")):
        ds = sorted([x for x in json.loads(p.read_text(encoding="utf-8")).get("destinations", [])
                     if x.get("flight_price") and (not a.budget or x["flight_price"] <= a.budget)],
                    key=lambda x: x["flight_price"])
        if ds:
            m = int(p.stem.split("-m")[1][:2])
            budget += (f'<h3>{m} 月出發{f"・預算 {money(a.budget)} 以內" if a.budget else ""}・{len(ds)} 個城市</h3><div class="chips">'
                       + "".join(f'<a href="{e(x.get("link", ""))}" target="_blank" rel="noopener">{e(x["name"])}'
                                 f'<b>{money(x["flight_price"])}</b></a>' for x in ds) + "</div>")
    if budget:
        budget = f'<section><h2>還能飛哪裡</h2><p class="muted">Google 探索,每個城市一週內來回的最低價</p>{budget}</section>'

    page = TEMPLATE.format(
        title=e(f"{out['frm']} → {out['to']} 機票掃描"), frm=e(out["frm"]), to=e(out["to"]),
        span=f"{d0.month}/{d0.day} ~ {d1.month}/{d1.day}", days="、".join(map(str, days_set)), n=len(rows),
        price=money(best["price"]), best_line=e(f"{best['date']} 出發・玩 {best['days']} 天・{best['ap_name']}・"
                                                 f"{best['airline']} {best['flight']}"),
        best_url=e(best["url"]), avg=money(round(sum(prices) / len(prices))), max=money(prices[-1]),
        n_ap=len(aps), cal="".join(cells), top=top, top_n=a.top, bars=bars, budget=budget,
        at=e(" ~ ".join(out["searched"])))
    path = Path(a.out) if a.out else G.data / f"report-{slug(a.frm)}-{slug(a.to)}.html"
    path.write_text(page, encoding="utf-8")
    print("寫出", path.resolve())


TEMPLATE = """<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
:root {{ --bg:#F5F4F0; --card:#FFF; --line:#E4E1D8; --fg:#1F1E1C; --muted:#6F6C66; --accent:#E8A317; color-scheme:light; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#111214; --card:#1A1B1E; --line:#2C2D31; --fg:#ECEBE8; --muted:#9C9A95; color-scheme:dark; }} }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:15px/1.6 -apple-system,"Noto Sans TC","PingFang TC","Microsoft JhengHei",sans-serif; }}
main {{ max-width:980px; margin:0 auto; padding:40px 16px 64px; display:flex; flex-direction:column; gap:22px; }}
section, .hero {{ background:var(--card); border:1px solid var(--line); border-radius:18px; padding:22px; min-width:0; }}
h1 {{ margin:0; font-size:15px; color:var(--muted); font-weight:600; letter-spacing:.04em; }}
h2 {{ margin:0 0 10px; font-size:19px; }} h3 {{ margin:16px 0 8px; font-size:15px; }}
.muted, small {{ color:var(--muted); }} small {{ display:block; font-size:12px; }}
.big {{ font-size:clamp(44px,9vw,72px); font-weight:800; line-height:1.1; margin:8px 0 4px; font-variant-numeric:tabular-nums; }}
.big span {{ font-size:.4em; color:var(--muted); font-weight:600; }}
.stats {{ display:flex; flex-wrap:wrap; gap:8px 22px; margin-top:14px; color:var(--muted); }} .stats b {{ color:var(--fg); }}
.btn {{ display:inline-block; margin-top:14px; background:var(--fg); color:var(--card); padding:9px 16px; border-radius:999px; text-decoration:none; font-weight:700; }}
.week {{ display:grid; grid-template-columns:repeat(7,1fr); gap:6px; }}
.wk {{ font-size:12px; color:var(--muted); text-align:center; }}
.day {{ display:flex; flex-direction:column; align-items:center; padding:6px 2px; border-radius:10px; text-decoration:none; color:#fff; background:var(--c); min-width:0; }}
.day i {{ font-style:normal; font-size:11px; opacity:.85; }} .day b {{ font-size:clamp(11px,2.2vw,15px); font-variant-numeric:tabular-nums; }}
.day s {{ text-decoration:none; font-size:10px; opacity:.8; }} .day.off {{ background:transparent; }}
.day.best {{ outline:3px solid var(--accent); outline-offset:1px; }}
.table {{ overflow-x:auto; }} table {{ width:100%; border-collapse:collapse; min-width:560px; }}
td {{ padding:9px 8px; border-top:1px solid var(--line); vertical-align:top; }}
.num {{ font-weight:800; font-variant-numeric:tabular-nums; }} td a {{ color:inherit; }}
.bar {{ display:grid; grid-template-columns:minmax(90px,150px) 1fr 70px; gap:10px; align-items:center; padding:5px 0; }}
.bar div {{ background:var(--bg); border-radius:6px; height:14px; }} .bar i {{ display:block; height:100%; border-radius:6px; background:var(--c); }}
.bar b {{ text-align:right; font-variant-numeric:tabular-nums; }}
.chips {{ display:flex; flex-wrap:wrap; gap:8px; }}
.chips a {{ border:1px solid var(--line); border-radius:999px; padding:5px 12px; text-decoration:none; color:var(--fg); }}
.chips b {{ margin-left:6px; }}
.foot {{ text-align:center; font-size:12px; color:var(--muted); }}
</style></head><body><main>
<div class="hero"><h1>{frm} → {to}・{span} 出發・玩 {days} 天</h1>
<div class="big">{price}<span> 元來回</span></div><div>{best_line}</div>
<div class="stats"><span>比了 <b>{n}</b> 組</span><span>{n_ap} 個機場</span><span>平均 <b>{avg}</b></span><span>最貴 <b>{max}</b></span></div>
<a class="btn" href="{best_url}" target="_blank" rel="noopener">在 Google 航班打開這張票</a></div>
<section><h2>價格日曆</h2><p class="muted">每格是那天出發最便宜的來回價,綠色便宜、紅色貴,點一下打開 Google 航班</p>
<div class="week"><span class="wk">一</span><span class="wk">二</span><span class="wk">三</span><span class="wk">四</span><span class="wk">五</span><span class="wk">六</span><span class="wk">日</span>{cal}</div></section>
<section><h2>最便宜的 {top_n} 組</h2><div class="table"><table>{top}</table></div></section>
<section><h2>每個機場最低多少</h2>{bars}</section>
{budget}
<p class="foot">查詢時間 {at}(UTC)・資料來自 Google 航班(SerpApi)・票價隨時在變,訂票前以 Google 航班當下為準</p>
</main></body></html>
"""


def main():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--data", default=os.environ.get("FLIGHT_SCAN_DATA", "flight-scan-data"), help="查詢結果存哪")
    common.add_argument("--currency", default="TWD")
    common.add_argument("--hl", default="zh-TW", help="語言")
    common.add_argument("--gl", default="tw", help="地區")
    route = argparse.ArgumentParser(add_help=False, parents=[common])
    route.add_argument("--from", dest="frm", default="TPE", help="出發機場,可以逗號隔開多個")
    route.add_argument("--to", required=True, help="目的地:國家代號(JP、KR…)、城市代號(TOKYO…)或機場代號")

    ap = argparse.ArgumentParser(description="用 SerpApi 讀 Google 航班,大範圍掃機票")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("account", parents=[common], help="方案與剩餘次數").set_defaults(fn=cmd_account)
    g = sub.add_parser("grid", parents=[route], help="出發日 × 天數 全部查一遍")
    g.add_argument("--start", required=True)
    g.add_argument("--end", required=True)
    g.add_argument("--days", default="5", help="來回玩幾天,可以多個:4,5,6")
    g.add_argument("--step", type=int, default=1, help="出發日每隔幾天查一次")
    g.add_argument("--max-calls", type=int, default=60, help="這次最多新查幾次")
    g.add_argument("--dry-run", action="store_true", help="只算要查幾次")
    g.set_defaults(fn=cmd_grid)
    an = sub.add_parser("analyze", parents=[route], help="整理 grid 結果")
    an.add_argument("--top", type=int, default=10)
    an.set_defaults(fn=cmd_analyze)
    r = sub.add_parser("report", parents=[route], help="做成一頁 HTML 報表")
    r.add_argument("--top", type=int, default=10)
    r.add_argument("--budget", type=int)
    r.add_argument("--out")
    r.set_defaults(fn=cmd_report)
    e = sub.add_parser("explore", parents=[route], help="Google 探索:每個城市的最低價")
    e.add_argument("--months", required=True, help="幾月出發,可以多個:11,12")
    e.add_argument("--duration", type=int, default=2, help="1 週末 / 2 一週 / 3 兩週")
    e.add_argument("--budget", type=int)
    e.set_defaults(fn=cmd_explore)
    for name, fn, hlp in (("insights", cmd_insights, "這張票便宜還是貴、價格紀錄"),
                          ("ticket", cmd_ticket, "最便宜那張的去回程班次")):
        s = sub.add_parser(name, parents=[route], help=hlp)
        s.add_argument("--depart", required=True)
        s.add_argument("--return", required=True)
        if name == "ticket":
            s.add_argument("--flight", help="指定去程班次,例如 'IT 232'")
        s.set_defaults(fn=fn)
    f = sub.add_parser("flight", parents=[route], help="同一班飛機每天的價格(讀 grid 結果)")
    f.add_argument("--flight", required=True, help="班次,例如 'TR 866'")
    f.add_argument("--days", type=int, help="只看玩幾天的")
    f.set_defaults(fn=cmd_flight)

    a = ap.parse_args()
    G.data = Path(a.data)
    G.locale = {"currency": a.currency, "hl": a.hl, "gl": a.gl}
    a.fn(a)


if __name__ == "__main__":
    main()
