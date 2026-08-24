import numpy as np

NEVER_BOOKED = "Never booked"
TRIED_ONCE = "Tried once"
REGULAR = "Regular"

#we have the oldt dbt macros here

def full_name(first_names, last_names):
    return first_names + " " + last_names


#booking count is Series. series are inside the dataframes
def classify_attendance(booking_counts):
    """Turn a column of numbers into a column of words.

    WHY THIS EXISTS
    ---------------
    `dim_attendance` has one row per member with a `total_bookings`
    count. A bare number tells the reader nothing -- is 2 good or bad?
    So we add a label next to it:

        0 bookings   ->  "Never booked"
        1 booking    ->  "Tried once"
        2 or more    ->  "Regular"

    This is the old `classify_attendance` macro:

        CASE
            WHEN count = 0 THEN 'Never booked'
            WHEN count = 1 THEN 'Tried once'
            ELSE 'Regular'
        END

    WHY NOT A NORMAL if / elif / else
    ---------------------------------
    `if` handles ONE value. We have a whole column (a Series).
    Writing `if booking_counts == 0:` raises:

        ValueError: The truth value of a Series is ambiguous

    Python is right to complain. You handed it 15 values, so there is no
    single yes-or-no answer. We need a tool that works on the whole
    column at once. `np.select` is that tool.

    HOW IT WORKS -- STEP 1
    ----------------------
    Comparing a Series to a number does NOT give back one True/False.
    It gives back a whole Series of True/False, one per row. This is
    called a "boolean mask":

        counts    counts == 0    counts == 1
        ------    -----------    -----------
        2         False          False
        1         False          True
        1         False          True
        2         False          False
        1         False          True

    HOW IT WORKS -- STEP 2
    ----------------------
    We line up two lists. The ORDER matters, because they pair up:

        conditions[0]  <->  labels[0]      "is it 0?"  <->  Never booked
        conditions[1]  <->  labels[1]      "is it 1?"  <->  Tried once

    HOW IT WORKS -- STEP 3
    ----------------------
    np.select walks each row, takes the FIRST condition that is True,
    and uses its label. If none are True, it uses `default`:

        row  counts  cond[0]  cond[1]  first True  result
        ---  ------  -------  -------  ----------  --------------------
        0    2       False    False    none        Regular   (default)
        1    1       False    True     cond[1]     Tried once
        2    1       False    True     cond[1]     Tried once
        3    2       False    False    none        Regular   (default)
        4    1       False    True     cond[1]     Tried once

    A column of numbers went in. A column of words came out.

    "First match wins, otherwise default" is exactly what SQL's CASE
    did -- the topmost WHEN is checked first. Same logic, different
    spelling.

    WITH THE CURRENT DATA
    ---------------------
    All 20 bookings belong to members who booked at least once, so
    today this returns only "Regular" (5 members) and "Tried once"
    (10 members). "Never booked" never appears. That is not a bug --
    that branch waits for a member who has never booked anything.

    ABOUT THE RETURN VALUE
    ----------------------
    np.select returns a numpy array, not a Series. That is fine.
    pandas converts it as soon as you assign it to a column:

        df["engagement"] = classify_attendance(df["total_bookings"])
    """
    conditions = [
        booking_counts == 0,
        booking_counts == 1,
    ]
    labels = [
        NEVER_BOOKED,
        TRIED_ONCE,
    ]
    return np.select(conditions, labels, default=REGULAR)#mask