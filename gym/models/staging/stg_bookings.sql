SELECT
    booking_id,
    member_id,
    class_id,
    booking_date,
    status
FROM {{ source('gym', 'bookings') }}