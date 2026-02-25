# run_all_scripts.py
# Runs all scripts in the specified order, one after another

# python run_all_scripts.py


import subprocess
import sys

# List your scripts in order
scripts = [
    "./src/pdf_to_txt.py",
    "./src/skills.py",
    "./src/sk.py", #scrapes sk offers
    "./src/cz.py", #scrapes cz offers
    "./src/fill.py", #sorts salary/location/title
    "./src/results.py", #gets compatbility final look
    "./src/choose.py" #you choose what jobs you applied to
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
