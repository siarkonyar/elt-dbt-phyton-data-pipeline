from datetime import datetime, timedelta
from airflow import DAG
from docker.types import Mount

from airflow.operators.python_operator import PythonOperator
from airflow.operators.bash import BashOperator

from airflow.providers.docker.operators.docker import DockerOperator
import os
import subprocess

# Paths on the host machine, injected by docker-compose. The Docker daemon that
# starts the dbt container runs on the host, so it cannot resolve paths that only
# exist inside this container.
HOST_PROJECT_PATH = os.environ["HOST_PROJECT_PATH"]
HOST_HOME = os.environ["HOST_HOME"]

default_args = {
  'owner': 'airflow',
  'depends_on_past': False,
  'email_on_failure': False,
  'email_on_retry': False,
}

def run_elt_script():
  script_path = "/opt/airflow/elt_script/elt_script.py"
  result = subprocess.run(["python", script_path], capture_output=True, text=True)
  if result.returncode != 0:
    raise Exception(f"Script failed with error: {result.stderr}")
  else:
    print(result.stdout)

dag = DAG(
  'elt_and_dbt',
  default_args=default_args,
  description='An ELT workflow with dbt',
  start_date=datetime(2026, 8, 21),
  catchup=False,
)

t1 = PythonOperator(
    task_id='run_elt_script',
    python_callable=run_elt_script,
    dag=dag,
)

t2 = DockerOperator(
    task_id='dbt_run',
    image='ghcr.io/dbt-labs/dbt-postgres:1.4.7',
    command=[
        "run",
        "--profiles-dir",
        "/root",
        "--project-dir",
        "/dbt",
        "--full-refresh"
    ],
    auto_remove=True,
    docker_url="unix://var/run/docker.sock",
    # Compose names its networks "<project>_<network>"; the project defaults to
    # this directory, so elt_network becomes elt_elt_network. Without this the
    # dbt container lands on the default bridge and cannot see destination_postgres.
    network_mode="elt_elt_network",
    mounts=[
        Mount(source=f"{HOST_PROJECT_PATH}/gym", target='/dbt', type='bind'),
        Mount(source=f"{HOST_HOME}/.dbt", target='/root', type='bind'),
    ],
    dag=dag
)

#task 1 should be executed before task 2
t1 >> t2