"""Record which embedder produced each job embedding vector.

Legacy vectors have unknown provenance and remain unlabelled. Dimension
alone cannot identify a model. A future enrichment run can regenerate them;
until then they degrade to keyword matching.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018_embedding_model"
down_revision = "0017_phone_members"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("embedding_model", sa.String(length=60), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "embedding_model")
