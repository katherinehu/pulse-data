# Recidiviz - a platform for tracking granular recidivism metrics in real time
# Copyright (C) 2018 Recidiviz, Inc.
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

"""Tests for ingest/scraper_control.py."""

from flask import Flask
from mock import call, patch

from recidiviz.ingest import scraper_control
from recidiviz.ingest.models.scrape_key import ScrapeKey

APP_ID = "recidiviz-worker-test"

app = Flask(__name__)
app.register_blueprint(scraper_control.scraper_control)
app.config['TESTING'] = True


class TestScraperStart:
    """Tests for requests to the Scraper Start API."""

    # noinspection PyAttributeOutsideInit
    def setup_method(self, _test_method):
        self.client = app.test_client()

    @patch("recidiviz.utils.regions.get_supported_region_codes")
    @patch("recidiviz.utils.regions.Region")
    @patch("recidiviz.ingest.sessions.create_session")
    @patch("recidiviz.ingest.tracker.purge_docket_and_session")
    @patch("recidiviz.ingest.docket.load_target_list")
    def test_start(self, mock_docket, mock_tracker, mock_sessions, mock_region,
                   mock_supported):
        """Tests that the start operation chains together the correct calls."""
        mock_docket.return_value = None
        mock_tracker.return_value = None
        mock_sessions.return_value = None
        fake_scraper = FakeScraper()
        mock_region.return_value = FakeRegion(fake_scraper)
        mock_supported.return_value = ['us_ut', 'us_wy']

        region = 'us_ut'
        scrape_type = 'background'
        scrape_key = ScrapeKey(region, scrape_type)
        request_args = {'region': region, 'scrape_type': scrape_type}
        headers = {'X-Appengine-Cron': "test-cron"}
        response = self.client.get('/start',
                                   query_string=request_args,
                                   headers=headers)
        assert response.status_code == 200

        mock_docket.assert_called_with(scrape_key, '', '')
        mock_tracker.assert_called_with(scrape_key)
        mock_sessions.assert_called_with(scrape_key)
        mock_region.assert_called_with('us_ut')
        mock_supported.assert_called_with()

    @patch("recidiviz.utils.regions.get_supported_region_codes")
    def test_start_unsupported_region(self, mock_supported):
        mock_supported.return_value = ['us_ny', 'us_pa']

        request_args = {'region': 'us_ca', 'scrape_type': 'all'}
        headers = {'X-Appengine-Cron': "test-cron"}
        response = self.client.get('/start',
                                   query_string=request_args,
                                   headers=headers)
        assert response.status_code == 400
        assert response.get_data().decode() == \
            "Missing or invalid parameters, see service logs."

        mock_supported.assert_called_with()


class TestScraperStop:
    """Tests for requests to the Scraper Stop API."""

    # noinspection PyAttributeOutsideInit
    def setup_method(self, _test_method):
        self.client = app.test_client()

    @patch("recidiviz.utils.regions.get_supported_region_codes")
    @patch("recidiviz.utils.regions.Region")
    @patch("recidiviz.ingest.sessions.end_session")
    def test_stop(self, mock_sessions, mock_region, mock_supported):
        mock_sessions.return_value = None
        mock_region.return_value = FakeRegion(FakeScraper())
        mock_supported.return_value = ['us_ca', 'us_ut']

        request_args = {'region': 'all', 'scrape_type': 'all'}
        headers = {'X-Appengine-Cron': "test-cron"}
        response = self.client.get('/stop',
                                   query_string=request_args,
                                   headers=headers)
        assert response.status_code == 200

        mock_sessions.assert_has_calls([call(ScrapeKey('us_ca', 'background')),
                                        call(ScrapeKey('us_ca', 'snapshot')),
                                        call(ScrapeKey('us_ut', 'background')),
                                        call(ScrapeKey('us_ut', 'snapshot'))])
        mock_region.assert_has_calls([call('us_ca'), call('us_ut')])
        mock_supported.assert_called_with()

    @patch("recidiviz.utils.regions.get_supported_region_codes")
    def test_stop_unsupported_region(self, mock_supported):
        mock_supported.return_value = ['us_ny', 'us_pa']

        request_args = {'region': 'us_ca', 'scrape_type': 'all'}
        headers = {'X-Appengine-Cron': "test-cron"}
        response = self.client.get('/stop',
                                   query_string=request_args,
                                   headers=headers)
        assert response.status_code == 400
        assert response.get_data().decode() == \
            "Missing or invalid parameters, see service logs."

        mock_supported.assert_called_with()


class TestScraperResume:
    """Tests for requests to the Scraper Resume API."""

    # noinspection PyAttributeOutsideInit
    def setup_method(self, _test_method):
        self.client = app.test_client()

    @patch("recidiviz.utils.regions.get_supported_region_codes")
    @patch("recidiviz.utils.regions.Region")
    @patch("recidiviz.ingest.sessions.create_session")
    def test_resume(self, mock_sessions, mock_region, mock_supported):
        mock_sessions.return_value = None
        mock_region.return_value = FakeRegion(FakeScraper())
        mock_supported.return_value = ['us_ca']

        region = 'us_ca'
        request_args = {'region': region, 'scrape_type': 'all'}
        headers = {'X-Appengine-Cron': "test-cron"}
        response = self.client.get('/resume',
                                   query_string=request_args,
                                   headers=headers)
        assert response.status_code == 200

        mock_sessions.assert_has_calls([call(ScrapeKey(region, 'background')),
                                        call(ScrapeKey(region, 'snapshot'))])
        mock_region.assert_called_with(region)
        mock_supported.assert_called_with()

    @patch("recidiviz.utils.regions.get_supported_region_codes")
    def test_resume_unsupported_region(self, mock_supported):
        mock_supported.return_value = ['us_ny', 'us_pa']

        request_args = {'region': 'us_ca', 'scrape_type': 'all'}
        headers = {'X-Appengine-Cron': "test-cron"}
        response = self.client.get('/resume',
                                   query_string=request_args,
                                   headers=headers)
        assert response.status_code == 400
        assert response.get_data().decode() == \
            "Missing or invalid parameters, see service logs."

        mock_supported.assert_called_with()


class FakeRegion:
    """A fake region to be returned from mocked out calls to Region"""
    def __init__(self, scraper):
        self.scraper = scraper

    def get_scraper(self):
        return self.scraper


class FakeScraper:
    """A fake scraper to be returned from mocked out calls to
    Region.get_scraper"""

    def start_scrape(self, scrape_type):
        return scrape_type

    def stop_scrape(self, scrape_types):
        return scrape_types

    def resume_scrape(self, scrape_type):
        return scrape_type
