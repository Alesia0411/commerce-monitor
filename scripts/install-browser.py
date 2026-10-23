"""Install Chromium into this project rather than a shared user cache."""
import os
import runpy
import sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'.deps'))
os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH',str(root/'.browsers'))
sys.argv=['playwright','install','chromium']
runpy.run_module('playwright',run_name='__main__')
