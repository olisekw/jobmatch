# extract_coding_patterns.py
# Extracts only front-end coding skills from a resume .txt file

import re

def extract_coding_patterns(text):
    """
    Extract front-end coding skills from resume text.
    Returns a sorted list of unique front-end skills.
    """
    # Lowercase for matching
    text = text.lower()

    # Front-end focused patterns (add/remove as needed)
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

    found_skills = set()

    for pattern in coding_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            # Clean up
            clean = re.sub(r'\s*\([^)]*\)', '', match).strip()  # remove parentheses
            clean = re.sub(r'\s+', ' ', clean)  # normalize spaces
            if clean and len(clean) > 1:  # skip single letters
                # Nice title case
                found_skills.add(' '.join(word.capitalize() for word in clean.split()))

    # Sort alphabetically
    return sorted(list(found_skills))


if __name__ == "__main__":
    # Change this to your actual resume text file
    txt_file = "resume.txt"  # ← put your file name/path here

    try:
        with open(txt_file, "r", encoding="utf-8") as f:
            resume_text = f.read()

        coding_patterns = extract_coding_patterns(resume_text)

        if coding_patterns:
            print("Extracted front-end coding skills:")
            for skill in coding_patterns:
                print("•", skill)

            # Save to file
            output_file = "frontend_skills.txt"
            with open(output_file, "w", encoding="utf-8") as f:
                f.write("My Front-End Coding Skills:\n")
                f.write("\n".join(coding_patterns))
            print(f"\nSaved {len(coding_patterns)} skills to: {output_file}")
        else:
            print("No front-end skills detected. Check if your resume mentions them clearly.")
            print("Tip: Add more patterns to the list if your skills use different wording.")

    except FileNotFoundError:
        print(f"File not found: {txt_file}")
        print("Make sure the file is in the same folder or use full path, e.g.:")
        print('txt_file = r"C:\\Users\\Oliver\\Desktop\\resume.txt"')
    except Exception as e:
        print(f"Error: {e}")