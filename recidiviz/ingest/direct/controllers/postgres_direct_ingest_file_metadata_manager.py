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
"""An implementation for a class that handles writing metadata about each direct ingest file to the operations
Postgres table.
"""
import datetime
from typing import Optional, List

from recidiviz.ingest.direct.controllers.direct_ingest_file_metadata_manager import DirectIngestFileMetadataManager
from recidiviz.ingest.direct.controllers.direct_ingest_gcs_file_system import DIRECT_INGEST_UNPROCESSED_PREFIX
from recidiviz.ingest.direct.controllers.gcsfs_direct_ingest_utils import GcsfsIngestViewExportArgs, \
    filename_parts_from_path, GcsfsDirectIngestFileType
from recidiviz.ingest.direct.controllers.gcsfs_path import GcsfsFilePath
from recidiviz.persistence.database.base_schema import OperationsBase
from recidiviz.persistence.database.schema.operations import schema, dao
from recidiviz.persistence.database.schema_entity_converter.schema_entity_converter import \
    convert_schema_object_to_entity
from recidiviz.persistence.database.session_factory import SessionFactory
from recidiviz.persistence.entity.operations.entities import DirectIngestRawFileMetadata, \
    DirectIngestIngestFileMetadata, DirectIngestFileMetadata


class PostgresDirectIngestFileMetadataManager(DirectIngestFileMetadataManager):
    """An implementation for a class that handles writing metadata about each direct ingest file to the operations
    Postgres table.
    """

    def __init__(self, region_code: str):
        self.region_code = region_code

    def register_ingest_file_export_job(self, ingest_view_job_args: GcsfsIngestViewExportArgs) -> None:
        session = SessionFactory.for_schema_base(OperationsBase)
        session.add(
            schema.DirectIngestIngestFileMetadata(
                region_code=self.region_code,
                file_tag=ingest_view_job_args.ingest_view_name,
                is_invalidated=False,
                job_creation_time=datetime.datetime.now(),
                datetimes_contained_lower_bound_exclusive=ingest_view_job_args.upper_bound_datetime_prev,
                datetimes_contained_upper_bound_inclusive=ingest_view_job_args.upper_bound_datetime_to_export
            )
        )
        session.commit()
        session.close()

    def register_new_file(self,
                          path: GcsfsFilePath) -> None:
        if not path.file_name.startswith(DIRECT_INGEST_UNPROCESSED_PREFIX):
            raise ValueError('Expect only unprocessed paths in this function.')

        parts = filename_parts_from_path(path)
        session = SessionFactory.for_schema_base(OperationsBase)
        if parts.file_type == GcsfsDirectIngestFileType.INGEST_VIEW:
            metadata = dao.get_file_metadata_row_for_path(session, self.region_code, path)
            metadata.discovery_time = datetime.datetime.utcnow()
        elif parts.file_type == GcsfsDirectIngestFileType.RAW_DATA:
            session.add(
                schema.DirectIngestRawFileMetadata(
                    region_code=self.region_code,
                    file_tag=parts.file_tag,
                    normalized_file_name=path.file_name,
                    discovery_time=datetime.datetime.utcnow(),
                    processed_time=None,
                    datetimes_contained_upper_bound_inclusive=parts.utc_upload_datetime
                )
            )
        else:
            raise ValueError(f'Unexpected path type: {parts.file_type}')
        session.commit()
        session.close()

    def get_file_metadata(self, path: GcsfsFilePath) -> DirectIngestFileMetadata:
        session = SessionFactory.for_schema_base(OperationsBase)
        metadata = dao.get_file_metadata_row_for_path(session, self.region_code, path)

        if isinstance(metadata, schema.DirectIngestRawFileMetadata):
            return self._raw_file_schema_metadata_as_entity(metadata)

        if isinstance(metadata, schema.DirectIngestIngestFileMetadata):
            return self._ingest_file_schema_metadata_as_entity(metadata)

        raise ValueError(f'Unexpected metadata type: {type(metadata)}')

    def mark_file_as_processed(self,
                               path: GcsfsFilePath,
                               metadata: DirectIngestFileMetadata) -> None:
        session = SessionFactory.for_schema_base(OperationsBase)
        parts = filename_parts_from_path(path)
        metadata = dao.get_file_metadata_row(session, parts.file_type, metadata.file_id)
        metadata.processed_time = datetime.datetime.utcnow()
        session.commit()
        session.close()

    def get_ingest_view_metadata_for_job(
            self, ingest_view_job_args: GcsfsIngestViewExportArgs) -> DirectIngestIngestFileMetadata:

        session = SessionFactory.for_schema_base(OperationsBase)
        metadata = dao.get_ingest_view_metadata_for_job(
            session=session,
            region_code=self.region_code,
            file_tag=ingest_view_job_args.ingest_view_name,
            datetimes_contained_lower_bound_exclusive=ingest_view_job_args.upper_bound_datetime_prev,
            datetimes_contained_upper_bound_inclusive=ingest_view_job_args.upper_bound_datetime_to_export
        )

        return self._ingest_file_schema_metadata_as_entity(metadata)

    def mark_ingest_view_exported(self,
                                  metadata: DirectIngestIngestFileMetadata,
                                  exported_path: GcsfsFilePath) -> None:
        parts = filename_parts_from_path(exported_path)
        if parts.file_type != GcsfsDirectIngestFileType.INGEST_VIEW:
            raise ValueError(f'Exported path has unexpected type {parts.file_type}')

        session = SessionFactory.for_schema_base(OperationsBase)

        metadata = dao.get_file_metadata_row(session, GcsfsDirectIngestFileType.INGEST_VIEW, metadata.file_id)
        metadata.export_time = datetime.datetime.utcnow()
        metadata.normalized_file_name = exported_path.file_name
        session.commit()
        session.close()

    def get_ingest_view_metadata_for_most_recent_valid_job(
            self,
            ingest_view_tag: str
    ) -> Optional[DirectIngestIngestFileMetadata]:
        session = SessionFactory.for_schema_base(OperationsBase)

        metadata = dao.get_ingest_view_metadata_for_most_recent_valid_job(
            session=session,
            region_code=self.region_code,
            file_tag=ingest_view_tag
        )

        if not metadata:
            return None

        return self._ingest_file_schema_metadata_as_entity(metadata)

    def get_ingest_view_metadata_pending_export(self) -> List[DirectIngestIngestFileMetadata]:
        session = SessionFactory.for_schema_base(OperationsBase)
        results = dao.get_ingest_view_metadata_pending_export(
            session=session,
            region_code=self.region_code,
        )

        return [self._ingest_file_schema_metadata_as_entity(metadata) for metadata in results]

    def get_metadata_for_raw_files_discovered_after_datetime(
            self,
            raw_file_tag: str,
            discovery_time_lower_bound_exclusive: Optional[datetime.datetime]
    ) -> List[DirectIngestRawFileMetadata]:
        session = SessionFactory.for_schema_base(OperationsBase)

        results = dao.get_metadata_for_raw_files_discovered_after_datetime(
            session=session,
            region_code=self.region_code,
            raw_file_tag=raw_file_tag,
            discovery_time_lower_bound_exclusive=discovery_time_lower_bound_exclusive
        )

        return [self._raw_file_schema_metadata_as_entity(metadata) for metadata in results]

    @staticmethod
    def _raw_file_schema_metadata_as_entity(
            schema_metadata: schema.DirectIngestRawFileMetadata) -> DirectIngestRawFileMetadata:
        entity_metadata = convert_schema_object_to_entity(schema_metadata)

        if not isinstance(entity_metadata, DirectIngestRawFileMetadata):
            raise ValueError(f'Unexpected metadata entity type: {type(entity_metadata)}')

        return entity_metadata

    @staticmethod
    def _ingest_file_schema_metadata_as_entity(
            schema_metadata: schema.DirectIngestIngestFileMetadata) -> DirectIngestIngestFileMetadata:
        entity_metadata = convert_schema_object_to_entity(schema_metadata)

        if not isinstance(entity_metadata, DirectIngestIngestFileMetadata):
            raise ValueError(f'Unexpected metadata entity type: {type(entity_metadata)}')

        return entity_metadata