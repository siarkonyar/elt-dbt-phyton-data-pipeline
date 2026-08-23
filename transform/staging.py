STAGING_COLUMNS = {
    "trainers": [
        "trainer_id", "first_name", "last_name",
        "specialty", "email", "hire_date",
    ],
    "members": [
        "member_id", "first_name", "last_name", "email",
        "date_of_birth", "gender", "join_date",
        "membership_type", "monthly_fee",
    ],
    "gym_classes": [
        "class_id", "class_name", "trainer_id",
        "category", "duration_mins", "max_capacity",
    ],
    "bookings": [
        "booking_id", "member_id", "class_id",
        "booking_date", "status",
    ],
}

#this function is to get the staging tables
def build_staging(raw_df, table_name):
    columns = STAGING_COLUMNS[table_name]
    return raw_df[columns].copy()