from macros import NEVER_BOOKED, REGULAR, TRIED_ONCE

BOOKING_STATUSES = ["Attended", "No-show", "Cancelled"]
ENGAGEMENT_LABELS = [NEVER_BOOKED, TRIED_ONCE, REGULAR]

class DataQualityError(Exception):
    """Raised when a data-quality check fails."""

#this function is to check if any row null in selected columns
def check_not_null(df, table_name, columns):
  for column in columns:
    bad_rows = df[df[column].isna()]#mask for filtering, filters NaN values in that colum
    if not bad_rows.empty:
      raise DataQualityError(
        f"not_null failed on {table_name}.{column}: "
        f"{len(bad_rows)} empty value(s)\n{bad_rows.head(10)}"
      )

#same logic as check_not_null but checks unique constraints
def check_unique(df, table_name, column):
  duplicates = df[df[column].duplicated(keep=False)]
  if not duplicates.empty:
    raise DataQualityError(
      f"unique failed on {table_name}.{column}: "
      f"{len(duplicates)} duplicated row(s)\n{duplicates.head(10)}"
    )

def check_relationship(child_df, child_column, parent_df, parent_column, label):
  orphans = child_df[~child_df[child_column].isin(parent_df[parent_column])]
  if not orphans.empty:
    raise DataQualityError(
      f"relationships failed on {label}: "
      f"{len(orphans)} row(s) point at a missing parent\n"
      f"{orphans.head(10)}"
    )

def check_accepted_values(df, table_name, column, allowed):
  bad_rows = df[~df[column].isin(allowed)]
  if not bad_rows.empty:
    found = sorted(bad_rows[column].unique())
    raise DataQualityError(
      f"accepted_values failed on {table_name}.{column}: "
      f"found {found}, allowed {allowed}"
    )


def check_same_row_count(df, expected_df, label):
  if len(df) != len(expected_df):
    raise DataQualityError(
      f"row count failed on {label}: "
      f"got {len(df)} rows, expected {len(expected_df)}"
    )

def run_all_checks(staged, fct_bookings, dim_attendance):
    stg_trainers = staged["trainers"]
    stg_members = staged["members"]
    stg_gym_classes = staged["gym_classes"]
    stg_bookings = staged["bookings"]

    # --- primary keys: present and unique -------------------------------
    for df, table_name, key in [
        (stg_trainers, "stg_trainers", "trainer_id"),
        (stg_members, "stg_members", "member_id"),
        (stg_gym_classes, "stg_gym_classes", "class_id"),
        (stg_bookings, "stg_bookings", "booking_id"),
    ]:
        check_not_null(df, table_name, [key])
        check_unique(df, table_name, key)

    # --- foreign keys: present, but NOT unique ---------------------------
    # A member books many classes, so member_id repeats in bookings.
    # Putting a `unique` test on a foreign key is a classic mistake --
    # it would fail on perfectly correct data.
    check_not_null(stg_bookings, "stg_bookings", ["member_id", "class_id"])
    check_not_null(stg_gym_classes, "stg_gym_classes", ["trainer_id"])

    # --- foreign keys point at something real ---------------------------
    check_relationship(
        stg_bookings, "member_id", stg_members, "member_id",
        "stg_bookings.member_id -> stg_members.member_id",
    )
    check_relationship(
        stg_bookings, "class_id", stg_gym_classes, "class_id",
        "stg_bookings.class_id -> stg_gym_classes.class_id",
    )
    check_relationship(
        stg_gym_classes, "trainer_id", stg_trainers, "trainer_id",
        "stg_gym_classes.trainer_id -> stg_trainers.trainer_id",
    )

    # --- only the values we expect --------------------------------------
    check_accepted_values(stg_bookings, "stg_bookings", "status", BOOKING_STATUSES)

    # --- the marts came out the right shape -----------------------------
    check_same_row_count(fct_bookings, stg_bookings, "fct_bookings")
    check_same_row_count(dim_attendance, stg_members, "dim_attendance")

    check_unique(fct_bookings, "fct_bookings", "booking_id")
    check_unique(dim_attendance, "dim_attendance", "member_id")

    # A gap here means a join silently failed to find a match.
    check_not_null(
        fct_bookings, "fct_bookings",
        ["member_name", "trainer_name", "class_category"],
    )
    check_not_null(dim_attendance, "dim_attendance", ["member_name", "total_bookings"])
    check_accepted_values(
        dim_attendance, "dim_attendance", "engagement", ENGAGEMENT_LABELS,
    )

    print("all data-quality checks passed")