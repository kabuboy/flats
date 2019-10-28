from airflow import DAG
from airflow.operators.python_operator import PythonOperator
from datetime import datetime, timedelta

from common import DATA_TYPES
from pipelines.concat_task import concat_data_task
from pipelines.scrape_task import scrape_task


default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'start_date': datetime(2019, 10, 28),
    'email': ['szczepanik.antoni@gmail.com'],
    'email_on_failure': True,
    'email_on_retry': False,
    'retries': 2,
    'retry_delay': timedelta(minutes=5),
}

dag = DAG('flats_data',
          default_args=default_args,
          schedule_interval=None)

for data_type in DATA_TYPES:
    scrape = PythonOperator(
        task_id=f'scrape_{data_type}',
        python_callable=scrape_task,
        op_kwargs={'data_type': data_type},
        dag=dag)

    concat = PythonOperator(
        task_id=f'concat_{data_type}',
        python_callable=concat_data_task,
        op_kwargs={'data_type': data_type},
        dag=dag)



    scrape >> concat