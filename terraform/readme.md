# Deploy to GCP

We tested it with a free-tier GCP account. Since the amount of data is not huge,
using a free-tier account should be enough.  

Currently, the script supports one deployment per a GCP project. 

## How to run

Read the pre-requisites in the main ```readme.md```. 
In short, you will need to have a GCP account with a corresponding
service account's JSON key file. You will also need to install Terraform
and obtain a JIRA API key. 

Create an App Engine: ``` gcloud app create [--region=REGION]```

You will need to enable multiple GCP APIs:
```bash
gcloud services enable cloudresourcemanager.googleapis.com
gcloud services enable cloudbilling.googleapis.com
gcloud services enable iam.googleapis.com
gcloud services enable compute.googleapis.com
gcloud services enable serviceusage.googleapis.com
gcloud services enable bigquery.googleapis.com
gcloud services enable bigquerystorage.googleapis.com
gcloud services enable cloudfunctions.googleapis.com
gcloud services enable pubsub.googleapis.com
gcloud services enable cloudbuild.googleapis.com
gcloud services enable cloudscheduler.googleapis.com
```

Init your Terraform project:

```bash
terraform init
```

The actual command to deploy:
 
```bash
terraform apply \
    -var='region=us-central1' \
    -var='region_zone=us-central1-a' \
    -var='project_name=my-project-id' \
    -var='jira_api_token=your-jira-api-key' \
    -var='jira_username=your-jira-username' \
    -var='rally_scan_offset=1' 
```

To destroy the deployment: 

```bash
terraform destroy \
    -var='region=us-central1' \
    -var='region_zone=us-central1-a' \
    -var='project_name=my-project-id' \
    -var='credentials_file_path=~/.gcloud/Terraform.json' \
    -var='rally_api_key=your-rally-api-key' \
    -var='rally_workspace=your-rally-workspace' \
    -var='rally_project=your-root-rally-project' \
    -var='rally_scan_offset=1' \
```

## TODO

* Figure out how to enable APIs (GCP complained about seven or eight). It seems 
that one can enable some of them through Terraform, but not all. 
* Apply Terraform best practices