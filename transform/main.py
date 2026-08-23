from db import get_engine, read_table

SOURCE_TABLES = ["trainers", "members", "gym_classes", "bookings"]


def main():
    engine = get_engine()
    print("Connected. Reading raw tables...")

    for table_name in SOURCE_TABLES:
        df = read_table(engine, table_name)
        print(f"  {table_name}: {len(df)} rows, {len(df.columns)} columns")

    print("Done.")


if __name__ == "__main__":
    main()