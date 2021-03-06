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
"""Utilities for ingesting a report (as CSVs) into the Justice Counts database.

Example usage:
python -m recidiviz.tools.justice_counts.manual_upload \
    --manifest-file recidiviz/tests/tools/justice_counts/reports/report1/manifest.yaml \
    --project-id recidiviz-staging
python -m recidiviz.tools.justice_counts.manual_upload \
    --manifest-file recidiviz/tests/tools/justice_counts/reports/report1/manifest.yaml \
    --project-id recidiviz-staging \
    --app-url http://127.0.0.1:5000
"""

from abc import abstractmethod, ABCMeta
import argparse
import datetime
import decimal
import enum
import logging
import os
import sys
from collections import defaultdict
from typing import Callable, Dict, Iterable, List, Optional, Tuple, Type, TypeVar, Union
import webbrowser

import attr
from more_itertools import peekable
import pandas
from sqlalchemy import cast
from sqlalchemy.orm.session import Session
from sqlalchemy.sql.schema import UniqueConstraint
import yaml

from recidiviz.common.constants.enum_overrides import EnumOverrides
from recidiviz.common.constants.entity_enum import EntityEnum, EntityEnumMeta, EnumParsingError
from recidiviz.common.date import DateRange, first_day_of_month, last_day_of_month
from recidiviz.common.str_field_utils import to_snake_case
from recidiviz.cloud_storage.gcsfs_factory import GcsfsFactory
from recidiviz.cloud_storage.gcsfs_path import GcsfsDirectoryPath, GcsfsFilePath
from recidiviz.cloud_storage.gcs_file_system import GCSFileSystem, GcsfsFileContentsHandle
from recidiviz.persistence.database.base_schema import JusticeCountsBase
from recidiviz.persistence.database.schema.justice_counts import schema
from recidiviz.persistence.database.session_factory import SessionFactory
from recidiviz.utils.yaml import YAMLDict
from recidiviz.utils import metadata

DimensionT = TypeVar('DimensionT', bound='Dimension')

# Dimensions

# TODO(#4472) Refactor all dimensions out to a common justice counts directory.
class Dimension:
    """Each dimension is represented as a class that is used to hold the values for that dimension and perform any
    necessary validation. All dimensions are categorical. Those with a pre-defined set of values are implemented as
    enums. Others are classes with a single text field to hold any value, and are potentially normalized to a
    pre-defined set of values as a separate dimension.
    """
    @classmethod
    @abstractmethod
    def get(cls: Type[DimensionT], dimension_cell_value: str, enum_overrides: Optional[EnumOverrides] = None) \
            -> DimensionT:
        """Create an instance of the dimension based on the given value.

        Raises an error if it is unable to create an instance of a dimension. Only returns None if the value is
        explicitly ignored in `enum_overrides`.
        """

    @classmethod
    @abstractmethod
    def dimension_identifier(cls) -> str:
        """The globally unique dimension_identifier of this dimension, used when storing it in the database.

        E.g. 'metric/population/type' or 'global/gender/raw'.
        """

    @property
    @abstractmethod
    def dimension_value(self) -> str:
        """The value of this dimension instance.

        E.g. 'FEMALE' is a potential value for an instance of the 'global/raw/gender' dimension.
        """

@attr.s(frozen=True)
class RawDimension(Dimension, metaclass=ABCMeta):
    """Base class to use to create a raw version of a normalized dimension.

    Child classes are typically created by passing a normalized dimension class to `raw_type_for_dimension`, which will
    create a raw, or not normalized, copy version of the dimension.
    """
    value: str = attr.ib()

    @classmethod
    def get(cls, dimension_cell_value: str, enum_overrides: Optional[EnumOverrides] = None) -> 'RawDimension':
        if enum_overrides is not None:
            raise ValueError(f"Unexpected enum_overrides when building raw dimension value: {enum_overrides}")
        return cls(dimension_cell_value)

    @property
    def dimension_value(self) -> str:
        return self.value

def raw_for_dimension_cls(dimension_cls: Type[Dimension]) -> Type[Dimension]:
    return type(f"{dimension_cls.__name__}Raw", (RawDimension, ), {
        'dimension_identifier': classmethod(lambda cls: '/'.join([dimension_cls.dimension_identifier(), 'raw']))
    })

EntityEnumT = TypeVar('EntityEnumT', bound=EntityEnum)
def parse_entity_enum(dimension_cls: Type[EntityEnumT], dimension_cell_value: str,
                      enum_overrides: Optional[EnumOverrides]) -> EntityEnumT:
    entity_enum = dimension_cls.parse(dimension_cell_value, enum_overrides or EnumOverrides.empty())
    if entity_enum is None or not isinstance(entity_enum, dimension_cls):
        raise ValueError(f"Attempting to parse '{dimension_cell_value}' as {dimension_cls} returned unexpected "
                         f"entity: {entity_enum}")
    return entity_enum

class PopulationType(Dimension, EntityEnum, metaclass=EntityEnumMeta):
    PAROLE = 'PAROLE'
    PROBATION = 'PROBATION'
    PRISON = 'PRISON'

    @classmethod
    def get(cls, dimension_cell_value: str, enum_overrides: Optional[EnumOverrides] = None) -> 'PopulationType':
        return parse_entity_enum(cls, dimension_cell_value, enum_overrides)

    @classmethod
    def dimension_identifier(cls) -> str:
        return 'metric/population/type'

    @property
    def dimension_value(self) -> str:
        return self.value

    @classmethod
    def _get_default_map(cls) -> Dict[str, 'PopulationType']:
        return {
            'PAROLE': cls.PAROLE,
            'PROBATION': cls.PROBATION,
            'PRISON': cls.PRISON,
        }

