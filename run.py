"""Local launcher; binds loopback and uses one worker intentionally."""
import os
import sys
from pathlib import Path
root = Path(__file__).resolve().parent
os.chdir(root)
sys.path.insert(0,str(root/'.deps'))
if __name__ == '__main__':
    import uvicorn
    uvicorn.run('app.main:app',host=os.getenv('HOST','127.0.0.1'),port=int(os.getenv('PORT','8000')))
