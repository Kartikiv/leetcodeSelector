from flask import Flask, render_template, jsonify, request, send_from_directory, redirect, url_for, session
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import json
import random
import os
import requests
import time
from typing import Dict, List
from functools import wraps

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-change-in-production')
app.config['PERMANENT_SESSION_LIFETIME'] = 2592000  # 30 days
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs('users', exist_ok=True)

# Setup Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


class User(UserMixin):
    def __init__(self, user_id, username, email):
        self.id = user_id
        self.username = username
        self.email = email

    @staticmethod
    def get_users_db():
        """Get users database"""
        if os.path.exists('users/users.json'):
            with open('users/users.json', 'r') as f:
                return json.load(f)
        return {}

    @staticmethod
    def save_users_db(users_db):
        """Save users database"""
        with open('users/users.json', 'w') as f:
            json.dump(users_db, f, indent=2)

    @staticmethod
    def get(user_id):
        """Get user by ID"""
        users_db = User.get_users_db()
        if user_id in users_db:
            user_data = users_db[user_id]
            return User(user_id, user_data['username'], user_data['email'])
        return None

    @staticmethod
    def get_by_username(username):
        """Get user by username"""
        users_db = User.get_users_db()
        for user_id, user_data in users_db.items():
            if user_data['username'] == username:
                return User(user_id, user_data['username'], user_data['email'])
        return None

    @staticmethod
    def create(username, email, password):
        """Create a new user"""
        users_db = User.get_users_db()

        # Check if username or email already exists
        for user_data in users_db.values():
            if user_data['username'] == username:
                return None, "Username already exists"
            if user_data['email'] == email:
                return None, "Email already exists"

        # Generate unique user ID
        user_id = str(len(users_db) + 1)
        while user_id in users_db:
            user_id = str(int(user_id) + 1)

        # Create user directory
        user_dir = f'users/{user_id}'
        os.makedirs(user_dir, exist_ok=True)

        # Save user - use pbkdf2:sha256 method explicitly for Python 3.9 compatibility
        users_db[user_id] = {
            'username': username,
            'email': email,
            'password_hash': generate_password_hash(password, method='pbkdf2:sha256'),
            'created_at': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        User.save_users_db(users_db)

        return User(user_id, username, email), None

    @staticmethod
    def verify_password(username, password):
        """Verify user password"""
        users_db = User.get_users_db()
        for user_id, user_data in users_db.items():
            if user_data['username'] == username:
                if check_password_hash(user_data['password_hash'], password):
                    return User(user_id, user_data['username'], user_data['email'])
        return None


@login_manager.user_loader
def load_user(user_id):
    return User.get(user_id)


class LeetCodeProblemSelector:
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.user_dir = f'users/{user_id}'
        os.makedirs(self.user_dir, exist_ok=True)

        self.progress_file = f'{self.user_dir}/progress.json'
        self.difficulty_cache_file = f'{self.user_dir}/difficulty_cache.json'
        self.problems_file = f'{self.user_dir}/problems_data.json'

        self.progress = self._load_progress()
        self.problems_data = None
        self.difficulty_map = None
        self.difficulty_cache = self._load_difficulty_cache()

        # Try to load previously uploaded problems
        self._load_saved_problems()

    def load_problems(self, problems_json: str):
        """Load problems from JSON string"""
        try:
            data = json.loads(problems_json)
            self.problems_data = data['result'] if 'result' in data else data

            # Save the problems data for persistence
            with open(self.problems_file, 'w') as f:
                json.dump(self.problems_data, f, indent=2)

            self.difficulty_map = self._initialize_difficulty_map()
            print(f"Problems loaded successfully for user {self.user_id}")
            return True
        except Exception as e:
            print(f"Error loading problems: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _load_saved_problems(self):
        """Load previously saved problems data"""
        if os.path.exists(self.problems_file):
            try:
                with open(self.problems_file, 'r') as f:
                    self.problems_data = json.load(f)
                self.difficulty_map = self._initialize_difficulty_map()
                print(f"Loaded previously uploaded problems data for user {self.user_id}")
                return True
            except Exception as e:
                print(f"Error loading saved problems: {e}")
                import traceback
                traceback.print_exc()
        return False

    def has_problems_loaded(self) -> bool:
        """Check if problems data is loaded"""
        return self.problems_data is not None

    def _load_progress(self) -> Dict:
        """Load progress from file or create new if doesn't exist"""
        if os.path.exists(self.progress_file):
            with open(self.progress_file, 'r') as f:
                data = json.load(f)

            # Migrate old format to new format
            if 'global_stats' not in data:
                print("Migrating old progress format to new format...")
                old_easy = data.get('easy_completed', 0)
                old_medium = data.get('medium_completed', 0)
                old_hard = data.get('hard_completed', 0)

                data['global_stats'] = {
                    'easy_completed': old_easy,
                    'medium_completed': old_medium,
                    'hard_completed': old_hard,
                    'total_completed': old_easy + old_medium + old_hard
                }
                data['current_session'] = {
                    'problems': [],
                    'easy_completed': 0,
                    'medium_completed': 0,
                    'hard_completed': 0,
                    'total_completed': 0,
                    'generated_at': None
                }

                # Remove old keys
                for key in ['easy_completed', 'medium_completed', 'hard_completed']:
                    if key in data:
                        del data[key]

                self._save_progress_data(data)

            return data

        return {
            'completed': [],
            'skipped': [],
            'revisit': [],
            'global_stats': {
                'easy_completed': 0,
                'medium_completed': 0,
                'hard_completed': 0,
                'total_completed': 0
            },
            'current_session': {
                'problems': [],
                'easy_completed': 0,
                'medium_completed': 0,
                'hard_completed': 0,
                'total_completed': 0,
                'generated_at': None
            }
        }

    def _save_progress_data(self, data):
        """Save specific progress data to file"""
        with open(self.progress_file, 'w') as f:
            json.dump(data, f, indent=2)

    def _load_difficulty_cache(self) -> Dict:
        """Load difficulty cache from file"""
        if os.path.exists(self.difficulty_cache_file):
            with open(self.difficulty_cache_file, 'r') as f:
                return json.load(f)
        return {}

    def _save_difficulty_cache(self):
        """Save difficulty cache to file"""
        with open(self.difficulty_cache_file, 'w') as f:
            json.dump(self.difficulty_cache, f, indent=2)

    def _save_progress(self):
        """Save progress to file"""
        with open(self.progress_file, 'w') as f:
            json.dump(self.progress, f, indent=2)

    def _get_problem_difficulty_from_api(self, problem_url: str) -> str:
        """Fetch problem difficulty from LeetCode GraphQL API"""
        # Extract slug from URL
        slug = problem_url.rstrip('/').split('/')[-1]

        # Check cache first
        if slug in self.difficulty_cache:
            return self.difficulty_cache[slug]

        # LeetCode GraphQL API endpoint
        url = "https://leetcode.com/graphql"

        query = """
        query questionData($titleSlug: String!) {
            question(titleSlug: $titleSlug) {
                difficulty
            }
        }
        """

        payload = {
            "query": query,
            "variables": {"titleSlug": slug}
        }

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0"
        }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get('data') and data['data'].get('question'):
                    difficulty = data['data']['question']['difficulty']
                    # Convert to lowercase for consistency
                    difficulty = difficulty.lower() if difficulty else 'medium'

                    # Cache the result
                    self.difficulty_cache[slug] = difficulty
                    self._save_difficulty_cache()

                    return difficulty
        except Exception as e:
            print(f"Error fetching difficulty for {slug}: {e}")

        # Default to medium if API call fails
        return 'medium'

    def _initialize_difficulty_map(self) -> Dict[str, List[str]]:
        """Categorize problems by difficulty using cache first, then LeetCode API"""
        difficulty_map = {'easy': [], 'medium': [], 'hard': []}

        print("Building difficulty map...")
        total_problems = sum(len(problems) for problems in self.problems_data.values())
        processed = 0
        api_calls = 0

        for category, problems in self.problems_data.items():
            for problem_url in problems:
                # Extract slug to check cache
                slug = problem_url.rstrip('/').split('/')[-1]

                # Try cache first
                if slug in self.difficulty_cache:
                    difficulty = self.difficulty_cache[slug]
                else:
                    # Only fetch from API if not in cache
                    difficulty = self._get_problem_difficulty_from_api(problem_url)
                    api_calls += 1
                    # Small delay to avoid rate limiting only for API calls
                    time.sleep(0.1)

                difficulty_map[difficulty].append(problem_url)

                processed += 1
                if processed % 10 == 0:
                    print(f"Progress: {processed}/{total_problems} problems processed ({api_calls} API calls)")

        print(f"Difficulty map created: {len(difficulty_map['easy'])} easy, "
              f"{len(difficulty_map['medium'])} medium, {len(difficulty_map['hard'])} hard")
        print(f"Used cache for {processed - api_calls} problems, fetched {api_calls} from API")

        return difficulty_map

    def _get_available_problems(self, difficulty: str) -> List[str]:
        """Get problems of specified difficulty that haven't been completed"""
        completed_set = set(self.progress['completed'])
        available = [p for p in self.difficulty_map[difficulty] if p not in completed_set]
        return available

    def _can_select_hard_problems(self) -> bool:
        """Check if hard problems can be selected based on current session"""
        session = self.progress['current_session']
        return (session['easy_completed'] >= 20 and
                session['medium_completed'] >= 3)

    def select_problems(self) -> List[Dict]:
        """Select 30 random problems with difficulty labels and start new session"""
        if not self.problems_data:
            return []

        selected = []

        # Select 20 easy problems
        available_easy = self._get_available_problems('easy')
        if len(available_easy) >= 20:
            selected.extend([{'difficulty': 'easy', 'url': p} for p in random.sample(available_easy, 20)])
        else:
            selected.extend([{'difficulty': 'easy', 'url': p} for p in available_easy])

        # Select 8 medium problems
        available_medium = self._get_available_problems('medium')
        num_medium = min(8, len(available_medium))
        if num_medium > 0:
            selected.extend([{'difficulty': 'medium', 'url': p} for p in random.sample(available_medium, num_medium)])

        # Select 2 hard problems if unlocked (always available for new session)
        available_hard = self._get_available_problems('hard')
        num_hard = min(2, len(available_hard))
        if num_hard > 0:
            selected.extend([{'difficulty': 'hard', 'url': p} for p in random.sample(available_hard, num_hard)])

        # Initialize new session
        self.progress['current_session'] = {
            'problems': [p['url'] for p in selected],
            'easy_completed': 0,
            'medium_completed': 0,
            'hard_completed': 0,
            'total_completed': 0,
            'generated_at': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        self._save_progress()

        return selected

    def mark_complete(self, problem_url: str):
        """Mark a problem as completed (updates both session and global stats)"""
        if problem_url in self.progress['completed']:
            return False

        # Check if this was originally in the current session (even if skipped)
        was_in_session = problem_url in self.progress['current_session']['problems']

        # Remove from skipped if present (but keep in revisit)
        if problem_url in self.progress['skipped']:
            self.progress['skipped'].remove(problem_url)

        difficulty = self._get_difficulty(problem_url)
        if difficulty:
            # Add to completed list
            self.progress['completed'].append(problem_url)

            # Update global stats
            self.progress['global_stats'][f'{difficulty}_completed'] += 1
            self.progress['global_stats']['total_completed'] += 1

            # Update session stats if problem is in current session
            if was_in_session:
                self.progress['current_session'][f'{difficulty}_completed'] += 1
                self.progress['current_session']['total_completed'] += 1

            self._save_progress()
            return True
        return False

    def mark_skip(self, problem_url: str):
        """Mark a problem as skipped and return a replacement"""
        if problem_url not in self.progress['skipped'] and problem_url not in self.progress['completed']:
            self.progress['skipped'].append(problem_url)

            # Get a replacement problem of the same difficulty
            difficulty = self._get_difficulty(problem_url)
            if difficulty:
                available = self._get_available_problems(difficulty)
                if available:
                    replacement = random.choice(available)

                    # Update current session if the skipped problem was in it
                    if problem_url in self.progress['current_session']['problems']:
                        # Replace in session's problem list
                        index = self.progress['current_session']['problems'].index(problem_url)
                        self.progress['current_session']['problems'][index] = replacement

                    self._save_progress()
                    return {'success': True, 'replacement': replacement, 'difficulty': difficulty}

            self._save_progress()
            return {'success': True, 'replacement': None, 'difficulty': None}
        return {'success': False, 'replacement': None, 'difficulty': None}

    def mark_revisit(self, problem_url: str):
        """Mark a problem for revisit (persists even after completion)"""
        if problem_url not in self.progress['revisit']:
            self.progress['revisit'].append(problem_url)
            self._save_progress()
            return True
        return False

    def is_in_revisit(self, problem_url: str) -> bool:
        """Check if a problem is marked for revisit"""
        return problem_url in self.progress['revisit']

    def is_in_current_session(self, problem_url: str) -> bool:
        """Check if a problem is in the current session"""
        return problem_url in self.progress['current_session']['problems']

    def _get_difficulty(self, problem_url: str) -> str:
        """Get difficulty of a problem"""
        if not self.difficulty_map:
            return None
        for diff, problems in self.difficulty_map.items():
            if problem_url in problems:
                return diff
        return None

    def get_progress(self) -> Dict:
        """Get current progress (both session and global)"""
        session = self.progress['current_session']
        global_stats = self.progress['global_stats']

        can_unlock = self._can_select_hard_problems()

        return {
            'global': {
                'total': global_stats['total_completed'],
                'easy': global_stats['easy_completed'],
                'medium': global_stats['medium_completed'],
                'hard': global_stats['hard_completed'],
            },
            'session': {
                'total': session['total_completed'],
                'easy': session['easy_completed'],
                'medium': session['medium_completed'],
                'hard': session['hard_completed'],
                'total_problems': len(session['problems']),
                'generated_at': session['generated_at'],
                'can_unlock_hard': can_unlock,
                'needs_easy': max(0, 20 - session['easy_completed']),
                'needs_medium': max(0, 3 - session['medium_completed'])
            },
            'skipped': len(self.progress['skipped']),
            'revisit': len(self.progress['revisit'])
        }

    def reset_all_progress(self):
        """Reset all progress data (keeps problems data)"""
        self.progress = {
            'completed': [],
            'skipped': [],
            'revisit': [],
            'global_stats': {
                'easy_completed': 0,
                'medium_completed': 0,
                'hard_completed': 0,
                'total_completed': 0
            },
            'current_session': {
                'problems': [],
                'easy_completed': 0,
                'medium_completed': 0,
                'hard_completed': 0,
                'total_completed': 0,
                'generated_at': None
            }
        }
        self._save_progress()
        return True

    def export_progress(self) -> Dict:
        """Export all progress data for backup"""
        return {
            'progress': self.progress,
            'export_timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'version': '1.0'
        }

    def import_progress(self, import_data: Dict) -> bool:
        """Import progress data from backup"""
        try:
            if 'progress' in import_data:
                # Validate the structure
                required_keys = ['completed', 'skipped', 'revisit', 'global_stats', 'current_session']
                if all(key in import_data['progress'] for key in required_keys):
                    self.progress = import_data['progress']
                    self._save_progress()
                    return True
            return False
        except Exception as e:
            print(f"Error importing progress: {e}")
            return False


def get_selector():
    """Get selector for current user"""
    if not current_user.is_authenticated:
        return None
    return LeetCodeProblemSelector(current_user.id)


# Authentication routes
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

    user, error = User.create(username, email, password)
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

    user = User.verify_password(username, password)
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
        return jsonify({
            'authenticated': True,
            'username': current_user.username,
            'email': current_user.email
        })
    return jsonify({'authenticated': False})


@app.route('/')
@login_required
def index():
    return render_template('index.html', username=current_user.username)


@app.route('/api/load_problems', methods=['POST'])
@login_required
def load_problems():
    """Load problems from JSON input or file upload"""
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

        print(f"Loading problems for user {current_user.id}")
        print(f"JSON length: {len(problems_json)} characters")

        if selector.load_problems(problems_json):
            print(f"Problems loaded successfully for user {current_user.id}")
            print(f"Problems data type: {type(selector.problems_data)}")
            print(f"Has difficulty map: {selector.difficulty_map is not None}")
            return jsonify({'success': True, 'message': 'Problems loaded successfully!'})
        else:
            return jsonify({'success': False, 'message': 'Invalid JSON format or error processing problems'})

    except Exception as e:
        print(f"Error in load_problems route: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/check_problems', methods=['GET'])
@login_required
def check_problems():
    """Check if problems data is loaded"""
    selector = get_selector()
    if not selector:
        return jsonify({'loaded': False, 'has_session': False})

    has_problems = selector.has_problems_loaded()
    has_session = len(selector.progress['current_session']['problems']) > 0

    print(f"Check problems for user {current_user.id}: loaded={has_problems}, has_session={has_session}")

    return jsonify({
        'loaded': has_problems,
        'has_session': has_session
    })


@app.route('/api/generate', methods=['POST'])
@login_required
def generate_problems():
    """Generate new problem set"""
    selector = get_selector()
    if not selector:
        return jsonify({'success': False, 'message': 'User session error'})

    print(f"Generate called for user {current_user.id}")
    print(f"Problems data loaded: {selector.problems_data is not None}")
    print(f"Difficulty map loaded: {selector.difficulty_map is not None}")

    if not selector.problems_data:
        return jsonify({'success': False, 'message': 'Please load problems first'})

    # Check if we should return current session or generate new
    force_new = request.json.get('force_new', False) if request.is_json else False

    print(f"Force new: {force_new}")
    print(f"Current session problems: {len(selector.progress['current_session']['problems'])}")

    if not force_new and len(selector.progress['current_session']['problems']) > 0:
        # Return current session
        problems = []
        for url in selector.progress['current_session']['problems']:
            difficulty = selector._get_difficulty(url)
            if difficulty:
                problems.append({
                    'url': url,
                    'difficulty': difficulty,
                    'is_revisit': selector.is_in_revisit(url)
                })
        print(f"Returning existing session with {len(problems)} problems")
        return jsonify({'success': True, 'problems': problems, 'existing_session': True})

    # Generate new session
    print("Generating new problem set...")
    problems = selector.select_problems()
    print(f"Generated {len(problems)} problems")

    # Add revisit status to each problem
    for problem in problems:
        problem['is_revisit'] = selector.is_in_revisit(problem['url'])

    return jsonify({'success': True, 'problems': problems, 'existing_session': False})


@app.route('/api/mark_complete', methods=['POST'])
@login_required
def mark_complete():
    """Mark a problem as complete"""
    selector = get_selector()
    url = request.json.get('url')
    if selector.mark_complete(url):
        return jsonify({'success': True, 'progress': selector.get_progress()})
    return jsonify({'success': False, 'message': 'Problem already completed'})


@app.route('/api/mark_skip', methods=['POST'])
@login_required
def mark_skip():
    """Mark a problem as skipped and return replacement"""
    selector = get_selector()
    url = request.json.get('url')
    result = selector.mark_skip(url)
    if result['success']:
        response_data = {
            'success': True,
            'progress': selector.get_progress()
        }
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
    """Mark a problem for revisit"""
    selector = get_selector()
    url = request.json.get('url')
    if selector.mark_revisit(url):
        return jsonify({'success': True, 'progress': selector.get_progress()})
    return jsonify({'success': False, 'message': 'Could not mark for revisit'})


@app.route('/api/progress', methods=['GET'])
@login_required
def get_progress():
    """Get current progress"""
    selector = get_selector()
    return jsonify(selector.get_progress())


@app.route('/api/lists/<list_type>', methods=['GET'])
@login_required
def get_list(list_type):
    """Get skipped or revisit list with revisit status"""
    selector = get_selector()
    if list_type in ['skipped', 'revisit']:
        urls = selector.progress[list_type]
        # Add revisit status for skipped list
        if list_type == 'skipped':
            url_data = [{'url': url, 'is_revisit': selector.is_in_revisit(url)} for url in urls]
            return jsonify({'urls': url_data})
        return jsonify({'urls': urls})
    return jsonify({'urls': []})


@app.route('/api/completed/<scope>/<difficulty>', methods=['GET'])
@login_required
def get_completed(scope, difficulty):
    """Get completed problems filtered by scope (session/global) and difficulty (all/easy/medium/hard)"""
    selector = get_selector()
    completed_urls = selector.progress['completed']

    # Filter by scope
    if scope == 'session':
        # Only get problems that are in the current session
        session_problems = set(selector.progress['current_session']['problems'])
        completed_urls = [url for url in completed_urls if url in session_problems]

    # Filter by difficulty
    if difficulty != 'all':
        completed_urls = [url for url in completed_urls if selector._get_difficulty(url) == difficulty]

    # Add revisit status
    url_data = [{'url': url, 'is_revisit': selector.is_in_revisit(url)} for url in completed_urls]

    return jsonify({'urls': url_data})


@app.route('/api/reset_progress', methods=['POST'])
@login_required
def reset_progress():
    """Reset all progress data"""
    selector = get_selector()
    if selector.reset_all_progress():
        return jsonify({'success': True, 'message': 'All progress has been reset'})
    return jsonify({'success': False, 'message': 'Failed to reset progress'})


@app.route('/api/export_progress', methods=['GET'])
@login_required
def export_progress():
    """Export progress data as JSON"""
    selector = get_selector()
    export_data = selector.export_progress()
    return jsonify(export_data)


@app.route('/api/import_progress', methods=['POST'])
@login_required
def import_progress():
    """Import progress data from JSON"""
    selector = get_selector()
    try:
        import_data = request.json
        if selector.import_progress(import_data):
            return jsonify({'success': True, 'message': 'Progress imported successfully!'})
        else:
            return jsonify({'success': False, 'message': 'Invalid progress data format'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


if __name__ == '__main__':
    app.run(debug=True, port=3000)