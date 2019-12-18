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
"""Tests for supervision/calculator.py."""
# pylint: disable=unused-import,wrong-import-order
import unittest
from datetime import date
from typing import Dict, List


from recidiviz.calculator.pipeline.supervision import calculator
from recidiviz.calculator.pipeline.supervision.supervision_time_bucket import \
    NonRevocationReturnSupervisionTimeBucket, SupervisionTimeBucket, \
    RevocationReturnSupervisionTimeBucket
from recidiviz.calculator.pipeline.utils.metric_utils import \
    MetricMethodologyType
from recidiviz.common.constants.person_characteristics import Gender, Race, \
    Ethnicity
from recidiviz.common.constants.state.state_supervision import \
    StateSupervisionType
from recidiviz.common.constants.state.state_supervision_violation import \
    StateSupervisionViolationType as ViolationType
from recidiviz.common.constants.state.state_supervision_violation_response \
    import StateSupervisionViolationResponseRevocationType as RevocationType
from recidiviz.persistence.entity.state.entities import StatePerson, \
    StatePersonRace, StatePersonEthnicity
from recidiviz.tests.calculator.calculator_test_utils import \
    demographic_metric_combos_count_for_person

ALL_INCLUSIONS_DICT = {
        'age_bucket': True,
        'gender': True,
        'race': True,
        'ethnicity': True,
    }

CALCULATION_METHODOLOGIES = len(MetricMethodologyType)


