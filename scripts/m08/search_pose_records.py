"""M08 compatibility entry: all writes use the shared library."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'common'))
from workflow.cli import run_module

def main():return run_module('M08')

if __name__=='__main__':main()
