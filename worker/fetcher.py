from datetime import datetime, timedelta, timezone
import time, os
from typing import List

from binance.client import Client
from pymongo import MongoClient, UpdateOne

INTERVAL  = Client.KLINE_INTERVAL_5MINUTE
STEP_MS   = 5 * 60 * 1000
BATCH     = 1000

client = Client(
    api_key=os.getenv("BINANCE_API_KEY"),
    api_secret=os.getenv("BINANCE_API_SECRET")
)
mongo  = MongoClient(os.getenv("MONGO_URL"))
db     = mongo[os.getenv("MONGO_DB", "crypto")]
col    = db["klines"]

col.create_index(
    [("symbol", 1), ("interval", 1), ("open_time", 1)],
    unique=True
)

def _period_start(period: str) -> int:
    delta = {"day": 1, "week": 7, "month": 30}.get(period)
    if not delta:
        raise ValueError("period must be day/week/month")
    dt = datetime.now(timezone.utc) - timedelta(days=delta)
    return int(dt.timestamp() * 1000)

def _bulk_upsert(ops: List[UpdateOne]):
    if ops:
        col.bulk_write(ops, ordered=False)

def fetch_symbol(symbol: str, period: str) -> int:
    start_ts = _period_start(period)
    now_ms   = int(datetime.now(timezone.utc).timestamp() * 1000)

    last = col.find_one(
        {"symbol": symbol, "interval": "5m", "open_time": {"$gte": start_ts}},
        sort=[("open_time", -1)],
        projection={"open_time": 1}
    )
    if last:
        start_ts = last["open_time"] + STEP_MS

    inserted, ops = 0, []
    while start_ts < now_ms:
        klines = client.get_klines(
            symbol=symbol,
            interval=INTERVAL,
            startTime=start_ts,
            endTime=now_ms,
            limit=BATCH
        )
        if not klines:
            break

        for k in klines:
            ops.append(
                UpdateOne(
                    {"symbol": symbol, "interval": "5m", "open_time": k[0]},
                    {"$setOnInsert": {
                        "open":   float(k[1]), "high":  float(k[2]),
                        "low":    float(k[3]), "close": float(k[4]),
                        "volume": float(k[5])
                    }},
                    upsert=True
                )
            )
        inserted += len(klines)
        start_ts = klines[-1][0] + STEP_MS
        time.sleep(0.2)

        if len(ops) >= BATCH:
            _bulk_upsert(ops); ops.clear()

    _bulk_upsert(ops)
    return inserted
