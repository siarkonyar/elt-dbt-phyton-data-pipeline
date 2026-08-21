# Use the official Airflow image as the base.
# Pinned on purpose: "latest" now resolves to Airflow 3, which removed
# `airflow db init` and the `webserver` command this project relies on.
FROM apache/airflow:2.7.2

# Install the Docker provider for Airflow
RUN pip install --no-cache-dir \
      "apache-airflow-providers-docker==3.7.5" \
      --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-2.7.2/constraints-3.8.txt"