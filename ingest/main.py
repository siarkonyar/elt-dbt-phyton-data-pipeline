import sys

from config import ConfigError, load_config
from db import apply_schema, get_engine
from writer import upsert_quotes
from yahoo_client import YahooApiError, YahooClient, build_session

def fetch_all(client, symbols):
    quotes = []

    for symbol in symbols:
        quote = client.fetch_quote(symbol)
        quotes.append(quote)
        print(f"  {quote.symbol:6} {quote.price}")

    return tuple(quotes)

def main():
    config = load_config()
    engine = get_engine()

    with engine.begin() as connection:
        apply_schema(connection)

    client = YahooClient(
        session=build_session(),
        base_url=config.base_url,
        timeout_seconds=config.timeout_seconds,
        max_retries=config.max_retries,
    )

    print(f"polling {', '.join(config.symbols)}")
    quotes = fetch_all(client, config.symbols)

    with engine.begin() as connection:
        inserted = upsert_quotes(connection, quotes)

    print(f"{len(quotes)} fetched, {inserted} new rows")

if __name__ == "__main__":
    try:
        main()
    except ConfigError as error:
        print(f"Configuration problem: {error}", file=sys.stderr)
        sys.exit(2)
    except YahooApiError as error:
        print(f"Yahoo problem: {error}", file=sys.stderr)
        sys.exit(1)