def assert_no_overrides(dimension_cls: Type[Dimension], enum_overrides: Optional[EnumOverrides]) -> None:
    if enum_overrides is not None:
        raise ValueError(f'Overrides not supported for {dimension_cls} but received {enum_overrides}')

class Country(Dimension, enum.Enum):
    US = 'US'

    @classmethod
    def get(cls, dimension_cell_value: str, enum_overrides: Optional[EnumOverrides] = None) -> 'Country':
        assert_no_overrides(cls, enum_overrides)
        return cls(dimension_cell_value)

    @classmethod
    def dimension_identifier(cls) -> str:
        return 'global/location/country'

    @property
    def dimension_value(self) -> str:
        return self.value


# TODO(#4472): Pull this out to a common place and add all states.
class State(Dimension, enum.Enum):
    US_CO = 'US_CO'
    US_MS = 'US_MS'
    US_TN = 'US_TN'

    @classmethod
    def get(cls, dimension_cell_value: str, enum_overrides: Optional[EnumOverrides] = None) -> 'State':
        assert_no_overrides(cls, enum_overrides)
        return cls(dimension_cell_value)

    @classmethod
    def dimension_identifier(cls) -> str:
        return 'global/location/state'

    @property
    def dimension_value(self) -> str:
        return self.value


class County(Dimension, enum.Enum):
    @classmethod
    def get(cls, dimension_cell_value: str, enum_overrides: Optional[EnumOverrides] = None) -> 'County':
        assert_no_overrides(cls, enum_overrides)
        return cls(dimension_cell_value)

    @classmethod
    def dimension_identifier(cls) -> str:
        return 'global/location/county'

    @property
    def dimension_value(self) -> str:
        return self.value

Location = Union[Country, State, County]

# TODO(#4473): Make this per jurisdiction
@attr.s(frozen=True)
class Facility(Dimension):
    name: str = attr.ib()

    @classmethod
    def get(cls, dimension_cell_value: str, enum_overrides: Optional[EnumOverrides] = None) -> 'Facility':
        assert_no_overrides(cls, enum_overrides)
        return cls(dimension_cell_value)

    @classmethod
    def dimension_identifier(cls) -> str:
        return 'global/facility/raw'

    @property
    def dimension_value(self) -> str:
        return self.name

# TODO(#4472): Use main Race enum and normalize values
@attr.s(frozen=True)
class Race(Dimension):
    value: str = attr.ib()

    @classmethod
    def get(cls, dimension_cell_value: str, enum_overrides: Optional[EnumOverrides] = None) -> 'Race':
        assert_no_overrides(cls, enum_overrides)
        return cls(dimension_cell_value)

    @classmethod
    def dimension_identifier(cls) -> str:
        return 'global/race/raw'

    @property
    def dimension_value(self) -> str:
        return self.value

# TODO(#4472): Use main Gender enum and normalize values
@attr.s(frozen=True)
class Gender(Dimension):
    value: str = attr.ib()

    @classmethod
    def get(cls, dimension_cell_value: str, enum_overrides: Optional[EnumOverrides] = None) -> 'Gender':
        assert_no_overrides(cls, enum_overrides)
        return cls(dimension_cell_value)

    @classmethod
    def dimension_identifier(cls) -> str:
        return 'global/gender/raw'

    @property
    def dimension_value(self) -> str:
        return self.value


# TODO(#4473): Raise an error if there are conflicting dimension names
def parse_dimension_name(dimension_name: str) -> Type[Dimension]:
    """Parses a dimension name to its corresponding Dimension class."""
    for dimension in Dimension.__subclasses__():
        if not issubclass(dimension, Dimension):
            raise ValueError(f'Non-dimension subclass returned: {dimension}')
        if dimension_name == to_snake_case(dimension.__name__).upper():
            return dimension
    raise KeyError(f"No dimension exists for name: {dimension_name}")

# Ingest Models
# TODO(#4472): Pull these out into the ingest directory, alongside existing ingest_info.

# Properties are used within the models to handle the conversion specific to each object. This is advantageous so that
# if and when, for instance, a new metric needs to be added, it is clear what conversion steps must be implemented. Any
# conversion that is not specific to a particular object, but instead a class of objects, e.g. all Metrics, is instead
# implemented within the persistence code itself.
class DateFormatType(enum.Enum):
    DATE = 'DATE'
    MONTH = 'MONTH'


DateFormatParserType = Callable[[str], datetime.date]


DATE_FORMAT_PARSERS: Dict[DateFormatType, DateFormatParserType] = {
    DateFormatType.DATE: datetime.date.fromisoformat,
    DateFormatType.MONTH: lambda text: datetime.datetime.strptime(text, "%Y-%m").date()
}


class MeasurementWindowType(enum.Enum):
    RANGE = 'RANGE'
    SNAPSHOT = 'SNAPSHOT'


# Currently we only expect one or two columns to be used to construct date ranges, but this can be expanded in the
# future if needed.
DateRangeConverterType = Union[
    Callable[[datetime.date], DateRange],
    Callable[[datetime.date, datetime.date], DateRange],
]


class RangeType(enum.Enum):
    @classmethod
    def get_or_default(cls, text: Optional[str]) -> 'RangeType':
        if text is None:
            return RangeType.CUSTOM
        return cls(text)

    CUSTOM = 'CUSTOM'
    MONTH = 'MONTH'


