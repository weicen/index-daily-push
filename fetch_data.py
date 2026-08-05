#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日美股指数日报（云端版）
数据源：
  - 行情:   CNBC 官方免费 API（.SPX / .NDX）
  - SPX PE: multpl.com（Shiller 权威数据，as-reported TTM，每日更新）
  - NDX PE: FMP 免费 API 取 QQQ（完全跟踪纳指100）的 trailing PE 代表
推送渠道：Server酱（微信）
周六/周日美股休市，自动跳过。
"""
import datetime
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "application/json,text/html,*/*",
}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CARDS_DIR = os.path.join(BASE_DIR, "cards")
os.makedirs(CARDS_DIR, exist_ok=True)


def http_get(url, timeout=40):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


def http_post(url, data, timeout=40):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={**UA, "Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


# ---------- 数据抓取 ----------

def get_cnbc_quotes():
    url = ("https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol"
           "?symbols=.SPX%7C.NDX&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json")
    out = {}
    # CNBC 偶发网络超时或盘中返回 change=UNCH，重试最多 3 次
    for _ in range(3):
        try:
            data = json.loads(http_get(url))
        except Exception as e:
            print("CNBC request error:", e)
            time.sleep(3)
            continue
        out = {}
        for q in data["FormattedQuoteResult"]["FormattedQuote"]:
            sym = q["symbol"]  # ".SPX" / ".NDX"
            try:
                out[sym] = {
                    "name": q["name"],
                    "price": float(q["last"].replace(",", "")),
                    "change": q["change"],
                    "change_pct": q["change_pct"],
                    "date": q["last_time"],   # "2026-08-04"
                }
            except (KeyError, ValueError):
                continue
        if ".SPX" in out and ".NDX" in out and \
           "UNCH" not in str(out[".SPX"]["change_pct"]) and \
           "UNCH" not in str(out[".NDX"]["change_pct"]):
            return out
        time.sleep(3)
    if ".SPX" not in out or ".NDX" not in out:
        raise RuntimeError("CNBC 行情解析失败: %s" % json.dumps(out, ensure_ascii=False))
    return out


def get_multpl_spx_pe():
    """返回 (PE, 数据日期描述)"""
    html = http_get("https://www.multpl.com/s-p-500-pe-ratio")
    # 页面结构: <div id="current"><b>Current<span class="currentTitle">S&P 500 PE Ratio</span>:</b>\n29.80...
    m = re.search(r'<div id="current">.*?</b>\s*([\d.]+)', html, re.S)
    dm = re.search(r'<div id="timestamp">\s*([^<]+)', html, re.S)
    if not m:
        raise RuntimeError("multpl SPX PE 解析失败")
    return float(m.group(1)), (dm.group(1).strip() if dm else "日期未知")


def get_nasdaq_qqq_pe():
    """
    Nasdaq 官方 API 取 QQQ(纳指100 ETF) 的 P/E，作为 FMP 失败时的兜底源。
    云端(GitHub Actions 美国节点)访问快；本机可能超时属正常。
    返回 (pe, None) 或 (None, None)。
    """
    try:
        url = "https://api.nasdaq.com/api/quote/QQQ/info?assetclass=etf"
        req = urllib.request.Request(url, headers={
            **UA, "Accept": "application/json",
            "Origin": "https://www.nasdaq.com",
            "Referer": "https://www.nasdaq.com/",
        })
        with urllib.request.urlopen(req, timeout=25) as r:
            data = json.loads(r.read().decode("utf-8", "ignore"))
        ks = ((data.get("data") or {}).get("keyStats")) or {}
        # keyStats 结构未知，宽松解析：label 含 pe/earnings 且 value 可转数字
        for k, v in ks.items():
            if isinstance(v, dict):
                label = str(v.get("label", "")).lower()
                if "pe" in label or "earnings" in label or "p/e" in label:
                    try:
                        pe = float(str(v.get("value", "")).replace(",", "").replace("x", "").strip())
                        if pe > 0:
                            print(f"Nasdaq QQQ PE source: {label} (pe={pe})")
                            return pe, None
                    except (ValueError, TypeError):
                        continue
        return None, None
    except Exception as e:
        print("Nasdaq QQQ PE failed:", e)
        return None, None


def get_fmp_qqq_pe(api_key):
    """
    返回 (pe, 交易日, 用到的symbol)。FMP 新版 stable API。
    FMP 免费层会把部分 ETF 标为 Special Endpoint（付费），因此依次尝试
    QQQ -> QQQM(同为纳指100 ETF) -> ^NDX(指数)，取第一个有 pe 的。
    全部失败返回 (None, None, None)，由上层降级。
    """
    candidates = ["QQQ", "QQQM", "%5ENDX"]
    for sym in candidates:
        try:
            url = f"https://financialmodelingprep.com/stable/quote?symbol={sym}&apikey={api_key}"
            data = json.loads(http_get(url))
            pe, date = _extract_pe(data)
            if pe is not None:
                print(f"FMP NDX PE source: {sym} (pe={pe})")
                return pe, date, sym
            print(f"FMP {sym}: no pe field")
            # 备用：key-metrics-ttm
            url2 = f"https://financialmodelingprep.com/stable/key-metrics-ttm?symbol={sym}&apikey={api_key}"
            data2 = json.loads(http_get(url2))
            pe2, date2 = _extract_pe_metrics(data2)
            if pe2 is not None:
                print(f"FMP NDX PE source: {sym} key-metrics (pe={pe2})")
                return pe2, date2, sym
        except Exception as e:
            print(f"FMP {sym} failed (will try next):", e)
    return None, None, None


def _extract_pe(data):
    if isinstance(data, dict):
        return data.get("pe"), data.get("date")
    if isinstance(data, list) and data:
        return data[0].get("pe"), data[0].get("date")
    return None, None


def _extract_pe_metrics(data):
    if isinstance(data, list) and data:
        d = data[0]
        for k in ("peRatioTTM", "peRatio", "pe", "trailingPE"):
            if d.get(k) is not None:
                return d[k], d.get("date")
    return None, None


def get_fmp_index_quotes(api_key):
    """备用行情源：FMP stable API 的 S&P 500(^GSPC) / Nasdaq-100(^NDX)"""
    url = f"https://financialmodelingprep.com/stable/batch-quote?symbols=%5EGSPC,%5ENDX&apikey={api_key}"
    data = json.loads(http_get(url))
    out = {}
    items = data if isinstance(data, list) else [data]
    for d in items:
        if not isinstance(d, dict):
            continue
        sym = d.get("symbol")  # "^GSPC" / "^NDX"
        key = ".SPX" if sym == "^GSPC" else (".NDX" if sym == "^NDX" else None)
        if not key:
            continue
        ts = d.get("timestamp")
        date = datetime.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d") if ts else "unknown"
        chg = d.get("change")
        chg_pct = d.get("changesPercentage")
        out[key] = {
            "name": d.get("name", key),
            "price": float(d.get("price") or 0),
            "change": f"{chg:+.2f}" if isinstance(chg, (int, float)) else chg,
            "change_pct": f"{chg_pct:.2f}%" if isinstance(chg_pct, (int, float)) else str(chg_pct or "0%"),
            "date": date,
        }
    return out


# ---------- 策略 ----------

def strategy(pe):
    if pe is None:
        return None
    if pe < 25:
        return ("🟢 极度低估", "多投 200%", "≈3,334元")
    if pe < 30:
        return ("🟢 低估", "多投 150%", "≈2,500元")
    if pe < 35:
        return ("🟡 合理", "正常投 100%", "1,667元")
    if pe < 38:
        return ("🟠 高估", "少投 50%", "≈833元")
    return ("🔴 极度高估", "暂停定投", "0元")


# ---------- 卡片生成 ----------

def gen_card(quotes, spx_pe, ndx_pe, ndx_pe_src_date, out_path):
    from PIL import Image, ImageDraw, ImageFont

    W, H = 750, 1400
    BG = (15, 27, 45)
    CARD = (26, 42, 66)
    CARD_LINE = (48, 70, 102)
    TITLE = (255, 255, 255)
    SUB = (160, 178, 202)
    UP_RED = (255, 77, 79)
    GOLD = (245, 185, 66)
    GREEN = (82, 196, 116)

    # 云端字体（GitHub Actions 需先安装 fonts-noto-cjk）
    def font(size, bold=False):
        for p in (
            r"/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold
            else r"/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            r"C:\Windows\Fonts\msyhbd.ttc" if bold else r"C:\Windows\Fonts\msyh.ttc",
        ):
            if os.path.exists(p):
                return ImageFont.truetype(p, size)
        return ImageFont.load_default()

    def tc(cx, y, s, f, fill):
        w = d.textlength(s, font=f)
        d.text((cx - w / 2, y), s, font=f, fill=fill)

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    trade_date = str(quotes[".SPX"]["date"])[:10]  # 只取 YYYY-MM-DD，避免盘中时间戳
    tc(W / 2, 66, "美股指数日报", font(46, True), TITLE)
    tc(W / 2, 132, f"{trade_date} 收盘 · 数据源：CNBC / multpl / FMP", font(22), SUB)

    y = 186
    items = [
        ("标普500", "S&P 500", quotes[".SPX"]),
        ("纳斯达克100", "Nasdaq-100", quotes[".NDX"]),
    ]
    for cname, code, q in items:
        d.rounded_rectangle([40, y, W - 40, y + 150], radius=20, fill=CARD, outline=CARD_LINE, width=2)
        d.text((72, y + 32), cname, font=font(32, True), fill=TITLE)
        d.text((72, y + 88), code, font=font(20), fill=SUB)
        tc(W / 2 + 100, y + 40, f"{q['price']:,.2f}", font(40, True), TITLE)
        tc(W / 2 + 100, y + 98, f"{q['change']}  {q['change_pct']}", font(28, True), UP_RED)
        y += 176

    tc(W / 2, y + 12, "估值水平（PE）", font(30, True), TITLE)
    y += 58
    pe_items = [
        ("标普500", f"{spx_pe:.2f}", "multpl 口径", GREEN),
        ("纳斯达克100", f"{ndx_pe:.2f}" if ndx_pe else "--", f"QQQ·{ndx_pe_src_date}", GREEN if ndx_pe else SUB),
    ]
    py = y
    for name, pe, tag, col in pe_items:
        d.rounded_rectangle([40, py, W - 40, py + 118], radius=20, fill=CARD, outline=CARD_LINE, width=2)
        d.text((72, py + 30), name, font=font(28, True), fill=TITLE)
        d.text((72, py + 74), f"PE {pe}", font=font(30, True), fill=GOLD)
        tc(W - 130, py + 44, tag, font(24, True), col)
        py += 140

    sy = py + 12
    d.rounded_rectangle([40, sy, W - 40, sy + 300], radius=20, fill=(20, 34, 56), outline=CARD_LINE, width=2)
    d.text((72, sy + 24), "定投策略提示（基准 1,667元/月）", font=font(30, True), fill=TITLE)
    s1 = strategy(spx_pe)
    s2 = strategy(ndx_pe)
    rows = [
        (f"标普500 · PE {spx_pe:.2f}", s1),
        (f"纳斯达克100 · PE {ndx_pe:.2f}" if ndx_pe else "纳斯达克100 · PE --", s2),
    ]
    syy = sy + 84
    for label, s in rows:
        if not s:
            d.text((72, syy), label, font=font(26, True), fill=SUB)
            d.text((72, syy + 42), "数据缺失", font=font(28, True), fill=SUB)
            syy += 96
            continue
        d.text((72, syy), label, font=font(26, True), fill=SUB)
        d.text((72, syy + 42), f"{s[0]} {s[1]}", font=font(28, True), fill=UP_RED if s[1].startswith("多投") else GOLD)
        tc(W - 130, syy + 38, s[2], font(30, True), GOLD)
        syy += 96

    rules = [
        "PE<25 极度低估多投200% | 25-30 低估多投150% | 30-35 正常100%",
        "35-38 高估少投50% | ≥38 极度高估暂停定投",
    ]
    ry = syy + 6
    for r in rules:
        tc(W / 2, ry, r, font(20), SUB)
        ry += 32

    ty = H - 116
    d.line([40, ty - 14, W - 40, ty - 14], fill=CARD_LINE, width=2)
    tc(W / 2, ty + 4, "基于PE估值的量化策略提示，不构成投资建议", font(22), SUB)
    tc(W / 2, ty + 44, "市场有风险，投资需谨慎", font(22), SUB)

    img.save(out_path)
    return out_path


# ---------- 主流程 ----------

def main():
    now = datetime.datetime.now()
    if now.weekday() >= 5:  # 周六/周日美股休市
        print("weekend, skip")
        return

    fmp_key = os.environ.get("FMP_KEY", "").strip()
    sendkey = os.environ.get("SERVERCHAN_SENDKEY", "").strip()
    if not fmp_key or not sendkey:
        print("ERROR: missing FMP_KEY or SERVERCHAN_SENDKEY env")
        sys.exit(1)

    quotes = {}
    try:
        quotes = get_cnbc_quotes()
        print("quotes source: CNBC")
    except Exception as e:
        print("CNBC failed, fallback to FMP:", e)
        quotes = get_fmp_index_quotes(fmp_key)
        print("quotes source: FMP fallback")
    if not quotes.get(".SPX") or not quotes.get(".NDX"):
        raise RuntimeError("行情获取失败: %s" % json.dumps(quotes, ensure_ascii=False))
    spx_pe, spx_pe_note = get_multpl_spx_pe()
    qqq_pe, qqq_date, qqq_sym = get_fmp_qqq_pe(fmp_key)
    if qqq_pe is None:
        # FMP 免费层对 QQQ 系标的多为付费墙，改用 Nasdaq 官方 API 兜底
        qqq_pe, _ = get_nasdaq_qqq_pe()
        qqq_sym = qqq_sym or "QQQ"
    ndx_pe = qqq_pe
    if ndx_pe is None:
        print("NDX PE unavailable -> will push with NDX PE marked as -- (SPX PE still complete)")

    trade_date = str(quotes[".SPX"]["date"])[:10]  # 只取 YYYY-MM-DD，避免盘中时间戳
    repo = os.environ.get("GITHUB_REPOSITORY", "owner/repo")
    card_file = os.path.join(CARDS_DIR, f"{trade_date}.png")
    gen_card(quotes, spx_pe, ndx_pe, qqq_date or "最新", card_file)
    img_url = f"https://raw.githubusercontent.com/{repo}/main/cards/{trade_date}.png"

    s1, s2 = strategy(spx_pe), strategy(ndx_pe)

    lines = []
    lines.append(f"## 📈 美股指数日报 · {trade_date} 收盘\n")
    lines.append("| 指数 | 收盘 | 涨跌 | 涨幅 |")
    lines.append("|---|---|---|---|")
    lines.append(f"| 标普500 | {quotes['.SPX']['price']:,.2f} | {quotes['.SPX']['change']} | **{quotes['.SPX']['change_pct']}** |")
    lines.append(f"| 纳斯达克100 | {quotes['.NDX']['price']:,.2f} | {quotes['.NDX']['change']} | **{quotes['.NDX']['change_pct']}** |")
    lines.append("")
    lines.append("## 💰 定投策略（基准 1,667元/月）\n")
    lines.append("| 标的 | PE | 判断 | 动作 | 金额 |")
    lines.append("|---|---|---|---|---|")
    lines.append(f"| 标普500 | {spx_pe:.2f} | {s1[0]} | {s1[1]} | **{s1[2]}** |" if s1 else "| 标普500 | -- | | | |")
    lines.append(f"| 纳斯达克100 | {ndx_pe:.2f} | {s2[0]} | {s2[1]} | **{s2[2]}** |" if s2 else "| 纳斯达克100 | -- | | | |")
    lines.append("")
    lines.append(f"PE 来源：SPX=multpl（{spx_pe_note}）；NDX={qqq_sym or 'QQQ'}（FMP，{qqq_date or '最新'}）")
    lines.append("")
    lines.append(f"![日报卡片]({img_url})")
    lines.append("")
    lines.append("> 基于PE估值的量化策略提示，不构成投资建议。市场有风险，投资需谨慎。")

    desp = "\n".join(lines)
    title = f"美股指数日报 {trade_date}"
    resp = http_post(f"https://sctapi.ftqq.com/{sendkey}.send",
                     {"title": title, "desp": desp})
    print(resp)
    print("OK push done")


if __name__ == "__main__":
    main()
