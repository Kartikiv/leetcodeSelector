from flask import Flask, render_template, jsonify, request, redirect, url_for, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import json
import random
import os
import requests
import time
from typing import Dict, List
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from models import db, User, ProblemSet, ProblemSetProblem, DifficultyCache, \
    UserProgress, UserSession, UserSessionProblem, UserActiveSet
app = Flask(__name__)

app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-change-in-production')
app.config['PERMANENT_SESSION_LIFETIME'] = 2592000  # 30 days

app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'DATABASE_URL',
    'postgresql://postgres:8182@localhost:5432/leetcode_selector'
)

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 300,
}

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db.init_app(app)

# Setup Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ---------------------------------------------------------------------------
# User helpers (replaces file-based User class methods)
# ---------------------------------------------------------------------------

def create_user(username, email, password):
    """Create a new user. Returns (user, error_message)."""
    if User.query.filter_by(username=username).first():
        return None, "Username already exists"
    if User.query.filter_by(email=email).first():
        return None, "Email already exists"

    user = User(
        username=username,
        email=email,
        password_hash=generate_password_hash(password, method='pbkdf2:sha256'),
        created_at=datetime.utcnow()
    )
    db.session.add(user)
    db.session.commit()
    return user, None


def verify_password(username, password):
    """Verify credentials. Returns User or None."""
    user = User.query.filter_by(username=username).first()
    if user and check_password_hash(user.password_hash, password):
        return user
    return None


# ---------------------------------------------------------------------------
# LeetCodeProblemSelector
# ---------------------------------------------------------------------------

