# JobMatch - Smart Job Finder

A Python-based job matching application that scrapes job listings from Slovak job boards, then intelligently matches them with your skills and preferences.

## Overview

JobMatch automates the tedious job search process by:
- Parsing your CV to extract key skills
- Understanding your job preferences (location, seniority, work type)
- Scraping job listings from job boards
- Analyzing each job for skill requirements and work conditions
- Scoring jobs based on how well they match your profile
- Helping you track which jobs you've applied to

## Project Structure

```
jobmatch/
├── main.py                 # Main entry point - runs the entire pipeline
├── config.py               # Configuration (paths, timeouts, patterns, weights)
├── data/
│   ├── cv.pdf             # Your CV (PDF format) - converted to text
│   ├── resume.txt         # Extracted text from your CV
│   ├── inputs.txt         # Your job preferences (optional, highest priority)
│   ├── user.csv           # Parsed user profile (Location, Skills, Seniority, Worktype)
│   ├── jobs.csv           # All scraped jobs with features extracted
│   ├── results.csv        # Matched jobs with compatibility scores
│   └── applied.csv        # Jobs you've applied to (for tracking)
└── src/
    ├── pdf_to_txt.py      # Convert CV from PDF to text
    ├── skills.py          # Extract user profile from CV + preferences
    ├── sk.py              # Scrape jobs from profesia.sk
    ├── fill.py            # Extract job features (skills, salary, worktype, etc)
    ├── results.py         # Score and rank jobs by compatibility
    └── choose.py          # Mark jobs as "applied" or "declined"
```

## Quick Start

### 1. Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Or install manually
pip install playwright beautifulsoup4 requests pandas
python -m playwright install chromium
```

### 2. Prepare Your Data

Create `jobmatch/data/cv.pdf` - your resume/CV in PDF format

**Optional:** Create `jobmatch/data/inputs.txt` to specify your preferences:
```
Bratislava, Slovakia
Remote, Hybrid
Senior, Medior
React, TypeScript, Python, Node.js
```

### 3. Run the Pipeline

```bash
cd jobmatch
python main.py
```

The script will:
1. Extract text from your CV → `resume.txt`
2. Create your profile → `user.csv`
3. Scrape job listings → jobs appended to `jobs.csv`
4. Extract job features → Fill `jobs.csv` with Skills, Worktype, Seniority
5. Score jobs by match → Create `results.csv` (sorted by compatibility)
6. Let you choose → Mark applied/declined in `applied.csv`

## Scanning Strategy

**First Run: Full Scan**
- When you run `python main.py` for the first time, it scrapes ALL available jobs
- This builds your initial database (`jobs.csv`)
- Takes longer (~30-60 minutes depending on jobs available)

**Daily Runs: Recent Jobs Only**
- After the first run, subsequent runs only scrape jobs from the **last day**
- Fast and efficient (~5-10 minutes)
- Automatically appends new jobs to `jobs.csv`
- Results are re-ranked in `results.csv` to show best matches

**Recommended Workflow:**
```bash
# Day 1: Initial full scan
cd jobmatch && python main.py

# Day 2-onwards: Daily quick scan (5 minutes)
cd jobmatch && python main.py
# Review results.csv for new matches
```

This way you get the complete job history on day 1, then stay updated with fresh opportunities daily without the overhead.

##  How It Works

### Step 1: User Profile (`skills.py`)
Extracts from your CV (and `inputs.txt` if provided):
- **Location**: Where you want to work (Bratislava, Prague, etc)
- **Skills**: Technologies you know (React, Python, etc)
- **Seniority**: Your experience level (Junior, Medior, Senior)
- **Worktype**: Preferred setup (Remote, Hybrid, Onsite)

### Step 2: Job Scraping (`sk.py`)
- Scrapes job listings from profesia.sk
- Extracts: Title, Company, Link, Location, Salary
- Stores in `jobs.csv`

### Step 3: Feature Extraction (`fill.py`)
For each job, extracts:
- **Skills**: Required technologies (parsed from job description)
- **Worktype**: Remote/Hybrid/Onsite requirements
- **Seniority**: Junior/Medior/Senior level
- **EmploymentType**: Full-time, Part-time, Freelance, Internship

### Step 4: Job Matching (`results.py`)
Scores each job (0-100) based on:
- **Skill Match**: How many of your skills match the job (40%)
- **Worktype Match**: Does it match your preferred setup (25%)
- **Location Match**: Is it in a location you want (20%)
- **Seniority Match**: Is it your level (15%)

Jobs ranked by score → saved to `results.csv`

### Step 5: Track Applications (`choose.py`)
Mark each job as:
- **Applied**: You applied to this job
- **Declined**: Not interested
- **Pending**: Still deciding

Tracked in `applied.csv`

## Configuration

Edit `config.py` to customize:

```python
# Search profiles - choose which type of jobs to look for
ACTIVE_SEARCH_PROFILE = "frontend"  # Options: frontend, fullstack, backend, native, devops, custom

