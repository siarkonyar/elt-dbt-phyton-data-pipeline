from fastapi import FastAPI

app = FastAPI(title="ELT candles API")

@app.get("/healt")
def healt():
  return {"status": "ok"}