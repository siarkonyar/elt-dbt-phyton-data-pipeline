{% macro full_name(first_name_column, last_name_column) %}
    {{ first_name_column }} || ' ' || {{ last_name_column }}
{% endmacro %}
