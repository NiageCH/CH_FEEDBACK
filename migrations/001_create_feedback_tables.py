"""
feedback/migrations/001_create_feedback_tables.py
Alembic migration — creates all Feedback module tables.
Run with: alembic upgrade head
"""

from alembic import op
import sqlalchemy as sa

revision = '001_feedback_tables'
down_revision = None   # set to your last existing migration ID
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('feedback_surveys',
        sa.Column('id',              sa.Integer(),     nullable=False),
        sa.Column('organization_id', sa.Integer(),     nullable=False),
        sa.Column('name',            sa.String(255),   nullable=False),
        sa.Column('qr_token',        sa.String(64),    nullable=False, unique=True),
        sa.Column('thank_you_msg',   sa.Text(),        nullable=True),
        sa.Column('is_active',       sa.Boolean(),     nullable=False, server_default='true'),
        sa.Column('created_at',      sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at',      sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_feedback_surveys_org',   'feedback_surveys', ['organization_id'])
    op.create_index('ix_feedback_surveys_token', 'feedback_surveys', ['qr_token'], unique=True)

    op.create_table('feedback_questions',
        sa.Column('id',         sa.Integer(),  nullable=False),
        sa.Column('survey_id',  sa.Integer(),  nullable=False),
        sa.Column('text',       sa.Text(),     nullable=False),
        sa.Column('type',       sa.String(20), nullable=False),
        sa.Column('sort_order', sa.Integer(),  nullable=False, server_default='0'),
        sa.Column('is_active',  sa.Boolean(),  nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("type IN ('stars','nps','yesno','text')", name='ck_question_type'),
        sa.ForeignKeyConstraint(['survey_id'], ['feedback_surveys.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_feedback_questions_survey', 'feedback_questions', ['survey_id'])

    op.create_table('feedback_responses',
        sa.Column('id',          sa.Integer(),  nullable=False),
        sa.Column('survey_id',   sa.Integer(),  nullable=False),
        sa.Column('branch_id',   sa.Integer(),  nullable=True),
        sa.Column('device_type', sa.String(20), nullable=True),
        sa.Column('created_at',  sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("device_type IN ('mobile','tablet','desktop')", name='ck_response_device'),
        sa.ForeignKeyConstraint(['survey_id'], ['feedback_surveys.id']),
        sa.ForeignKeyConstraint(['branch_id'], ['branches.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_feedback_responses_survey',     'feedback_responses', ['survey_id'])
    op.create_index('ix_feedback_responses_branch',     'feedback_responses', ['branch_id'])
    op.create_index('ix_feedback_responses_created_at', 'feedback_responses', ['created_at'])

    op.create_table('feedback_answers',
        sa.Column('id',          sa.Integer(),        nullable=False),
        sa.Column('response_id', sa.Integer(),        nullable=False),
        sa.Column('question_id', sa.Integer(),        nullable=False),
        sa.Column('value_num',   sa.Numeric(5, 2),    nullable=True),
        sa.Column('value_text',  sa.Text(),           nullable=True),
        sa.Column('created_at',  sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['response_id'], ['feedback_responses.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['question_id'], ['feedback_questions.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_feedback_answers_response', 'feedback_answers', ['response_id'])
    op.create_index('ix_feedback_answers_question', 'feedback_answers', ['question_id'])

    op.create_table('feedback_configs',
        sa.Column('id',              sa.Integer(),    nullable=False),
        sa.Column('organization_id', sa.Integer(),    nullable=False, unique=True),
        sa.Column('brand_color',     sa.String(7),    nullable=True, server_default="'#FAD51B'"),
        sa.Column('brand_name',      sa.String(255),  nullable=True),
        sa.Column('welcome_msg',     sa.Text(),       nullable=True),
        sa.Column('thank_you_msg',   sa.Text(),       nullable=True),
        sa.Column('show_powered_by', sa.Boolean(),    nullable=False, server_default='true'),
        sa.Column('created_at',      sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at',      sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('feedback_user_branches',
        sa.Column('user_id',    sa.Integer(), nullable=False),
        sa.Column('branch_id',  sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['user_id'],   ['users.id'],    ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['branch_id'], ['branches.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id', 'branch_id'),
    )


def downgrade():
    op.drop_table('feedback_user_branches')
    op.drop_table('feedback_configs')
    op.drop_table('feedback_answers')
    op.drop_table('feedback_responses')
    op.drop_table('feedback_questions')
    op.drop_table('feedback_surveys')
