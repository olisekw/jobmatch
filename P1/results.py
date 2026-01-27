# compare_skills.py
# Compares candidate front-end skills with jobs and outputs a compatibility percentage

from pathlib import Path

JOBS_FILE = "skills_jobs.txt"
CANDIDATE_FILE = "frontend_skills.txt"
OUTPUT_FILE = "results.txt"

def load_candidate_skills(path):
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    skills = set()
    for line in lines:
        line = line.strip()
        if line and not line.lower().startswith("my front-end coding skills"):
            skills.add(line.lower())
    return skills

def load_jobs(path):
    jobs = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.strip().split(maxsplit=1)
        if len(parts) == 2:
            url, skills_str = parts
            skills = set(skill.strip().lower() for skill in skills_str.split(",") if skill.strip())
            jobs.append((url, skills))
    return jobs

def compute_compatibility(candidate_skills, job_skills):
    if not job_skills:
        return 0
    matched = candidate_skills.intersection(job_skills)
    return round(len(matched) / len(job_skills) * 100, 2)

def main():
    candidate_skills = load_candidate_skills(CANDIDATE_FILE)
    jobs = load_jobs(JOBS_FILE)
    output_lines = []

    for url, job_skills in jobs:
        percent = compute_compatibility(candidate_skills, job_skills)
        output_lines.append(f"{url} {percent}%")

    Path(OUTPUT_FILE).write_text("\n".join(output_lines), encoding="utf-8")
    print(f"Saved compatibility results to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
