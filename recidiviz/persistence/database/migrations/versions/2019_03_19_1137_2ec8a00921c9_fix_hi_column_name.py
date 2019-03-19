"""fix_hi_column_name

Revision ID: 2ec8a00921c9
Revises: 8741527863fd
Create Date: 2019-03-19 11:37:15.523125

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '2ec8a00921c9'
down_revision = '8741527863fd'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('hi_facility_aggregate',
    sa.Column('record_id', sa.Integer(), nullable=False),
    sa.Column('fips', sa.String(length=255), nullable=False),
    sa.Column('report_date', sa.Date(), nullable=False),
    sa.Column('aggregation_window', postgresql.ENUM('DAILY', 'WEEKLY', 'MONTHLY', 'QUARTERLY', 'YEARLY', create_type=False, name='time_granularity'), nullable=False),
    sa.Column('report_frequency', postgresql.ENUM('DAILY', 'WEEKLY', 'MONTHLY', 'QUARTERLY', 'YEARLY', create_type=False, name='time_granularity'), nullable=False),
    sa.Column('facility_name', sa.String(length=255), nullable=False),
    sa.Column('design_bed_capacity', sa.Integer(), nullable=True),
    sa.Column('operation_bed_capacity', sa.Integer(), nullable=True),
    sa.Column('total_population', sa.Integer(), nullable=True),
    sa.Column('male_population', sa.Integer(), nullable=True),
    sa.Column('female_population', sa.Integer(), nullable=True),
    sa.Column('sentenced_felony_male_population', sa.Integer(), nullable=True),
    sa.Column('sentenced_felony_female_population', sa.Integer(), nullable=True),
    sa.Column('sentenced_felony_probation_male_population', sa.Integer(), nullable=True),
    sa.Column('sentenced_felony_probation_female_population', sa.Integer(), nullable=True),
    sa.Column('sentenced_misdemeanor_male_population', sa.Integer(), nullable=True),
    sa.Column('sentenced_misdemeanor_female_population', sa.Integer(), nullable=True),
    sa.Column('pretrial_felony_male_population', sa.Integer(), nullable=True),
    sa.Column('pretrial_felony_female_population', sa.Integer(), nullable=True),
    sa.Column('pretrial_misdemeanor_male_population', sa.Integer(), nullable=True),
    sa.Column('pretrial_misdemeanor_female_population', sa.Integer(), nullable=True),
    sa.Column('held_for_other_jurisdiction_male_population', sa.Integer(), nullable=True),
    sa.Column('held_for_other_jurisdiction_female_population', sa.Integer(), nullable=True),
    sa.Column('parole_violation_male_population', sa.Integer(), nullable=True),
    sa.Column('parole_violation_female_population', sa.Integer(), nullable=True),
    sa.Column('probation_violation_male_population', sa.Integer(), nullable=True),
    sa.Column('probation_violation_female_population', sa.Integer(), nullable=True),
    sa.PrimaryKeyConstraint('record_id'),
    sa.UniqueConstraint('fips', 'facility_name', 'report_date', 'aggregation_window')
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('hi_facility_aggregate')
    # ### end Alembic commands ###