RANGE_CONVERTERS: Dict[RangeType, DateRangeConverterType] = {
    RangeType.CUSTOM: DateRange,
    RangeType.MONTH: DateRange.for_month_of_date,
}


class SnapshotType(enum.Enum):
    @classmethod
    def get_or_default(cls, text: Optional[str]) -> 'SnapshotType':
        if text is None:
            return SnapshotType.DAY
        return cls(text)

    DAY = 'DAY'
    FIRST_DAY_OF_MONTH = 'FIRST_DAY_OF_MONTH'
    LAST_DAY_OF_MONTH = 'LAST_DAY_OF_MONTH'


SNAPSHOT_CONVERTERS: Dict[SnapshotType, DateRangeConverterType] = {
    SnapshotType.DAY: DateRange.for_day,
    SnapshotType.FIRST_DAY_OF_MONTH: lambda date: DateRange.for_day(first_day_of_month(date)),
    SnapshotType.LAST_DAY_OF_MONTH: lambda date: DateRange.for_day(last_day_of_month(date)),
}


class Metric:
    @property
    @abstractmethod
    def filters(self) -> List[Dimension]:
        """Any dimensions where the data only represents a subset of values for that dimension.

        For instance, a table for the population metric may only cover data for the prison population, not those on
        parole or probation. In that case filters would contain PopulationType.PRISON.
        """

    @abstractmethod
    def get_measurement_type(self) -> schema.MeasurementType:
        """How the metric over a given time window was reduced to a single point."""

    @classmethod
    @abstractmethod
    def get_metric_type(cls) -> schema.MetricType:
        """The metric type that this corresponds to in the schema."""


# TODO(#4483): Add implementations for other metrics
@attr.s(frozen=True)
class Population(Metric):
    measurement_type: schema.MeasurementType = attr.ib(converter=schema.MeasurementType)

    population_type: PopulationType = attr.ib(converter=PopulationType)

    @property
    def filters(self) -> List[Dimension]:
        return [self.population_type]

    def get_measurement_type(self) -> schema.MeasurementType:
        return self.measurement_type

    @classmethod
    def get_metric_type(cls) -> schema.MetricType:
        return schema.MetricType.POPULATION

class DateRangeProducer:
    """Produces DateRanges for a given table, splitting the table as needed.
    """
    @abstractmethod
    def split_dataframe(self, df: pandas.DataFrame) -> List[Tuple[DateRange, pandas.DataFrame]]:
        pass

@attr.s(frozen=True, kw_only=True)
class FixedDateRangeProducer(DateRangeProducer):
    """Used when data in the table is for a single date range, configured outside of the table.
    """
    # The date range for the table
    fixed_range: DateRange = attr.ib()

    def split_dataframe(self, df: pandas.DataFrame) -> List[Tuple[DateRange, pandas.DataFrame]]:
        return [(self.fixed_range, df)]

@attr.s(frozen=True, kw_only=True)
class DynamicDateRangeProducer(DateRangeProducer):
    """Used when data in the table is for multiple date ranges, represented by the
    values of a particular set of columns in the table.
    """
    # The columns that contain the date ranges and how to parse the values in that column.
    # The parsed values are passed to `converter` in the same order in which the columns are specified in the dict.
    columns: Dict[str, DateFormatParserType] = attr.ib()
    # The function to use to convert the column values into date ranges
    converter: DateRangeConverterType = attr.ib()

    @property
    def column_names(self) -> List[str]:
        return list(self.columns.keys())

    @property
    def column_parsers(self) -> List[DateFormatParserType]:
        return list(self.columns.values())

    def split_dataframe(self, df: pandas.DataFrame) -> List[Tuple[DateRange, pandas.DataFrame]]:
        # - Groups the df by the specified column, getting a separate df per date range
        # - Converts the column values to a `DateRange`, using the provided converter
        # - Drops the columns from the split dfs, as they are no longer needed
        return [(self._convert(date_args), split.drop(self.column_names, axis=1))
                for date_args, split in df.groupby(self.column_names)]

    def _convert(self, args: Union[str, List[str]]) -> DateRange:
        unified_args: List[str] = [args] if isinstance(args, str) else args
        parsed_args: List[datetime.date] = [parser(arg) for arg, parser in zip(unified_args, self.column_parsers)]
        # pylint: disable=not-callable
        return self.converter(*parsed_args)


@attr.s(frozen=True)
class ColumnDimensionMapping:
    """Denotes that a particular dimension column can generate dimensions of a given type, with information about how
    to map values in that column to dimensions of this type.
    """
    # The class of the Dimension this column can generate.
    dimension_cls: Type[Dimension] = attr.ib()

    # Any enum overrides to use when converting to the dimension.
    overrides: Optional[EnumOverrides] = attr.ib()

    # If true, enum parsing will throw if a value in this column is not covered by enum overrides.
    strict: bool = attr.ib(default=True)

    @classmethod
    def from_input(
            cls,
            dimension_cls: Type[Dimension],
            mapping_overrides: Optional[Dict[str, str]] = None,
            strict: Optional[bool] = None
    ) -> 'ColumnDimensionMapping':
        overrides = None
        if mapping_overrides is not None:
            if not issubclass(dimension_cls, EntityEnum):
                raise ValueError(f"Overrides can only be specified for EntityEnum dimensions, not {dimension_cls}")
            overrides_builder = EnumOverrides.Builder()
            for value, mapping in mapping_overrides.items():
                mapped = dimension_cls.get(mapping)
                if mapped is None:
                    raise ValueError(f"Unable to parse override value '{mapping}' as {dimension_cls}")
                overrides_builder.add(value, mapped)
            overrides = overrides_builder.build()
        return cls(dimension_cls, overrides, strict if strict is not None else True)

    def get_raw_dimension_cls(self) -> Optional[Type[Dimension]]:
        # If it is an EntityEnum, it needs to be normalized.
        if issubclass(self.dimension_cls, EntityEnum):
            return raw_for_dimension_cls(self.dimension_cls)
        return None


