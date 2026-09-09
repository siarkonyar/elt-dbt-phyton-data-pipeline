from fastapi import FastAPI
from functools import lru_cache

from api import db

app = FastAPI(title="ELT candles API")

@app.get("/healt")
def healt():
  return {"status": "ok"}

@lru_cache(maxsize=1)
def _engine():
  return db.get_engine()

def read_candles(symbol, hours):
  return db.read_candles(_engine, symbol, hours)

def get_reader():
  return read_candles