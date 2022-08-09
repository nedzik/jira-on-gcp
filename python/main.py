#!/usr/bin/env python

import datetime
import functools
import operator
import os
import sys
from time import sleep

import click
import pytz
from atlassian import Jira
from google.cloud import bigquery
from requests.exceptions import RequestException

UTC = pytz.UTC
EVENTS_TABLE = 'jira.events'
ISSUES_TABLE = 'jira.issues'
TIMESTAMP_FORMAT = '%Y-%m-%dT%H:%M:%S.%f%z'
EVENT_TYPE_ID_MAP = {
    'DEPARTURE': 1,
    'OTHER': 2,
    'ARRIVAL': 3
}


# Helpers - JIRA
def initialize_jira():
    print(f' - initializing JIRA API ...', file=sys.stderr)
    url = os.getenv('JIRA_URL', 'https://shiftkey.atlassian.net')
    username = os.getenv('JIRA_USERNAME')
    api_access_token = os.getenv('JIRA_API_TOKEN')
    return Jira(url=url, username=username, password=api_access_token, cloud=True)


def retry(func):
    def wrapper(*args, **kwargs):
        for count in range(5):
            try:
                return func(*args, **kwargs)
            except RequestException as re:
                print(f' - caught an exception {type(re)}', file=sys.stderr)
                if count == 4:
                    raise
                else:
                    sleep(5)
                    print(f' - retrying ...', file=sys.stderr)

    return wrapper


@retry
def get_issue_changelog(jira, issue):
    return jira.get_issue_changelog(issue['key'])


@retry
def get_issues(jira, from_date, start_at, jira_filter=None):
    jql = f"""updated >= {from_date} and type in (bug, story, 'tech task', 'tech debt')"""
    jql = f"""{jql} and {jira_filter}""" if jira_filter else jql
    print(f"Using query '{jql}', from position {start_at} ...", file=sys.stderr)
    found = jira.jql(jql=jql, limit=100, start=start_at)
    return found


def get_issues_from_jira(jira, from_date, jira_filter=None):
    start_at = 0
    while True:
        found = get_issues(jira, from_date, start_at, jira_filter)
        total = found.get('total', 0)
        print(f"Got {len(found['issues'])} out of {total} issues. Processing ...", file=sys.stderr)
        for issue in found['issues']: yield issue
        if start_at + len(found['issues']) >= total: break
        start_at += len(found['issues'])


# Helpers - JIRA to BQ conversion
def to_bq_schedule_event_row(issue_id, issue_type, event_type, state_id, state_name, timestamp, project):
    utc_timestamp = datetime.datetime.utcfromtimestamp(float(timestamp.strftime("%s")))
    return {
        u'issue_id': issue_id,
        u'issue_type': issue_type,
        u'state_id': state_id,
        u'state_name': state_name,
        u'event_id': EVENT_TYPE_ID_MAP.get(event_type, 99),
        u'event_name': event_type,
        u'timestamp': datetime.datetime.strftime(utc_timestamp, '%Y-%m-%d %H:%M:%S.%f'),
        u'project': project
    }


def to_bq_item_row(issue_id, estimate):
    return {
        u'issue_id': issue_id,
        u'estimate': estimate
    }


def extract_bq_rows_from_change_log(issue, history_entry, status_change_entry):
    issue_id = issue['key']
    issue_type = issue['fields']['issuetype']['name']
    project = issue['fields']['project']['name']
    timestamp = datetime.datetime.strptime(history_entry['created'], TIMESTAMP_FORMAT)
    return [
        to_bq_schedule_event_row(
            issue_id, issue_type, 'DEPARTURE', int(status_change_entry['from']), status_change_entry['fromString'],
            timestamp, project
        ),
        to_bq_schedule_event_row(
            issue_id, issue_type, 'ARRIVAL', int(status_change_entry['to']), status_change_entry['toString'],
            timestamp, project
        )
    ]


def extract_bq_rows_from_issue(jira, issue):
    return sorted(functools.reduce(operator.iconcat, [
        extract_bq_rows_from_change_log(issue, h, i) for h in get_issue_changelog(jira, issue)['histories']
        for i in h['items'] if i['field'] == 'status'
    ], []), key=lambda x: x['timestamp'])


# Helpers - BQ operations
def events_table_is_empty(client, table):
    print(f' - checking there is no data in {table} ...', file=sys.stderr)
    query = f'''SELECT count(*) as row_count from {table}'''
    return next((x.row_count for x in client.query(query)), -1) == 0