@attr.s(frozen=True)
class DimensionGenerator:
    """Generates dimensions and dimension values for a single column"""

    # The column name in the input file
    column_name: str = attr.ib()

    dimension_mappings: List[ColumnDimensionMapping] = attr.ib()

    def possible_dimensions_for_column(self) -> List[Type[Dimension]]:
        """Generates a list of all dimension classes that may be associated with a column."""
        output = []
        for mapping in self.dimension_mappings:
            output.append(mapping.dimension_cls)
            raw_dimension_cls = mapping.get_raw_dimension_cls()
            if raw_dimension_cls is not None:
                output.append(raw_dimension_cls)
        return output

    def dimension_values_for_cell(self, dimension_cell_value: str) -> List[Dimension]:
        """Converts a single value in a dimension column to a list of dimension values."""
        dimension_values = []
        for mapping in self.dimension_mappings:

            try:
                base_dimension_value: Optional[Dimension] = mapping.dimension_cls.get(dimension_cell_value,
                                                                                      mapping.overrides)
            except EnumParsingError as e:
                if mapping.strict:
                    raise e
                base_dimension_value = None

            if base_dimension_value is not None:
                dimension_values.append(base_dimension_value)

            raw_dimension = mapping.get_raw_dimension_cls()
            if raw_dimension is not None:
                raw_dimension_value = raw_dimension.get(dimension_cell_value)
                if raw_dimension_value is not None:
                    dimension_values.append(raw_dimension_value)

            if not dimension_values:
                raise ValueError(f"Unable to parse '{dimension_cell_value}' as {mapping.dimension_cls}, but no raw "
                                 f"dimension exists.'")
        return dimension_values


# A single data point that has been annotated with a set of dimensions that it represents.
DimensionalDataPoint = Tuple[Tuple[Dimension, ...], decimal.Decimal]

def _dimension_generators_by_name(dimension_generators: List[DimensionGenerator]) \
        -> Dict[str, DimensionGenerator]:
    return {dimension_generator.column_name: dimension_generator for dimension_generator in dimension_generators}

@attr.s(frozen=True)
class TableConverter:
    """Maps all dimension column values to Dimensions in a table into dimensionally-annotated data points."""

    # For each dimension column, an object that can produce the list of possible dimension types in that column and
    # convert dimension cell values to those types.
    dimension_generators: Dict[str, DimensionGenerator] = attr.ib(converter=_dimension_generators_by_name)

    value_column: str = attr.ib()

    def dimension_classes_for_columns(self, columns: List[str]) -> List[Type[Dimension]]:
        """Returns a list of all possible dimensions that a value in a table could have (superset of possible dimensions
        from individual columns)."""
        dimensions: List[Type[Dimension]] = []
        for column in columns:
            if column in self.dimension_generators:
                possible_dimensions = self.dimension_generators[column].possible_dimensions_for_column()
                dimensions.extend(possible_dimensions)
            elif column != self.value_column:
                raise ValueError(f"Column '{column}' was not mapped.")
        return dimensions

    def table_to_data_points(self, df: pandas.DataFrame) -> List[DimensionalDataPoint]:
        data_points = []
        for row_idx in df.index:
            row = df.loc[row_idx]

            dimension_values_list: List[Dimension] = []
            for column_name in row.index:
                if column_name in self.dimension_generators:
                    dimension_values_list.extend(
                        self._dimension_values_for_dimension_cell(column_name, row[column_name]))
            dimension_values = tuple(dimension_values_list)

            raw_value = row[self.value_column]
            if isinstance(raw_value, str):
                raw_value = raw_value.replace(',', '')
            else:
                raw_value = raw_value.item()

            value = decimal.Decimal(raw_value)
            data_points.append((dimension_values, value))
        return data_points

    def _dimension_values_for_dimension_cell(
            self, dimension_column_name: str, dimension_value: str) -> Iterable[Dimension]:
        return self.dimension_generators[dimension_column_name].dimension_values_for_cell(dimension_value)


HasIdentifierT = TypeVar('HasIdentifierT', Dimension, Type[Dimension])
def _sort_dimensions(dimensions: Iterable[HasIdentifierT]) -> List[HasIdentifierT]:
    return sorted(dimensions, key=lambda dimension: dimension.dimension_identifier())

