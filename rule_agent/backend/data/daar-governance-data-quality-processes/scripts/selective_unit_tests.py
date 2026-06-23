import os
import glob
import io

with os.popen("git branch --show-current") as f:
    current_branch = f.read().replace("\n", "")

with os.popen(f"git diff --name-only {current_branch} origin/develop") as f:
    changed_files = f.readlines()

changed_processes = [
    f.replace("governance_data_quality_processes/configs/", "").replace("\n", "")
    for f in changed_files
    if "governance_data_quality_processes/configs/processes/" in f
]

selected_tests = []
f_tests = glob.glob("tests/unit/configs/processes/**/*.py", recursive=True)
for f_test in f_tests:
    with io.open(f_test, "r") as fp:
        test_content = fp.read()
        for proc in changed_processes:
            if proc in test_content:
                selected_tests.append(f_test)

if selected_tests:
    print(" ".join(selected_tests))
else:
    print("--ignore=tests/unit/configs/processes tests/unit")
