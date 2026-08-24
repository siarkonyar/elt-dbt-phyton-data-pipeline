from checks import run_all_checks
from db import get_engine, read_table, write_table
from marts import build_dim_attendance, build_fct_bookings
from staging import STAGING_COLUMNS, build_staging

SOURCE_TABLES = list(STAGING_COLUMNS)#returns a list of only the keys, in this case table names

def build_all_staging(engine):
  staged = {}

  for table_name in SOURCE_TABLES:
    raw_df = read_table(engine, table_name)
    staged[table_name] = build_staging(raw_df, table_name)
    print(f"read {table_name}: {len(raw_df)} rows")

  return staged

def main():
  engine = get_engine()

  print("Reading raw tables...")
  staged = build_all_staging(engine)

  print("Building marts...")
  fct_bookings = build_fct_bookings(
    staged["bookings"],
    staged["members"],
    staged["gym_classes"],
    staged["trainers"],
  )
  dim_attendance = build_dim_attendance(staged["members"], staged["bookings"])

  #Nothing has touched the database yet -- everything above happened in
  #memory. We only write once every table has been built successfully,
  #so a crash halfway through cannot leave half-updated tables behind.
  print("Running data-quality checks...")
  run_all_checks(staged, fct_bookings, dim_attendance)

  outputs = {
    "stg_trainers": staged["trainers"],
    "stg_members": staged["members"],
    "stg_gym_classes": staged["gym_classes"],
    "stg_bookings": staged["bookings"],
    "fct_bookings": fct_bookings,
    "dim_attendance": dim_attendance,
  }

  print("Writing tables...")
  for table_name, df in outputs.items():
    row_count = write_table(engine, df, table_name)
    print(f"  wrote {table_name}: {row_count} rows")

  print("Transform finished.")


if __name__ == "__main__":
    main()