@attr.s(frozen=True)
class Table:
    """Ingest model that represents a table in a report"""
    date_range: DateRange = attr.ib()
    metric: Metric = attr.ib()
    system: schema.System = attr.ib(converter=schema.System)
    methodology: str = attr.ib()

    # These are dimensions that apply to all data points in this table
    location: Optional[Location] = attr.ib()
    table_filters: List[Dimension] = attr.ib()

    # The superset of all possible dimension classes that may be associated with a row in this table.
    dimensions: List[Type[Dimension]] = attr.ib()

    # Each row in `data_points` may contain a subset of the dimensions in `dimensions`.
    data_points: List[DimensionalDataPoint] = attr.ib()

    @data_points.validator
    def _rows_dimension_combinations_are_unique(
            self, _attribute: attr.Attribute, data_points: List[DimensionalDataPoint]) -> None:
        row_dimension_values = set()
        for dimension_values, _value in data_points:
            if dimension_values in row_dimension_values:
                raise ValueError(f"Multiple rows in table with identical dimensions: {dimension_values}")
            row_dimension_values.add(dimension_values)

    def __attrs_post_init__(self) -> None:
        # Validate consistency between `dimensions` and `data`.
        dimension_identifiers = {dimension.dimension_identifier() for dimension in self.dimensions}
        if len(dimension_identifiers) != len(self.dimensions):
            raise ValueError(f"Duplicate dimensions in table: {self.dimensions}")
        for dimensions, _value in self.data_points:
            row_dimension_identifiers = {dimension_value.dimension_identifier() for dimension_value in dimensions}
            if len(row_dimension_identifiers) != len(dimensions):
                raise ValueError(f"Duplicate dimensions in row: {dimensions}")
            if not dimension_identifiers.issuperset(row_dimension_identifiers):
                raise ValueError(f"Row has dimensions not defined for table. Row dimensions: "
                                 f"'{row_dimension_identifiers}', table dimensions: '{dimension_identifiers}'")

    @classmethod
    def from_table(
            cls, date_range: DateRange, table_converter: TableConverter, metric: Metric, system: str, methodology: str,
            location: Optional[Location], additional_filters: List[Dimension], df: pandas.DataFrame) -> 'Table':
        return cls(date_range=date_range,
                   metric=metric,
                   system=system,
                   methodology=methodology,
                   dimensions=table_converter.dimension_classes_for_columns(df.columns.values),
                   data_points=table_converter.table_to_data_points(df),
                   location=location,
                   table_filters=additional_filters)

    @classmethod
    def list_from_dataframe(
            cls, date_range_producer: DateRangeProducer, table_converter: TableConverter, metric: Metric, system: str,
            methodology: str, location: Optional[Location], additional_filters: List[Dimension],
            df: pandas.DataFrame) -> List['Table']:
        tables = []
        for date_range, df_date in date_range_producer.split_dataframe(df):
            tables.append(cls.from_table(
                date_range=date_range, table_converter=table_converter, metric=metric, system=system,
                methodology=methodology, location=location, additional_filters=additional_filters,
                df=df_date))
        return tables

    @property
    def filters(self) -> List[Dimension]:
        filters = self.metric.filters + self.table_filters
        if self.location is not None:
            filters.append(self.location)
        return _sort_dimensions(filters)

    @property
    def filtered_dimension_names(self) -> List[str]:
        return [filter.dimension_identifier() for filter in self.filters]

    @property
    def filtered_dimension_values(self) -> List[str]:
        return [filter.dimension_value for filter in self.filters]

    @property
    def aggregated_dimensions(self) -> List[Type[Dimension]]:
        return _sort_dimensions(self.dimensions)

    @property
    def aggregated_dimension_names(self) -> List[str]:
        return [dimension.dimension_identifier() for dimension in self.aggregated_dimensions]

    @property
    def cells(self) -> List[Tuple[List[Optional[str]], decimal.Decimal]]:
        table_dimensions = self.aggregated_dimensions

        results = []
        for row in self.data_points:
            cell_dimension_values: List[Optional[str]] = []

            # Align the row dimension values with the table dimensions, filling in with None for any dimension that the
            # row does not have.
            row_dimension_values = _sort_dimensions(row[0])
            row_dimension_iter = peekable(row_dimension_values)
            for table_dimension in table_dimensions:
                if table_dimension.dimension_identifier() == row_dimension_iter.peek().dimension_identifier():
                    cell_dimension_values.append(next(row_dimension_iter).dimension_value)
                else:
                    cell_dimension_values.append(None)

            try:
                next(row_dimension_iter)
                raise ValueError(f"Dimensions for cell not aligned with table. Table dimensions: "
                                 f"'{self.aggregated_dimensions}', row dimensions: '{row_dimension_values}'")
            except StopIteration:
                pass

            results.append((cell_dimension_values, row[1]))

        return results


@attr.s(frozen=True)
class Report:
    # Name of the website or organization that published the report, e.g. 'Mississippi Department of Corrections'
    source_name: str = attr.ib()
    # Distinguishes between the many types of reports that a single source may produce, e.g. 'Daily Status Report' or
    # 'Monthly Fact Sheet'
    report_type: str = attr.ib()
    # Identifies a specific instance of a report type, and should be unique within report type and source, e.g. 'August
    # 2020' for the August Monthly Fact Sheet.
    report_instance: str = attr.ib()

    tables: List[Table] = attr.ib()

    # The date the report was published, used to identify updated reports.
    publish_date: datetime.date = attr.ib(converter=datetime.date.fromisoformat)  # type: ignore[misc]

    # TODO(#4481): Add field to store URL the report was pulled from, or other text describing how it was acquired.


# Parsing Layer
# TODO(#4480): Pull this out to somewhere within ingest

def _parse_location(location_input: YAMLDict) -> Location:
    """Expects a dict with a single entry, e.g. `{'state': 'US_XX'}`"""
    if len(location_input) == 1:
        [[location_type, location_name]] = location_input.get().items()
        if location_type == 'country':
            return Country(location_name)
        if location_type == 'state':
            return State(location_name)
        if location_type == 'county':
            return County(location_name)
    raise ValueError(f"Invalid location, expected a dictionary with a single key that is one of ('country', 'state', "
                     f"'county') but received: {repr(location_input)}")

