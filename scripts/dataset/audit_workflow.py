"""Read-only module migration inventory and isolated library-copy command."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'common'))
from workflow.cli import audit_main

if __name__ == '__main__':
    audit_main()
