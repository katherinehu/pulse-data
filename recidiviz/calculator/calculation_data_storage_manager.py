# Recidiviz - a data platform for criminal justice reform
# Copyright (C) 2020 Recidiviz, Inc.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
# =============================================================================
"""Manages the storage of data produced by calculations.

Run locally with the following command:

    python -m recidiviz.calculator.calculation_data_storage_manager \
        --project_id [PROJECT_ID]
        --function_to_execute [cold_storage_export, update_schemas]

"""
import argparse
import logging
import sys
from http import HTTPStatus
from typing import Tuple, List

import flask
from google.cloud.bigquery import WriteDisposition

from recidiviz.big_query.big_query_client import BigQueryClientImpl
from recidiviz.calculator.calculation_data_storage_config import DATAFLOW_METRICS_COLD_STORAGE_DATASET, \
    MAX_DAYS_IN_DATAFLOW_METRICS_TABLE, DATAFLOW_METRICS_TO_TABLES
from recidiviz.calculator.query.state.dataset_config import DATAFLOW_METRICS_DATASET, REFERENCE_VIEWS_DATASET
from recidiviz.utils.auth import authenticate_request
from recidiviz.utils.environment import GCP_PROJECT_STAGING, GCP_PROJECT_PRODUCTION
from recidiviz.utils.metadata import local_project_id_override

calculation_data_storage_manager_blueprint = flask.Blueprint('calculation_data_storage_manager', __name__)


@calculation_data_storage_manager_blueprint.route('/prune_old_dataflow_data')
@authenticate_request
def prune_old_dataflow_data()-> Tuple[str, HTTPStatus]:
    """Calls the move_old_dataflow_metrics_to_cold_storage function."""
    move_old_dataflow_metrics_to_cold_storage()

    return '', HTTPStatus.OK


def move_old_dataflow_metrics_to_cold_storage() -> None:
    """Moves old output in Dataflow metrics tables to tables in a cold storage dataset. We only keep the
    MAX_DAYS_IN_DATAFLOW_METRICS_TABLE days worth of data in a Dataflow metric table at once. All other
    output is moved to cold storage.
    """
    bq_client = BigQueryClientImpl()
    dataflow_metrics_dataset = DATAFLOW_METRICS_DATASET
    cold_storage_dataset = DATAFLOW_METRICS_COLD_STORAGE_DATASET
    dataflow_metrics_tables = bq_client.list_tables(dataflow_metrics_dataset)

    for table_ref in dataflow_metrics_tables:
        table_id = table_ref.table_id

        source_data_join_clause = """LEFT JOIN
                          (SELECT DISTINCT job_id AS keep_job_id FROM
                          `{project_id}.{reference_views_dataset}.most_recent_job_id_by_metric_and_state_code_materialized`)
                        ON job_id = keep_job_id
                        LEFT JOIN 
                          (SELECT DISTINCT created_on AS keep_created_date FROM
                          `{project_id}.{dataflow_metrics_dataset}.{table_id}`
                          ORDER BY created_on DESC
                          LIMIT {day_count_limit})
                        ON created_on = keep_created_date
                        """.format(
                            project_id=table_ref.project,
                            dataflow_metrics_dataset=table_ref.dataset_id,
                            reference_views_dataset=REFERENCE_VIEWS_DATASET,
                            table_id=table_id,
                            day_count_limit=MAX_DAYS_IN_DATAFLOW_METRICS_TABLE
                        )

        # Exclude these columns leftover from the exclusion join from being added to the metric tables in cold storage
        columns_to_exclude_from_transfer = ['keep_job_id', 'keep_created_date']

        # This filter will return the rows that should be moved to cold storage
        insert_filter_clause = "WHERE keep_job_id IS NULL AND keep_created_date IS NULL"

        # Query for rows to be moved to the cold storage table
        insert_query = """
            SELECT * EXCEPT({columns_to_exclude}) FROM
            `{project_id}.{dataflow_metrics_dataset}.{table_id}`
            {source_data_join_clause}
            {insert_filter_clause}
        """.format(
            columns_to_exclude=', '.join(columns_to_exclude_from_transfer),
            project_id=table_ref.project,
            dataflow_metrics_dataset=table_ref.dataset_id,
            table_id=table_id,
            source_data_join_clause=source_data_join_clause,
            insert_filter_clause=insert_filter_clause
        )

        # Move data from the Dataflow metrics dataset into the cold storage table, creating the table if necessary
        insert_job = bq_client.insert_into_table_from_query(
            destination_dataset_id=cold_storage_dataset,
            destination_table_id=table_id,
            query=insert_query,
            allow_field_additions=True,
            write_disposition=WriteDisposition.WRITE_APPEND)

        # Wait for the insert job to complete before running the replace job
        insert_job.result()

        # This will return the rows that were not moved to cold storage and should remain in the table
        replace_query = """
            SELECT * EXCEPT({columns_to_exclude}) FROM
            `{project_id}.{dataflow_metrics_dataset}.{table_id}`
            {source_data_join_clause}
            WHERE keep_job_id IS NOT NULL OR keep_created_date IS NOT NULL
        """.format(
            columns_to_exclude=', '.join(columns_to_exclude_from_transfer),
            project_id=table_ref.project,
            dataflow_metrics_dataset=table_ref.dataset_id,
            table_id=table_id,
            source_data_join_clause=source_data_join_clause,
        )

        # Replace the Dataflow table with only the rows that should remain
        replace_job = bq_client.create_table_from_query_async(
            dataflow_metrics_dataset, table_ref.table_id, query=replace_query, overwrite=True)

        # Wait for the replace job to complete before moving on
        replace_job.result()


def update_dataflow_metric_tables_schemas() -> None:
    """For each table that stores Dataflow metric output, ensures that all attributes on the corresponding metric are
    present in the table in BigQuery."""
    bq_client = BigQueryClientImpl()
    dataflow_metrics_dataset_id = DATAFLOW_METRICS_DATASET
    dataflow_metrics_dataset_ref = bq_client.dataset_ref_for_id(dataflow_metrics_dataset_id)

    bq_client.create_dataset_if_necessary(dataflow_metrics_dataset_ref)

    for metric_class, table_id in DATAFLOW_METRICS_TO_TABLES.items():
        schema_for_metric_class = metric_class.bq_schema_for_metric_table()

        if bq_client.table_exists(dataflow_metrics_dataset_ref, table_id):
            # Add any missing fields to the table's schema
            bq_client.add_missing_fields_to_schema(dataflow_metrics_dataset_id, table_id, schema_for_metric_class)
        else:
            # Create a table with this schema
            bq_client.create_table_with_schema(dataflow_metrics_dataset_id, table_id, schema_for_metric_class)


def parse_arguments(argv: List[str]) -> Tuple[argparse.Namespace, List[str]]:
    """Parses the arguments needed to call the desired function."""
    parser = argparse.ArgumentParser()

    parser.add_argument('--project_id',
                        dest='project_id',
                        type=str,
                        choices=[GCP_PROJECT_STAGING, GCP_PROJECT_PRODUCTION],
                        required=True)
    parser.add_argument('--function_to_execute',
                        dest='function_to_execute',
                        type=str,
                        choices=['cold_storage_export', 'update_schemas'],
                        required=True)

    return parser.parse_known_args(argv)


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.INFO)
    known_args, _ = parse_arguments(sys.argv)

    with local_project_id_override(known_args.project_id):
        if known_args.function_to_execute == 'cold_storage_export':
            move_old_dataflow_metrics_to_cold_storage()
        elif known_args.function_to_execute == 'update_schemas':
            update_dataflow_metric_tables_schemas()