def _get_converter(range_type_input: str, range_converter_input: Optional[str] = None) -> DateRangeConverterType:
    range_type = MeasurementWindowType(range_type_input)
    if range_type is MeasurementWindowType.SNAPSHOT:
        return SNAPSHOT_CONVERTERS[SnapshotType.get_or_default(range_converter_input)]
    if range_type is MeasurementWindowType.RANGE:
        return RANGE_CONVERTERS[RangeType.get_or_default(range_converter_input)]
    raise ValueError(f"Enum case not handled for {range_type} when building converter.")

# TODO(#4480): Generalize these parsing methods, instead of creating one for each class. If value is a dict, pop it,
# find all implementing classes of `key`, find matching class, pass inner dict as parameters to matching class.
def _parse_date_range(range_input: YAMLDict) -> DateRange:
    """Expects a dict with a single entry that is a dict, e.g. `{'snapshot': {'date': '2020-11-01'}}`"""
    if len(range_input) == 1:
        [[range_type, range_args]] = range_input.get().items()
        converter = _get_converter(range_type.upper())
        if isinstance(range_args, dict):
            parsed_args = {key: datetime.date.fromisoformat(value) for key, value in range_args.items()}
            return converter(**parsed_args)  # type: ignore[call-arg]
    raise ValueError(f"Invalid date range, expected a dictionary with a single key that is one of but received: "
                        f"{repr(range_input)}")


def _parse_dynamic_date_range_producer(range_input: YAMLDict) -> DynamicDateRangeProducer:
    """Expects a dict with type (str), columns (dict) and converter (str, optional) entries.

    E.g. `{'type': 'SNAPSHOT' {'columns': 'Date': 'DATE'}}`
    """
    range_type = range_input.pop('type', str)
    range_converter = range_input.pop_optional('converter', str)
    column_names = range_input.pop('columns', dict)
    columns = {key: DATE_FORMAT_PARSERS[DateFormatType(value)] for key, value in column_names.items()}

    if len(range_input) > 0:
        raise ValueError(f"Received unexpected parameters for date range: {repr(range_input)}")

    return DynamicDateRangeProducer(converter=_get_converter(range_type, range_converter), columns=columns)


def _parse_date_range_producer(range_producer_input: YAMLDict) -> DateRangeProducer:
    """Expects a dict with a single entry that is the arguments for the producer, e.g. `{'fixed': ...}`"""
    if len(range_producer_input) == 1:
        [range_producer_type] = range_producer_input.get().keys()
        range_producer_args = range_producer_input.pop_dict(range_producer_type)
        if range_producer_type == 'fixed':
            return FixedDateRangeProducer(fixed_range=_parse_date_range(range_producer_args))
        if range_producer_type == 'dynamic':
            return _parse_dynamic_date_range_producer(range_producer_args)
    raise ValueError(f"Invalid date range, expected a dictionary with a single key that is one of ('fixed', 'dynamic'"
                     f") but received: {repr(range_producer_input)}")


def _parse_dimensions_from_additional_filters(additional_filters_input: Optional[YAMLDict]) -> List[Dimension]:
    if additional_filters_input is None:
        return []
    dimensions = []
    for dimension_name in list(additional_filters_input.get().keys()):
        dimension_cls = parse_dimension_name(dimension_name)
        value = additional_filters_input.pop(dimension_name, str)
        dimension_value = dimension_cls.get(value)
        if dimension_value is None:
            raise ValueError(f"Unable to parse filter value '{value}' as {dimension_cls}")
        dimensions.append(dimension_value)
    return dimensions


def _parse_table_converter(
        value_column_input: YAMLDict, dimension_columns_input: Optional[List[YAMLDict]]) -> TableConverter:
    """Expects a dict with the value column name and, optionally, a list of dicts describing the dimension columns.

    E.g. `value_column_input={'column_name': 'Population'}}
          dimension_columns_input=[{'column_name': 'Race', 'dimension_name': 'Race', 'mapping_overrides': {...}}, ...]`
    """
    column_dimension_mappings: Dict[str, List[ColumnDimensionMapping]] = defaultdict(list)
    if dimension_columns_input is not None:
        for dimension_column_input in dimension_columns_input:
            column_name = dimension_column_input.pop('column_name', str)
            dimension_cls = parse_dimension_name(dimension_column_input.pop('dimension_name', str))

            overrides_input = dimension_column_input.pop_dict_optional('mapping_overrides')
            overrides = None
            if overrides_input is not None:
                overrides = {key: overrides_input.pop(key, str)
                             for key in list(overrides_input.get().keys())}

            strict = dimension_column_input.pop_optional('strict', bool)

            if len(dimension_column_input) > 0:
                raise ValueError(f"Received unexpected input for dimension column: {repr(dimension_column_input)}")
            column_dimension_mappings[column_name].append(ColumnDimensionMapping.from_input(
                dimension_cls=dimension_cls, mapping_overrides=overrides, strict=strict))

    dimension_generators = []
    for column_name, mappings in column_dimension_mappings.items():
        dimension_generators.append(DimensionGenerator(column_name=column_name, dimension_mappings=mappings))

    value_column = value_column_input.pop('column_name', str)

    if len(value_column_input) > 0:
        raise ValueError(f"Received unexpected parameters for value column: {repr(value_column_input)}")

    return TableConverter(dimension_generators=dimension_generators, value_column=value_column)


def _parse_metric(metric_input: YAMLDict) -> Metric:
    """Expects a dict with a single entry that is the arguments for the metric, e.g. `{'population': ...}`"""
    if len(metric_input) == 1:
        [metric_type] = metric_input.get().keys()
        metric_args = metric_input.pop(metric_type, dict)
        if metric_type == 'population':
            return Population(**metric_args)
    raise ValueError(f"Invalid metric, expected a dictionary with a single key that is one of ('population') but "
                     f"received: {repr(metric_input)}")


