import os
import subprocess
import sys

def build():
    # Find pyinstaller in our designated virtualenv
    pyinstaller_bin = os.path.expanduser("~/.virtualenvs/tracker/bin/pyinstaller")
    if not os.path.exists(pyinstaller_bin):
        pyinstaller_bin = "pyinstaller" # fallback

    # Add templates and static files to the package
    cmd = [
        pyinstaller_bin,
        "--name=N890GF_Tracker",
        "--onedir",
        "--windowed", # builds a .app bundle on macOS
        "--add-data=../templates:templates",
        "--add-data=../static:static",
        "--add-data=../src:src",
        "--noconfirm",
        "main.py"
    ]
    
    print("Running command:", " ".join(cmd))
    result = subprocess.run(cmd, cwd=os.path.dirname(os.path.abspath(__file__)))
    if result.returncode == 0:
        print("Build completed successfully!")
    else:
        print("Build failed with code:", result.returncode)
        sys.exit(result.returncode)

if __name__ == "__main__":
    build()
