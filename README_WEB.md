# LeetCode Problem Selector - Web Application

A beautiful web-based application that helps you manage your LeetCode practice with intelligent problem selection and progress tracking. Works in any browser!

## ✨ Features

🎯 **Dynamic JSON Input**: Paste JSON or upload a file - works with ANY problem list  
🎲 **Smart Selection**: Generates 30 random problems (20 Easy, 8 Medium, 2 Hard)  
🔒 **Progressive Unlocking**: Hard problems unlock after completing 20 Easy + 3 Medium  
🔗 **One-Click Access**: Click any problem to open in browser  
📊 **Real-time Progress**: Live tracking of completed, skipped, and revisit problems  
💾 **Auto-Save**: All progress persists across sessions  
🚫 **No Duplicates**: Completed problems never appear again  

## 🚀 Quick Start

### 1. Install Python & Flask

```bash
# Install Flask
pip install flask

# Or use requirements.txt
pip install -r requirements.txt
```

### 2. Run the Application

```bash
python app.py
```

### 3. Open in Browser

Navigate to: **http://localhost:5000**

That's it! No Tkinter, no GUI dependencies - just a web browser!

## 📖 How to Use

### Step 1: Load Your Problems

**Option A: Paste JSON**
1. Copy your JSON data (like the one you provided)
2. Paste it in the text area
3. Click "Load Problems"

**Option B: Upload File**
1. Click "Choose File" 
2. Select your `.json` file
3. Click "Upload File"
4. Click "Load Problems"

### Step 2: Generate Problem Set

Click **"🎲 Generate 30 Problems"** to get your randomized set

### Step 3: Solve & Track

For each problem:
- **Click the problem name** (blue text) to open in LeetCode
- **✓ Complete** - Mark when solved (won't appear again)
- **⊘ Skip** - Skip for now (can appear in future sets)
- **↻ Revisit** - Mark for later review

### Step 4: View Lists

- **📋 Show Skipped** - See all skipped problems
- **↻ Show Revisit** - See problems marked for review

## 🔓 Unlocking System

Hard problems are **locked** by default.

**To unlock:**
- ✅ Complete 20 Easy problems
- ✅ Complete 3 Medium problems

Once unlocked, you'll get 2 hard problems per set!

## 📊 Progress Tracking

Your dashboard shows:
- Total problems completed
- Easy completed (out of 20 needed)
- Medium completed (out of 3 needed)
- Hard problems completed
- Number of skipped problems
- Number of revisit problems
- Lock/unlock status for hard problems

## 💾 Data Storage

Progress is saved in `progress.json`:

```json
{
  "completed": ["list of URLs"],
  "skipped": ["list of URLs"],
  "revisit": ["list of URLs"],
  "easy_completed": 0,
  "medium_completed": 0,
  "hard_completed": 0
}
```

**To reset:** Delete `progress.json` and refresh the page

## 🎨 Features Breakdown

### Dynamic JSON Input
Works with any JSON structure:
```json
{
  "result": {
    "Category1": ["url1", "url2"],
    "Category2": ["url3", "url4"]
  }
}
```

OR

```json
{
  "Category1": ["url1", "url2"],
  "Category2": ["url3", "url4"]
}
```

### Smart Difficulty Classification
Problems are automatically categorized as Easy/Medium/Hard based on:
- Problem name patterns
- Common LeetCode difficulty indicators
- Curated lists of known difficulty levels

### No Duplicates
Once you mark a problem complete:
- It's removed from future problem sets
- Your progress is saved permanently
- You can focus on new challenges

## 🖥️ System Requirements

- Python 3.6+
- Flask (automatically installed)
- Any modern web browser (Chrome, Firefox, Safari, Edge)
- No GUI dependencies needed!

## 📱 Browser Compatibility

Works on:
- ✅ Chrome/Chromium
- ✅ Firefox
- ✅ Safari
- ✅ Edge
- ✅ Mobile browsers (iOS Safari, Chrome Mobile)

## 🔧 Customization

### Change Port
Edit `app.py` last line:
```python
app.run(debug=True, port=5000)  # Change 5000 to your port
```

### Modify Difficulty Rules
Edit the `easy_patterns` and `hard_patterns` lists in `app.py`

### Adjust Problem Distribution
Edit the `select_problems()` method to change:
- Number of easy problems (default: 20)
- Number of medium problems (default: 8)
- Number of hard problems (default: 2)
- Unlock criteria (default: 20 easy + 3 medium)

## 🐛 Troubleshooting

**Problem: "Address already in use"**
```bash
# Kill the process using port 5000
lsof -ti:5000 | xargs kill -9

# Or use a different port
python app.py  # Edit port in app.py
```

**Problem: Flask not found**
```bash
pip install flask
# or
pip3 install flask
```

**Problem: Progress not saving**
- Check write permissions in the directory
- Ensure `progress.json` can be created

**Problem: JSON parse error**
- Verify your JSON is valid at https://jsonlint.com
- Check for trailing commas or missing brackets

## 💡 Pro Tips

1. **Keep it running**: Leave the server running while you solve problems
2. **Use bookmarks**: Bookmark http://localhost:5000 for quick access
3. **Regular backups**: Copy `progress.json` to backup your progress
4. **Mobile friendly**: Access from your phone on the same network using your computer's IP
5. **Multiple lists**: Use different JSON files for different problem sets

## 🌐 Access from Other Devices

To access from phone/tablet on same WiFi:

1. Find your computer's IP:
   ```bash
   # Mac/Linux
   ifconfig | grep "inet "
   
   # Windows
   ipconfig
   ```

2. Edit `app.py` last line:
   ```python
   app.run(debug=True, host='0.0.0.0', port=5000)
   ```

3. Access from other device:
   ```
   http://YOUR_IP:5000
   ```

## 📄 Example JSON Format

```json
{
    "result": {
        "Arrays & Hashing": [
            "https://leetcode.com/problems/two-sum/",
            "https://leetcode.com/problems/contains-duplicate/"
        ],
        "Two Pointers": [
            "https://leetcode.com/problems/valid-palindrome/",
            "https://leetcode.com/problems/3sum/"
        ],
        "Dynamic Programming": [
            "https://leetcode.com/problems/climbing-stairs/",
            "https://leetcode.com/problems/house-robber/"
        ]
    }
}
```

## 🎯 Workflow Example

1. **Monday**: Load JSON, generate 30 problems
2. **During the week**: Solve problems, mark complete
3. **Friday**: Generate new set (only unsolved problems appear)
4. **Weekend**: Review skipped/revisit lists
5. **Repeat**: Keep going until you unlock hard problems!

## 🔐 Privacy Note

All data is stored locally on your machine in `progress.json`. Nothing is sent to external servers.

## 📝 License

Free to use and modify for personal learning purposes.

## 🙏 Contributing

Feel free to enhance:
- Add more difficulty classification patterns
- Implement statistics/charts
- Add time tracking
- Create themes
- Export progress reports

Enjoy your LeetCode journey! 🚀