class LeetCodeProblemSelector:
    # In-memory difficulty cache shared across all instances (synced with DB)
    _global_difficulty_cache: Dict[str, str] = None

    def __init__(self, user_id: int):
        self.user_id = user_id

        # Load global cache once
        if LeetCodeProblemSelector._global_difficulty_cache is None:
            LeetCodeProblemSelector._global_difficulty_cache = self._load_global_difficulty_cache()

        # In-memory state (lazily populated from DB)
        self.problems_data: Dict[str, List[str]] = None
        self.difficulty_map: Dict[str, List[str]] = None
        self._active_set_id: str = None

        # Load active problem set
        self._load_active_problem_set()

    # ------------------------------------------------------------------
    # Difficulty cache
    # ------------------------------------------------------------------

    def _load_global_difficulty_cache(self) -> Dict[str, str]:
        rows = DifficultyCache.query.all()
        cache = {r.problem_slug: r.difficulty for r in rows}
        print(f"Loaded global difficulty cache with {len(cache)} entries")
        return cache

    def _save_difficulty_entry(self, slug: str, difficulty: str):
        """Upsert a single entry into the difficulty_cache table."""
        row = DifficultyCache.query.filter_by(problem_slug=slug).first()
        if row:
            row.difficulty = difficulty
            row.updated_at = datetime.utcnow()
        else:
            row = DifficultyCache(problem_slug=slug, difficulty=difficulty)
            db.session.add(row)
        db.session.commit()

    # ------------------------------------------------------------------
    # Problem sets
    # ------------------------------------------------------------------

    def _load_active_problem_set(self):
        active = UserActiveSet.query.filter_by(user_id=self.user_id).first()
        if active:
            self._active_set_id = active.set_id
            self._load_problem_set_by_id(active.set_id)

    def _load_problem_set_by_id(self, set_id: str) -> bool:
        ps = ProblemSet.query.filter_by(set_id=set_id).first()
        if not ps:
            return False

        problems_data: Dict[str, List[str]] = {}
        for p in ps.problems.order_by(ProblemSetProblem.position):
            problems_data.setdefault(p.category, []).append(p.problem_url)

        self.problems_data = problems_data
        self.difficulty_map = self._initialize_difficulty_map()
        return True

    def _count_problems_in_set(self, problems_data) -> int:
        if isinstance(problems_data, dict):
            return sum(len(v) for v in problems_data.values() if isinstance(v, list))
        elif isinstance(problems_data, list):
            return len(problems_data)
        return 0

    def get_problem_sets(self):
        active = UserActiveSet.query.filter_by(user_id=self.user_id).first()
        active_set_id = active.set_id if active else None

        sets = []

        # Public sets
        public_sets = ProblemSet.query.filter_by(is_public=True).all()
        for ps in public_sets:
            problem_count = ps.problems.count()
            sets.append({
                'id': ps.set_id,
                'name': ps.name,
                'description': ps.description or '',
                'problem_count': problem_count,
                'is_public': True,
                'is_active': ps.set_id == active_set_id,
                'created_by': ps.created_by or 'System',
                'created_at': ps.created_at.strftime('%Y-%m-%d') if ps.created_at else ''
            })

        # User's private sets
        private_sets = ProblemSet.query.filter_by(is_public=False, owner_user_id=self.user_id).all()
        for ps in private_sets:
            problem_count = ps.problems.count()
            sets.append({
                'id': ps.set_id,
                'name': ps.name,
                'description': ps.description or '',
                'problem_count': problem_count,
                'is_public': False,
                'is_active': ps.set_id == active_set_id,
                'created_by': 'You',
                'created_at': ps.created_at.strftime('%Y-%m-%d') if ps.created_at else ''
            })

        return sorted(sets, key=lambda x: (not x['is_public'], x['name']))

    def create_problem_set(self, name: str, description: str, problems_json: str, is_public: bool = False):
        try:
            data = json.loads(problems_json)
            problems = data['result'] if 'result' in data else data

            set_id = name.lower().replace(' ', '_').replace('-', '_')
            set_id = ''.join(c for c in set_id if c.isalnum() or c == '_')
            set_id = f"{set_id}_{int(time.time())}"

            ps = ProblemSet(
                set_id=set_id,
                name=name,
                description=description,
                is_public=is_public,
                owner_user_id=self.user_id if not is_public else None,
                created_by=str(self.user_id),
                created_at=datetime.utcnow()
            )
            db.session.add(ps)
            db.session.flush()  # get ps.id before inserting problems

            position = 0
            for category, urls in problems.items():
                for url in urls:
                    db.session.add(ProblemSetProblem(
                        problem_set_id=ps.id,
                        category=category,
                        problem_url=url,
                        position=position
                    ))
                    position += 1

            db.session.commit()
            return set_id
        except Exception as e:
            db.session.rollback()
            print(f"Error creating problem set: {e}")
            import traceback
            traceback.print_exc()
            return None

    def set_active_problem_set(self, set_id: str) -> bool:
        if not self._load_problem_set_by_id(set_id):
            return False

        active = UserActiveSet.query.filter_by(user_id=self.user_id).first()
        if active:
            active.set_id = set_id
            active.updated_at = datetime.utcnow()
        else:
            db.session.add(UserActiveSet(user_id=self.user_id, set_id=set_id))

        db.session.commit()
        self._active_set_id = set_id
        return True

    def delete_problem_set(self, set_id: str) -> bool:
        ps = ProblemSet.query.filter_by(set_id=set_id, owner_user_id=self.user_id).first()
        if not ps:
            return False

        # Clear active set if it was this one
        active = UserActiveSet.query.filter_by(user_id=self.user_id, set_id=set_id).first()
        if active:
            db.session.delete(active)
            self.problems_data = None
            self.difficulty_map = None

        db.session.delete(ps)
        db.session.commit()
        return True

    def export_problem_set(self, set_id: str):
        ps = ProblemSet.query.filter_by(set_id=set_id).filter(
            (ProblemSet.is_public == True) | (ProblemSet.owner_user_id == self.user_id)
        ).first()
        if not ps:
            return None

        problems: Dict[str, List[str]] = {}
        for p in ps.problems.order_by(ProblemSetProblem.position):
            problems.setdefault(p.category, []).append(p.problem_url)

        return {
            'id': ps.set_id,
            'name': ps.name,
            'description': ps.description,
            'problems': problems,
            'created_by': ps.created_by,
            'created_at': ps.created_at.strftime('%Y-%m-%d %H:%M:%S') if ps.created_at else '',
            'is_public': ps.is_public
        }

    # ------------------------------------------------------------------
    # Load problems (from raw JSON upload)
    # ------------------------------------------------------------------

    def load_problems(self, problems_json: str) -> bool:
        try:
            data = json.loads(problems_json)
            problems = data['result'] if 'result' in data else data

            set_id = f"uploaded_{self.user_id}_{int(time.time())}"

            ps = ProblemSet(
                set_id=set_id,
                name=f"Uploaded Problems",
                description="Custom uploaded problem set",
                is_public=False,
                owner_user_id=self.user_id,
                created_by=str(self.user_id),
                created_at=datetime.utcnow()
            )
            db.session.add(ps)
            db.session.flush()

            position = 0
            for category, urls in problems.items():
                for url in urls:
                    db.session.add(ProblemSetProblem(
                        problem_set_id=ps.id,
                        category=category,
                        problem_url=url,
                        position=position
                    ))
                    position += 1

            db.session.commit()

            # Activate it
            self.set_active_problem_set(set_id)
            print(f"Problems loaded and activated for user {self.user_id}")
            return True
        except Exception as e:
            db.session.rollback()
            print(f"Error loading problems: {e}")
            import traceback
            traceback.print_exc()
            return False

    def has_problems_loaded(self) -> bool:
        return self.problems_data is not None

    # ------------------------------------------------------------------
    # Difficulty map
    # ------------------------------------------------------------------

    def _initialize_difficulty_map(self) -> Dict[str, List[str]]:
        difficulty_map = {'easy': [], 'medium': [], 'hard': []}

        all_problems = []
        problems_to_fetch = []
        cached_count = 0

        for category, urls in self.problems_data.items():
            for url in urls:
                slug = url.rstrip('/').split('/')[-1]
                all_problems.append((url, slug))
                if slug in LeetCodeProblemSelector._global_difficulty_cache:
                    difficulty_map[LeetCodeProblemSelector._global_difficulty_cache[slug]].append(url)
                    cached_count += 1
                else:
                    problems_to_fetch.append((url, slug))

        print(f"Found {cached_count} in cache, fetching {len(problems_to_fetch)} from API")

        if problems_to_fetch:
            new_entries: Dict[str, str] = {}

            with ThreadPoolExecutor(max_workers=10) as executor:
                future_to_problem = {
                    executor.submit(self._fetch_difficulty_parallel, url, slug): (url, slug)
                    for url, slug in problems_to_fetch
                }
                for future in as_completed(future_to_problem):
                    url, slug = future_to_problem[future]
                    try:
                        difficulty = future.result()
                        difficulty_map[difficulty].append(url)
                        new_entries[slug] = difficulty
                    except Exception as e:
                        print(f"Error fetching {slug}: {e}")
                        difficulty_map['medium'].append(url)

            # Bulk-upsert new cache entries
            for slug, difficulty in new_entries.items():
                LeetCodeProblemSelector._global_difficulty_cache[slug] = difficulty
                row = DifficultyCache.query.filter_by(problem_slug=slug).first()
                if row:
                    row.difficulty = difficulty
                    row.updated_at = datetime.utcnow()
                else:
                    db.session.add(DifficultyCache(problem_slug=slug, difficulty=difficulty))
            db.session.commit()

        return difficulty_map

    def _fetch_difficulty_parallel(self, problem_url: str, slug: str) -> str:
        if slug in LeetCodeProblemSelector._global_difficulty_cache:
            return LeetCodeProblemSelector._global_difficulty_cache[slug]

        try:
            response = requests.post(
                "https://leetcode.com/graphql",
                json={
                    "query": "query questionData($titleSlug: String!) { question(titleSlug: $titleSlug) { difficulty } }",
                    "variables": {"titleSlug": slug}
                },
                headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                if data.get('data') and data['data'].get('question'):
                    return data['data']['question']['difficulty'].lower()
        except Exception as e:
            print(f"Error fetching difficulty for {slug}: {e}")

        return 'medium'

    # ------------------------------------------------------------------
    # Progress helpers
    # ------------------------------------------------------------------

    def _get_progress_row(self, problem_url: str):
        return UserProgress.query.filter_by(user_id=self.user_id, problem_url=problem_url).first()

    def _get_or_create_progress_row(self, problem_url: str) -> UserProgress:
        row = self._get_progress_row(problem_url)
        if not row:
            row = UserProgress(user_id=self.user_id, problem_url=problem_url)
            db.session.add(row)
        return row

    def _get_session(self) -> UserSession:
        s = UserSession.query.filter_by(user_id=self.user_id).first()
        if not s:
            s = UserSession(user_id=self.user_id)
            db.session.add(s)
            db.session.flush()
        return s

    def _get_completed_urls(self) -> List[str]:
        rows = UserProgress.query.filter_by(user_id=self.user_id, is_completed=True).all()
        return [r.problem_url for r in rows]

    def _get_skipped_urls(self) -> List[str]:
        rows = UserProgress.query.filter_by(user_id=self.user_id, is_skipped=True).all()
        return [r.problem_url for r in rows]

    def _get_revisit_urls(self) -> List[str]:
        rows = UserProgress.query.filter_by(user_id=self.user_id, is_revisit=True).all()
        return [r.problem_url for r in rows]

    def _get_session_problem_urls(self) -> List[str]:
        s = UserSession.query.filter_by(user_id=self.user_id).first()
        if not s:
            return []
        return [p.problem_url for p in s.session_problems.order_by(UserSessionProblem.position)]

    def _can_select_hard_problems(self) -> bool:
        s = UserSession.query.filter_by(user_id=self.user_id).first()
        if not s:
            return False
        return s.easy_completed >= 20 and s.medium_completed >= 3

    # ------------------------------------------------------------------
    # Available problems (exclude completed)
    # ------------------------------------------------------------------

    def _get_available_problems(self, difficulty: str) -> List[str]:
        completed_set = set(self._get_completed_urls())
        return [p for p in self.difficulty_map[difficulty] if p not in completed_set]

    # ------------------------------------------------------------------
    # Session generation
    # ------------------------------------------------------------------

    def select_problems(self) -> List[Dict]:
        return self.select_problems_custom(20, 8, 2)

    def select_problems_custom(self, easy_count=20, medium_count=8, hard_count=2) -> List[Dict]:
        if not self.problems_data:
            return []

        selected = []

        available_easy = self._get_available_problems('easy')
        num_easy = min(easy_count, len(available_easy))
        if num_easy > 0:
            selected.extend([{'difficulty': 'easy', 'url': p} for p in random.sample(available_easy, num_easy)])

        available_medium = self._get_available_problems('medium')
        num_medium = min(medium_count, len(available_medium))
        if num_medium > 0:
            selected.extend([{'difficulty': 'medium', 'url': p} for p in random.sample(available_medium, num_medium)])

        available_hard = self._get_available_problems('hard')
        num_hard = min(hard_count, len(available_hard))
        if num_hard > 0:
            selected.extend([{'difficulty': 'hard', 'url': p} for p in random.sample(available_hard, num_hard)])

        # Persist session
        s = self._get_session()
        s.easy_completed = 0
        s.medium_completed = 0
        s.hard_completed = 0
        s.total_completed = 0
        s.generated_at = datetime.utcnow()

        # Replace session problems
        UserSessionProblem.query.filter_by(session_id=s.id).delete()
        for i, prob in enumerate(selected):
            db.session.add(UserSessionProblem(session_id=s.id, problem_url=prob['url'], position=i))

        db.session.commit()
        return selected

    # ------------------------------------------------------------------
    # Mark operations
    # ------------------------------------------------------------------

    def mark_complete(self, problem_url: str) -> bool:
        row = self._get_progress_row(problem_url)
        if row and row.is_completed:
            return False

        difficulty = self._get_difficulty(problem_url)
        if not difficulty:
            return False

        row = self._get_or_create_progress_row(problem_url)
        was_skipped = row.is_skipped
        row.is_completed = True
        row.is_skipped = False
        row.completed_at = datetime.utcnow()

        # Update session stats if problem is in current session
        session_urls = set(self._get_session_problem_urls())
        if problem_url in session_urls:
            s = self._get_session()
            s.__dict__[f'{difficulty}_completed'] = getattr(s, f'{difficulty}_completed') + 1
            s.total_completed += 1

        db.session.commit()
        return True

    def mark_skip(self, problem_url: str) -> Dict:
        row = self._get_progress_row(problem_url)
        if row and (row.is_skipped or row.is_completed):
            return {'success': False, 'replacement': None, 'difficulty': None}

        row = self._get_or_create_progress_row(problem_url)
        row.is_skipped = True

        difficulty = self._get_difficulty(problem_url)
        replacement = None

        if difficulty:
            available = self._get_available_problems(difficulty)
            # Exclude the skipped problem itself
            available = [p for p in available if p != problem_url]
            if available:
                replacement = random.choice(available)

                # Replace in session
                s = self._get_session()
                sp = UserSessionProblem.query.filter_by(
                    session_id=s.id, problem_url=problem_url
                ).first()
                if sp:
                    sp.problem_url = replacement

        db.session.commit()
        return {'success': True, 'replacement': replacement, 'difficulty': difficulty}

    def mark_revisit(self, problem_url: str) -> bool:
        row = self._get_progress_row(problem_url)
        if row and row.is_revisit:
            return False

        row = self._get_or_create_progress_row(problem_url)
        row.is_revisit = True
        db.session.commit()
        return True

    def is_in_revisit(self, problem_url: str) -> bool:
        row = self._get_progress_row(problem_url)
        return bool(row and row.is_revisit)

    def is_in_current_session(self, problem_url: str) -> bool:
        return problem_url in set(self._get_session_problem_urls())

    # ------------------------------------------------------------------
    # Difficulty / category lookups
    # ------------------------------------------------------------------

    def _get_difficulty(self, problem_url: str) -> str:
        if not self.difficulty_map:
            # Try cache directly
            slug = problem_url.rstrip('/').split('/')[-1]
            return LeetCodeProblemSelector._global_difficulty_cache.get(slug)
        for diff, problems in self.difficulty_map.items():
            if problem_url in problems:
                return diff
        return None

    def _get_problem_category(self, problem_url: str) -> str:
        if not self.problems_data:
            return "Unknown"
        for category, problems in self.problems_data.items():
            if problem_url in problems:
                return category
        return "Unknown"

    # ------------------------------------------------------------------
    # Progress / stats
    # ------------------------------------------------------------------

    def get_progress(self) -> Dict:
        s = UserSession.query.filter_by(user_id=self.user_id).first()
        session_problems = []
        sess_easy = sess_medium = sess_hard = sess_total = 0
        generated_at = None

        if s:
            session_problems = [p.problem_url for p in s.session_problems.order_by(UserSessionProblem.position)]
            sess_easy = s.easy_completed
            sess_medium = s.medium_completed
            sess_hard = s.hard_completed
            sess_total = s.total_completed
            generated_at = s.generated_at.strftime('%Y-%m-%d %H:%M:%S') if s.generated_at else None

        # Global stats from DB
        completed_rows = UserProgress.query.filter_by(user_id=self.user_id, is_completed=True).all()
        global_easy = global_medium = global_hard = 0
        for row in completed_rows:
            diff = self._get_difficulty(row.problem_url)
            if diff == 'easy':
                global_easy += 1
            elif diff == 'medium':
                global_medium += 1
            elif diff == 'hard':
                global_hard += 1

        can_unlock = bool(s and s.easy_completed >= 20 and s.medium_completed >= 3)

        skipped_count = UserProgress.query.filter_by(user_id=self.user_id, is_skipped=True).count()
        revisit_count = UserProgress.query.filter_by(user_id=self.user_id, is_revisit=True).count()

        return {
            'global': {
                'total': len(completed_rows),
                'easy': global_easy,
                'medium': global_medium,
                'hard': global_hard,
            },
            'session': {
                'total': sess_total,
                'easy': sess_easy,
                'medium': sess_medium,
                'hard': sess_hard,
                'total_problems': len(session_problems),
                'generated_at': generated_at,
                'can_unlock_hard': can_unlock,
                'needs_easy': max(0, 20 - sess_easy),
                'needs_medium': max(0, 3 - sess_medium)
            },
            'skipped': skipped_count,
            'revisit': revisit_count
        }

    def reset_all_progress(self) -> bool:
        UserProgress.query.filter_by(user_id=self.user_id).delete()
        s = UserSession.query.filter_by(user_id=self.user_id).first()
        if s:
            UserSessionProblem.query.filter_by(session_id=s.id).delete()
            s.easy_completed = 0
            s.medium_completed = 0
            s.hard_completed = 0
            s.total_completed = 0
            s.generated_at = None
        db.session.commit()
        return True

    def export_progress(self) -> Dict:
        completed = self._get_completed_urls()
        skipped = self._get_skipped_urls()
        revisit = self._get_revisit_urls()
        session_urls = self._get_session_problem_urls()

        s = UserSession.query.filter_by(user_id=self.user_id).first()
        sess_stats = {
            'problems': session_urls,
            'easy_completed': s.easy_completed if s else 0,
            'medium_completed': s.medium_completed if s else 0,
            'hard_completed': s.hard_completed if s else 0,
            'total_completed': s.total_completed if s else 0,
            'generated_at': s.generated_at.strftime('%Y-%m-%d %H:%M:%S') if s and s.generated_at else None
        }

        # Recompute global stats
        global_easy = sum(1 for u in completed if self._get_difficulty(u) == 'easy')
        global_medium = sum(1 for u in completed if self._get_difficulty(u) == 'medium')
        global_hard = sum(1 for u in completed if self._get_difficulty(u) == 'hard')

        return {
            'progress': {
                'completed': completed,
                'skipped': skipped,
                'revisit': revisit,
                'global_stats': {
                    'easy_completed': global_easy,
                    'medium_completed': global_medium,
                    'hard_completed': global_hard,
                    'total_completed': len(completed)
                },
                'current_session': sess_stats
            },
            'export_timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'version': '2.0'
        }

    def import_progress(self, import_data: Dict) -> bool:
        try:
            if 'progress' not in import_data:
                return False

            p = import_data['progress']
            required_keys = ['completed', 'skipped', 'revisit', 'global_stats', 'current_session']
            if not all(k in p for k in required_keys):
                return False

            existing_completed = set(self._get_completed_urls())
            all_completed = existing_completed | set(p['completed'])

            # Upsert completed
            for url in all_completed:
                row = self._get_or_create_progress_row(url)
                row.is_completed = True
                if not row.completed_at:
                    row.completed_at = datetime.utcnow()

            # Upsert skipped (only if not completed)
            for url in p['skipped']:
                if url not in all_completed:
                    row = self._get_or_create_progress_row(url)
                    row.is_skipped = True

            # Upsert revisit
            for url in p['revisit']:
                row = self._get_or_create_progress_row(url)
                row.is_revisit = True

            # Import session (remove already-completed)
            session_problems = [u for u in p['current_session'].get('problems', [])
                                 if u not in all_completed]

            s = self._get_session()
            s.easy_completed = 0
            s.medium_completed = 0
            s.hard_completed = 0
            s.total_completed = 0
            s.generated_at = datetime.utcnow()
            UserSessionProblem.query.filter_by(session_id=s.id).delete()
            for i, url in enumerate(session_problems):
                db.session.add(UserSessionProblem(session_id=s.id, problem_url=url, position=i))

            db.session.commit()
            return True
        except Exception as e:
            db.session.rollback()
            print(f"Error importing progress: {e}")
            import traceback
            traceback.print_exc()
            return False


# ---------------------------------------------------------------------------
# Selector factory
# ---------------------------------------------------------------------------

def get_selector():
    if not current_user.is_authenticated:
        return None
    return LeetCodeProblemSelector(current_user.id)


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@app.route('/login', methods=['GET'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    return render_template('login.html')


@app.route('/register', methods=['GET'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    return render_template('register.html')


@app.route('/api/register', methods=['POST'])
def api_register():
    data = request.json
    username = data.get('username', '').strip()
    email = data.get('email', '').strip()
    password = data.get('password', '')

    if not username or not email or not password:
        return jsonify({'success': False, 'message': 'All fields are required'})
    if len(password) < 6:
        return jsonify({'success': False, 'message': 'Password must be at least 6 characters'})

    user, error = create_user(username, email, password)
    if error:
        return jsonify({'success': False, 'message': error})

    login_user(user, remember=True)
    session.permanent = True
    return jsonify({'success': True, 'message': 'Account created successfully!'})


@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.json
    username = data.get('username', '')
    password = data.get('password', '')
    remember = data.get('remember', True)

    user = verify_password(username, password)
    if user:
        login_user(user, remember=remember)
        if remember:
            session.permanent = True
        return jsonify({'success': True, 'message': 'Login successful!'})

    return jsonify({'success': False, 'message': 'Invalid username or password'})


@app.route('/api/logout', methods=['POST'])
@login_required
def api_logout():
    logout_user()
    return jsonify({'success': True, 'message': 'Logged out successfully'})


@app.route('/api/current_user', methods=['GET'])
def api_current_user():
    if current_user.is_authenticated:
        return jsonify({'authenticated': True, 'username': current_user.username, 'email': current_user.email})
    return jsonify({'authenticated': False})


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------

@app.route('/')
@login_required
def index():
    return render_template('index.html', username=current_user.username)


@app.route('/problem_sets')
@login_required
def problem_sets_page():
    return render_template('problem_sets.html')


# ---------------------------------------------------------------------------
# Problem API routes
# ---------------------------------------------------------------------------

@app.route('/api/load_problems', methods=['POST'])
@login_required
def load_problems():
    selector = get_selector()
    if not selector:
        return jsonify({'success': False, 'message': 'User session error'})

    try:
        problems_json = None
        if 'file' in request.files:
            file = request.files['file']
            if file.filename == '':
                return jsonify({'success': False, 'message': 'No file selected'})
            if file and file.filename.endswith('.json'):
                problems_json = file.read().decode('utf-8')
        elif 'json_text' in request.form:
            problems_json = request.form['json_text']
        else:
            return jsonify({'success': False, 'message': 'No input provided'})

        if not problems_json:
            return jsonify({'success': False, 'message': 'No JSON content provided'})

        if selector.load_problems(problems_json):
            return jsonify({'success': True, 'message': 'Problems loaded successfully!'})
        return jsonify({'success': False, 'message': 'Invalid JSON format or error processing problems'})
    except Exception as e:
        print(f"Error in load_problems route: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/check_problems', methods=['GET'])
@login_required
def check_problems():
    selector = get_selector()
    if not selector:
        return jsonify({'loaded': False, 'has_session': False})

    has_problems = selector.has_problems_loaded()
    has_session = len(selector._get_session_problem_urls()) > 0
    return jsonify({'loaded': has_problems, 'has_session': has_session})


@app.route('/api/generate', methods=['POST'])
@login_required
def generate_problems():
    selector = get_selector()
    if not selector:
        return jsonify({'success': False, 'message': 'User session error'})

    if not selector.problems_data:
        return jsonify({'success': False, 'message': 'Please load problems first'})

    force_new = request.json.get('force_new', False) if request.is_json else False
    easy_count = request.json.get('easy_count', 20) if request.is_json else 20
    medium_count = request.json.get('medium_count', 8) if request.is_json else 8
    hard_count = request.json.get('hard_count', 2) if request.is_json else 2

    session_urls = selector._get_session_problem_urls()

    if not force_new and session_urls:
        completed_set = set(selector._get_completed_urls())
        problems = []
        for url in session_urls:
            if url in completed_set:
                continue
            difficulty = selector._get_difficulty(url)
            if difficulty:
                problems.append({
                    'url': url,
                    'difficulty': difficulty,
                    'category': selector._get_problem_category(url),
                    'is_revisit': selector.is_in_revisit(url)
                })
        return jsonify({'success': True, 'problems': problems, 'existing_session': True})

    problems = selector.select_problems_custom(easy_count, medium_count, hard_count)
    for problem in problems:
        problem['is_revisit'] = selector.is_in_revisit(problem['url'])
        problem['category'] = selector._get_problem_category(problem['url'])

    return jsonify({'success': True, 'problems': problems, 'existing_session': False})


@app.route('/api/mark_complete', methods=['POST'])
@login_required
def mark_complete():
    selector = get_selector()
    url = request.json.get('url')
    if selector.mark_complete(url):
        return jsonify({'success': True, 'progress': selector.get_progress()})
    return jsonify({'success': False, 'message': 'Problem already completed'})


@app.route('/api/mark_skip', methods=['POST'])
@login_required
def mark_skip():
    selector = get_selector()
    url = request.json.get('url')
    result = selector.mark_skip(url)
    if result['success']:
        response_data = {'success': True, 'progress': selector.get_progress()}
        if result['replacement']:
            response_data['replacement'] = {
                'url': result['replacement'],
                'difficulty': result['difficulty'],
                'is_revisit': selector.is_in_revisit(result['replacement'])
            }
        return jsonify(response_data)
    return jsonify({'success': False, 'message': 'Could not skip problem'})


@app.route('/api/mark_revisit', methods=['POST'])
@login_required
def mark_revisit():
    selector = get_selector()
    url = request.json.get('url')
    if selector.mark_revisit(url):
        return jsonify({'success': True, 'progress': selector.get_progress()})
    return jsonify({'success': False, 'message': 'Could not mark for revisit'})


@app.route('/api/progress', methods=['GET'])
@login_required
def get_progress():
    selector = get_selector()
    return jsonify(selector.get_progress())


@app.route('/api/lists/<list_type>', methods=['GET'])
@login_required
def get_list(list_type):
    selector = get_selector()
    if list_type == 'skipped':
        urls = selector._get_skipped_urls()
        url_data = [{
            'url': url,
            'is_revisit': selector.is_in_revisit(url),
            'difficulty': selector._get_difficulty(url),
            'category': selector._get_problem_category(url)
        } for url in urls]
        return jsonify({'urls': url_data})
    elif list_type == 'revisit':
        urls = selector._get_revisit_urls()
        url_data = [{
            'url': url,
            'is_revisit': True,
            'category': selector._get_problem_category(url)
        } for url in urls]
        return jsonify({'urls': url_data})
    return jsonify({'urls': []})


@app.route('/api/lists/<list_type>/<difficulty>', methods=['GET'])
@login_required
def get_list_by_difficulty(list_type, difficulty):
    selector = get_selector()
    if list_type == 'skipped':
        urls = selector._get_skipped_urls()
    elif list_type == 'revisit':
        urls = selector._get_revisit_urls()
    else:
        return jsonify({'urls': []})

    if difficulty != 'all':
        urls = [url for url in urls if selector._get_difficulty(url) == difficulty]

    if list_type == 'skipped':
        url_data = [{'url': url, 'is_revisit': selector.is_in_revisit(url), 'difficulty': selector._get_difficulty(url)} for url in urls]
    else:
        url_data = [{'url': url, 'difficulty': selector._get_difficulty(url)} for url in urls]

    return jsonify({'urls': url_data})


@app.route('/api/completed/<scope>/<difficulty>', methods=['GET'])
@login_required
def get_completed(scope, difficulty):
    selector = get_selector()
    completed_urls = selector._get_completed_urls()

    if scope == 'session':
        session_problems = set(selector._get_session_problem_urls())
        completed_urls = [url for url in completed_urls if url in session_problems]

    if difficulty != 'all':
        completed_urls = [url for url in completed_urls if selector._get_difficulty(url) == difficulty]

    url_data = [{
        'url': url,
        'is_revisit': selector.is_in_revisit(url),
        'category': selector._get_problem_category(url),
        'difficulty': selector._get_difficulty(url)
    } for url in completed_urls]

    return jsonify({'urls': url_data})


@app.route('/api/reset_progress', methods=['POST'])
@login_required
def reset_progress():
    selector = get_selector()
    if selector.reset_all_progress():
        return jsonify({'success': True, 'message': 'All progress has been reset'})
    return jsonify({'success': False, 'message': 'Failed to reset progress'})


@app.route('/api/export_progress', methods=['GET'])
@login_required
def export_progress():
    selector = get_selector()
    return jsonify(selector.export_progress())


@app.route('/api/import_progress', methods=['POST'])
@login_required
def import_progress():
    selector = get_selector()
    try:
        if selector.import_progress(request.json):
            return jsonify({'success': True, 'message': 'Progress imported successfully!'})
        return jsonify({'success': False, 'message': 'Invalid progress data format'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


# ---------------------------------------------------------------------------
# Problem set management routes
# ---------------------------------------------------------------------------

@app.route('/api/problem_sets', methods=['GET'])
@login_required
def get_problem_sets():
    selector = get_selector()
    return jsonify({'success': True, 'sets': selector.get_problem_sets()})


@app.route('/api/problem_sets', methods=['POST'])
@login_required
def create_problem_set():
    selector = get_selector()
    data = request.json
    name = data.get('name')
    description = data.get('description', '')
    problems_json = data.get('problems_json')
    is_public = data.get('is_public', False)

    if not name or not problems_json:
        return jsonify({'success': False, 'message': 'Name and problems data are required'})

    set_id = selector.create_problem_set(name, description, problems_json, is_public)
    if set_id:
        return jsonify({'success': True, 'set_id': set_id, 'message': f'Problem set "{name}" created successfully!'})
    return jsonify({'success': False, 'message': 'Failed to create problem set'})


@app.route('/api/problem_sets/<set_id>/activate', methods=['POST'])
@login_required
def activate_problem_set(set_id):
    selector = get_selector()
    if selector.set_active_problem_set(set_id):
        return jsonify({'success': True, 'message': 'Problem set activated successfully!'})
    return jsonify({'success': False, 'message': 'Failed to activate problem set'})


@app.route('/api/problem_sets/<set_id>', methods=['DELETE'])
@login_required
def delete_problem_set(set_id):
    selector = get_selector()
    if selector.delete_problem_set(set_id):
        return jsonify({'success': True, 'message': 'Problem set deleted successfully!'})
    return jsonify({'success': False, 'message': 'Failed to delete problem set or set does not exist'})


@app.route('/api/problem_sets/<set_id>/export', methods=['GET'])
@login_required
def export_problem_set(set_id):
    selector = get_selector()
    set_data = selector.export_problem_set(set_id)
    if set_data:
        return jsonify(set_data)
    return jsonify({'success': False, 'message': 'Problem set not found'}), 404


@app.route('/api/problem_sets/<set_id>/stats', methods=['GET'])
@login_required
def get_problem_set_stats(set_id):
    selector = get_selector()
    if not selector._load_problem_set_by_id(set_id):
        return jsonify({'success': False, 'message': 'Problem set not found'})

    all_problems = [url for urls in selector.problems_data.values() for url in urls]
    completed_set = set(selector._get_completed_urls())

    completed_problems = [p for p in all_problems if p in completed_set]
    pending_problems = [p for p in all_problems if p not in completed_set]

    def enrich(url):
        return {
            'url': url,
            'difficulty': selector._get_difficulty(url),
            'category': selector._get_problem_category(url),
            'is_revisit': selector.is_in_revisit(url)
        }

    return jsonify({
        'success': True,
        'total': len(all_problems),
        'completed': len(completed_problems),
        'pending': len(pending_problems),
        'completed_problems': [enrich(u) for u in completed_problems],
        'pending_problems': [enrich(u) for u in pending_problems]
    })


@app.route('/api/search_problem_sets', methods=['POST'])
@login_required
def search_problem_sets_api():
    selector = get_selector()
    if not selector:
        return jsonify({'success': False, 'error': 'User session error'})

    try:
        query = request.json.get('query', '').strip()
        all_sets = selector.get_problem_sets()

        if not query:
            return jsonify({'success': True, 'problem_sets': all_sets, 'total_sets': len(all_sets), 'query': ''})

        query_lower = query.lower()
        matched_sets = []
        for problem_set in all_sets:
            name_lower = problem_set['name'].lower()
            if query_lower == name_lower:
                score = 100
            elif name_lower.startswith(query_lower):
                score = 90
            elif f' {query_lower} ' in f' {name_lower} ':
                score = 80
            elif query_lower in name_lower:
                score = 70
            else:
                qi = 0
                for char in name_lower:
                    if qi < len(query_lower) and char == query_lower[qi]:
                        qi += 1
                score = 50 if qi == len(query_lower) else 0

            if score > 0:
                problem_set['match_score'] = score
                matched_sets.append(problem_set)

        matched_sets.sort(key=lambda x: (-x['match_score'], x['name']))
        for s in matched_sets:
            del s['match_score']

        return jsonify({'success': True, 'query': query, 'problem_sets': matched_sets, 'total_sets': len(matched_sets)})
    except Exception as e:
        print(f"Error searching problem sets: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/problem_set_details/<set_id>', methods=['GET'])
@login_required
def get_problem_set_details(set_id):
    selector = get_selector()
    if not selector._load_problem_set_by_id(set_id):
        return jsonify({'success': False, 'error': 'Problem set not found'}), 404

    try:
        difficulty_counts = {'Easy': 0, 'Medium': 0, 'Hard': 0}
        all_problems = []
        completed_set = set(selector._get_completed_urls())

        for category, problems in selector.problems_data.items():
            for url in problems:
                difficulty = selector._get_difficulty(url)
                if difficulty:
                    key = difficulty.capitalize()
                    if key in difficulty_counts:
                        difficulty_counts[key] += 1
                    all_problems.append({
                        'url': url,
                        'category': category,
                        'difficulty': key,
                        'completed': url in completed_set,
                        'is_revisit': selector.is_in_revisit(url)
                    })

        return jsonify({
            'success': True,
            'set_id': set_id,
            'counts': {**difficulty_counts, 'total': sum(difficulty_counts.values())},
            'problems': all_problems
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ---------------------------------------------------------------------------
# DB init + seed public problem sets
# ---------------------------------------------------------------------------

def seed_public_problem_sets():
    """Load public problem sets from JSON files into the DB (idempotent)."""
    public_dir = 'problem_sets/public'
    if not os.path.exists(public_dir):
        return

    for filename in os.listdir(public_dir):
        if not filename.endswith('.json'):
            continue
        filepath = os.path.join(public_dir, filename)
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)

            set_id = data['id']
            # Skip if already in DB
            if ProblemSet.query.filter_by(set_id=set_id).first():
                continue

            ps = ProblemSet(
                set_id=set_id,
                name=data['name'],
                description=data.get('description', ''),
                is_public=True,
                owner_user_id=None,
                created_by=data.get('created_by', 'System'),
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
            print(f"Seeded public problem set: {data['name']}")
        except Exception as e:
            db.session.rollback()
            print(f"Error seeding {filename}: {e}")


with app.app_context():
    db.create_all()
    seed_public_problem_sets()


if __name__ == '__main__':
    app.run(debug=True, port=3000)
