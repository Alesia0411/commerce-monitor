"""Run via a restricted container; see docs/TECHNICAL.md for limits."""
import json
from app.evaluation import evaluate_security
print(json.dumps(evaluate_security(),ensure_ascii=False,indent=2))
