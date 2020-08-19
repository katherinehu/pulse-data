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

"""Table for augmenting agent information that has been ingested into the state_agent table with state-specific info
in static tables.
"""

# pylint: disable=trailing-whitespace, line-too-long

from recidiviz.big_query.big_query_view import SimpleBigQueryViewBuilder
from recidiviz.calculator.query.state import dataset_config
from recidiviz.utils.environment import GCP_PROJECT_STAGING
from recidiviz.utils.metadata import local_project_id_override

AUGMENTED_AGENT_INFO_VIEW_NAME = \
    'augmented_agent_info'

AUGMENTED_AGENT_INFO_DESCRIPTION = \
    """Agent information table that adds agent info from one-off reference tables to info from the state_agent table
    for use in the pipelines.
    """

AUGMENTED_AGENT_INFO_QUERY_TEMPLATE = \
    """
    /*{description}*/
    WITH
    agents_base AS (
      SELECT 
        agent_id, 
        state_code, 
        agent_type, 
        external_id, 
        full_name,
        REPLACE(JSON_EXTRACT(full_name, '$.given_names'), '"', '')  AS given_names,
        REPLACE(JSON_EXTRACT(full_name, '$.surname'), '"', '') AS surname
      FROM `{project_id}.{base_dataset}.state_agent` agent
    ),
    agents AS (
        SELECT 
          agent_id, 
          state_code, 
          agent_type, 
          external_id,
          CASE 
            WHEN state_code = 'US_ND' THEN COALESCE(given_names, FNAME)
            ELSE given_names
          END AS given_names,
          CASE 
            WHEN state_code = 'US_ND' THEN COALESCE(surname, LNAME)
            ELSE surname
          END AS surname, 
          CASE 
            WHEN state_code = 'US_ND' THEN CAST(SITEID AS STRING)
            ELSE NULL
          END AS latest_district_external_id
        FROM agents_base
        LEFT JOIN `{project_id}.{static_reference_dataset}.nd_officers_temp` off
        ON agents_base.state_code = 'US_ND' AND agents_base.external_id = CAST(off.OFFICER as STRING)
    )
    SELECT 
      *, 
      COALESCE(CONCAT(agents.external_id, ': ', agents.given_names, ' ', agents.surname),
               agents.external_id) as agent_external_id
    FROM agents

"""

AUGMENTED_AGENT_INFO_VIEW_BUILDER = SimpleBigQueryViewBuilder(
    dataset_id=dataset_config.REFERENCE_VIEWS_DATASET,
    view_id=AUGMENTED_AGENT_INFO_VIEW_NAME,
    view_query_template=AUGMENTED_AGENT_INFO_QUERY_TEMPLATE,
    description=AUGMENTED_AGENT_INFO_DESCRIPTION,
    base_dataset=dataset_config.STATE_BASE_DATASET,
    static_reference_dataset=dataset_config.STATIC_REFERENCE_TABLES_DATASET,
)

if __name__ == '__main__':
    with local_project_id_override(GCP_PROJECT_STAGING):
        AUGMENTED_AGENT_INFO_VIEW_BUILDER.build_and_print()
