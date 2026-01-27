import re
from pathlib import Path

SKILLS_FILE = "frontend_skills.txt"
JOBS_FILE = "descriptions.txt"
OUTPUT_FILE = "matched.txt"

def load_skills(path):
    return [line.strip().lower() for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]

def extract_jobs(text):
    url_pattern = r"(https?://www\.profesia\.sk/\S+)"
    parts = re.split(url_pattern, text)
    jobs = []
    for i in range(1, len(parts), 2):
        link = parts[i]
        content = parts[i + 1] if i + 1 < len(parts) else ""
        jobs.append((link, content.lower()))
    return jobs

def extract_matching_skills(skills, text):
    """
    Returns all skills from the list that appear anywhere in the text
    """
    matched = []
    for skill in skills:
        if re.search(rf"\b{re.escape(skill)}\b", text):
            matched.append(skill)
    return matched

def main():
    skills = load_skills(SKILLS_FILE)
    job_text = Path(JOBS_FILE).read_text(encoding="utf-8")

    jobs = extract_jobs(job_text)
    output_lines = []

    for link, content in jobs:
        matched_skills = extract_matching_skills(skills, content)
        if matched_skills:
            output_lines.append(link)
            output_lines.append(",".join(sorted(matched_skills)))

    Path(OUTPUT_FILE).write_text("\n".join(output_lines), encoding="utf-8")

if __name__ == "__main__":
    main()
