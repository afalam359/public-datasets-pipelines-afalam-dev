/**
 * Copyright 2021 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */


resource "google_bigquery_dataset" "america_health_rankings" {
  dataset_id  = "america_health_rankings"
  project     = var.project_id
  description = "America Health Rankings"
}

output "bigquery_dataset-america_health_rankings-dataset_id" {
  value = google_bigquery_dataset.america_health_rankings.dataset_id
}

resource "google_storage_bucket" "america-health-rankings" {
  name                        = "${var.bucket_name_prefix}-america-health-rankings"
  force_destroy               = true
  location                    = "US"
  uniform_bucket_level_access = true
}

output "storage_bucket-america-health-rankings-name" {
  value = google_storage_bucket.america-health-rankings.name
}