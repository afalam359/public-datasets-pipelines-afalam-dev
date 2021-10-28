# Copyright 2021 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


from airflow import DAG
from airflow.contrib.operators import gcs_to_bq, kubernetes_pod_operator

default_args = {
    "owner": "Google",
    "depends_on_past": False,
    "start_date": "2021-04-01",
}


with DAG(
    dag_id="covid19_italy.data_by_province",
    default_args=default_args,
    max_active_runs=1,
    schedule_interval="@daily",
    catchup=False,
    default_view="graph",
) as dag:

    # Run CSV transform within kubernetes pod
    data_by_province_transform_csv = kubernetes_pod_operator.KubernetesPodOperator(
        task_id="data_by_province_transform_csv",
        startup_timeout_seconds=600,
        name="covid19_italy_data_by_province",
        namespace="default",
        affinity={
            "nodeAffinity": {
                "requiredDuringSchedulingIgnoredDuringExecution": {
                    "nodeSelectorTerms": [
                        {
                            "matchExpressions": [
                                {
                                    "key": "cloud.google.com/gke-nodepool",
                                    "operator": "In",
                                    "values": ["pool-e2-standard-4"],
                                }
                            ]
                        }
                    ]
                }
            }
        },
        image_pull_policy="Always",
        image="{{ var.json.covid19_italy.container_registry.run_csv_transform_kub }}",
        env_vars={
            "SOURCE_URL": "https://raw.githubusercontent.com/pcm-dpc/COVID-19/master/dati-province/dpc-covid19-ita-province.csv",
            "SOURCE_FILE": "files/data.csv",
            "TARGET_FILE": "files/data_output.csv",
            "TARGET_GCS_BUCKET": "{{ var.value.composer_bucket }}",
            "TARGET_GCS_PATH": "data/covid19_italy/data_by_province/data_output.csv",
            "CSV_HEADERS": '["date","country","region_code","region_name","province_code","province_name","province_abbreviation","latitude","longitude","location_geom","confirmed_cases","note"]',
            "RENAME_MAPPINGS": '{"data": "date","stato": "country","codice_regione": "region_code","denominazione_regione": "region_name","lat": "latitude","long": "longitude","codice_provincia": "province_code","denominazione_provincia": "province_name","sigla_provincia": "province_abbreviation","totale_casi": "confirmed_cases","note": "note"}',
            "PIPELINE_NAME": "data_by_province",
        },
        resources={"request_memory": "4G", "request_cpu": "1"},
    )

    # Task to load CSV data to a BigQuery table
    load_data_by_province_to_bq = gcs_to_bq.GoogleCloudStorageToBigQueryOperator(
        task_id="load_data_by_province_to_bq",
        bucket="{{ var.value.composer_bucket }}",
        source_objects=["data/covid19_italy/data_by_province/data_output.csv"],
        source_format="CSV",
        destination_project_dataset_table="covid19_italy.data_by_province",
        skip_leading_rows=1,
        write_disposition="WRITE_TRUNCATE",
        schema_fields=[
            {"name": "date", "type": "TIMESTAMP", "mode": "NULLABLE"},
            {"name": "country", "type": "STRING", "mode": "NULLABLE"},
            {"name": "region_code", "type": "STRING", "mode": "NULLABLE"},
            {"name": "name", "type": "STRING", "mode": "NULLABLE"},
            {"name": "province_code", "type": "STRING", "mode": "NULLABLE"},
            {"name": "province_name", "type": "STRING", "mode": "NULLABLE"},
            {"name": "province_abbreviation", "type": "STRING", "mode": "NULLABLE"},
            {"name": "latitude", "type": "FLOAT", "mode": "NULLABLE"},
            {"name": "longitude", "type": "FLOAT", "mode": "NULLABLE"},
            {"name": "location_geom", "type": "GEOGRAPHY", "mode": "NULLABLE"},
            {"name": "confirmed_cases", "type": "INTEGER", "mode": "NULLABLE"},
            {"name": "note", "type": "STRING", "mode": "NULLABLE"},
        ],
    )

    data_by_province_transform_csv >> load_data_by_province_to_bq