# Only three layers of dictionary nesting is currently supported by the table parsing logic but we use the recursive
# dictionary type for convenience.
def _parse_tables(gcs: GCSFileSystem, directory_path: GcsfsDirectoryPath, tables_input: List[YAMLDict]) -> List[Table]:
    """Parses the YAML list of dictionaries describing tables into Table objects"""
    tables = []
    for table_input in tables_input:
        # Parse nested objects separately
        date_range_producer = _parse_date_range_producer(table_input.pop_dict('date_range'))
        table_converter = _parse_table_converter(table_input.pop_dict('value_column'),
                                                 table_input.pop_dicts_optional('dimension_columns'))
        location_dimension: Location = _parse_location(table_input.pop_dict('location'))
        filter_dimensions = \
            _parse_dimensions_from_additional_filters(table_input.pop_dict_optional('additional_filters'))
        metric = _parse_metric(table_input.pop_dict('metric'))

        table_path = GcsfsFilePath.from_directory_and_file_name(directory_path, table_input.pop('file', str))
        logging.info('Reading table: %s', table_path)
        table_handle = gcs.download_to_temp_file(table_path)
        if table_handle is None:
            raise ValueError(f"Unable to download table from path: {table_path}")
        with table_handle.open() as table_file:
            df = pandas.read_csv(table_file)

        tables.extend(Table.list_from_dataframe(
            date_range_producer=date_range_producer, table_converter=table_converter, metric=metric,
            system=table_input.pop('system', str), methodology=table_input.pop('methodology', str),
            location=location_dimension,
            additional_filters=filter_dimensions, df=df))

        if len(table_input) > 0:
            raise ValueError(f"Received unexpected parameters for table: {table_input}")

    return tables


def _get_report(gcs: GCSFileSystem, manifest_path: GcsfsFilePath) -> Report:
    logging.info('Reading report manifest: %s', manifest_path)
    manifest_handle = gcs.download_to_temp_file(manifest_path)
    if manifest_handle is None:
        raise ValueError(f"Unable to download manifest from path: {manifest_path}")
    with manifest_handle.open() as manifest_file:
        loaded_yaml = yaml.full_load(manifest_file)
        if not isinstance(loaded_yaml, dict):
            raise ValueError(f"Expected manifest to contain a top-level dictionary, but received: {loaded_yaml}")
        manifest = YAMLDict(loaded_yaml)

        directory_path = GcsfsDirectoryPath.from_file_path(manifest_path)
        # Parse tables separately
        # TODO(#4479): Also allow for location to be a column in the csv, as is done for dates.
        tables = _parse_tables(gcs, directory_path, manifest.pop_dicts('tables'))

        report = Report(
            source_name=manifest.pop('source', str),
            report_type=manifest.pop('report_type', str),
            report_instance=manifest.pop('report_instance', str),
            publish_date=manifest.pop('publish_date', str),
            tables=tables)

        if len(manifest) > 0:
            raise ValueError(f"Received unexpected parameters in manifest: {manifest}")

        return report

# Persistence Layer
# TODO(#4478): Refactor this into the persistence layer (including splitting out conversion, validation)

@attr.s(frozen=True)
class Metadata:
    acquisition_method: schema.AcquisitionMethod = attr.ib()


def _update_existing_or_create(ingested_entity: schema.JusticeCountsDatabaseEntity, session: Session) \
        -> schema.JusticeCountsDatabaseEntity:
    # Note: Using on_conflict_do_update to resolve whether there is an existing entity could be more efficient as it
    # wouldn't incur multiple roundtrips. However for some entities we need to know whether there is an existing entity
    # (e.g. table instance) so we can clear child entities, so we probably wouldn't win much if anything.
    table = ingested_entity.__table__
    [unique_constraint] = [constraint for constraint in table.constraints if isinstance(constraint, UniqueConstraint)]
    query = session.query(table)
    for column in unique_constraint:
        # TODO(#4477): Instead of making an assumption about how the property name is formed from the column name, use
        # an Entity method here to follow the foreign key relationship.
        if column.name.endswith('_id'):
            value = getattr(ingested_entity, column.name[:-len('_id')]).id
        else:
            value = getattr(ingested_entity, column.name)
        # Cast to the type because array types aren't deduced properly.
        query = query.filter(column == cast(value, column.type))
    table_entity: Optional[JusticeCountsBase] = query.first()
    if table_entity is not None:
        # TODO(#4477): Instead of assuming the primary key field is named `id`, use an Entity method.
        ingested_entity.id = table_entity.id
        # TODO(#4477): Merging here doesn't seem perfect, although it should work so long as the given entity always has
        # all the properties set explicitly. To avoid the merge, the method could instead take in the entity class as
        # one parameter and the parameters to construct it separately and then query based on those parameters. However
        # this would likely make mypy less useful.
        merged_entity = session.merge(ingested_entity)
        return merged_entity
    session.add(ingested_entity)
    return ingested_entity


