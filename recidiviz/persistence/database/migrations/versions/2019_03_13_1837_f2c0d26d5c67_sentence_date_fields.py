"""sentence_date_fields

Revision ID: f2c0d26d5c67
Revises: 1662025f6145
Create Date: 2019-03-13 18:37:41.781966

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f2c0d26d5c67'
down_revision = '1662025f6145'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('sentence', sa.Column('completion_date', sa.Date(), nullable=True))
    op.add_column('sentence', sa.Column('date_imposed', sa.Date(), nullable=True))
    op.add_column('sentence', sa.Column('projected_completion_date', sa.Date(), nullable=True))
    op.add_column('sentence_history', sa.Column('completion_date', sa.Date(), nullable=True))
    op.add_column('sentence_history', sa.Column('date_imposed', sa.Date(), nullable=True))
    op.add_column('sentence_history', sa.Column('projected_completion_date', sa.Date(), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('sentence_history', 'projected_completion_date')
    op.drop_column('sentence_history', 'date_imposed')
    op.drop_column('sentence_history', 'completion_date')
    op.drop_column('sentence', 'projected_completion_date')
    op.drop_column('sentence', 'date_imposed')
    op.drop_column('sentence', 'completion_date')
    # ### end Alembic commands ###
