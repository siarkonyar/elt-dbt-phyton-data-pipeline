from datetime import UTC, datetime, timedelta

from aiohttp import WSMsgType, web

PORT = 8080

# Far enough back that a slightly fast container clock cannot put the
# trades in the future, close enough to stay inside the rollup window.
MINUTES_BACK = 2

# aiohttp warns if you key app state with a bare string. An AppKey is a
# typed key: the name plus what type is stored under it.
BURST_SENT = web.AppKey("burst_sent", bool)

# (symbol, seconds past the minute, price, volume)
BURST = (
    ("NVDA", 10, 100.0, 1.0),
    ("NVDA", 20, 108.0, 2.0),
    ("NVDA", 30, 95.0, 3.0),
    ("NVDA", 40, 104.0, 4.0),
    ("AMZN", 15, 200.0, 5.0),
)

def burst_payload(now=None):
    """The five trades as ONE Finnhub trade message.

    The base time is floored to a whole minute, so all four NVDA trades
    land inside the same minute and therefore inside the same candle.
    """
    now = now or datetime.now(UTC)
    base = now.replace(second=0, microsecond=0) - timedelta(minutes=MINUTES_BACK)

    return {
        "type": "trade",
        "data": [
            {
                "s": symbol,
                # Finnhub sends epoch MILLISECONDS; the parser divides by 1000.
                "t": int((base + timedelta(seconds=offset)).timestamp() * 1000),
                "p": price,
                "v": volume,
                "c": [],
            }
            for symbol, offset, price, volume in BURST
        ],
    }

async def market_status(request):
    """GET /stock/market-status?exchange=US — always open, always regular."""
    return web.json_response({"isOpen": True, "session": "regular"})


async def websocket(request):
    """The stream subscribes once per symbol. The first one triggers the burst."""
    socket = web.WebSocketResponse()
    await socket.prepare(request)

    async for message in socket:
        if message.type is not WSMsgType.TEXT:
            continue

        if not request.app[BURST_SENT]:
            # Set the flag BEFORE sending, so the four subscribes that
            # arrive right behind this one cannot each fire a burst.
            request.app[BURST_SENT] = True
            await socket.send_json(burst_payload())

    # Reached only when the client hangs up. Until then the loop above
    # holds the connection open, which is what stops stream reconnecting.
    return socket

def make_app():
    app = web.Application()
    app[BURST_SENT] = False
    app.add_routes(
        [
            # No path in the socket URL, so the upgrade lands on "/".
            web.get("/", websocket),
            web.get("/stock/market-status", market_status),
        ]
    )
    return app

if __name__ == "__main__":
    # 0.0.0.0, not localhost: inside a container localhost is invisible
    # to every other container.
    web.run_app(make_app(), host="0.0.0.0", port=PORT)
