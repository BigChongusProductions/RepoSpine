# Test fixture: should NOT trigger no-bare-exit rule
# sys.exit() is valid — it raises SystemExit internally
import sys

def main():
    if something_wrong():
        sys.exit(1)  # GOOD: this is the approved pattern