class TestMapSupervisionCombinations(unittest.TestCase):
    """Tests the map_supervision_combinations function."""

    def test_map_supervision_combinations(self):
        """Tests the map_supervision_combinations function."""
        person = StatePerson.new_with_defaults(person_id=12345,
                                               birthdate=date(1984, 8, 31),
                                               gender=Gender.FEMALE)

        race = StatePersonRace.new_with_defaults(state_code='CA',
                                                 race=Race.WHITE)

        person.races = [race]

        ethnicity = StatePersonEthnicity.new_with_defaults(
            state_code='CA',
            ethnicity=Ethnicity.NOT_HISPANIC)

        person.ethnicities = [ethnicity]

        supervision_time_buckets = [
            NonRevocationReturnSupervisionTimeBucket(
                'AK', 2018, 3, StateSupervisionType.PAROLE),
            NonRevocationReturnSupervisionTimeBucket(
                'AK', 2018, None, StateSupervisionType.PAROLE)
        ]

        supervision_combinations = calculator.map_supervision_combinations(
            person, supervision_time_buckets, ALL_INCLUSIONS_DICT
        )

        expected_combinations_count = expected_metric_combos_count(
            person, supervision_time_buckets, ALL_INCLUSIONS_DICT)

        self.assertEqual(expected_combinations_count,
                         len(supervision_combinations))
        assert all(value == 1 for _combination, value
                   in supervision_combinations)

    def test_map_supervision_revocation_combinations(self):
        """Tests the map_supervision_combinations function for a
        revocation month."""
        person = StatePerson.new_with_defaults(person_id=12345,
                                               birthdate=date(1984, 8, 31),
                                               gender=Gender.FEMALE)

        race = StatePersonRace.new_with_defaults(state_code='CA',
                                                 race=Race.WHITE)

        person.races = [race]

        ethnicity = StatePersonEthnicity.new_with_defaults(
            state_code='CA',
            ethnicity=Ethnicity.NOT_HISPANIC)

        person.ethnicities = [ethnicity]

        supervision_time_buckets = [
            RevocationReturnSupervisionTimeBucket(
                'AK', 2018, 3, StateSupervisionType.PAROLE,
                RevocationType.SHOCK_INCARCERATION, ViolationType.FELONY)
        ]

        supervision_combinations = calculator.map_supervision_combinations(
            person, supervision_time_buckets, ALL_INCLUSIONS_DICT
        )

        # 256 combinations of: 4 demographics + methodology + supervision type
        # + revocation type + violation type
        # * 1 month = 256 metrics (for Revocation)
        # +
        # 64 combinations of: 4 demographics + methodology + supervision type
        # * 1 month = 64 metrics (for Population)
        expected_combinations_count = expected_metric_combos_count(
            person, supervision_time_buckets, ALL_INCLUSIONS_DICT)

        self.assertEqual(expected_combinations_count,
                         len(supervision_combinations))

        assert all(value == 1 for _combination, value
                   in supervision_combinations)

    def test_map_supervision_combinations_revocation_and_not(self):
        """Tests the map_supervision_combinations function."""
        person = StatePerson.new_with_defaults(person_id=12345,
                                               birthdate=date(1984, 8, 31),
                                               gender=Gender.FEMALE)

        race = StatePersonRace.new_with_defaults(state_code='CA',
                                                 race=Race.WHITE)

        person.races = [race]

        ethnicity = StatePersonEthnicity.new_with_defaults(
            state_code='CA',
            ethnicity=Ethnicity.NOT_HISPANIC)

        person.ethnicities = [ethnicity]

        supervision_time_buckets = [
            NonRevocationReturnSupervisionTimeBucket(
                'AK', 2018, 2, StateSupervisionType.PAROLE),
            NonRevocationReturnSupervisionTimeBucket(
                'AK', 2018, 3, StateSupervisionType.PAROLE),
            RevocationReturnSupervisionTimeBucket(
                'AK', 2018, 4, StateSupervisionType.PAROLE,
                RevocationType.SHOCK_INCARCERATION, ViolationType.FELONY)
        ]

        supervision_combinations = calculator.map_supervision_combinations(
            person, supervision_time_buckets, ALL_INCLUSIONS_DICT
        )

        # For the non-revocation month:
        # 64 combinations of: 4 demographics + methodology + supervision type
        # * 2 month = 128 metrics (for Population)
        #
        # For the revocation month:
        # 256 combinations of: 4 demographics + methodology + supervision type
        # + revocation type + violation type
        # * 1 month = 256 metrics (for Revocation)
        # +
        # 64 combinations of: 4 demographics + methodology + supervision type
        # * 1 month = 64 metrics (for Population)
        expected_combinations_count = expected_metric_combos_count(
            person, supervision_time_buckets, ALL_INCLUSIONS_DICT)

        self.assertEqual(expected_combinations_count,
                         len(supervision_combinations))

        assert all(value == 1 for _combination, value
                   in supervision_combinations)

    def test_map_supervision_combinations_multiple_months(self):
        """Tests the map_supervision_combinations function where the person
        was on supervision for multiple months."""
        person = StatePerson.new_with_defaults(person_id=12345,
                                               birthdate=date(1984, 8, 31),
                                               gender=Gender.FEMALE)

        race = StatePersonRace.new_with_defaults(state_code='CA',
                                                 race=Race.WHITE)

        person.races = [race]

        ethnicity = StatePersonEthnicity.new_with_defaults(
            state_code='CA',
            ethnicity=Ethnicity.NOT_HISPANIC)

        person.ethnicities = [ethnicity]

        supervision_time_buckets = [
            NonRevocationReturnSupervisionTimeBucket(
                'AK', 2018, 3, StateSupervisionType.PAROLE),
            NonRevocationReturnSupervisionTimeBucket(
                'AK', 2018, 4, StateSupervisionType.PAROLE),
            NonRevocationReturnSupervisionTimeBucket(
                'AK', 2018, 5, StateSupervisionType.PAROLE),
            NonRevocationReturnSupervisionTimeBucket(
                'AK', 2018, 6, StateSupervisionType.PAROLE),
            NonRevocationReturnSupervisionTimeBucket(
                'AK', 2018, None, StateSupervisionType.PAROLE),
        ]

        supervision_combinations = calculator.map_supervision_combinations(
            person, supervision_time_buckets, ALL_INCLUSIONS_DICT
        )

        expected_combinations_count = expected_metric_combos_count(
            person, supervision_time_buckets, ALL_INCLUSIONS_DICT
        )

        self.assertEqual(expected_combinations_count,
                         len(supervision_combinations))
        assert all(value == 1 for _combination, value
                   in supervision_combinations)

    def test_map_supervision_combinations_overlapping_months(self):
        """Tests the map_supervision_combinations function where the person
        was serving multiple supervision sentences simultaneously in a given
        month."""
        person = StatePerson.new_with_defaults(person_id=12345,
                                               birthdate=date(1984, 8, 31),
                                               gender=Gender.FEMALE)

        race = StatePersonRace.new_with_defaults(state_code='CA',
                                                 race=Race.WHITE)

        person.races = [race]

        ethnicity = StatePersonEthnicity.new_with_defaults(
            state_code='CA',
            ethnicity=Ethnicity.NOT_HISPANIC)

        person.ethnicities = [ethnicity]

        supervision_time_buckets = [
            NonRevocationReturnSupervisionTimeBucket(
                'AK', 2018, 3, StateSupervisionType.PROBATION),
            NonRevocationReturnSupervisionTimeBucket(
                'AK', 2018, 3, StateSupervisionType.PROBATION),
            NonRevocationReturnSupervisionTimeBucket(
                'AK', 2018, None, StateSupervisionType.PROBATION)
        ]

        supervision_combinations = calculator.map_supervision_combinations(
            person, supervision_time_buckets, ALL_INCLUSIONS_DICT
        )

        # Person-based metrics:
        # 32 combinations of demographics and supervision type
        # * 2 time buckets (1 month + 1 year) = 64 person-based metrics
        # Event-based metrics:
        # 32 combinations of demographics and supervision type
        # * 3 time buckets (2 months + 1 year) = 96 event-based metrics
        self.assertEqual(160, len(supervision_combinations))
        assert all(value == 1 for _combination, value
                   in supervision_combinations)