def get_latest_timestamps_from_bq(bq_client, issues):
    query = f'''
            SELECT issue_id, max(timestamp) AS timestamp FROM {EVENTS_TABLE}
            WHERE issue_id IN UNNEST(@CANDIDATES)
            GROUP BY issue_id
        '''
    job_config = bigquery.QueryJobConfig()
    # noinspection PyTypeChecker
    job_config.query_parameters = [
        bigquery.ArrayQueryParameter('CANDIDATES', 'STRING', [x['key'] for x in issues])
    ]
    return dict([(x.issue_id, x.timestamp) for x in bq_client.query(query, job_config=job_config)])


def insert_rows_into_bq(bq_client, bq_table, bq_rows):
    batch_size = 10000
    print(f' - inserting {len(bq_rows)} row(s) into {bq_table} ...', file=sys.stderr)
    for index in range(0, len(bq_rows), batch_size):
        batch_rows = bq_rows[index:index + batch_size]
        print(f' --- inserting next {len(batch_rows)} rows starting from offset {index} ...', file=sys.stderr)
        errors = bq_client.insert_rows_json(bq_table, batch_rows, row_ids=[None] * len(batch_rows))
        if errors:
            print(f' --- aborting due to the errors encountered while inserting rows:', file=sys.stderr)
            for x in errors: print(f' ----- {x}', file=sys.stderr)
            return
        print(f' --- inserted {len(batch_rows)} row(s) into {bq_table}.', file=sys.stderr)
    print(f' - done inserting {len(bq_rows)} row(s) into {bq_table}.', file=sys.stderr)


def to_datetime_utc(timestamp):
    return datetime.datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S.%f').replace(tzinfo=UTC)


# Helpers - Scheduler Logic
def extract_new_bq_rows_from_candidates(jira, candidate_issues, timestamps_by_id):
    bq_rows = []
    for candidate_issue in candidate_issues:
        issue_id = candidate_issue[u'key']
        issue_last_updated = datetime.datetime.strptime(candidate_issue['fields']['updated'], TIMESTAMP_FORMAT)
        issue_last_updated_utc = datetime.datetime.utcfromtimestamp(float(issue_last_updated.strftime("%s")))
        print(f' - considering JIRA item {issue_id}, last updated in JIRA on {issue_last_updated_utc} ...',
              file=sys.stderr)
        bq_last_updated = timestamps_by_id.get(issue_id, None)
        print(f' - the latest event in BQ for {issue_id} was on {bq_last_updated} ...', file=sys.stderr)
        if not bq_last_updated or bq_last_updated < issue_last_updated:
            message = 'a brand new item' if not bq_last_updated else f'the item has new events after {bq_last_updated}'
            print(f''' --- {message}. Processing ...''', file=sys.stderr)
            bq_rows += extract_new_bq_rows_from_candidate(jira, candidate_issue, bq_last_updated, issue_last_updated)
        else:
            print(f' --- up-to-date in {EVENTS_TABLE} (last time updated on {bq_last_updated}. Skipping ...',
                  file=sys.stderr)
    return bq_rows


def extract_new_bq_rows_from_candidate(jira, candidate_issue, bq_last_updated, issue_last_updated):
    bq_rows_from_item = extract_bq_rows_from_issue(jira, candidate_issue)
    print(f' --- all items ({len(bq_rows_from_item)}) ...', file=sys.stderr)
    for x in bq_rows_from_item: print(x, file=sys.stderr)
    selected_bq_rows_from_item = [
        x for x in bq_rows_from_item if to_datetime_utc(x[u'timestamp']) > bq_last_updated
    ] if bq_last_updated and bq_last_updated < issue_last_updated else bq_rows_from_item
    print(f' --- selected items ({len(selected_bq_rows_from_item)})...', file=sys.stderr)
    for x in selected_bq_rows_from_item: print(x, file=sys.stderr)
    return selected_bq_rows_from_item


def get_bq_rows_from_jira(jira, from_date):
    return functools.reduce(
        operator.iconcat, [j for j in [
            extract_bq_rows_from_issue(jira, i) for i in get_issues_from_jira(jira, f'{from_date:%Y-%m-%d}')
        ]], []
    )


def create_bq_client():
    # noinspection PyTypeChecker
    return bigquery.Client(project=os.getenv('GCP_PROJECT'))


