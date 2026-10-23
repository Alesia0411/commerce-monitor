"""Install local dependencies and a pinned Vue build. Run from any directory."""
import argparse
import subprocess
import sys
import urllib.request
from pathlib import Path

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--index-url', default='https://pypi.org/simple')
parser.add_argument('--vue-only', action='store_true')
args = parser.parse_args()
if not args.vue_only:
    subprocess.check_call([sys.executable,'-m','pip','install','--target',str(root/'.deps'),
        '--index-url',args.index_url,'-r',str(root/'requirements.txt')])
target = root/'web/vendor/vue.global.prod.js'
target.parent.mkdir(parents=True, exist_ok=True)
urllib.request.urlretrieve('https://cdn.jsdelivr.net/npm/vue@3.5.13/dist/vue.global.prod.js',target)
print('Ready. Run: python run.py')
