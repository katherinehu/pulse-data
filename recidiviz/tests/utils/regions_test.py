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

"""Tests for utils/regions.py."""
from typing import Optional
from unittest import TestCase
from unittest.mock import patch

import pytest
import pytz
from mock import Mock, PropertyMock, mock_open

from recidiviz.utils import regions
from recidiviz.utils.regions import Region, get_region_manifest

US_NY_MANIFEST_CONTENTS = """
    agency_name: Department of Corrections and Community Supervision
    agency_type: prison
    base_url: http://nysdoccslookup.doccs.ny.gov
    names_file: us_ny_names.csv
    queue:
      rate: 18/m
    timezone: America/New_York
    environment: production
    jurisdiction_id: jid_ny
    should_proxy: true
    """
US_IN_MANIFEST_CONTENTS = """
    agency_name: Department of Corrections
    agency_type: prison
    base_url: https://www.in.gov/apps/indcorrection/ofs/ofs
    names_file: us_in_names.csv
    shared_queue: some-vendor-queue
    timezone: America/Indiana/Indianapolis
    environment: production
    jurisdiction_id: jid_in
    stripe: '1'
    """
US_CA_MANIFEST_CONTENTS = """
    agency_name: Corrections
    agency_type: jail
    base_url: test
    timezone: America/Los_Angeles
    environment: production
    jurisdiction_id: jid_ca
    stripe: '1'
    """
BAD_QUEUE_MANIFEST_CONTENTS = """
    agency_name: Corrections
    agency_type: jail
    base_url: test
    timezone: America/Los_Angeles
    shared_queue: some-vendor-queue
    environment: production
    queue:
      rate: 18/m
    jurisdiction_id: jid_bad
    """
BAD_ENV_BOOL_MANIFEST_CONTENTS = """
    agency_name: Corrections
    agency_type: jail
    base_url: test
    timezone: America/Los_Angeles
    environment: true
    queue:
      rate: 18/m
    jurisdiction_id: jid_bad
    """
BAD_ENV_STR_MANIFEST_CONTENTS = """
    agency_name: Corrections
    agency_type: jail
    base_url: test
    timezone: America/Los_Angeles
    environment: unknown
    queue:
      rate: 18/m
    jurisdiction_id: jid_bad
    """
US_MA_MIDDLESEX_CONTENTS = """
    agency_name: Middlesex Sheriff's Office
    agency_type: jail
    timezone: America/New_York
    environment: staging
    jurisdiction_id: jid
"""
REGION_TO_MANIFEST = {
    'us_ny': US_NY_MANIFEST_CONTENTS,
    'us_in': US_IN_MANIFEST_CONTENTS,
    'us_ca': US_CA_MANIFEST_CONTENTS,
    'bad_queue': BAD_QUEUE_MANIFEST_CONTENTS,
    'bad_env_bool': BAD_ENV_BOOL_MANIFEST_CONTENTS,
    'bad_env_str': BAD_ENV_STR_MANIFEST_CONTENTS,
    'us_ma_middlesex': US_MA_MIDDLESEX_CONTENTS,
}


def fake_modules(*names):
    modules = []
    for name in names:
        fake_module = Mock()
        type(fake_module).name = PropertyMock(return_value=name)
        modules.append(fake_module)
    return modules


