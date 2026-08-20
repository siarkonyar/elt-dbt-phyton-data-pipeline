{% macro classify_attendance(booking_count) %}
    CASE
        WHEN {{ booking_count }} = 0 THEN 'Never booked'
        WHEN {{ booking_count }} = 1 THEN 'Tried once'
        ELSE 'Regular'
    END
{% endmacro %}