class TestCharacteristicCombinations(unittest.TestCase):
    """Tests the characteristic_combinations function."""

    def test_characteristic_combinations(self):
        person = StatePerson.new_with_defaults(person_id=12345,
                                               birthdate=date(1984, 8, 31),
                                               gender=Gender.FEMALE)

        race = StatePersonRace.new_with_defaults(state_code='CA',
                                                 race=Race.WHITE)

        person.races = [race]

        ethnicity = StatePersonEthnicity.new_with_defaults(
            state_code='CA',
            ethnicity=Ethnicity.NOT_HISPANIC)

        person.ethnicities = [ethnicity]

        supervision_time_bucket = NonRevocationReturnSupervisionTimeBucket(
            'AK', 2018, 3, StateSupervisionType.PAROLE)

        combinations = calculator.characteristic_combinations(
            person, supervision_time_bucket, ALL_INCLUSIONS_DICT)

        # 32 combinations of demographics and supervision type
        assert len(combinations) == 32

    def test_characteristic_combinations_year_bucket(self):
        person = StatePerson.new_with_defaults(person_id=12345,
                                               birthdate=date(1984, 8, 31),
                                               gender=Gender.FEMALE)

        race = StatePersonRace.new_with_defaults(state_code='CA',
                                                 race=Race.WHITE)

        person.races = [race]

        ethnicity = StatePersonEthnicity.new_with_defaults(
            state_code='CA',
            ethnicity=Ethnicity.NOT_HISPANIC)

        person.ethnicities = [ethnicity]

        supervision_time_bucket = NonRevocationReturnSupervisionTimeBucket(
            'AK', 2018, None, StateSupervisionType.PAROLE)

        combinations = calculator.characteristic_combinations(
            person, supervision_time_bucket, ALL_INCLUSIONS_DICT)

        # 32 combinations of demographics and supervision type
        assert len(combinations) == 32

    def test_characteristic_combinations_exclude_age(self):
        person = StatePerson.new_with_defaults(person_id=12345,
                                               birthdate=date(1984, 8, 31),
                                               gender=Gender.FEMALE)

        race = StatePersonRace.new_with_defaults(state_code='CA',
                                                 race=Race.WHITE)

        person.races = [race]

        ethnicity = StatePersonEthnicity.new_with_defaults(
            state_code='CA',
            ethnicity=Ethnicity.NOT_HISPANIC)

        person.ethnicities = [ethnicity]

        supervision_time_bucket = NonRevocationReturnSupervisionTimeBucket(
            'AK', 2018, 3, StateSupervisionType.PAROLE)

        inclusions = {
            **ALL_INCLUSIONS_DICT,
            'age_bucket': False,
        }

        combinations = calculator.characteristic_combinations(
            person, supervision_time_bucket, inclusions)

        # 16 combinations of demographics and supervision type
        assert len(combinations) == 16

        for combo in combinations:
            assert combo.get('age_bucket') is None

    def test_characteristic_combinations_exclude_gender(self):
        person = StatePerson.new_with_defaults(person_id=12345,
                                               birthdate=date(1984, 8, 31),
                                               gender=Gender.FEMALE)

        race = StatePersonRace.new_with_defaults(state_code='CA',
                                                 race=Race.WHITE)

        person.races = [race]

        ethnicity = StatePersonEthnicity.new_with_defaults(
            state_code='CA',
            ethnicity=Ethnicity.NOT_HISPANIC)

        person.ethnicities = [ethnicity]

        supervision_time_bucket = NonRevocationReturnSupervisionTimeBucket(
            'AK', 2018, 3, StateSupervisionType.PAROLE)

        inclusions = {
            **ALL_INCLUSIONS_DICT,
            'gender': False,
        }

        combinations = calculator.characteristic_combinations(
            person, supervision_time_bucket, inclusions)

        # 16 combinations of demographics and supervision type
        assert len(combinations) == 16

        for combo in combinations:
            assert combo.get('gender') is None

    def test_characteristic_combinations_exclude_race(self):
        person = StatePerson.new_with_defaults(person_id=12345,
                                               birthdate=date(1984, 8, 31),
                                               gender=Gender.FEMALE)

        race = StatePersonRace.new_with_defaults(state_code='CA',
                                                 race=Race.WHITE)

        person.races = [race]

        ethnicity = StatePersonEthnicity.new_with_defaults(
            state_code='CA',
            ethnicity=Ethnicity.NOT_HISPANIC)

        person.ethnicities = [ethnicity]

        supervision_time_bucket = NonRevocationReturnSupervisionTimeBucket(
            'AK', 2018, 3, StateSupervisionType.PAROLE)

        inclusions = {
            **ALL_INCLUSIONS_DICT,
            'race': False,
        }

        combinations = calculator.characteristic_combinations(
            person, supervision_time_bucket, inclusions)

        # 16 combinations of demographics and supervision type
        assert len(combinations) == 16

        for combo in combinations:
            assert combo.get('race') is None

    def test_characteristic_combinations_exclude_ethnicity(self):
        person = StatePerson.new_with_defaults(person_id=12345,
                                               birthdate=date(1984, 8, 31),
                                               gender=Gender.FEMALE)

        race = StatePersonRace.new_with_defaults(state_code='CA',
                                                 race=Race.WHITE)

        person.races = [race]

        ethnicity = StatePersonEthnicity.new_with_defaults(
            state_code='CA',
            ethnicity=Ethnicity.NOT_HISPANIC)

        person.ethnicities = [ethnicity]

        supervision_time_bucket = NonRevocationReturnSupervisionTimeBucket(
            'AK', 2018, 3, StateSupervisionType.PAROLE)

        inclusions = {
            **ALL_INCLUSIONS_DICT,
            'ethnicity': False,
        }

        combinations = calculator.characteristic_combinations(
            person, supervision_time_bucket, inclusions)

        # 16 combinations of demographics and supervision type
        assert len(combinations) == 16

        for combo in combinations:
            assert combo.get('ethnicity') is None

    def test_characteristic_combinations_exclude_multiple(self):
        person = StatePerson.new_with_defaults(person_id=12345,
                                               birthdate=date(1984, 8, 31),
                                               gender=Gender.FEMALE)

        race = StatePersonRace.new_with_defaults(state_code='CA',
                                                 race=Race.WHITE)

        person.races = [race]

        ethnicity = StatePersonEthnicity.new_with_defaults(
            state_code='CA',
            ethnicity=Ethnicity.NOT_HISPANIC)

        person.ethnicities = [ethnicity]

        supervision_time_bucket = NonRevocationReturnSupervisionTimeBucket(
            'AK', 2018, 3, StateSupervisionType.PAROLE)

        inclusions = {
            **ALL_INCLUSIONS_DICT,
            'age_bucket': False,
            'ethnicity': False,
        }

        combinations = calculator.characteristic_combinations(
            person, supervision_time_bucket, inclusions)

        # 8 combinations of demographics and supervision type
        assert len(combinations) == 8

        for combo in combinations:
            assert combo.get('age_bucket') is None
            assert combo.get('ethnicity') is None

    def test_characteristic_combinations_revocation(self):
        person = StatePerson.new_with_defaults(person_id=12345,
                                               birthdate=date(1984, 8, 31),
                                               gender=Gender.FEMALE)

        race = StatePersonRace.new_with_defaults(state_code='CA',
                                                 race=Race.WHITE)

        person.races = [race]

        ethnicity = StatePersonEthnicity.new_with_defaults(
            state_code='CA',
            ethnicity=Ethnicity.NOT_HISPANIC)

        person.ethnicities = [ethnicity]

        supervision_time_bucket = RevocationReturnSupervisionTimeBucket(
            'AK', 2018, 3, StateSupervisionType.PAROLE,
            RevocationType.SHOCK_INCARCERATION, ViolationType.FELONY)

        combinations = calculator.characteristic_combinations(
            person, supervision_time_bucket, ALL_INCLUSIONS_DICT,
            with_revocation_dimensions=True)

        # 128 combinations of: 4 demographic dimensions
        # + supervision type + revocation type + violation type
        expected_combinations_count = expected_metric_combos_count(
            person, [supervision_time_bucket], ALL_INCLUSIONS_DICT,
            with_methodologies=False, include_both_metrics=False)

        self.assertEqual(expected_combinations_count, len(combinations))

    def test_characteristic_combinations_revocation_with_types_disabled(self):
        person = StatePerson.new_with_defaults(person_id=12345,
                                               birthdate=date(1984, 8, 31),
                                               gender=Gender.FEMALE)

        race = StatePersonRace.new_with_defaults(state_code='CA',
                                                 race=Race.WHITE)

        person.races = [race]

        ethnicity = StatePersonEthnicity.new_with_defaults(
            state_code='CA',
            ethnicity=Ethnicity.NOT_HISPANIC)

        person.ethnicities = [ethnicity]

        supervision_time_bucket = RevocationReturnSupervisionTimeBucket(
            'AK', 2018, 3, StateSupervisionType.PAROLE,
            RevocationType.SHOCK_INCARCERATION, ViolationType.FELONY)

        combinations = calculator.characteristic_combinations(
            person, supervision_time_bucket, ALL_INCLUSIONS_DICT,
            with_revocation_dimensions=False)

        # 32 combinations of: 4 demographic dimensions + supervision type
        expected_combinations_count = expected_metric_combos_count(
            person, [supervision_time_bucket], ALL_INCLUSIONS_DICT,
            with_revocation_dimensions=False, with_methodologies=False,
            include_both_metrics=False)

        self.assertEqual(expected_combinations_count, len(combinations))

    def test_characteristic_combinations_revocation_no_revocation_type(self):
        person = StatePerson.new_with_defaults(person_id=12345,
                                               birthdate=date(1984, 8, 31),
                                               gender=Gender.FEMALE)

        race = StatePersonRace.new_with_defaults(state_code='CA',
                                                 race=Race.WHITE)

        person.races = [race]

        ethnicity = StatePersonEthnicity.new_with_defaults(
            state_code='CA',
            ethnicity=Ethnicity.NOT_HISPANIC)

        person.ethnicities = [ethnicity]

        supervision_time_bucket = RevocationReturnSupervisionTimeBucket(
            'AK', 2018, 3, StateSupervisionType.PAROLE,
            None, ViolationType.FELONY)

        combinations = calculator.characteristic_combinations(
            person, supervision_time_bucket, ALL_INCLUSIONS_DICT,
            with_revocation_dimensions=True)

        # 64 combinations of: 4 demographic dimensions
        # + supervision type + violation type
        expected_combinations_count = expected_metric_combos_count(
            person, [supervision_time_bucket], ALL_INCLUSIONS_DICT,
            with_methodologies=False, include_both_metrics=False)

        self.assertEqual(expected_combinations_count, len(combinations))

        for combo in combinations:
            assert combo.get('revocation_type') is None

    def test_characteristic_combinations_revocation_no_violation_type(self):
        person = StatePerson.new_with_defaults(person_id=12345,
                                               birthdate=date(1984, 8, 31),
                                               gender=Gender.FEMALE)

        race = StatePersonRace.new_with_defaults(state_code='CA',
                                                 race=Race.WHITE)

        person.races = [race]

        ethnicity = StatePersonEthnicity.new_with_defaults(
            state_code='CA',
            ethnicity=Ethnicity.NOT_HISPANIC)

        person.ethnicities = [ethnicity]

        supervision_time_bucket = RevocationReturnSupervisionTimeBucket(
            'AK', 2018, 3, StateSupervisionType.PAROLE,
            RevocationType.SHOCK_INCARCERATION, None)

        combinations = calculator.characteristic_combinations(
            person, supervision_time_bucket, ALL_INCLUSIONS_DICT,
            with_revocation_dimensions=True)

        # 64 combinations of: 4 demographic dimensions
        # + supervision type + revocation type
        expected_combinations_count = expected_metric_combos_count(
            person, [supervision_time_bucket], ALL_INCLUSIONS_DICT,
            with_methodologies=False, include_both_metrics=False)

        self.assertEqual(expected_combinations_count, len(combinations))

        for combo in combinations:
            assert combo.get('violation_type') is None

    def test_characteristic_combinations_revocation_no_extra_types(self):
        person = StatePerson.new_with_defaults(person_id=12345,
                                               birthdate=date(1984, 8, 31),
                                               gender=Gender.FEMALE)

        race = StatePersonRace.new_with_defaults(state_code='CA',
                                                 race=Race.WHITE)

        person.races = [race]

        ethnicity = StatePersonEthnicity.new_with_defaults(
            state_code='CA',
            ethnicity=Ethnicity.NOT_HISPANIC)

        person.ethnicities = [ethnicity]

        supervision_time_bucket = RevocationReturnSupervisionTimeBucket(
            'AK', 2018, 3, StateSupervisionType.PROBATION, None, None)

        combinations = calculator.characteristic_combinations(
            person, supervision_time_bucket, ALL_INCLUSIONS_DICT,
            with_revocation_dimensions=True)

        # 32 combinations of: 4 demographic dimensions + supervision type
        expected_combinations_count = expected_metric_combos_count(
            person, [supervision_time_bucket], ALL_INCLUSIONS_DICT,
            with_methodologies=False, include_both_metrics=False)

        self.assertEqual(expected_combinations_count, len(combinations))

        for combo in combinations:
            assert combo.get('revocation_type') is None
            assert combo.get('violation_type') is None


