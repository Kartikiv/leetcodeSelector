#!/usr/bin/env python3
"""
Migrate existing file-based data to PostgreSQL.

Usage:
    python migrate_to_postgres.py

Set DATABASE_URL env var to override the default connection string.
Default: postgresql://localhost/leetcode_selector
"""

import json
import os
import sys
from datetime import datetime

from app import app, seed_public_problem_sets
from models import db, User, ProblemSet, ProblemSetProblem, DifficultyCache, \
    UserProgress, UserSession, UserSessionProblem, UserActiveSet
from werkzeug.security import generate_password_hash


def migrate_difficulty_cache():
    """Migrate global difficulty_cache.json → difficulty_cache table."""
    cache_file = 'difficulty_cache.json'
    if not os.path.exists(cache_file):
        print("No global difficulty_cache.json found, skipping.")
        return

    with open(cache_file) as f:
        cache = json.load(f)

    count = 0
    for slug, difficulty in cache.items():
        if not DifficultyCache.query.filter_by(problem_slug=slug).first():
            db.session.add(DifficultyCache(problem_slug=slug, difficulty=difficulty))
            count += 1

    db.session.commit()
    print(f"Migrated {count} difficulty cache entries.")


def migrate_users():
    """Migrate users/users.json → users table. Returns {old_id: new_user} map."""
    users_file = 'users/users.json'
    if not os.path.exists(users_file):
        print("No users/users.json found, skipping user migration.")
        return {}

    with open(users_file) as f:
        users_db = json.load(f)

    user_map = {}  # old string ID → new User object
    for old_id, data in users_db.items():
        existing = User.query.filter_by(username=data['username']).first()
        if existing:
            print(f"  User '{data['username']}' already exists, skipping.")
            user_map[old_id] = existing
            continue

        user = User(
            username=data['username'],
            email=data['email'],
            password_hash=data['password_hash'],
            created_at=datetime.strptime(data.get('created_at', '2026-01-01 00:00:00'), '%Y-%m-%d %H:%M:%S')
        )
        db.session.add(user)
        db.session.flush()
        user_map[old_id] = user
        print(f"  Migrated user: {data['username']} (old id={old_id} → new id={user.id})")

    db.session.commit()
    return user_map


def migrate_private_problem_sets(old_user_id: str, new_user: User):
    """Migrate users/{old_id}/problem_sets/*.json → problem_sets table."""
    sets_dir = f'users/{old_user_id}/problem_sets'
    if not os.path.exists(sets_dir):
        return

    for filename in os.listdir(sets_dir):
        if not filename.endswith('.json'):
            continue
        filepath = os.path.join(sets_dir, filename)
        try:
            with open(filepath) as f:
                data = json.load(f)

            set_id = data['id']
            if ProblemSet.query.filter_by(set_id=set_id).first():
                print(f"    Problem set '{set_id}' already exists, skipping.")
                continue

            ps = ProblemSet(
                set_id=set_id,
                name=data['name'],
                description=data.get('description', ''),
                is_public=False,
                owner_user_id=new_user.id,
                created_by=data.get('created_by', str(new_user.id)),
                created_at=datetime.utcnow()
            )
            db.session.add(ps)
            db.session.flush()

            position = 0
            for category, urls in data['problems'].items():
                for url in urls:
                    db.session.add(ProblemSetProblem(
                        problem_set_id=ps.id,
                        category=category,
                        problem_url=url,
                        position=position
                    ))
                    position += 1

            db.session.commit()
            print(f"    Migrated private set: {data['name']}")
        except Exception as e:
            db.session.rollback()
            print(f"    Error migrating {filename}: {e}")


def migrate_user_progress(old_user_id: str, new_user: User):
    """Migrate users/{old_id}/progress.json → user_progress + user_sessions tables."""
    progress_file = f'users/{old_user_id}/progress.json'
    if not os.path.exists(progress_file):
        print(f"  No progress.json for user {old_user_id}, skipping.")
        return

    with open(progress_file) as f:
        data = json.load(f)

    # Migrate completed
    completed = data.get('completed', [])
    skipped = data.get('skipped', [])
    revisit = data.get('revisit', [])

    # Build combined url set
    all_urls = set(completed) | set(skipped) | set(revisit)
    skipped_set = set(skipped)
    completed_set = set(completed)
    revisit_set = set(revisit)

    existing = {r.problem_url for r in UserProgress.query.filter_by(user_id=new_user.id).all()}

    count = 0
    for url in all_urls:
        if url in existing:
            continue
        row = UserProgress(
            user_id=new_user.id,
            problem_url=url,
            is_completed=url in completed_set,
            is_skipped=url in skipped_set and url not in completed_set,
            is_revisit=url in revisit_set,
            completed_at=datetime.utcnow() if url in completed_set else None
        )
        db.session.add(row)
        count += 1

    db.session.flush()

    # Migrate session
    session_data = data.get('current_session', {})
    session_problems = session_data.get('problems', [])

    if session_problems:
        s = UserSession.query.filter_by(user_id=new_user.id).first()
        if not s:
            s = UserSession(
                user_id=new_user.id,
                easy_completed=session_data.get('easy_completed', 0),
                medium_completed=session_data.get('medium_completed', 0),
                hard_completed=session_data.get('hard_completed', 0),
                total_completed=session_data.get('total_completed', 0),
                generated_at=datetime.utcnow()
            )
            db.session.add(s)
            db.session.flush()

            for i, url in enumerate(session_problems):
                db.session.add(UserSessionProblem(session_id=s.id, problem_url=url, position=i))

    # Migrate active set
    active_file = f'users/{old_user_id}/active_problem_set.json'
    if os.path.exists(active_file):
        try:
            with open(active_file) as f:
                active_data = json.load(f)
            set_id = active_data.get('set_id')
            if set_id and not UserActiveSet.query.filter_by(user_id=new_user.id).first():
                db.session.add(UserActiveSet(user_id=new_user.id, set_id=set_id))
        except Exception as e:
            print(f"  Error migrating active set: {e}")

    db.session.commit()
    print(f"  Migrated {count} progress rows for user {new_user.username} "
          f"({len(completed)} completed, {len(skipped)} skipped, {len(revisit)} revisit).")


def main():
    with app.app_context():
        print("Creating tables if they don't exist...")
        db.create_all()

        print("\n1. Migrating difficulty cache...")
        migrate_difficulty_cache()

        print("\n2. Seeding public problem sets...")
        seed_public_problem_sets()

        print("\n3. Migrating users...")
        user_map = migrate_users()

        print("\n4. Migrating per-user data...")
        users_dir = 'users'
        if os.path.exists(users_dir):
            for old_id in os.listdir(users_dir):
                if not os.path.isdir(os.path.join(users_dir, old_id)) or old_id == 'users':
                    continue
                if old_id not in user_map:
                    print(f"  No user mapping for directory '{old_id}', skipping.")
                    continue
                new_user = user_map[old_id]
                print(f"  Processing user {old_id} → {new_user.username}...")
                migrate_private_problem_sets(old_id, new_user)
                migrate_user_progress(old_id, new_user)

        print("\nMigration complete!")


if __name__ == '__main__':
    main()
