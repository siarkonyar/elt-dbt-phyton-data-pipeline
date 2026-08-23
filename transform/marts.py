from macros import classify_attendance, full_name

#the exact column lists from the old marts
FCT_BOOKINGS_COLUMNS = [
    "booking_id",
    "booking_date",
    "member_name",
    "status",
    "trainer_name",
    "class_category",
]

DIM_ATTENDANCE_COLUMNS = [
    "member_id",
    "member_name",
    "total_bookings",
    "engagement",
]

def build_fct_bookings(stg_bookings, stg_members, stg_gym_classes, stg_trainers):
  #assign creates the variable name as a new column and returns a new dataframe with that column included
  members = stg_members.assign(
    member_name=full_name(stg_members["first_name"], stg_members["last_name"])
  )[["member_id", "member_name"]]#only get member_id column and newly created member_name column

  trainers = stg_trainers.assign(
    trainer_name=full_name(stg_trainers["first_name"], stg_trainers["last_name"])
  )[["trainer_id", "trainer_name"]]

  classes = stg_gym_classes[["class_id", "trainer_id", "category"]]

  joined = (
    stg_bookings
    .merge(members, on="member_id", how="inner")
    .merge(classes, on="class_id", how="inner")
    .merge(trainers, on="trainer_id", how="inner")
    .rename(columns={"category": "class_category"})
  )

  return joined[FCT_BOOKINGS_COLUMNS].copy()

def build_dim_attendance(stg_members, stg_bookings):
  joined = stg_members.merge(stg_bookings, on="member_id", how="left")

  counts = (
    joined
    .groupby("member_id")["booking_id"]#group by member_id and get booking_ids
    .count()
    .reset_index(name="total_bookings")#create this count into total_bookings column
  )

  dim = stg_members.merge(counts, on="member_id", how="left")

  dim = dim.assign(
    member_name=full_name(dim["first_name"], dim["last_name"]),
    total_bookings=dim["total_bookings"].fillna(0).astype(int),
  )#put these coulms into data frame
  dim = dim.assign(engagement=classify_attendance(dim["total_bookings"]))

  return dim[DIM_ATTENDANCE_COLUMNS].copy()#copy the dataframe but only the specified columns