# Or set custom search terms
SEARCH_TERMS = [
    "developer", "programator", "react", "javascript", "frontend"
]

# Scraping delays (seconds) - be respectful to servers
MIN_DELAY = 8
MAX_DELAY = 16

# Timeouts (milliseconds)
TIMEOUT_GOTO = 45000      # How long to wait for page load
TIMEOUT_CARD = 25000      # How long to wait for job card

# Add/remove skills to detect
CODING_PATTERNS = [...]

# Adjust matching weights (0-1, sum = 1.0)
SKILL_MATCH_WEIGHT = 0.4        # Skills importance
WORKTYPE_MATCH_WEIGHT = 0.25
LOCATION_MATCH_WEIGHT = 0.2
SENIORITY_MATCH_WEIGHT = 0.15

# Minimum match score to show
MIN_MATCH_SCORE = 30
```

### Search Profiles

Built-in profiles for different roles:
- **frontend**: React, TypeScript, JavaScript, UI/UX
- **fullstack**: Full-stack development, Node.js, Python, databases
- **backend**: Python, Go, Java, databases, APIs
- **native**: Mobile development, React Native, Flutter
- **devops**: DevOps, Infrastructure, Docker, Kubernetes
- **custom**: Define your own search terms

## Input Files

### `inputs.txt` (Optional)
Your job preferences - one per line, comma/newline separated:
```
Bratislava
Senior
Remote
React, TypeScript, Node.js
```

**Priority**: `inputs.txt` > CV analysis

### `cv.pdf` (Required)
Your resume. Must be in PDF format.
Automatically converted to `resume.txt`

## Output Files

### `user.csv`
Your parsed profile:
```csv
Location,Skills,Seniority,Worktype
Bratislava,"React, TypeScript, Python",Senior,Remote
```

### `jobs.csv`
All scraped jobs with extracted features:
```csv
Title,Company,Link,Description,Skills,Worktype,Seniority,EmploymentType,Salary,Location,Posted,Source
Senior React Dev,Acme Inc,https://...,Seeking experienced...,react; typescript,Remote,Senior,Full-time,2000-3000 EUR,Bratislava,2025-06-13,profesia.sk
```

### `results.csv`
Jobs ranked by match score:
```csv
Title,Company,Link,MatchScore,SkillsMatch,Location,Worktype,Seniority
Senior React Dev,Acme Inc,https://...,85,0.9,Bratislava,Remote,Senior
```

### `applied.csv`
Your application tracking:
```csv
Title,Company,Link,Status,AppliedDate,Notes
Senior React Dev,Acme Inc,https://...,Applied,2025-06-13,Great company!
```

## Troubleshooting

**Problem: "CV file not found"**
- Make sure `cv.pdf` is in `jobmatch/data/`
- File must be named exactly `cv.pdf`

**Problem: No skills extracted**
- CV might not have clear skill listings
- Create `inputs.txt` with your skills manually
- Add more skill patterns to `CODING_PATTERNS` in `config.py`

**Problem: Scraping is slow**
- Intentional delays between requests (8-16 sec) respect website servers
- Increase `MIN_DELAY`/`MAX_DELAY` in `config.py` to speed up (but be respectful!)

**Problem: Jobs CSV is empty**
- Job board websites may have changed their HTML structure
- Check that profesia.sk is accessible
- Website might have rate-limiting protections

**Problem: Low match scores**
- Your skills might not match current job market
- Try expanding your skill set in `inputs.txt`
- Adjust weights in `config.py` to prioritize what matters to you

## Dependencies

- **pandas**: Data manipulation
- **beautifulsoup4**: Web scraping HTML parsing
- **playwright**: Browser automation for dynamic content
- **requests**: HTTP requests

Install all:
```bash
pip install pandas beautifulsoup4 playwright requests
python -m playwright install chromium
```

## Disclaimer

- Respects website terms of service with deliberate delays
- This tool is for personal job search assistance only
- Don't abuse it for mass scraping or commercial use
- Job board terms may prohibit automated scraping - use responsibly

## License

Personal use only.

## Tips

1. **Keep your CV updated** - More detailed CVs = better skill extraction
2. **Be specific in `inputs.txt`** - Helps override CV analysis if needed
3. **Check results.csv regularly** - New jobs added frequently, re-run often
4. **Adjust match weights** - If you're not seeing jobs you like, tweak the scoring
5. **Review the source code** - Understand what data is collected and how

---

**Need help?** Check the source files in `src/` - each script has detailed comments explaining what it does.