def demographic_metric_combos_count_for_person_supervision(
        person: StatePerson,
        inclusions: Dict[str, bool]) -> int:
    """Returns the number of possible demographic metric combinations for a
    given person, given the metric inclusions list."""

    total_metric_combos = demographic_metric_combos_count_for_person(
        person, inclusions
    )

    # Supervision type is always included
    total_metric_combos *= 2

    return total_metric_combos


def expected_metric_combos_count(
        person: StatePerson,
        supervision_time_buckets: List[SupervisionTimeBucket],
        inclusions: Dict[str, bool],
        with_revocation_dimensions: bool = True,
        with_methodologies: bool = True,
        include_both_metrics: bool = True) -> int:
    """Calculates the expected number of characteristic combinations given
    the person, the supervision time buckets, and the dimensions that should
    be included in the explosion of feature combinations."""

    demographic_metric_combos = \
        demographic_metric_combos_count_for_person_supervision(
            person, inclusions)

    # Some test cases above use a different call that doesn't take methodology
    # into account as a dimension
    methodology_multiplier = 1
    if with_methodologies:
        methodology_multiplier *= CALCULATION_METHODOLOGIES

    # Calculate total combos for supervision population
    num_buckets = len(supervision_time_buckets)

    revocation_buckets = [
        bucket for bucket in supervision_time_buckets
        if isinstance(bucket, RevocationReturnSupervisionTimeBucket)
    ]
    num_revocation_buckets = len(revocation_buckets)

    supervision_population_combos = \
        demographic_metric_combos * methodology_multiplier * \
        num_buckets

    # Calculate total combos for supervision revocation
    revocation_dimension_multiplier = 1
    if with_revocation_dimensions:
        if revocation_buckets and revocation_buckets[0].revocation_type:
            revocation_dimension_multiplier *= 2
        if revocation_buckets and revocation_buckets[0].source_violation_type:
            revocation_dimension_multiplier *= 2

    supervision_revocation_combos = \
        demographic_metric_combos * methodology_multiplier * \
        num_revocation_buckets * revocation_dimension_multiplier

    # Pick which one is relevant for the test case: some tests above use a
    # different call that only looks at combos for either population or
    # revocation, but not both
    if include_both_metrics:
        return supervision_population_combos + supervision_revocation_combos

    if num_revocation_buckets > 0:
        return supervision_revocation_combos
    return supervision_population_combos