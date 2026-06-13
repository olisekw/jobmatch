# Run all scripts in specified order

import subprocess
import sys

# List scripts in execution order
scripts = [
    "./src/pdf_to_txt.py",
    "./src/skills.py",
    "./src/sk.py",
    "./src/fill.py",
    "./src/results.py",
    "./src/choose.py"
]

def run_script(script_name):
    print(f"Running {script_name}...")
    result = subprocess.run([sys.executable, script_name])
    if result.returncode != 0:
        print(f"Error: {script_name} failed with exit code {result.returncode}")
        sys.exit(result.returncode)
    print(f"Finished {script_name}\n")

def main():
    for script in scripts:
        run_script(script)
    print("All scripts completed successfully!")

if __name__ == "__main__":
    main()