class TestRegions(TestCase):
    """Tests for regions.py."""

    def setup_method(self, _test_method):
        regions.REGIONS = {}

    def teardown_method(self, _test_method):
        regions.REGIONS = {}

    def test_get_region_manifest(self):
        manifest = with_manifest(regions.get_region_manifest, 'us_ny')
        assert manifest == {
            'agency_name': 'Department of Corrections and '
                           'Community Supervision',
            'agency_type': 'prison',
            'base_url': 'http://nysdoccslookup.doccs.ny.gov',
            'names_file': 'us_ny_names.csv',
            'queue': {'rate': '18/m'},
            'timezone': 'America/New_York',
            'environment': 'production',
            'jurisdiction_id': 'jid_ny',
            'should_proxy': True,
        }

    def test_get_region_proxy_set(self):
        region = with_manifest(regions.get_region, 'us_ny')
        assert region.should_proxy

        region = with_manifest(regions.get_region, 'us_in')
        assert not region.should_proxy

    def test_get_region_manifest_not_found(self):
        with pytest.raises(FileNotFoundError):
            with_manifest(regions.get_region_manifest, 'us_az')

    @patch('pkgutil.iter_modules',
           return_value=fake_modules('us_ny', 'us_in', 'us_ca'))
    def test_get_supported_regions(self, _mock_modules):
        supported_regions = with_manifest(regions.get_supported_scrape_regions)
        self.assertCountEqual(
            [region.region_code for region in supported_regions],
            ['us_ny', 'us_in', 'us_ca'])

    @patch('pkgutil.iter_modules',
           return_value=fake_modules('us_ny', 'us_in', 'us_ca'))
    def test_get_supported_region_codes(self, _mock_modules):
        supported_regions = with_manifest(
            regions.get_supported_scrape_region_codes)
        assert supported_regions == {'us_ny', 'us_in', 'us_ca'}

    @patch('pkgutil.iter_modules',
           return_value=fake_modules('us_ny', 'us_in', 'us_ca'))
    def test_get_supported_region_codes_timezone(self, _mock_modules):
        supported_regions = with_manifest(
            regions.get_supported_scrape_region_codes,
            timezone=pytz.timezone('America/New_York'))
        assert supported_regions == {'us_ny', 'us_in'}

    @patch('pkgutil.iter_modules',
           return_value=fake_modules('us_ny', 'us_in', 'us_ca'))
    def test_get_supported_region_codes_stripe(self, _mock_modules):
        supported_regions = with_manifest(
            regions.get_supported_scrape_region_codes,
            stripes="1")
        assert supported_regions == {'us_in', 'us_ca'}

    @patch('pkgutil.iter_modules',
           return_value=fake_modules('us_ny', 'us_in', 'us_ca'))
    def test_get_supported_region_codes_timezone_stripe(self, _mock_modules):
        supported_regions = with_manifest(
            regions.get_supported_scrape_region_codes,
            timezone=pytz.timezone('America/New_York'),
            stripes="1")
        assert supported_regions == {'us_in'}

    @patch('pkgutil.iter_modules',
           return_value=fake_modules('us_ny', 'us_in', 'us_ca'))
    def test_get_supported_region_codes_stripes(self, _mock_modules):
        supported_regions = with_manifest(
            regions.get_supported_scrape_region_codes,
            stripes=["0", "1"])
        assert supported_regions == {'us_ny', 'us_in', 'us_ca'}

    @patch('pkgutil.iter_modules',
           return_value=fake_modules('us_ny', 'us_in', 'us_ca'))
    def test_validate_region_code_valid(self, _mock_modules):
        assert with_manifest(regions.validate_region_code, 'us_in')

    @patch('pkgutil.iter_modules',
           return_value=fake_modules('us_ny', 'us_in', 'us_ca'))
    def test_validate_region_code_invalid(self, _mock_modules):
        assert not with_manifest(regions.validate_region_code, 'us_az')

    def test_get_scraper(self):
        mock_package = Mock()
        mock_scraper = Mock()
        mock_package.UsNyScraper.return_value = mock_scraper

        module_obj = {
            'recidiviz.ingest.scrape.regions.us_ny.us_ny_scraper': mock_package}
        with patch('importlib.import_module', module_obj.get):
            region = with_manifest(regions.get_region, 'us_ny')
            scraper = region.get_ingestor()
            assert scraper is mock_scraper

    def test_get_direct_controller(self):
        mock_package = Mock()
        mock_direct = Mock()
        mock_package.UsMaMiddlesexController.return_value = mock_direct

        module_obj = {'recidiviz.ingest.direct.regions.us_ma_middlesex.'
                      'us_ma_middlesex_controller': mock_package}
        with patch('importlib.import_module', module_obj.get):
            region = with_manifest(regions.get_region, 'us_ma_middlesex',
                                   is_direct_ingest=True)
            direct = region.get_ingestor()
            assert direct is mock_direct

    def test_create_queue_name(self):
        region = with_manifest(regions.get_region, 'us_ny')
        assert region.get_queue_name() == 'us-ny-scraper-v2'

    def test_shared_queue_name(self):
        region = with_manifest(regions.get_region, 'us_in')
        assert region.get_queue_name() == 'some-vendor-queue'

    def test_set_both_queues_error(self):
        with pytest.raises(ValueError) as e:
            with_manifest(regions.get_region, 'bad_queue')
            assert 'queue' in e.message

    def test_invalid_region_error_bool(self):
        with pytest.raises(ValueError) as e:
            with_manifest(regions.get_region, 'bad_env_bool')
            assert 'environment' in e.message

    def test_invalid_region_error_str(self):
        with pytest.raises(ValueError) as e:
            with_manifest(regions.get_region, 'bad_env_str')
            assert 'environment' in e.message

    @staticmethod
    def make_sql_preprocessing_flag_region(
            raw_vs_ingest_file_name_differentiation_enabled_env: Optional[str] = None,
            raw_data_bq_imports_enabled_env: Optional[str] = None,
            ingest_view_exports_enabled_env: Optional[str] = None
    ):
        region_code = 'us_mo'

        flag_overrides = {
            'raw_vs_ingest_file_name_differentiation_enabled_env': raw_vs_ingest_file_name_differentiation_enabled_env,
            'raw_data_bq_imports_enabled_env': raw_data_bq_imports_enabled_env,
            'ingest_view_exports_enabled_env': ingest_view_exports_enabled_env,
        }

        kwargs = {
            **get_region_manifest(region_code, True),
            **flag_overrides
        }

        return Region(region_code=region_code, is_direct_ingest=True, **kwargs)

    @patch("recidiviz.utils.environment.get_gae_environment")
    def test_is_raw_vs_ingest_file_name_detection_enabled_production(self, mock_environment):
        mock_environment.return_value = 'production'

        region = with_manifest(self.make_sql_preprocessing_flag_region)
        self.assertFalse(region.is_raw_vs_ingest_file_name_detection_enabled())

        region = with_manifest(self.make_sql_preprocessing_flag_region,
                               raw_vs_ingest_file_name_differentiation_enabled_env='staging')
        self.assertFalse(region.is_raw_vs_ingest_file_name_detection_enabled())

        region = with_manifest(self.make_sql_preprocessing_flag_region,
                               raw_vs_ingest_file_name_differentiation_enabled_env='production')
        self.assertTrue(region.is_raw_vs_ingest_file_name_detection_enabled())

    @patch("recidiviz.utils.environment.get_gae_environment")
    def test_is_raw_vs_ingest_file_name_detection_enabled_staging(self, mock_environment):
        mock_environment.return_value = 'staging'

        region = with_manifest(self.make_sql_preprocessing_flag_region)
        self.assertFalse(region.is_raw_vs_ingest_file_name_detection_enabled())

        region = with_manifest(self.make_sql_preprocessing_flag_region,
                               raw_vs_ingest_file_name_differentiation_enabled_env='staging')
        self.assertTrue(region.is_raw_vs_ingest_file_name_detection_enabled())

        region = with_manifest(self.make_sql_preprocessing_flag_region,
                               raw_vs_ingest_file_name_differentiation_enabled_env='production')
        self.assertTrue(region.is_raw_vs_ingest_file_name_detection_enabled())

    @patch("recidiviz.utils.environment.get_gae_environment")
    def test_are_raw_data_bq_imports_enabled_in_env_production(self, mock_environment):
        mock_environment.return_value = 'production'

        region = with_manifest(self.make_sql_preprocessing_flag_region)
        self.assertFalse(region.are_raw_data_bq_imports_enabled_in_env())

        region = with_manifest(self.make_sql_preprocessing_flag_region,
                               raw_vs_ingest_file_name_differentiation_enabled_env='staging',
                               raw_data_bq_imports_enabled_env='staging')
        self.assertFalse(region.are_raw_data_bq_imports_enabled_in_env())

        region = with_manifest(self.make_sql_preprocessing_flag_region,
                               raw_data_bq_imports_enabled_env='production')
        self.assertFalse(region.are_raw_data_bq_imports_enabled_in_env())

        region = with_manifest(self.make_sql_preprocessing_flag_region,
                               raw_vs_ingest_file_name_differentiation_enabled_env='production',
                               raw_data_bq_imports_enabled_env='production')
        self.assertTrue(region.are_raw_data_bq_imports_enabled_in_env())

    @patch("recidiviz.utils.environment.get_gae_environment")
    def test_are_raw_data_bq_imports_enabled_in_env_staging(self, mock_environment):
        mock_environment.return_value = 'staging'

        region = with_manifest(self.make_sql_preprocessing_flag_region)
        self.assertFalse(region.are_raw_data_bq_imports_enabled_in_env())

        region = with_manifest(self.make_sql_preprocessing_flag_region,
                               raw_vs_ingest_file_name_differentiation_enabled_env='staging',
                               raw_data_bq_imports_enabled_env='staging')
        self.assertTrue(region.are_raw_data_bq_imports_enabled_in_env())

        region = with_manifest(self.make_sql_preprocessing_flag_region,
                               raw_vs_ingest_file_name_differentiation_enabled_env='production',
                               raw_data_bq_imports_enabled_env='production')
        self.assertTrue(region.are_raw_data_bq_imports_enabled_in_env())

    @patch("recidiviz.utils.environment.get_gae_environment")
    def test_are_ingest_view_exports_enabled_in_env_production(self, mock_environment):
        mock_environment.return_value = 'production'

        region = with_manifest(self.make_sql_preprocessing_flag_region)
        self.assertFalse(region.are_ingest_view_exports_enabled_in_env())

        region = with_manifest(self.make_sql_preprocessing_flag_region,
                               raw_vs_ingest_file_name_differentiation_enabled_env='production',
                               raw_data_bq_imports_enabled_env='production',
                               ingest_view_exports_enabled_env='staging')
        self.assertFalse(region.are_ingest_view_exports_enabled_in_env())

        region = with_manifest(self.make_sql_preprocessing_flag_region,
                               raw_vs_ingest_file_name_differentiation_enabled_env='staging',
                               raw_data_bq_imports_enabled_env='staging',
                               ingest_view_exports_enabled_env='production')
        self.assertFalse(region.are_ingest_view_exports_enabled_in_env())

        region = with_manifest(self.make_sql_preprocessing_flag_region,
                               raw_vs_ingest_file_name_differentiation_enabled_env='production',
                               raw_data_bq_imports_enabled_env='production',
                               ingest_view_exports_enabled_env='production')
        self.assertTrue(region.are_ingest_view_exports_enabled_in_env())

    @patch("recidiviz.utils.environment.get_gae_environment")
    def test_are_ingest_view_exports_enabled_in_env_staging(self, mock_environment):
        mock_environment.return_value = 'staging'

        region = with_manifest(self.make_sql_preprocessing_flag_region)
        self.assertFalse(region.are_ingest_view_exports_enabled_in_env())

        region = with_manifest(self.make_sql_preprocessing_flag_region,
                               raw_vs_ingest_file_name_differentiation_enabled_env='production',
                               raw_data_bq_imports_enabled_env='staging',
                               ingest_view_exports_enabled_env='staging')
        self.assertTrue(region.are_ingest_view_exports_enabled_in_env())

        region = with_manifest(self.make_sql_preprocessing_flag_region,
                               raw_vs_ingest_file_name_differentiation_enabled_env='production',
                               raw_data_bq_imports_enabled_env='production',
                               ingest_view_exports_enabled_env='production')
        self.assertTrue(region.are_ingest_view_exports_enabled_in_env())


def mock_manifest_open(filename, *args):
    if filename.endswith('manifest.yaml'):
        region = filename.split('/')[-2]
        if region in REGION_TO_MANIFEST:
            content = REGION_TO_MANIFEST[region]
            file_object = mock_open(read_data=content).return_value
            file_object.__iter__.return_value = content.splitlines(True)
            return file_object
    return open(filename, *args)


def with_manifest(func, *args, **kwargs):
    with patch("recidiviz.utils.regions.open", new=mock_manifest_open):
        return func(*args, **kwargs)
