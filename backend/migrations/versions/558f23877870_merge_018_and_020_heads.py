"""merge 018 and 020 heads

Revision ID: 558f23877870
Revises: 018, 020
Create Date: 2026-05-07 19:33:46.871176

"""
from typing import Sequence, Union

revision: str = '558f23877870'
down_revision: Union[str, None] = ('018', '020')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    pass

def downgrade() -> None:
    pass
