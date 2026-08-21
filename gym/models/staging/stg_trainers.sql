SELECT
    trainer_id,
    first_name,
    last_name,
    specialty,
    email,
    hire_date
FROM {{ source('gym', 'trainers') }}