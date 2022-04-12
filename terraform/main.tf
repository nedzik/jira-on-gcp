provider "google" {
  region      = var.region
  project     = var.project_name
#  credentials = file(var.credentials_file_path)
  zone        = var.region_zone
}

# Generate a random vm name
resource "random_string" "seed" {
  length  = 6
  upper   = false
  number  = false
  lower   = true
  special = false
}

locals {
  topic-name = "${random_string.seed.result}-rally-scheduler-topc"
  job-name = "${random_string.seed.result}-rally-scheduler-job"
  bucket-name = "${random_string.seed.result}-rally-on-gcp-deployment"
}

resource "google_pubsub_topic" "topic" {
  name = local.topic-name
}

resource "google_cloud_scheduler_job" "job" {
  name        = local.job-name
  description = "a job to kick off the JIRA updater"
  schedule    = "1 */4 * * *"

  pubsub_target {
    topic_name = google_pubsub_topic.topic.id
    data       = base64encode("test")
  }
}

resource "google_storage_bucket" "deployment_bucket" {
  name     = local.bucket-name
  location = var.region
}

data "archive_file" "src" {
  type        = "zip"
  source_dir  = "${path.root}/../python"
  output_path = "/tmp/function.zip"
}

resource "google_storage_bucket_object" "archive" {
  name   = "${data.archive_file.src.output_md5}.zip"
  bucket = google_storage_bucket.deployment_bucket.name
  source = "/tmp/function.zip"
}

resource "google_cloudfunctions_function" "scheduler_function" {
  name        = "rally-scheduler-function"
  description = "A Cloud Function that is triggered by a Cloud Schedule."
  runtime     = "python37"

  environment_variables = {
    JIRA_API_TOKEN   = var.jira_api_token
    JIRA_USERNAME    = var.jira_username
    JIRA_SCAN_OFFSET = var.jira_scan_offset
  }

  available_memory_mb   = 256
  source_archive_bucket = google_storage_bucket.deployment_bucket.name
  source_archive_object = google_storage_bucket_object.archive.name
  timeout               = 500
  entry_point           = "scheduler"

  event_trigger {
    event_type = "google.pubsub.topic.publish"
    resource = google_pubsub_topic.topic.name
  }
}

resource "google_bigquery_dataset" "jira" {
  dataset_id                  = "jira"
  friendly_name               = "jira"
  description                 = "Dataset for JIRA statistics"
}

resource "google_bigquery_table" "events" {
  dataset_id = google_bigquery_dataset.jira.dataset_id
  table_id   = "events"
  schema = <<EOF
[
  {
    "name": "issue_id",
    "type": "STRING",
    "mode": "REQUIRED",
    "description": "JIRA Issue ID"
  },
  {
    "name": "issue_type",
    "type": "STRING",
    "mode": "REQUIRED",
    "description": "JIRA Issue Type (Bug, Story, Tech Task)"
  },
  {
    "name": "state_id",
    "type": "INTEGER",
    "mode": "REQUIRED",
    "description": "Scheduled State"
  },
  {
    "name": "state_name",
    "type": "STRING",
    "mode": "REQUIRED",
    "description": "Scheduled State"
  },
  {
    "name": "event_id",
    "type": "INTEGER",
    "mode": "REQUIRED",
    "description": "ARRIVAL or DEPARTURE"
  },
  {
    "name": "event_name",
    "type": "STRING",
    "mode": "REQUIRED",
    "description": "ARRIVAL or DEPARTURE"
  },
  {
    "name": "timestamp",
    "type": "TIMESTAMP",
    "mode": "REQUIRED",
    "description": "Event's Timestamp"
  },
  {
    "name": "project",
    "type": "STRING",
    "mode": "REQUIRED",
    "description": "Path to the Root Project"
  }
]
EOF
}

resource "google_bigquery_table" "issues" {
  dataset_id = google_bigquery_dataset.jira.dataset_id
  table_id   = "issues"
  schema = <<EOF
[
  {
    "name": "issue_id",
    "type": "STRING",
    "mode": "REQUIRED",
    "description": "Rally Object's Formatted ID"
  },
  {
    "name": "estimate",
    "type": "FLOAT64",
    "mode": "NULLABLE",
    "description": "Planning Estimate in Story Points"
  }
]
EOF
}

