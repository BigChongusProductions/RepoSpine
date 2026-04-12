# Test fixture: should trigger no-bare-exit rule
# This file intentionally contains a bare exit() call
def main():
    if something_wrong():
        exit(1)  # BAD: should use raise SystemExit(1)
