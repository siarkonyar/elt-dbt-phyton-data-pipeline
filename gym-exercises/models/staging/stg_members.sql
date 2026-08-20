SELECT
    member_id,
    first_name,
    last_name,
    email,
    date_of_birth,
    gender,
    join_date,
    membership_type,
    monthly_fee
FROM {{ source('gym', 'members') }}