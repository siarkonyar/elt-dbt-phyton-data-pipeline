import sys

from config import ConfigError, load_config
from db import apply_schema, get_engine
from hf_client import HfApiError, HfDatasetsClient, build_session
from runs import FAILED, SUCCEEDED, finish_run, start_run
from sampling import plan_offsets
from writer import upsert_rows


def check_split_exists(client, config):
    """Fail early and clearly if the requested split is not there."""
    available = client.fetch_splits(config.dataset_name)
    wanted = (config.dataset_config, config.split)

    if wanted not in available:
        raise HfApiError(
            f"{config.dataset_name} has no config/split {wanted}. "
            f"Available: {list(available)}"
        )

def run_ingest(config, engine, client):
    check_split_exists(client, config)

    # We cannot plan the offsets until the API tells us how big the dataset is,
    # and it only tells us that inside a rows response. So we fetch page zero
    # first -- which is the first planned offset under both strategies anyway.
    first_page = client.fetch_page(
        config.dataset_name, config.dataset_config, config.split, 0, config.page_size
    )
    num_rows_total = first_page.num_rows_total

    offsets = plan_offsets(
        num_rows_total, config.target_rows, config.page_size, config.sampling
    )
    print(f"{num_rows_total} rows upstream; fetching {len(offsets)} pages ({config.sampling})")

    rows_fetched = 0
    rows_inserted = 0

    for position, offset in enumerate(offsets, start=1):
        page = (
            first_page
            if offset == 0
            else client.fetch_page(
                config.dataset_name,
                config.dataset_config,
                config.split,
                offset,
                config.page_size,
            )
        )

        with engine.begin() as connection:
            inserted = upsert_rows(
                connection,
                config.dataset_name,
                config.dataset_config,
                config.split,
                page,
            )

        rows_fetched += len(page.rows)
        rows_inserted += inserted
        print(
            f"  page {position}/{len(offsets)} offset={offset}: "
            f"{len(page.rows)} fetched, {inserted} new"
        )

    return rows_fetched, rows_inserted, num_rows_total

def main():
    config = load_config()
    engine = get_engine()

    with engine.begin() as connection:
        apply_schema(connection)

    client = HfDatasetsClient(
        session=build_session(),
        text_column=config.text_column,
        label_column=config.label_column,
        timeout_seconds=config.timeout_seconds,
        max_retries=config.max_retries,
    )

    with engine.begin() as connection:
        run_id = start_run(connection, config)

    print(
        f"run {run_id}: {config.dataset_name} / {config.dataset_config} / {config.split}"
    )

    try:
        fetched, inserted, total = run_ingest(config, engine, client)
    except Exception as error:
        with engine.begin() as connection:
            finish_run(
                connection,
                run_id,
                FAILED,
                error_message=f"{type(error).__name__}: {error}",
            )
        raise

    with engine.begin() as connection:
        finish_run(
            connection,
            run_id,
            SUCCEEDED,
            num_rows_total=total,
            rows_fetched=fetched,
            rows_inserted=inserted,
        )

    print(f"run {run_id} finished: {fetched} fetched, {inserted} new rows")


if __name__ == "__main__":
    try:
        main()
    except ConfigError as error:
        print(f"Configuration problem: {error}", file=sys.stderr)
        sys.exit(2)