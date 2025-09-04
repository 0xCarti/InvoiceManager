"""add purchase gl code to location stand item"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'add_purchase_gl_code_to_location_stand_item'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('location_stand_item', sa.Column('purchase_gl_code_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_location_stand_item_purchase_gl_code', 'location_stand_item', 'gl_code', ['purchase_gl_code_id'], ['id'])


def downgrade():
    op.drop_constraint('fk_location_stand_item_purchase_gl_code', 'location_stand_item', type_='foreignkey')
    op.drop_column('location_stand_item', 'purchase_gl_code_id')
