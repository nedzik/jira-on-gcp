variable "region" {
  default = "us-central1"
}

variable "region_zone" {
  default = "us-central1-a"
}

variable "project_name" {
  description = "The ID of the Google Cloud project"
}

variable "jira_api_token" {
  description = "JIRA API token"
}

variable "jira_username" {
  description = "JIRA username"
}

variable "jira_scan_offset" {
  description = "Offset (in days) that scheduler will use to scan for updated stories/defects"
  default = "1"
}
