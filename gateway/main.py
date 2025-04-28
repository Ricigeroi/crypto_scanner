import os, json
import pika, httpx
from fastapi import FastAPI, HTTPException, Response, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

# ───────────────────────────── RabbitMQ ──
AMQP_URL = os.getenv("AMQP_URL")
connection = pika.BlockingConnection(pika.URLParameters(AMQP_URL))
channel    = connection.channel()
channel.queue_declare(queue="fetch_request", durable=True)

# ───────────────────────────── Models ──
class LoadRequest(BaseModel):
    symbols: list[str]
    period:  str

# ───────────────────────────── Upstreams ──
CHART_SVC = "http://chart-svc:9000"
YOLO_SVC  = "http://yolo-svc:9100"
client    = httpx.AsyncClient(timeout=30)

# ───────────────────────────── FastAPI ──
app = FastAPI(title="crypto-gateway")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=False,
    allow_methods=["*"],  allow_headers=["*"],
)

# ① очередь на воркеры-грузчики
@app.post("/load")
def load(req: LoadRequest):
    if not req.symbols:
        raise HTTPException(400, "symbols empty")
    if req.period not in ("day", "week", "month"):
        raise HTTPException(400, "bad period")

    for sym in req.symbols:
        channel.basic_publish(
            exchange="", routing_key="fetch_request",
            body=json.dumps({"symbol": sym.upper(), "period": req.period}),
            properties=pika.BasicProperties(delivery_mode=2)  # persist
        )
    return {"status": "queued", "symbols": req.symbols, "period": req.period}

# ② новый прокси-роут для графика
@app.get("/charts/{symbol}")
async def proxy_chart(
    symbol: str,
    interval: str = Query("5m", pattern="^(5|10|15)m$"),
    limit:   int  = Query(100, ge=20, le=500),
    offset:  int  = Query(0, ge=0),
):
    params = {"interval": interval, "limit": limit, "offset": offset}
    r = await client.get(f"{CHART_SVC}/charts/{symbol}", params=params)
    if r.status_code != 200:
        raise HTTPException(r.status_code, PlainTextResponse(r.text, status_code=r.status_code))
    return r.json()

# ③ прокси YOLO
@app.post("/detect")
async def proxy_detect(body: dict):
    try:
        resp = await client.post(f"{YOLO_SVC}/detect", json=body)
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type=resp.headers.get("content-type", "application/json"),
    )
