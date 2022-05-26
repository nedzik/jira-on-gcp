# Sample Queries

Please, feel free to share your queries. 

## General Flow of JIRA Events

Replace ```<value>``` with the name of your project.

```sql
SELECT * FROM jira.events 
WHERE project = "value" 
ORDER BY issue_id, timestamp, type_id, state_id;
```

## Data for Building Cycle Time Scatter-Plot or Histogram

Add ```STARTS_WITH(path_to_root, "<value>")``` to ```WHERE``` clause to filter.

```sql
CREATE VIEW jira.cycle_times AS
SELECT 
  arrivals.issue_id as issue_id, 
  arrivals.issue_type as issue_type,
  TIMESTAMP_DIFF(departures.departure, arrivals.arrival, DAY) + 1 as cycle_time_in_days, 
  EXTRACT(DATE FROM departures.departure AT TIME ZONE "America/Chicago") as completion_date,
  arrivals.project as project
FROM 
  (
    SELECT issue_id, issue_type, project, MIN(timestamp) as arrival 
    FROM jira.events 
    WHERE UPPER(state_name) = 'IN PROGRESS' AND event_name = 'ARRIVAL' 
    GROUP BY issue_id, issue_type, project
  ) as arrivals,
  (
    SELECT issue_id, MAX(timestamp) as departure 
    FROM jira.events 
        WHERE UPPER(state_name) = 'DONE' AND event_name = 'ARRIVAL' 
    GROUP BY issue_id
  ) as departures
WHERE 
  arrivals.issue_id = departures.issue_id
```

```sql
CREATE VIEW jira.cycle_time_frequencies AS 
SELECT cycle_time_in_days, project, count(*) as frequency FROM 
(
SELECT 
  arrivals.issue_id as issue_id,
  TIMESTAMP_DIFF(departures.departure, arrivals.arrival, DAY) + 1 as cycle_time_in_days, 
  project
FROM
  (
      SELECT issue_id, project, MIN(timestamp) as arrival
      FROM jira.events
      WHERE UPPER(state_name) = 'IN PROGRESS' AND event_name = 'ARRIVAL'
      GROUP BY issue_id, project
  ) as arrivals,
  (
      SELECT issue_id, MAX(timestamp) as departure
      FROM jira.events
      WHERE UPPER(state_name) = 'DONE' AND event_name = 'ARRIVAL'
      GROUP BY issue_id
  ) as departures
WHERE 
  arrivals.issue_id = departures.issue_id
) 
WHERE 
  cycle_time_in_days > 0 
GROUP BY
  cycle_time_in_days, project
```

## Throughput Distribution by Date (for Monte-Carlo Simulations)

Note that it just a sample and requires future work. For example, we need to exclude items that did not
flow through the system (i.e., did not enter ```IN-PROGRESS``` and other pre-```DONE``` states)

Add ```project = "value"``` to ```WHERE``` clause to filter.

```sql
SELECT 
  departure as completion_date,
  count(*) as throughput 
FROM 
  (
    SELECT issue_id, issue_type, project, EXTRACT(DATE from MAX(timestamp) AT TIME ZONE "America/Chicago") as departure 
    FROM jira.events 
    WHERE UPPER(state_name) = 'DONE' AND event_name = 'ARRIVAL' 
    GROUP BY issue_id, issue_type, project 
  ) as departures
GROUP BY
  departure
ORDER BY 
  departure
```

## Report Deviations from the Recommended Flow Patterns

```sql
SELECT 
  issue_id, ARRAY_TO_STRING(state_sequence, '->') as flow, project 
FROM 
  (
    SELECT 
      issue_id, project, ARRAY_AGG(UPPER(state_name) ORDER BY(timestamp)) as state_sequence 
    FROM 
      jira.events 
    WHERE 
      event_name = 'ARRIVAL' 
    GROUP BY 
      issue_id, project 
  )
WHERE
    CONTAINS_SUBSTR(ARRAY_TO_STRING(state_sequence, '->'), 'IN PROGRESS') AND 
    CONTAINS_SUBSTR(ARRAY_TO_STRING(state_sequence, '->'), 'DONE') AND 
    NOT CONTAINS_SUBSTR(ARRAY_TO_STRING(state_sequence, '->'), 'IN PROGRESS->IN REVIEW->READY FOR QA->IN QA->DONE')
ORDER BY 
  project
```

## Cycle Time vs. Estimate

```sql
SELECT 
    cycle_times.issue_id AS issue_id, 
    cycle_times.completion_date AS completion_date,
    cycle_times.issue_type AS issue_type,
    CAST(cycle_time_in_days AS float64) AS cycle_time_in_days, 
    CAST(estimate AS float64) AS estimate_in_story_points, 
    cycle_times.project AS project 
FROM 
    jira.cycle_times AS cycle_times, 
    jira.issues AS issues 
WHERE 
    cycle_times.issue_id = issues.issue_id AND estimate IS NOT NULL AND estimate != 0
```

## Cycle Time Frequencies (To Check the Histogram)

```sql
SELECT 
    COUNT(*) AS frequency, cycle_time_in_days 
FROM 
    jira.cycle_times 
WHERE 
    project = 'your project+' 
GROUP BY 
    cycle_time_in_days 
ORDER BY 
    cycle_time_in_days
```