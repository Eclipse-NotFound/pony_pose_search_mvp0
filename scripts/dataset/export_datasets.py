"""Compatibility adapter. Training requires a frozen shared-library snapshot."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'common'))
from workflow.cli import run_module

def main():
    return run_module('M06', ['--action','export']+sys.argv[1:])

if __name__=='__main__':main()
