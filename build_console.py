#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
글로벌 경제 관제실 — 일일 자동 빌드
공개 데이터(무료·API 키 불필요)를 수집하여 docs/index.html 을 생성한다.

  시세     : Yahoo Finance (yfinance)
  거시     : FRED CSV, 뉴욕연준 침체확률, multpl(실러 CAPE)
  부동산   : Zillow ZHVI
  기관보유 : SEC EDGAR 13F-HR

실행 : python build_console.py
"""

import io
import json
import os
import re
import sys
import time
import datetime as dt
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent
CONF = ROOT / "config"
DOCS = ROOT / "docs"
DOCS.mkdir(exist_ok=True)

UA = os.environ.get("CONTACT_UA", "macro-console (contact: a01092796847@gmail.com)")
HEAD = {"User-Agent": UA, "Accept-Encoding": "gzip, deflate"}
TIMEOUT = 90

LOG = []


def log(msg):
    line = f"[{dt.datetime.utcnow():%H:%M:%S}] {msg}"
    print(line, flush=True)
    LOG.append(line)


def http(url, headers=None, tries=3, sleep=3):
    h = dict(HEAD)
    if headers:
        h.update(headers)
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, headers=h, timeout=TIMEOUT)
            r.raise_for_status()
            return r
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(sleep * (i + 1))
    raise RuntimeError(f"GET 실패 {url} :: {last}")


# ──────────────────────────────────────────────────────────────
# 1. 시세
# ──────────────────────────────────────────────────────────────
def pct(a, b):
    if a is None or b is None or b == 0 or pd.isna(a) or pd.isna(b):
        return None
    return round((a / b - 1) * 100, 2)


def nearest_before(s: pd.Series, target: pd.Timestamp):
    """target 이전(포함) 마지막 값."""
    sub = s.loc[:target]
    return float(sub.iloc[-1]) if len(sub) else None


def build_prices(universe):
    import yfinance as yf

    groups = {}
    for gname, items in universe.items():
        out = []
        for it in items:
            tk = it["ticker"]
            try:
                t = yf.Ticker(tk)
                d = t.history(period="1y", interval="1d", auto_adjust=False)
                m = t.history(period="25y", interval="1mo", auto_adjust=False)
                if d.empty:
                    log(f"  ! 일봉 없음 {tk} ({it['name']})")
                    continue
                dc = d["Close"].dropna()
                dc.index = pd.to_datetime(dc.index).tz_localize(None)
                mc = m["Close"].dropna() if not m.empty else pd.Series(dtype=float)
                if len(mc):
                    mc.index = pd.to_datetime(mc.index).tz_localize(None)

                last = float(dc.iloc[-1])
                lastdate = dc.index[-1]
                ref = {
                    "d1": nearest_before(dc, lastdate - pd.Timedelta(days=1)),
                    "w1": nearest_before(dc, lastdate - pd.Timedelta(days=7)),
                    "m1": nearest_before(dc, lastdate - pd.DateOffset(months=1)),
                    "m3": nearest_before(dc, lastdate - pd.DateOffset(months=3)),
                    "m6": nearest_before(dc, lastdate - pd.DateOffset(months=6)),
                    "y1": nearest_before(dc, lastdate - pd.DateOffset(years=1)),
                }
                jan1 = pd.Timestamp(year=lastdate.year, month=1, day=1)
                prev_close = nearest_before(dc, jan1 - pd.Timedelta(days=1))
                if prev_close is None and len(mc):
                    prev_close = nearest_before(mc, jan1 - pd.Timedelta(days=1))

                out.append({
                    "name": it["name"],
                    "last": round(last, 4),
                    "asof": lastdate.strftime("%Y-%m-%d"),
                    "chg": {k: pct(last, v) for k, v in ref.items()},
                    "ytd": pct(last, prev_close),
                    "daily": [[i.strftime("%Y-%m-%d"), round(float(v), 4)] for i, v in dc.items()],
                    "monthly": [[i.strftime("%Y-%m"), round(float(v), 4)] for i, v in mc.items()],
                    "ticker": tk,
                })
                time.sleep(0.4)
            except Exception as e:  # noqa: BLE001
                log(f"  ! 시세 실패 {tk} ({it['name']}) :: {e}")
        groups[gname] = out
        log(f"  시세 {gname}: {len(out)}/{len(items)}")
    return groups


# ──────────────────────────────────────────────────────────────
# 2. 거시 · 안정성
# ──────────────────────────────────────────────────────────────
def fred(series_id):
    r = http(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}")
    df = pd.read_csv(io.BytesIO(r.content))
    df.columns = ["date", "value"]
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.dropna()


def fred_last(series_id):
    df = fred(series_id)
    row = df.iloc[-1]
    return float(row["value"]), row["date"].strftime("%Y-%m-%d")


def band(x, lo_is_100, hi_is_0):
    """lo_is_100 이하 = 100점, hi_is_0 이상 = 0점 사이 선형 환산."""
    if x is None:
        return None
    if hi_is_0 == lo_is_100:
        return None
    v = 100.0 * (hi_is_0 - x) / (hi_is_0 - lo_is_100)
    return round(max(0.0, min(100.0, v)), 1)


def nyfed_recession():
    r = http("https://www.newyorkfed.org/medialibrary/media/research/capital_markets/allmonth.xls")
    df = pd.read_excel(io.BytesIO(r.content))
    df = df[["Date", "Rec_prob"]].dropna()
    row = df.iloc[-1]
    horizon = pd.to_datetime(row["Date"])
    prob = float(row["Rec_prob"]) * 100
    series = [[pd.to_datetime(d).strftime("%Y-%m"), round(float(p) * 100, 2)]
              for d, p in df.tail(360).values]
    return prob, horizon.strftime("%Y-%m"), series


def shiller_cape():
    r = http("https://www.multpl.com/shiller-pe/table/by-month")
    h = re.sub(r"&[#a-zA-Z0-9]+;", " ", r.text)   # &#x2002; 등 엔티티 제거 (숫자 오인 방지)
    rows = re.findall(
        r"<td[^>]*>\s*([A-Z][a-z]{2} \d{1,2}, \d{4})\s*</td>\s*<td[^>]*>\s*([\d]{1,3}\.[\d]{1,2})\s*</td>", h)
    if not rows:
        raise RuntimeError("CAPE 파싱 실패")
    v = float(rows[0][1])
    if not (3 < v < 100):
        raise RuntimeError(f"CAPE 값 범위 이상: {v}")
    return v, rows[0][0]


def build_stability(vix_last):
    comps, metrics = [], []

    prob, horizon, rec_series = nyfed_recession()
    s_rec = band(prob, 0, 60)
    comps.append({"name": "침체 확률 (뉴욕연준 모형)", "score": s_rec,
                  "detail": f"{horizon} 시점 침체확률 {prob:.1f}% · 현재 수익률곡선 기준 12개월 후 예측"})

    cpi = fred("CPILFESL")
    cpi = cpi.set_index("date")["value"]
    core_yoy = (cpi.iloc[-1] / cpi.iloc[-13] - 1) * 100
    cpi_asof = cpi.index[-1].strftime("%Y-%m")
    gap = abs(core_yoy - 2.0)
    s_cpi = band(gap, 0, 5)
    comps.append({"name": "물가 (근원 CPI)", "score": s_cpi,
                  "detail": f"근원 전년비 {core_yoy:.2f}% ({cpi_asof}) · 목표 2%와 {gap:.2f}%p 이격"})

    nfci, nfci_asof = fred_last("NFCI")
    s_nfci = band(nfci, -0.5, 1.5)
    comps.append({"name": "금융여건 (시카고연준 NFCI)", "score": s_nfci,
                  "detail": f"NFCI {nfci:.3f} (0 미만 = 평균보다 완화) · {nfci_asof} 기준"})

    y10, y10d = fred_last("DGS10")
    y3m, _ = fred_last("DGS3MO")
    try:
        spread, _ = fred_last("T10Y3M")      # 채권등가 기준 공식 계열
    except Exception:  # noqa: BLE001
        spread = y10 - y3m
    s_spr = band(spread, 1.5, -0.6)
    comps.append({"name": "수익률곡선 (10Y−3M)", "score": s_spr,
                  "detail": f"10년 {y10:.2f}% − 3개월 {y3m:.2f}% = {spread:+.2f}%p · "
                            f"{'정상' if spread > 0 else '역전'}"})

    s_vix = band(vix_last, 12, 48) if vix_last else None
    comps.append({"name": "시장 스트레스 (VIX)", "score": s_vix,
                  "detail": f"VIX {vix_last:.1f}" if vix_last else "VIX 수집 실패"})

    un, un_asof = fred_last("UNRATE")
    s_un = band(un, 3.5, 10.0)
    comps.append({"name": "고용 (실업률)", "score": s_un,
                  "detail": f"실업률 {un:.1f}% · {un_asof[:7]} 기준"})

    cape, cape_asof = shiller_cape()
    s_cape = band(cape, 10, 42)
    comps.append({"name": "시장 밸류에이션 (CAPE)", "score": s_cape,
                  "detail": f"실러 CAPE {cape:.1f} — 경기 지표가 아니라 시장이 감당하는 위험의 크기 "
                            f"({cape_asof})"})

    effr, _ = fred_last("DFF")
    try:
        mort, _ = fred_last("MORTGAGE30US")
    except Exception:  # noqa: BLE001
        mort = None
    metrics = [
        {"name": "연방기금 실효금리", "value": f"{effr:.2f}%"},
        {"name": "미 10년물", "value": f"{y10:.2f}%"},
        {"name": "미 3개월물", "value": f"{y3m:.2f}%"},
        {"name": "장단기 금리차 10Y−3M", "value": f"{spread:+.2f}%p"},
        {"name": "근원 CPI 전년비", "value": f"{core_yoy:.2f}%"},
        {"name": "실업률", "value": f"{un:.1f}%"},
        {"name": "시카고연준 NFCI", "value": f"{nfci:.3f}"},
        {"name": "실러 CAPE", "value": f"{cape:.1f}"},
        {"name": "VIX", "value": f"{vix_last:.1f}" if vix_last else "—"},
        {"name": "미 30년 고정 모기지", "value": f"{mort:.2f}%" if mort else "—"},
    ]

    comps = [c for c in comps if c["score"] is not None]
    valid = [c["score"] for c in comps]
    score = round(sum(valid) / len(valid), 1)
    label = ("매우 안정" if score >= 80 else "안정" if score >= 65
             else "중립" if score >= 50 else "주의" if score >= 35 else "경계")

    weak = min(comps, key=lambda c: c["score"] if c["score"] is not None else 999)
    strong = max(comps, key=lambda c: c["score"] if c["score"] is not None else -1)
    comment = (f"7개 축 중 가장 취약한 곳은 「{weak['name']}」({weak['score']}점), "
               f"가장 견조한 곳은 「{strong['name']}」({strong['score']}점)이다. "
               f"종합 {score}점은 {label} 구간이며, 점수 자체보다 어느 축이 무너지고 있는지가 판단 재료다.")

    return {
        "score": score,
        "label": label,
        "components": comps,
        "metrics": metrics,
        "comment": comment,
        "method": ("7개 축을 각 0~100점(100=안정)으로 환산해 단순 평균. 환산 구간 — "
                   "침체확률 0%→100점/60%→0점, 근원CPI 목표이격 0%p→100점/5%p→0점, "
                   "NFCI −0.5→100점/+1.5→0점, 10Y−3M +1.5%p→100점/−0.6%p→0점, "
                   "VIX 12→100점/48→0점, 실업률 3.5%→100점/10%→0점, CAPE 10→100점/42→0점."),
        "recession_series": rec_series,
    }, effr


# ──────────────────────────────────────────────────────────────
# 2-b. 쏠림 지표 (SPY − RSP 12개월 수익률 격차)
# ──────────────────────────────────────────────────────────────
def build_concentration():
    """시가총액 가중(SPY)과 동일가중(RSP)의 12개월 수익률 격차.

    값이 클수록 소수 대형주가 지수를 끌고 가는 쏠림 국면이다.
    보유 포트폴리오가 대형 AI주에 집중돼 있으므로, 이 격차의 '축소 전환'이
    개별 종목 악재보다 먼저 오는 조기 경보 신호가 된다.
    """
    import yfinance as yf

    try:
        px = {}
        for tk in ("SPY", "RSP"):
            h = yf.Ticker(tk).history(period="max", interval="1d", auto_adjust=True)
            if h.empty:
                raise RuntimeError(f"{tk} 시세 없음")
            s = h["Close"].dropna()
            s.index = pd.to_datetime(s.index).tz_localize(None)
            px[tk] = s
            time.sleep(0.4)
        df = pd.DataFrame(px).dropna()
        if len(df) < 300:
            raise RuntimeError("표본 부족")

        W = 252                                     # 12개월
        spread = ((df["SPY"] / df["SPY"].shift(W) - 1)
                  - (df["RSP"] / df["RSP"].shift(W) - 1)) * 100
        spread = spread.dropna()

        last = float(spread.iloc[-1])
        asof = spread.index[-1]
        pctile = float((spread <= last).mean() * 100)
        d63 = float(last - spread.iloc[-64]) if len(spread) > 64 else None
        d126 = float(last - spread.iloc[-127]) if len(spread) > 127 else None

        # 수준 : 이력 백분위 기준
        if pctile >= 90:
            level, lcol = "극단 쏠림", "down"
        elif pctile >= 70:
            level, lcol = "쏠림 확대", "warn"
        elif pctile >= 30:
            level, lcol = "중립", "blue"
        else:
            level, lcol = "분산 우위", "up"

        # 방향 : 최근 3개월 변화
        if d63 is None:
            trend = "판단 보류"
        elif d63 <= -1.0:
            trend = "축소 전환"
        elif d63 >= 1.0:
            trend = "확대 진행"
        else:
            trend = "횡보"

        alert = bool(pctile >= 60 and d63 is not None and d63 <= -1.0)
        if alert:
            comment = (f"쏠림이 되돌아오는 중이다. 12개월 격차가 3개월 만에 {d63:+.1f}%p 줄었다. "
                       "대형 AI주 집중 포트폴리오와 모멘텀 노출은 같은 방향 리스크이므로, "
                       "이 국면에서는 두 손실이 동시에 발생한다. 신규 집중 매수를 늦추고 편중도를 점검할 것.")
        elif trend == "확대 진행" and pctile >= 70:
            comment = ("소수 대형주로의 쏠림이 계속 강해지고 있다. 지수는 버티지만 평균적인 종목은 그렇지 않은 국면이며, "
                       "되돌림이 시작되면 조정 폭이 커진다. 신규 진입은 분할로 제한할 것.")
        elif pctile < 30:
            comment = ("동일가중이 시가총액 가중을 앞서는 분산 국면이다. 대형주 편중의 상대적 불리함이 이미 반영된 구간으로, "
                       "집중 포트폴리오의 추가 하방 압력은 제한적이다.")
        else:
            comment = ("쏠림 강도는 역사적 중간 수준이다. 격차의 절대 수준보다 방향 전환 시점이 중요하므로, "
                       "3개월 변화가 −1%p를 밑도는지 계속 볼 것.")

        # 차트용 : 최근 12년 월말 표본
        m = spread.resample("ME").last().dropna()
        m = m[m.index >= (asof - pd.DateOffset(years=12))]
        series = [[i.strftime("%Y-%m"), round(float(v), 2)] for i, v in m.items()]

        yearly = []
        for y in sorted({i.year for i in spread.index})[-8:]:
            sub = spread[spread.index.year == y]
            yearly.append({"year": int(y), "avg": round(float(sub.mean()), 2),
                           "end": round(float(sub.iloc[-1]), 2)})

        log(f"  쏠림 격차 {last:+.2f}%p (백분위 {pctile:.0f}%, 3개월 {d63:+.2f}%p) — {level}·{trend}")
        return {
            "last": round(last, 2),
            "asof": asof.strftime("%Y-%m-%d"),
            "pctile": round(pctile, 1),
            "chg_3m": None if d63 is None else round(d63, 2),
            "chg_6m": None if d126 is None else round(d126, 2),
            "level": level, "level_color": lcol, "trend": trend, "alert": alert,
            "comment": comment,
            "hi": round(float(spread.max()), 2), "hi_at": spread.idxmax().strftime("%Y-%m"),
            "lo": round(float(spread.min()), 2), "lo_at": spread.idxmin().strftime("%Y-%m"),
            "series": series, "yearly": yearly,
            "method": "SPY(시총가중) 12개월 수익률 − RSP(동일가중) 12개월 수익률 · 일별 산출",
        }
    except Exception as e:  # noqa: BLE001
        log(f"  ! 쏠림 지표 실패 :: {e}")
        return None


# ──────────────────────────────────────────────────────────────
# 3. 부동산
# ──────────────────────────────────────────────────────────────
def build_housing():
    out = []
    try:
        r = http("https://files.zillowstatic.com/research/public_csvs/zhvi/"
                 "Metro_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv")
        df = pd.read_csv(io.BytesIO(r.content))
        us = df[df["RegionName"] == "United States"]
        cols = [c for c in df.columns if re.match(r"^\d{4}-\d{2}-\d{2}$", str(c))]
        ser = [[c[:7], round(float(us[c].iloc[0]), 0)] for c in cols if pd.notna(us[c].iloc[0])]
        last = ser[-1][1]
        yoy = pct(last, ser[-13][1]) if len(ser) > 13 else None
        out.append({"name": "미국 주택가격 (Zillow ZHVI 전국)", "source": "Zillow Research",
                    "last": last, "asof": ser[-1][0], "yoy": yoy, "series": ser})
        log(f"  주택 ZHVI {ser[-1][0]} {last:,.0f}")
    except Exception as e:  # noqa: BLE001
        log(f"  ! ZHVI 실패 :: {e}")

    for sid, nm in [("CSUSHPINSA", "미국 케이스-실러 전국 주택가격지수")]:
        try:
            df = fred(sid)
            df = df.set_index("date")["value"].resample("MS").last().dropna()
            ser = [[i.strftime("%Y-%m"), round(float(v), 3)] for i, v in df.items()]
            last = ser[-1][1]
            yoy = pct(last, ser[-13][1]) if len(ser) > 13 else None
            out.append({"name": nm, "source": "FRED", "last": last,
                        "asof": ser[-1][0], "yoy": yoy, "series": ser})
        except Exception as e:  # noqa: BLE001
            log(f"  ! {sid} 실패 :: {e}")
    return out


# ──────────────────────────────────────────────────────────────
# 4. FOMC 금리 확률 (연방기금 선물 근사)
# ──────────────────────────────────────────────────────────────
MONTH_CODE = {1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M",
              7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z"}


def ff_future(year, month):
    import yfinance as yf
    tk = f"ZQ{MONTH_CODE[month]}{str(year)[-2:]}.CBT"
    try:
        h = yf.Ticker(tk).history(period="10d")
        if h.empty:
            return None
        return round(100 - float(h["Close"].dropna().iloc[-1]), 3)
    except Exception:  # noqa: BLE001
        return None


def next_fomc(events):
    """narrative.json 의 이벤트 중 날짜가 있는 FOMC 항목에서 다음 회의를 고른다."""
    today = dt.date.today().isoformat()
    cand = [e for e in events
            if "FOMC" in e.get("name", "") and re.match(r"^\d{4}-\d{2}-\d{2}$", e.get("date", ""))
            and e["date"] >= today]
    if not cand:
        return "다음 FOMC"
    e = min(cand, key=lambda x: x["date"])
    return f"다음 FOMC {e['date']}"


def odds_from_bills(effr, y3m):
    """선물 수집 실패 시 — 3개월 국채가 반영한 금리 경로에서 환산.
    3개월 구간에는 통상 FOMC 가 2회 열리므로 회의당 반영폭 = (3개월물 − 실효금리) ÷ 2."""
    bp = (y3m - effr) * 100
    per_meeting = bp / 2.0
    p = max(0, min(100, round(abs(per_meeting) / 25 * 100)))
    if per_meeting < -3:
        outcomes = [{"key": "cut", "label": "25bp 인하", "prob": p},
                    {"key": "hold", "label": "동결", "prob": 100 - p}]
    elif per_meeting > 3:
        outcomes = [{"key": "hike", "label": "25bp 인상", "prob": p},
                    {"key": "hold", "label": "동결", "prob": 100 - p}]
    else:
        outcomes = [{"key": "hold", "label": "동결", "prob": 100 - p},
                    {"key": "hike" if per_meeting >= 0 else "cut",
                     "label": "25bp 인상" if per_meeting >= 0 else "25bp 인하", "prob": p}]
    method = (f"⚠ 연방기금 선물 수집 실패 — 3개월 국채금리 기준 대체 환산. "
              f"실효금리 {effr:.2f}% → 3개월물 {y3m:.2f}% = 3개월간 {bp:+.0f}bp 반영, "
              f"이 구간 FOMC 2회로 나누어 회의당 {per_meeting:+.0f}bp ÷ 25bp. "
              "CME FedWatch 공식 수치가 아닌 근사치.")
    path = [{"label": "현재 실효금리", "v": f"{effr:.2f}%"},
            {"label": "3개월물 금리", "v": f"{y3m:.2f}%"},
            {"label": "3개월 반영폭", "v": f"{bp:+.0f}bp"},
            {"label": "회의당 반영폭", "v": f"{per_meeting:+.0f}bp"}]
    return outcomes, method, path


def build_rate_odds(effr, fallback, events):
    today = dt.date.today()
    nxt = today.replace(day=1) + dt.timedelta(days=32)
    nxt = nxt.replace(day=1)
    later = (nxt + dt.timedelta(days=32)).replace(day=1)
    dec = dt.date(today.year, 12, 1) if today.month < 12 else dt.date(today.year + 1, 12, 1)

    imp1 = ff_future(nxt.year, nxt.month)
    if imp1 is None:
        cur = imp2 = impd = None
    else:
        cur = ff_future(today.year, today.month)
        imp2 = ff_future(later.year, later.month)
        impd = ff_future(dec.year, dec.month)

    if imp1 is None:
        log("  ! 연방기금 선물 수집 실패 — 3개월 국채 기준 대체 환산")
        y3m, _ = fred_last("DGS3MO")
        outcomes, method, path = odds_from_bills(effr, y3m)
        return {"meeting": next_fomc(events),
                "asof": today.strftime("%Y-%m-%d"),
                "outcomes": outcomes, "method": method, "path": path}

    diff_bp = (imp1 - effr) * 100
    p_hike = max(0, min(100, round(diff_bp / 25 * 100)))
    if diff_bp < -3:
        outcomes = [{"key": "cut", "label": "25bp 인하", "prob": min(100, round(abs(diff_bp) / 25 * 100))},
                    {"key": "hold", "label": "동결", "prob": max(0, 100 - min(100, round(abs(diff_bp) / 25 * 100)))}]
    else:
        outcomes = [{"key": "hike", "label": "25bp 인상", "prob": p_hike},
                    {"key": "hold", "label": "동결", "prob": 100 - p_hike}]

    path = [{"label": "현재 실효금리", "v": f"{effr:.2f}%"}]
    for lbl, v in [(f"{today.month}월물 내재", cur), (f"{nxt.month}월물 내재", imp1),
                   (f"{later.month}월물 내재", imp2), ("12월물 내재", impd)]:
        if v is not None:
            path.append({"label": lbl, "v": f"{v:.2f}%"})
    if impd is not None:
        path.append({"label": "연말까지 반영폭", "v": f"{(impd - effr) * 100:+.0f}bp"})

    return {
        "meeting": next_fomc(events),
        "asof": today.strftime("%Y-%m-%d"),
        "outcomes": outcomes,
        "method": (f"연방기금 선물 내재금리 기준 · 현재 실효금리 {effr:.2f}% → "
                   f"익월물 내재 {imp1:.2f}% · 차이 {diff_bp:+.0f}bp ÷ 25bp. "
                   "CME FedWatch 공식 수치가 아니라 선물 가격에서 직접 환산한 근사치."),
        "path": path,
    }


# ──────────────────────────────────────────────────────────────
# 5. 기관 13F
# ──────────────────────────────────────────────────────────────
def build_institutions(insts, prev):
    prev_map = {i["key"]: i for i in (prev or [])}
    out = []
    for it in insts:
        key, cik = it["key"], it["cik"]
        try:
            sub = http(f"https://data.sec.gov/submissions/CIK{cik}.json").json()
            rec = sub["filings"]["recent"]
            cand = [i for i, f in enumerate(rec["form"]) if f == "13F-HR"]
            if not cand:
                raise RuntimeError("13F-HR 없음")
            idx = max(cand, key=lambda i: (rec["reportDate"][i], rec["filingDate"][i]))
            acc = rec["accessionNumber"][idx].replace("-", "")
            rdate = rec["reportDate"][idx]

            old = prev_map.get(key)
            if old and old.get("accession") == acc:
                log(f"  13F {key}: 변동 없음 ({rdate})")
                out.append(old)
                continue

            base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}"
            files = http(f"{base}/index.json").json()["directory"]["item"]
            xml = next((f["name"] for f in files
                        if f["name"].lower().endswith(".xml")
                        and "primary_doc" not in f["name"].lower()), None)
            if not xml:
                raise RuntimeError("정보표 XML 없음")
            raw = http(f"{base}/{xml}").text
            names = re.findall(r"<(?:\w+:)?nameOfIssuer>(.*?)</(?:\w+:)?nameOfIssuer>", raw)
            vals = re.findall(r"<(?:\w+:)?value>(.*?)</(?:\w+:)?value>", raw)
            n = min(len(names), len(vals))
            agg = {}
            for i in range(n):
                v = float(vals[i].replace(",", ""))
                agg[names[i].strip()] = agg.get(names[i].strip(), 0.0) + v
            # 2023년 이후 신고는 단위가 달러, 그 이전은 천 달러
            total = sum(agg.values())
            if total < 1e9:
                agg = {k: v * 1000 for k, v in agg.items()}
                total *= 1000
            top = sorted(agg.items(), key=lambda x: -x[1])[:15]
            out.append({
                "key": key, "label": it["label"], "report_date": rdate,
                "accession": acc,
                "total_value_usd": round(total, 0), "n_positions": len(agg),
                "top": [{"name": k, "value": round(v, 0), "pct": round(v / total * 100, 2)}
                        for k, v in top],
            })
            log(f"  13F {key}: {rdate} · {len(agg)}종목 · ${total/1e9:,.1f}B")
            time.sleep(0.5)
        except Exception as e:  # noqa: BLE001
            log(f"  ! 13F 실패 {key} :: {e}")
            if prev_map.get(key):
                out.append(prev_map[key])
    return out


# ──────────────────────────────────────────────────────────────
# main
# ──────────────────────────────────────────────────────────────
def main():
    universe = json.loads((CONF / "universe.json").read_text(encoding="utf-8"))
    narrative = json.loads((CONF / "narrative.json").read_text(encoding="utf-8"))
    insts = json.loads((CONF / "institutions.json").read_text(encoding="utf-8"))

    prev = {}
    pf = DOCS / "payload.json"
    if pf.exists():
        try:
            prev = json.loads(pf.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            prev = {}
    if not prev and os.environ.get("PREV_PAYLOAD_URL"):
        # GitHub Pages 로 직접 배포하는 구성에서는 직전 결과가 저장소에 남지 않는다.
        # 현재 공개 중인 페이지에서 내려받아 13F 캐시로 재사용한다.
        try:
            prev = http(os.environ["PREV_PAYLOAD_URL"], tries=1).json()
            log(f"  직전 payload 회수 (기준 {prev.get('asof')})")
        except Exception as e:  # noqa: BLE001
            log(f"  직전 payload 없음 — 전체 신규 수집 :: {e}")

    log("1/5 시세 수집")
    groups = build_prices(universe)
    if not groups.get("indices"):
        if prev.get("groups"):
            log("  ! 시세 전량 실패 — 직전 시세 유지")
            groups = prev["groups"]
        else:
            log("  !! 시세 수집 실패로 중단")
            sys.exit(1)

    vix = next((x["last"] for x in groups.get("indices", []) if x["ticker"] == "^VIX"), None)

    log("2/5 거시 지표 · 안정성 점수")
    stability, effr = build_stability(vix)
    log(f"  경제 안정성 {stability['score']} ({stability['label']})")

    log("2-b/5 쏠림 지표 (SPY vs RSP)")
    concentration = build_concentration()
    if concentration is None and prev.get("concentration"):
        log("  직전 쏠림 지표 유지")
        concentration = prev["concentration"]

    log("3/5 부동산")
    housing = build_housing()

    log("4/5 금리 확률")
    rate_odds = build_rate_odds(effr, narrative.get("rate_odds_fallback", {}), narrative["events"])

    log("5/5 기관 13F")
    institutions = build_institutions(insts, prev.get("institutions"))

    payload = {
        "asof": dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "groups": groups,
        "institutions": institutions,
        "stability": stability,
        "concentration": concentration,
        "housing": housing,
        "rate_odds": rate_odds,
        "events": narrative["events"],
        "scenarios": narrative["scenarios"],
        "sources": {"prices": "Yahoo Finance",
                    "macro": "NY연준·시카고연준·BLS·Zillow·multpl",
                    "inst": "SEC EDGAR 13F"},
        "disclaimer": narrative["disclaimer"],
    }

    pf.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    shell = (ROOT / "shell.html").read_text(encoding="utf-8")
    html = shell.replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=False))
    (DOCS / "index.html").write_text(html, encoding="utf-8")

    (DOCS / "build.log").write_text("\n".join(LOG), encoding="utf-8")
    log(f"완료 · index.html {len(html)/1024:,.0f}KB")


if __name__ == "__main__":
    main()