def _convert_entities(session: Session, ingested_report: Report, report_metadata: Metadata) -> None:
    """Convert the ingested report into SQLAlchemy models"""
    report = _update_existing_or_create(schema.Report(
        source=_update_existing_or_create(schema.Source(name=ingested_report.source_name), session),
        type=ingested_report.report_type,
        instance=ingested_report.report_instance,
        publish_date=ingested_report.publish_date,
        acquisition_method=report_metadata.acquisition_method,
    ), session)

    for table in ingested_report.tables:
        table_definition = _update_existing_or_create(schema.ReportTableDefinition(
            system=table.system,
            metric_type=table.metric.get_metric_type(),
            measurement_type=table.metric.get_measurement_type(),
            filtered_dimensions=table.filtered_dimension_names,
            filtered_dimension_values=table.filtered_dimension_values,
            aggregated_dimensions=table.aggregated_dimension_names,
        ), session)

        # TODO(#4476): Add ingested date to table_instance so that if we ingest a report update we can see which tables
        # are newer and prefer them.

        table_instance = _update_existing_or_create(schema.ReportTableInstance(
            report=report,
            report_table_definition=table_definition,
            time_window_start=table.date_range.lower_bound_inclusive_date,
            time_window_end=table.date_range.upper_bound_exclusive_date,
        ), session)

        # TODO(#4476): Clear any existing cells in the database for this report table instance. In the common case,
        # there won't be any, but if this is an update to a report, and the set of dimension combinations covered by
        # the new table is different, we want to make sure no stale data is left accidentally.
        for dimensions, value in table.cells:
            _update_existing_or_create(schema.Cell(
                report_table_instance=table_instance,
                aggregated_dimension_values=dimensions,
                value=value), session)


def _persist_report(report: Report, report_metadata: Metadata) -> None:
    session: Session = SessionFactory.for_schema_base(JusticeCountsBase)

    try:
        _convert_entities(session, report, report_metadata)
        # TODO(#4475): Add sanity check validation of the data provided, either here or as part of objects above. E.g.:
        # - If there is only one value for a dimension in a table it should be a filter not an aggregated dimension
        # - Ensure the measurement type is valid with the window type
        # - Sanity check custom date ranges
        # Validation of dimension values should already be enforced by enums above.

        session.commit()
    except:
        session.rollback()
        raise
    finally:
        session.close()


def ingest(gcs: GCSFileSystem, manifest_filepath: GcsfsFilePath) -> None:
    logging.info('Fetching report for ingest...')
    report = _get_report(gcs, manifest_filepath)
    logging.info('Ingesting report...')
    _persist_report(report, Metadata(acquisition_method=schema.AcquisitionMethod.MANUALLY_ENTERED))
    logging.info('Report ingested.')

# TODO(#4127): Everything above should be refactored out of the tools directory so only the script below is left.

def _create_parser() -> argparse.ArgumentParser:
    """Creates the CLI argument parser."""
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument(
        '--manifest-file', required=True, type=str,
        help="The yaml describing how to ingest the data"
    )
    parser.add_argument(
        '--project-id', required=True, type=str,
        help="The GCP project to ingest the data into"
    )
    parser.add_argument(
        '--app-url', required=False, type=str,
        help="Override the url of the app."
    )
    parser.add_argument(
        '--log', required=False, default='INFO', type=logging.getLevelName,
        help="Set the logging level"
    )
    return parser

def upload(gcs: GCSFileSystem, manifest_path: str) -> GcsfsFilePath:
    with open(manifest_path, mode='r') as manifest_file:
        directory = os.path.dirname(manifest_path)
        manifest: dict = yaml.full_load(manifest_file)

        gcs_directory = GcsfsDirectoryPath.from_absolute_path(
            os.path.join(f'gs://{metadata.project_id()}-justice-counts-ingest', manifest['source'],
                         manifest['report_type'], manifest['report_instance'])
        )

        for table in manifest['tables']:
            table_filename = table['file']
            gcs.upload_from_contents_handle(
                path=GcsfsFilePath.from_directory_and_file_name(gcs_directory, table_filename),
                contents_handle=GcsfsFileContentsHandle(os.path.join(directory, table_filename)),
                content_type='text/csv'
            )

        manifest_gcs_path = GcsfsFilePath.from_directory_and_file_name(gcs_directory, os.path.basename(manifest_path))
        gcs.upload_from_contents_handle(
            path=manifest_gcs_path,
            contents_handle=GcsfsFileContentsHandle(manifest_path),
            content_type='text/yaml'
        )
        return manifest_gcs_path

def trigger_ingest(gcs_path: GcsfsFilePath, app_url: Optional[str]) -> None:
    app_url = app_url or f'https://{metadata.project_id()}.appspot.com'
    webbrowser.open(url=f'{app_url}/justice_counts/ingest?manifest_path={gcs_path.uri()}')


def main(manifest_path: str, app_url: Optional[str]) -> None:
    logging.info('Uploading report for ingest...')
    gcs_path = upload(GcsfsFactory.build(), manifest_path)

    # We can't hit the endpoint on the app directly from the python script as we don't have IAP credentials. Instead we
    # launch the browser to hit the app and allow the user to auth in browser.
    logging.info('Opening browser to trigger ingest...')
    trigger_ingest(gcs_path, app_url)
    # Then we ask the user if the browser request was successful or displayed an error.
    i = input('Was the ingest successful? [Y/n]: ')
    if i and i.strip().lower() != 'y':
        logging.error('Ingest failed.')
        sys.exit(1)
    logging.info('Report ingested.')


def _configure_logging(level: str) -> None:
    root = logging.getLogger()
    root.setLevel(level)


if __name__ == '__main__':
    arg_parser = _create_parser()
    arguments = arg_parser.parse_args()

    _configure_logging(arguments.log)

    with metadata.local_project_id_override(arguments.project_id):
        main(arguments.manifest_file, arguments.app_url)
