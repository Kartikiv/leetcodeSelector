from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()


class User(db.Model, UserMixin):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    progress = db.relationship('UserProgress', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    session = db.relationship('UserSession', backref='user', uselist=False, cascade='all, delete-orphan')
    active_set = db.relationship('UserActiveSet', backref='user', uselist=False, cascade='all, delete-orphan')
    problem_sets = db.relationship('ProblemSet', backref='owner', lazy='dynamic',
                                   foreign_keys='ProblemSet.owner_user_id')


class ProblemSet(db.Model):
    __tablename__ = 'problem_sets'

    id = db.Column(db.Integer, primary_key=True)
    set_id = db.Column(db.String(200), unique=True, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default='')
    is_public = db.Column(db.Boolean, default=False, index=True)
    owner_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    created_by = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    problems = db.relationship('ProblemSetProblem', backref='problem_set', lazy='dynamic',
                               cascade='all, delete-orphan', order_by='ProblemSetProblem.position')


class ProblemSetProblem(db.Model):
    __tablename__ = 'problem_set_problems'

    id = db.Column(db.Integer, primary_key=True)
    problem_set_id = db.Column(db.Integer, db.ForeignKey('problem_sets.id'), nullable=False, index=True)
    category = db.Column(db.String(200), nullable=False)
    problem_url = db.Column(db.String(500), nullable=False)
    position = db.Column(db.Integer, default=0)

    __table_args__ = (
        db.Index('ix_psp_set_category', 'problem_set_id', 'category'),
    )


class DifficultyCache(db.Model):
    __tablename__ = 'difficulty_cache'

    id = db.Column(db.Integer, primary_key=True)
    problem_slug = db.Column(db.String(300), unique=True, nullable=False, index=True)
    difficulty = db.Column(db.String(20), nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class UserProgress(db.Model):
    """Tracks per-problem status for each user."""
    __tablename__ = 'user_progress'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    problem_url = db.Column(db.String(500), nullable=False)
    is_completed = db.Column(db.Boolean, default=False)
    is_skipped = db.Column(db.Boolean, default=False)
    is_revisit = db.Column(db.Boolean, default=False)
    completed_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'problem_url', name='uq_user_problem'),
        db.Index('ix_up_user_completed', 'user_id', 'is_completed'),
        db.Index('ix_up_user_skipped', 'user_id', 'is_skipped'),
        db.Index('ix_up_user_revisit', 'user_id', 'is_revisit'),
    )


class UserSession(db.Model):
    """Stores the current active problem session for a user."""
    __tablename__ = 'user_sessions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False)
    easy_completed = db.Column(db.Integer, default=0)
    medium_completed = db.Column(db.Integer, default=0)
    hard_completed = db.Column(db.Integer, default=0)
    total_completed = db.Column(db.Integer, default=0)
    generated_at = db.Column(db.DateTime, nullable=True)

    session_problems = db.relationship('UserSessionProblem', backref='session', lazy='dynamic',
                                       cascade='all, delete-orphan', order_by='UserSessionProblem.position')


class UserSessionProblem(db.Model):
    """Problems in a user's current session (ordered)."""
    __tablename__ = 'user_session_problems'

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('user_sessions.id'), nullable=False, index=True)
    problem_url = db.Column(db.String(500), nullable=False)
    position = db.Column(db.Integer, default=0)


class UserActiveSet(db.Model):
    """Tracks which problem set a user currently has active."""
    __tablename__ = 'user_active_sets'

    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), primary_key=True)
    set_id = db.Column(db.String(200), nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
