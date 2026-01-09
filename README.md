# LeetCode Problem Selector with Authentication

A web application for tracking LeetCode problem-solving progress with user authentication and personalized data storage.

## Features

### 🔐 **Authentication System**
- User registration and login
- Secure password hashing
- "Remember me" functionality (30-day sessions)
- Per-user data isolation
- Logout functionality

### 📊 **Progress Tracking**
- Session-based tracking (current 30 problems)
- Global statistics (all-time)
- Clickable stats to view completed problems
- Easy/Medium/Hard difficulty breakdown

### 🎯 **Smart Problem Management**
- Auto-replace skipped problems
- Revisit marking with visual indicators
- Progressive difficulty unlocking
- Persistent sessions across page reloads

### 💾 **Data Management**
- Export progress as JSON
- Import progress from backup
- Reset all progress
- User-specific data storage

## Installation

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Set up directory structure:**
   ```
   project/
   ├── app.py
   ├── requirements.txt
   ├── templates/
   │   ├── index.html
   │   ├── login.html
   │   └── register.html
   └── users/          # Created automatically
       ├── users.json  # User database
       └── {user_id}/  # Per-user directories
           ├── progress.json
           ├── problems_data.json
           └── difficulty_cache.json
   ```

3. **Set secret key (IMPORTANT for production):**
   ```bash
   export SECRET_KEY='your-very-secret-random-key-here'
   ```
   Or generate a secure one:
   ```python
   import secrets
   print(secrets.token_hex(32))
   ```

4. **Run the application:**
   ```bash
   python app.py
   ```

5. **Access the app:**
   - Open browser to `http://localhost:3000`
   - You'll be redirected to `/login`
   - Create an account at `/register`

## Usage

### First Time Setup

1. **Register an account:**
   - Navigate to `/register`
   - Create username (min 3 chars)
   - Enter email
   - Set password (min 6 chars)
   - Check "Remember me" to stay logged in

2. **Upload problems JSON:**
   - After login, paste your JSON or upload file
   - Problems data is saved automatically
   - No need to re-upload on future sessions

3. **Generate problems:**
   - Click "Generate 30 Problems"
   - Start solving!

### Data Isolation

Each user has completely separate:
- ✓ Problems data
- ✓ Progress tracking
- ✓ Current session
- ✓ Skipped problems
- ✓ Revisit list
- ✓ Global statistics

**Example file structure:**
```
users/
├── users.json              # All user accounts
├── 1/                      # User 1's data
│   ├── progress.json
│   ├── problems_data.json
│   └── difficulty_cache.json
└── 2/                      # User 2's data
    ├── progress.json
    ├── problems_data.json
    └── difficulty_cache.json
```

### Session Management

- **Login:** Sessions last 30 days with "Remember me"
- **Logout:** Click logout button in header
- **Auto-login:** Browser remembers you until logout
- **Security:** Password hashing with werkzeug

## Features by User

### Per-User Features
- Separate problem sets
- Independent progress tracking
- Individual session management
- Personal export/import

### Shared Features (Global)
- Difficulty cache (for performance)
- Application code
- UI/UX

## Security Notes

1. **Production Deployment:**
   - ALWAYS set a unique SECRET_KEY
   - Use HTTPS in production
   - Consider using a proper database (SQLite/PostgreSQL)
   - Add rate limiting for login attempts

2. **Password Security:**
   - Passwords are hashed with werkzeug
   - Never stored in plain text
   - 6 character minimum enforced

3. **Session Security:**
   - Flask-Login handles session management
   - Sessions expire after 30 days (configurable)
   - Logout clears session immediately

## API Endpoints

### Authentication
- `POST /api/register` - Create new account
- `POST /api/login` - Login user
- `POST /api/logout` - Logout user
- `GET /api/current_user` - Get current user info

### Problems Management
- `POST /api/load_problems` - Upload problems JSON
- `GET /api/check_problems` - Check if problems loaded
- `POST /api/generate` - Generate/get problem set

### Progress Tracking
- `GET /api/progress` - Get all stats
- `POST /api/mark_complete` - Mark problem complete
- `POST /api/mark_skip` - Skip problem
- `POST /api/mark_revisit` - Mark for revisit

### Data Management
- `GET /api/export_progress` - Export progress
- `POST /api/import_progress` - Import progress
- `POST /api/reset_progress` - Reset all progress

### Lists
- `GET /api/lists/{type}` - Get skipped/revisit list
- `GET /api/completed/{scope}/{difficulty}` - Get completed problems

## Troubleshooting

**Can't login after registration:**
- Check browser console for errors
- Ensure SECRET_KEY is set
- Try clearing cookies

**Data not saving:**
- Check file permissions on `users/` directory
- Ensure user directory was created
- Check server logs for errors

**Sessions not persisting:**
- Ensure "Remember me" is checked
- Check SECRET_KEY is consistent
- Clear cookies and re-login

**Multiple users showing same data:**
- This should never happen!
- Check user_id in file structure
- Verify Flask-Login is working
- Check `current_user.id` in logs

## Development

To add more features:
1. Backend: Add routes in `app.py`
2. Frontend: Modify `templates/index.html`
3. User data: Stored in `users/{user_id}/`

## Credits

Built with:
- Flask (Web framework)
- Flask-Login (Authentication)
- Werkzeug (Password hashing)
- Vanilla JavaScript (Frontend)