"""Initialize persistent data once; restart never overwrites user data."""
import os
from pathlib import Path
import shutil
import sys
root=Path(__file__).resolve().parents[1]
data=Path(os.environ.get("VO_DATA_DIR",root/"data"))
data.mkdir(parents=True,exist_ok=True)
for name in ("ukrf_sanctions.json","sample_cases.json","official_stats.json","law_history.json","law_versions.json","law_seed.json"):
    target=data/name
    if not target.exists(): shutil.copy2(root/"seed"/name,target)
os.execv(sys.executable,[sys.executable,"-m","uvicorn","app.main:app","--host","0.0.0.0","--port","8000"])
