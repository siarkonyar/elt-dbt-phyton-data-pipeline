/* name starts with dim because it is not an event. comes from "DIMENSION" */
SELECT
  m.member_id,
  {{full_name('m.first_name', 'm.last_name')}} as member_name,
  COUNT(b.booking_id) AS total_bookings,
  {{ classify_attendance('COUNT(b.booking_id)') }} AS engagement
FROM {{ref('stg_members')}} m

LEFT JOIN {{ref('stg_bookings')}} b
  ON m.member_id = b.member_id

GROUP BY
  m.member_id,
  m.first_name,
  m.last_name