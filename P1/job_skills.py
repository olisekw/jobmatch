# extract_skills_per_job_inline_extended.py
# Extracts coding skills from job descriptions and puts them next to the job URL

import re
from pathlib import Path

INPUT_FILE = "descriptions.txt"
OUTPUT_FILE = "skills_jobs.txt"

# Extended coding skill patterns (front-end + general programming + game dev + libraries)
coding_patterns = [
    # Front-end
    r'html[5]?', r'css[3]?', r'sass', r'scss', r'less',
    r'javascript', r'typescript', r'js', r'es6', r'es2015',
    r'react', r'react\.?js', r'next\.?js', r'react native',
    r'vue\.?js', r'vue', r'nuxt\.?js',
    r'angular', r'angularjs',
    r'svelte', r'sveltekit',
    r'tailwind', r'tailwindcss', r'bootstrap', r'material ui', r'mui',

    # Backend & general programming
    r'python', r'c', r'c\+\+', r'c#', r'java', r'ruby', r'php', r'go', r'rust',
    r'sql', r'mysql', r'ms sql', r'oracle', r'postgres', r'mongodb', r'redis',
    r'node\.?js', r'django', r'flask', r'spring', r'laravel', r'express',
    r'graphql', r'apollo', r'relay',
    r'redux', r'react query', r'zustand', r'mobx',

    # Python libraries
    r'numpy', r'pandas', r'scikit\-learn', r'tensorflow', r'keras', r'pygame', r'matplotlib',
    r'sqlalchemy', r'beautifulsoup', r'requests', r'flask', r'django',

    # Dev tools
    r'git', r'github', r'gitlab', r'docker', r'kubernetes', r'ci/cd', r'jenkins', r'webpack', r'vite', r'parcel', r'gulp', r'grunt', r'npm', r'yarn', r'pnpm',
    
    # Testing
    r'jest', r'vitest', r'cypress', r'playwright', r'unittest', r'pytest', r'testing library',

    # Game development / graphics
    r'unity', r'unreal engine', r'godot', r'blender', r'openGL', r'directx', r'three\.?js', r'webgl', r'gsap', r'anime\.?js',

    # General tech terms
    r'pwa', r'spa', r'ssr', r'ssg', r'isr', r'rest api', r'graphql api', r'mobile first', r'responsive design', r'cross-browser', r'accessibility', r'a11y', r'performance optimization',
]

def extract_skills(text):
    text = text.lower()
    found = set()
    for pattern in coding_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            clean = re.sub(r'\s*\([^)]*\)', '', match).strip()
            clean = re.sub(r'\s+', ' ', clean)
            if clean and len(clean) > 1:
                found.add(' '.join(word.capitalize() for word in clean.split()))
    return sorted(found)

def extract_jobs(text):
    url_pattern = r"(https?://www\.profesia\.sk/praca/\S+)"
    parts = re.split(url_pattern, text)
    jobs = []
    for i in range(1, len(parts), 2):
        url = parts[i]
        content = parts[i + 1] if i + 1 < len(parts) else ""
        jobs.append((url, content))
    return jobs

def main():
    if not Path(INPUT_FILE).exists():
        print(f"Input file not found: {INPUT_FILE}")
        return

    text = Path(INPUT_FILE).read_text(encoding="utf-8")
    jobs = extract_jobs(text)
    output_lines = []

    for url, content in jobs:
        skills = extract_skills(content)
        if skills:
            output_lines.append(f"{url} {','.join(skills)}")

    Path(OUTPUT_FILE).write_text("\n".join(output_lines), encoding="utf-8")
    print(f"Saved skills per job to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
