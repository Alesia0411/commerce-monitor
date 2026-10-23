"""Convenience launcher using the same project-local dependencies."""
import sys
import tempfile
from pathlib import Path
root = Path(__file__).resolve().parent
sys.path.insert(0,str(root/'.deps'))
sys.path.insert(0,str(root))
import pytest
# A fresh workspace directory also works in restricted Windows environments.
scratch = root/'.test-tmp'
scratch.mkdir(exist_ok=True)
tempfile.tempdir = str(scratch)
base = tempfile.mkdtemp(prefix='run-',dir=scratch)
raise SystemExit(pytest.main([str(root/'tests'),'-q','--tb=short','--basetemp',base]))
