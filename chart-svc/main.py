import io, base64, os, time, requests
from datetime import datetime, timezone, timedelta
import pandas as pd, mplfinance as mpf
from fastapi import FastAPI, HTTPException, Query
from dotenv import load_dotenv
from pymongo import MongoClient, ASCENDING
from zoneinfo import ZoneInfo

load_dotenv()
client = MongoClient(os.getenv("MONGO_URL"))
col = client[os.getenv("MONGO_DB", "crypto")]["klines"]      # structure = prev. version

# индексы для быстрого поиска (создадутся 1 раз)
col.create_index([("symbol", ASCENDING), ("interval", ASCENDING), ("open_time", ASCENDING)],
                 unique=True)

app = FastAPI(title="chart-svc v2")

# ─────────────────────────────────────────────────────────────── helpers ──
BINANCE = "https://api.binance.com/api/v3/klines"
TOP10   = ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT",
           "ADAUSDT","DOGEUSDT","AVAXUSDT","DOTUSDT","LINKUSDT"]

def fetch_klines(symbol:str, start_ms:int, end_ms:int):
    """Скачивает 5-минутные свечи с бинанса (пачками по 1000)"""
    all_rows = []
    cursor = start_ms
    while cursor < end_ms:
        params = dict(symbol=symbol, interval="5m", startTime=cursor,
                      endTime=min(end_ms, cursor + 1000*5*60*1000), limit=1000)
        rows = requests.get(BINANCE, params=params, timeout=15).json()
        if not rows: break
        all_rows.extend(rows)
        cursor = rows[-1][0] + 5*60*1000          # next candle open_time
        time.sleep(0.25)                          # чуть бережнее к API
    docs = [dict(symbol=symbol, interval="5m",
                 open_time=r[0], open=float(r[1]), high=float(r[2]),
                 low=float(r[3]),  close=float(r[4]), volume=float(r[5]))
            for r in all_rows]
    if docs:
        col.insert_many(docs, ordered=False, bypass_document_validation=True)
    return len(docs)

def ensure_last_month(symbol:str):
    """Гарантирует, что в Mongo есть минимум последние 30 дней"""
    if symbol not in TOP10:
        raise HTTPException(400, f"symbol {symbol} not allowed")
    now_ms = int(datetime.utcnow().timestamp()*1000)
    month_ago_ms = int((datetime.utcnow()-timedelta(days=30))
                       .timestamp()*1000)
    # есть ли свеча за последние 30 дней?
    doc = col.find_one({"symbol":symbol,"interval":"5m",
                        "open_time":{"$gte":month_ago_ms}},
                       projection={"_id":0,"open_time":1},
                       sort=[("open_time",ASCENDING)])
    if doc is None:
        added = fetch_klines(symbol, month_ago_ms, now_ms)
        if added == 0:
            raise HTTPException(404,"Binance returned no data")

def get_df(symbol:str) -> pd.DataFrame:
    """DataFrame всех 5-мин свечей за последние 30 дней"""
    ensure_last_month(symbol)
    month_ago = datetime.utcnow() - timedelta(days=30)
    cur = col.find({"symbol":symbol,"interval":"5m",
                    "open_time":{"$gte":int(month_ago.timestamp()*1000)}},
                   {"_id":0})
    df = (pd.DataFrame(cur)
            .rename(columns={"open_time":"Date"})
            .assign(Date=lambda d: pd.to_datetime(d.Date, unit="ms"))
            .set_index("Date")
            .sort_index())
    return df[["open","high","low","close","volume"]]

def resample(df5:pd.DataFrame, target:str)->pd.DataFrame:
    if target=="5m": return df5
    rule = target.replace("m","T")
    agg  = {"open":"first","high":"max","low":"min","close":"last","volume":"sum"}
    return (df5.resample(rule,label='left',closed='left').apply(agg).dropna())

# ─────────────────────────────────────────────────────────────── endpoint ──
@app.get("/charts/{symbol}")
def chart(symbol:str,
          interval:str = Query("5m", pattern="^(5|10|15)m$"),
          limit:int    = Query(100, ge=20, le=500),
          offset:int   = Query(0, ge=0),
          tz: str = Query("UTC")):
    """
    Возвращает base64 PNG-картинку N (=limit) свечей, начиная от `offset`
    (0 = самые свежие). Если данных нет — тянем за последний месяц с Binance.
    """
    symbol = symbol.upper()
    df5 = get_df(symbol)
    if offset >= len(df5):
        raise HTTPException(416, "offset too large")

    df = resample(df5, interval)
    df.index = df.index.tz_localize("UTC").tz_convert("Europe/Chisinau")
    # срез «с конца» → [-offset-limit : -offset]   (-0 ≡ None)
    slice_df = df.iloc[-offset-limit : len(df)-offset] if offset else df.iloc[-limit:]
    if slice_df.empty:
        raise HTTPException(404, "no data for slice")

    buf = io.BytesIO()
    mpf.plot(slice_df, type="candle", style="charles",
             figsize=(6.4,6.4), savefig=buf, tight_layout=True)
    buf.seek(0)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return {"image":f"data:image/png;base64,{b64}"}
