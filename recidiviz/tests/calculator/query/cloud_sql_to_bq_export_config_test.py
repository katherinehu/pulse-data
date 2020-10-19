# Recidiviz - a data platform for criminal justice reform
# Copyright (C) 2019 Recidiviz, Inc.
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

"""Tests for cloud_sql_to_bq_export_config.py."""

import string
import unittest
from unittest import mock
from typing import List

import sqlalchemy
from google.cloud import bigquery

from recidiviz.persistence.database.export import cloud_sql_to_bq_export_config
from recidiviz.persistence.database.export.cloud_sql_to_bq_export_config import CloudSqlToBQConfig
from recidiviz.persistence.database.sqlalchemy_engine_manager import SchemaType


class CloudSqlToBQConfigTest(unittest.TestCase):
    """Tests for cloud_sql_to_bq_export_config.py."""

    def setUp(self) -> None:
        self.schema_types = list(SchemaType)
        self.mock_project_id = 'fake-recidiviz-project'
        self.environment_patcher = mock.patch(
            'recidiviz.persistence.database.export.cloud_sql_to_bq_export_config.GCP_PROJECT_STAGING',
            self.mock_project_id
        )
        self.metadata_patcher = mock.patch(
            'recidiviz.persistence.database.export.cloud_sql_to_bq_export_config.metadata')
        self.mock_metadata = self.metadata_patcher.start()
        self.mock_metadata.project_id.return_value = self.mock_project_id
        self.environment_patcher.start()

    def tearDown(self) -> None:
        self.environment_patcher.stop()
        self.metadata_patcher.stop()


    def test_for_schema_type_raises_error(self) -> None:
        with self.assertRaises(ValueError):
            CloudSqlToBQConfig.for_schema_type('random-schema-type')  # type: ignore[arg-type]


    def test_for_schema_type_returns_instance(self) -> None:
        for schema_type in self.schema_types:
            config = CloudSqlToBQConfig.for_schema_type(schema_type)
            self.assertIsInstance(config, CloudSqlToBQConfig)


    def test_get_gcs_export_uri_for_table(self) -> None:
        """Test that get_gcs_export_uri_for_table generates a GCS URI
            with the correct project ID and table name.
        """
        config = CloudSqlToBQConfig.for_schema_type(SchemaType.JAILS)
        fake_table = 'my_fake_table'
        bucket = '{}-dbexport'.format(self.mock_project_id)
        gcs_export_uri = 'gs://{bucket}/{table_name}.csv'.format(
            bucket=bucket, table_name=fake_table)
        self.assertEqual(
            gcs_export_uri, config.get_gcs_export_uri_for_table(fake_table))


    def test_get_bq_schema_for_table(self) -> None:
        """Test that get_bq_schema_for_table returns a list
            of SchemaField objects when given a valid table_name

            Assert that excluded columns are not in the schema.
        """
        for schema_type in self.schema_types:
            config = CloudSqlToBQConfig.for_schema_type(schema_type)
            table_name = config.sorted_tables[0].name
            schema = config.get_bq_schema_for_table(table_name)
            for schema_field in schema:
                self.assertIsInstance(schema_field, bigquery.SchemaField)

            for table, column in config.columns_to_exclude.items():
                schema = config.get_bq_schema_for_table(table)
                self.assertTrue(
                    column not in list(map(lambda s: s.name, schema)),
                    msg='Column "{}" should not be included. It is found in '
                        'COUNTY_COLUMNS_TO_EXCLUDE` for this table "{}".')


    def test_get_tables_to_export(self) -> None:
        """Assertions for the method get_tables_to_export
            1. Assert that it returns a list of type sqlalchemy.Table
            2. For the StateBase schema, assert that included history tables are included
            3. For the StateBase schema, assert that other history tables are excluded
        """
        for schema_type in self.schema_types:
            config = CloudSqlToBQConfig.for_schema_type(schema_type)
            tables_to_export = config.get_tables_to_export()

            self.assertIsInstance(tables_to_export, List)

            for table in tables_to_export:
                self.assertIsInstance(table, sqlalchemy.Table)

            if schema_type == SchemaType.STATE:
                history_tables_to_include = config.history_tables_to_include
                for history_table in history_tables_to_include:
                    table_names = list(map(lambda t: t.name, tables_to_export))
                    self.assertIn(history_table, table_names)

                for table in config.sorted_tables:
                    if 'history' in table.name and table.name not in config.history_tables_to_include:
                        self.assertNotIn(table, tables_to_export)


    def test_dataset_ref(self) -> None:
        """Make sure dataset_ref is defined correctly.

        Checks that it is a string, checks that it has characters,
        and checks that those characters are letters, numbers, or _.
        """
        for schema_type in self.schema_types:
            config = CloudSqlToBQConfig.for_schema_type(schema_type)
            allowed_characters = set(string.ascii_letters + string.digits + '_')

            self.assertIsInstance(config.dataset_ref, str)

            for char in config.dataset_ref:
                self.assertIn(char, allowed_characters)


    def test_get_table_export_query(self) -> None:
        """For each SchemaType and for each table:
            1. Assert that each export query is of type string
            2. Assert that excluded columns are not in the query
        """
        for schema_type in self.schema_types:
            config = CloudSqlToBQConfig.for_schema_type(schema_type)
            for table in config.sorted_tables:
                query = config.get_table_export_query(table.name)
                self.assertIsInstance(query, str)

                for column in config.columns_to_exclude:
                    search_pattern = '[ ]*{}[, ]+'.format(column)
                    self.assertNotRegex(
                        query, search_pattern,
                        msg='Column "{}" not excluded properly from table "{}".'
                            ' Check cloud_sql_to_bq_export_config.COUNTY_TABLE_COLUMNS_TO_EXPORT'.format(
                                column, table.name)
                    )


    def test_COUNTY_COLUMNS_TO_EXCLUDE_typos(self) -> None:
        """Make sure COUNTY_COLUMNS_TO_EXCLUDE are defined correctly in case of
        typos.

        1) Check that all tables are defined in tables to export.

        2) Check that all columns are defined in their respective tables.
        """
        config = CloudSqlToBQConfig.for_schema_type(SchemaType.JAILS)
        tables = config.get_tables_to_export()
        table_names = list(map(lambda t: t.name, tables))

        for table, _ in cloud_sql_to_bq_export_config.COUNTY_COLUMNS_TO_EXCLUDE.items():
            self.assertTrue(
                table in table_names,
                msg='Table "{}" in `cloud_sql_to_bq_export_config.COUNTY_COLUMNS_TO_EXCLUDE`'
                    ' not found in in the JailsBase schema.'
                    ' Did you spell it correctly?'.format(table)
            )
