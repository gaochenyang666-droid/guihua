"""add indexes on comments vote notifications

Revision ID: 3bca8decaf57
Revises: 
Create Date: 2026-03-19 20:47:35.597072

"""
from alembic import op


revision = '3bca8decaf57'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('comments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_comments_author_id'), ['author_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_comments_post_id'), ['post_id'], unique=False)

    with op.batch_alter_table('notifications', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_notifications_sender_id'), ['sender_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_notifications_user_id'), ['user_id'], unique=False)

    with op.batch_alter_table('votes', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_votes_post_id'), ['post_id'], unique=False)


def downgrade():
    with op.batch_alter_table('votes', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_votes_post_id'))

    with op.batch_alter_table('notifications', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_notifications_user_id'))
        batch_op.drop_index(batch_op.f('ix_notifications_sender_id'))

    with op.batch_alter_table('comments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_comments_post_id'))
        batch_op.drop_index(batch_op.f('ix_comments_author_id'))
