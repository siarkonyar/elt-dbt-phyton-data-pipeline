from fastapi import Depends, FastAPI, Query
from functools import lru_cache

import db
from serialize import candle_to_dict

app = FastAPI(title="ELT candles API")

@app.get("/health")
def health():
  return {"status": "ok"}

@lru_cache(maxsize=1)
def _engine():
  return db.get_engine()

def read_candles(symbol, hours):
  return db.read_candles(_engine(), symbol, hours)

def get_reader():
  return read_candles

@app.get("/candles")
def candles(symbol: str = Query(..., min_length=1, max_length=10), hours: int = Query(1, ge=1, le=24), reader = Depends(get_reader)):
  return [candle_to_dict(row) for row in reader(symbol.upper(), hours)]