/* the name starts with fct because it is an event. i comes from "FACTS" */
SELECT
  b.booking_id,
  b.booking_date,
  {{ full_name('m.first_name', 'm.last_name') }} as member_name,
  b.status,
  {{ full_name('t.first_name', 't.last_name') }} as trainer_name,
  c.category as class_category

FROM {{ ref('stg_bookings') }} b

INNER JOIN {{ref('stg_members')}} m
  ON b.member_id = m.member_id
INNER JOIN {{ref('stg_gym_classes')}} c
  ON b.class_id = c.class_id
INNER JOIN {{ref('stg_trainers')}} t
  ON c.trainer_id = t.trainer_id