"""Start the actual unpacked app over HTTP with isolated synthetic data."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error


def run(root):
    root = Path(root).resolve()
    with tempfile.TemporaryDirectory(prefix="vo-smoke-") as tmp:
        work = Path(tmp)
        data = work / "data"
        data.mkdir()
        for src in (root / "data").glob("*.json"):
            shutil.copy2(src, data / src.name)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = dict(os.environ, VO_DATA_DIR=str(data), VO_STATIC_DIR=str(root / "app/static"),
                   VO_DEMO_USER="demo", VO_DEMO_PASSWORD="demo123", PYTHONIOENCODING="utf-8")
        base = f"http://127.0.0.1:{port}"
        def request(path, body=None, token=None):
            headers = {"Content-Type":"application/json"}
            if token: headers["Authorization"] = "Bearer " + token
            req = urllib.request.Request(base+path, data=json.dumps(body).encode() if body is not None else None, headers=headers)
            with urllib.request.urlopen(req, timeout=20) as res:
                return json.load(res)
        with (work / "server.log").open("wb") as log:
            process = subprocess.Popen([sys.executable,"-m","uvicorn","app.main:app","--host","127.0.0.1","--port",str(port)],
                cwd=root, env=env, stdout=log, stderr=log,
                creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
            try:
                for _ in range(80):
                    try:
                        request("/api/health")
                        break
                    except (OSError, ValueError):
                        if process.poll() is not None: raise RuntimeError("Server exited before health check")
                        time.sleep(.2)
                else: raise RuntimeError("Health check timeout")
                try:
                    request("/api/history")
                    raise AssertionError("History accessible without login")
                except urllib.error.HTTPError as exc:
                    assert exc.code == 401
                token = request("/api/login", {"username":"demo","password":"demo123"})["token"]
                report = {"transport":"real HTTP loopback", "unauthorized_history":"401", "samples":{}}
                for sample in ("ok","error","attempt"):
                    result = request("/api/demo/"+sample, {}, token)
                    errors = [v["code"] for v in result["check"]["violations"] if v["level"] == "ошибка"]
                    if sample == "ok": assert not errors, errors
                    if sample == "error": assert {"OUT_OF_RANGE_MAX","PROBATION_RECIDIVISM"} <= set(errors), errors
                    if sample == "attempt": assert "CAP_66_ATT" in errors, errors
                    report["samples"][sample] = {"status":result["check"]["status"],"errors":errors}
                return report
            except Exception:
                log.flush()
                print((work / "server.log").read_text(encoding="utf-8",errors="replace"),file=sys.stderr)
                raise
            finally:
                process.terminate()
                try: process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == "__main__":
    root = Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).resolve().parents[1]
    print(json.dumps(run(root), ensure_ascii=False, indent=2))
