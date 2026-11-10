"""Initial catalog schema (immutable snapshot; safe for future migrations).

Revision ID: 0001
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('anime',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('source_title', sa.String(500), nullable=False),
        sa.Column('overview', sa.Text()),
        sa.Column('year', sa.Integer()),
        sa.Column('premiere', sa.String(32)),
        sa.Column('anidb_id', sa.Integer()),
        sa.Column('anilist_id', sa.Integer()),
        sa.Column('provider_ids', sa.JSON(), nullable=False),
        sa.Column('match_status', sa.String(30), nullable=False),
        sa.Column('match_confidence', sa.Float()),
        sa.Column('match_candidates', sa.JSON(), nullable=False),
        sa.Column('total_episodes', sa.Integer()),
        sa.Column('file_count', sa.Integer(), nullable=False),
        sa.Column('dubbed_count', sa.Integer(), nullable=False),
        sa.Column('audio_languages', sa.JSON(), nullable=False),
        sa.Column('subtitle_languages', sa.JSON(), nullable=False),
        sa.Column('release_groups', sa.JSON(), nullable=False),
        sa.Column('studios', sa.JSON(), nullable=False),
        sa.Column('relations', sa.JSON(), nullable=False),
        sa.Column('cover_url', sa.Text()),
        sa.Column('personal_rating', sa.Float()),
        sa.Column('personal_review', sa.Text(), nullable=False),
        sa.Column('available', sa.Boolean(), nullable=False),
        sa.Column('enriched_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_anime_anidb_id', 'anime', ['anidb_id'])
    op.create_index('ix_anime_anilist_id', 'anime', ['anilist_id'])
    op.create_table('episodes',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('anime_id', sa.String(64), sa.ForeignKey('anime.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(500), nullable=False),
        sa.Column('season', sa.Integer()),
        sa.Column('number', sa.Integer()),
        sa.Column('path', sa.Text()),
        sa.Column('audio_languages', sa.JSON(), nullable=False),
        sa.Column('subtitle_languages', sa.JSON(), nullable=False),
        sa.Column('release_group', sa.String(200)),
    )
    op.create_index('ix_episodes_anime_id', 'episodes', ['anime_id'])
    op.create_table('sidecars',
        sa.Column('relative_path', sa.Text(), primary_key=True),
        sa.Column('release', sa.String(500), nullable=False),
        sa.Column('language_hint', sa.String(30)),
        sa.Column('episode_hint', sa.Integer()),
        sa.Column('extension', sa.String(20), nullable=False),
        sa.Column('seen_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_sidecars_release', 'sidecars', ['release'])
    op.create_table('state',
        sa.Column('key', sa.String(120), primary_key=True),
        sa.Column('value', sa.Text(), nullable=False),
    )


def downgrade():
    op.drop_table('state')
    op.drop_index('ix_sidecars_release', table_name='sidecars')
    op.drop_table('sidecars')
    op.drop_index('ix_episodes_anime_id', table_name='episodes')
    op.drop_table('episodes')
    op.drop_index('ix_anime_anilist_id', table_name='anime')
    op.drop_index('ix_anime_anidb_id', table_name='anime')
    op.drop_table('anime')
