import sys
import time

from breaker import CircuitBreaker
from client import FinnhubClient, build_session
from config import ConfigError, load_config
from db import apply_schema, get_engine
from rate_limiting import TokenBucket
from runs import FAILED, SUCCEEDED, finish_poll, start_poll
from writer import upsert_quotes

def build_client(config):
    return FinnhubClient(
        session=build_session(config.api_key),
        api_key=config.api_key,
        base_url=config.base_url,
        timeout_seconds=config.timeout_seconds,
        max_retries=config.max_retries,
        bucket=TokenBucket(config.rate_per_second, config.rate_burst),
        breaker=CircuitBreaker(
            config.breaker_failure_threshold, config.breaker_cooldown_seconds
        ),
    )

def run_cycle(config, engine, client):
    """One poll: market status, then every quote, then one transaction."""
    client.reset_stats()

    with engine.begin() as connection:
        poll_id = start_poll(connection, config.symbols)

    try:
        status = client.fetch_market_status()
        quotes = tuple(client.fetch_quote(symbol) for symbol in config.symbols)

        with engine.begin() as connection:
            inserted = upsert_quotes(connection, quotes)
            finish_poll(
                connection,
                poll_id,
                SUCCEEDED,
                market_open=status.is_open,
                session=status.session,
                requests_made=client.requests_made,
                rows_inserted=inserted,
                throttled_seconds=client.throttled_seconds,
                retries=client.retries,
                breaker_state=client.breaker.status,
            )
    except Exception as error:
        with engine.begin() as connection:
            finish_poll(
                connection,
                poll_id,
                FAILED,
                requests_made=client.requests_made,
                throttled_seconds=client.throttled_seconds,
                retries=client.retries,
                breaker_state=client.breaker.status,
                error_message=f"{type(error).__name__}: {error}",
            )
        raise

    return status, len(quotes), inserted

def main():
    config = load_config()
    engine = get_engine()

    with engine.begin() as connection:
        apply_schema(connection)

    client = build_client(config)
    print(
        f"polling {', '.join(config.symbols)} "
        f"every {config.poll_interval_seconds:.0f}s "
        f"({config.market_closed_poll_seconds:.0f}s when closed)"
    )

    while True:
        started = time.monotonic()
        interval = config.poll_interval_seconds

        try:
            status, fetched, inserted = run_cycle(config, engine, client)
            if not status.is_open:
                interval = config.market_closed_poll_seconds

            print(
                f"{fetched} quotes, {inserted} new | "
                f"market={status.session or 'closed'} | "
                f"requests={client.requests_made} retries={client.retries} "
                f"throttled={client.throttled_seconds:.2f}s "
                f"breaker={client.breaker.status}"
            )
        except Exception as error:
            print(f"cycle failed: {type(error).__name__}: {error}", file=sys.stderr)

        elapsed = time.monotonic() - started
        time.sleep(max(0.0, interval - elapsed))

if __name__ == "__main__":
    try:
        main()
    except ConfigError as error:
        print(f"Configuration problem: {error}", file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        print("stopped")