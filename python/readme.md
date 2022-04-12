# Data Loader, Cloud Function Handlers and Monte-Carlo Forecaster

## Pre-requisites

* Create a GCP deployment using Terraform - see ```../terraform/readme.md```
* It is a good idea to create a Python virtual environment
* Install the dependencies: 
```bash
pip install -r requirements.txt
```
* Set the following environment variables:
```bash
export APIKEY=<value>
export RALLY_PROJECT='<value>'
export RALLY_WORKSPACE='<value>'
export GOOGLE_APPLICATION_CREDENTIALS=~/.gcloud/your-key.json 
export RALLY_SCAN_OFFSET=1
```

## Loading the data

* Ensure the pre-requisites
* Run the loader (replace ```2020-11-01``` with your "from" date):
```bash
    python main.py loader --from-date 2020-11-01
    python main.py loader -f 2020-11-01
```
* The loader will show the progress - currently loading the data
  from 07/01/2020 till 11/29/2020 for a ~150 strong org takes about 
  30 minutes due to how Rally navigates its object graph.
  
## Testing Cloud Function handler for Scheduler

It is still WIP, only printing the Rally items that have changed
within the scan window. One can run it outside of GCP by following these steps:

* Ensure the pre-requisites
* Set ```RALLY_SCAN_OFFSET``` to a different number of days if desired
* Run the scheduler handler:
```bash
python main.py scheduler
```

## Getting Rally paths available in the BQ dataset

To filter data in BQ dataset or run Monte-Carlo forecasts, it is necessary to know which Rally path to apply. 
The script provides a utility mode for getting all paths available in BQ dataset:

```bash
    python main.py list-paths
```

## Running a Monte-Carlo simulation

To run a Monte-Carlo forecast against throughput data in the BQ dataset, use the command below.

For backlog size mode (how long will it take to complete 200 items), use the following syntax:

```bash
    python main.py forecast 200 'Games/Minecraft' -r 2021-03-14 2021-03-27 -c 100
```

For future date mode (how many items will get done by 2021-11-01), use the following syntax:

```bash
    python main.py forecast 2021-11-01 'Games/Minecraft' -r 2021-03-14 2021-03-27 -c 100
```

The above commands run Monte-Carlo simulations consisting of ```100``` experiments. 
If ```-c``` option is not provided, the script uses the default of ```1,000``` experiments. 
The script uses the throughput data collected from the BQ dataset for the provided path 
(the ```Games/Minecraft``` teams) and within the specified data range
(```2021-03-14``` ```2021-03-27```). If the data range is absent, the script uses all throughput data 
available for the path in question. 

Note that the path argument works as a prefix, i.e., the script collects and combines the throughput data
for all projects/teams whose Rally path starts with the path argument. Use with caution.

For the full help on the forecast mode, run ```python main.py forecast --help```

## TODO

* Add a separate table for flow events
* Filter out older Rally items that get in because the re-org recently touched them (e.g. US212917)