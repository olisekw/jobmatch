# run_all_scripts.py
# Runs all scripts in the specified order, one after another

# python run_all_scripts.py


import subprocess
import sys

# List your scripts in order
scripts = [
    "cz.py",
    "sk.py", #scrapes sk offers
    "des.py", #gets description
    "fill.py", #sorts salary/location/title
    "results.py" #gets compatbility final look"
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
