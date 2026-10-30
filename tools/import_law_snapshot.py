"""Import a reviewed local JSON snapshot; never downloads or crawls remote sites."""
from pathlib import Path
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.law_index import import_snapshot
if __name__ == "__main__":
    print(json.dumps(import_snapshot(Path(sys.argv[1]) if len(sys.argv)>1 else None),ensure_ascii=False,indent=2))