# Cloud Function handler for scanning for recently modified stories/defects
# Takes the scan offset from JIRA_SCAN_OFFSET environment variable
# For each found story/defect, issues a PubSub message that updater Cloud Function will process
# noinspection PyUnusedLocal
def scheduler(event, context):
    print(' - starting the scheduler ...', file=sys.stderr)
    bq_client = create_bq_client()
    if events_table_is_empty(bq_client, EVENTS_TABLE):
        print(f' --- {EVENTS_TABLE} is still empty. Please perform the initial data load. Exiting ...', file=sys.stderr)
        return
    jira = initialize_jira()
    jira_scan_offset = int(os.getenv('JIRA_SCAN_OFFSET', '1'))
    print(' - scanning for candidates with new events ...', file=sys.stderr)
    from_date = (datetime.datetime.now() - datetime.timedelta(days=jira_scan_offset))
    candidate_issues = [x for x in get_issues_from_jira(jira, f'{from_date:%Y-%m-%d}')]
    if candidate_issues:
        print(f' - found {len(candidate_issues)} candidates. Retrieving their info from BQ ...', file=sys.stderr)
        timestamps_by_id = get_latest_timestamps_from_bq(bq_client, candidate_issues)
        bq_rows = extract_new_bq_rows_from_candidates(jira, candidate_issues, timestamps_by_id)
        insert_rows_into_bq(bq_client, EVENTS_TABLE, bq_rows)
    print(f'Done.', file=sys.stderr)


# Bulk loader of JIRA events into BQ. Scans for all stories/defects that have been updates since from_date
@click.command()
@click.option('-f', '--from-date', type=click.DateTime(formats=['%Y-%m-%d']), default='2021-10-01')
def load_events(from_date):
    print(f' - starting the schedule event loader ...', file=sys.stderr)
    print(f' --- will attempt to load events starting from {from_date:%Y-%m-%d}', file=sys.stderr)
    bq_client = create_bq_client()
    if not events_table_is_empty(bq_client, EVENTS_TABLE):
        print(f' --- {EVENTS_TABLE} is not empty or its status is unknown. Exiting ...', file=sys.stderr)
        return
    jira = initialize_jira()
    insert_rows_into_bq(bq_client, EVENTS_TABLE, get_bq_rows_from_jira(jira, from_date))
    print('Done.', file=sys.stderr)


def extract_bq_item_rows_from_issues(issues):
    return [to_bq_item_row(x['key'], x['fields']['customfield_11020']) for x in issues]


@click.command()
@click.option('-f', '--from-date', type=click.DateTime(formats=['%Y-%m-%d']), default='2021-10-01')
@click.option('-o', '--output', type=str, default='bq')
@click.option('-j', '--jira-filter', type=str, default=None)
def load_issues(from_date, output, jira_filter):
    print(f' - starting the schedule event loader ...', file=sys.stderr)
    print(f' --- will attempt to load issues starting from {from_date:%Y-%m-%d}', file=sys.stderr)
    bq_client = create_bq_client()
    if output == 'bq' and not events_table_is_empty(bq_client, ISSUES_TABLE):
        print(f' --- {ISSUES_TABLE} is not empty or its status is unknown. Exiting ...', file=sys.stderr)
        return
    jira = initialize_jira()
    issues = get_issues_from_jira(jira, f'{from_date:%Y-%m-%d}', jira_filter)
    if output == 'bq':
        bq_rows = extract_bq_item_rows_from_issues(issues)
        insert_rows_into_bq(bq_client, ISSUES_TABLE, bq_rows)
    else:
        print('ID,estimate,value')
        for x in issues:
            value = x['fields']['customfield_11121']['value'] if 'customfield_11121' in x['fields'] else 'None'
            print(f'''{x['key']},{x['fields']['customfield_11020']},{value}''')
    print('Done.', file=sys.stderr)


@click.group()
def cli():
    # A groping function for the click package
    pass


@click.command()
def sync():
    scheduler({}, {})


FORECAST_HELP = 'runs a simulation with backlog size or future date goal using throughput data from the BQ dataset'
DATE_RANGE_HELP = 'use throughput data from within the date range'

# @click.command(help=FORECAST_HELP)
# @click.argument('goal')
# @click.argument('path-to-root')
# @click.option('-r', '--sample-date-range', nargs=2, type=click.DateTime(formats=['%Y-%m-%d']), help=DATE_RANGE_HELP)
# @click.option('-c', '--experiment-count', 'count', default=1000, type=int, show_default=True)
# # TODO: add support for options: a) weekday-to-weekday simulation, b) include weekends
# def forecast(goal, path_to_root, sample_date_range, count):
#     print_information_header(goal, count, path_to_root, sample_date_range)
#     bq_throughput_data = get_throughput_data_from_bq(bigquery.Client(), path_to_root, sample_date_range)
#     data = prepare_throughput_data(bq_throughput_data, sample_date_range)
#     run_simulation = get_simulation(goal)
#     results = [run_simulation(data, goal) for _ in range(count)]
#     print_simulation_results(results, goal)


if __name__ == '__main__':
    cli.add_command(load_events)
    cli.add_command(sync)
    cli.add_command(load_issues)
    # cli.add_command(forecast)
    cli()
