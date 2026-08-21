SELECT
    class_id,
    class_name,
    trainer_id,
    category,
    duration_mins,
    max_capacity
FROM {{ source('gym', 'gym_classes') }}