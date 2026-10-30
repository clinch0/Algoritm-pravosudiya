"""Opt-in real local-model smoke with synthetic data and a disposable backend."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import httpx
from dotenv import load_dotenv

root = Path(__file__).resolve().parents[1]
load_dotenv(root / '.env', override=False)
assert os.environ.get('VO_LLM_MODEL'), 'Configure a local model in .env first'
with tempfile.TemporaryDirectory(prefix='vo-live-') as directory:
    data = Path(directory)
    for path in (root / 'data').glob('*.json'):
        shutil.copy2(path, data / path.name)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--port', str(port)],
        cwd=root, env=dict(os.environ, VO_DATA_DIR=str(data)),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=210, trust_env=False) as client:
            for _ in range(100):
                try:
                    if client.get('/api/health').is_success:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(.1)
            response = client.post('/api/login', json={'username': 'demo', 'password': os.environ.get('VO_DEMO_PASSWORD', 'demo123')})
            response.raise_for_status()
            client.headers['Authorization'] = 'Bearer ' + response.json()['token']
            pid = client.post('/api/projects', json={'title': 'Synthetic local LLM smoke'}).json()['id']
            prefix = f'/api/projects/{pid}'
            name = 'Иванов Иван Иванович'
            response = client.post(prefix + '/documents', files={'file': ('synthetic.txt',
                (name + ' сообщил о публикации личной переписки. Он просит защитить частную жизнь.').encode(), 'text/plain')})
            response.raise_for_status()
            draft = client.post(prefix + '/preview', json={'payload': {'message':
                f'Какие гарантии неприкосновенности частной жизни закреплены в Конституции для {name}?'}}).json()
            assert name not in json.dumps(draft['payload'], ensure_ascii=False)
            start = time.monotonic()
            response = client.post(prefix + '/send', json={'draft_id': draft['draft_id'], 'reviewed': True})
            response.raise_for_status()
            answer = response.json()['answer']
            assert answer['model_called'] and answer['citations']
            assert name not in answer['answer']
            assert answer['retrieval']['document_chunks'] >= 1
            saved = client.get(prefix).json()['requests'][0]['answer']
            assert saved == answer
            restored = client.post(prefix + '/restore', json={'draft_id': draft['draft_id']})
            restored.raise_for_status()
            # An answer may omit the person entirely. Any namespace mention
            # must round-trip to the original synthetic value.
            if '·' in answer['answer']:
                assert name in restored.json()['payload']['answer']
            report = {'model': os.environ['VO_LLM_MODEL'], 'seconds': round(time.monotonic()-start, 2),
                'http_roundtrip': True, 'persistent_answer': True, 'restoration_endpoint': True, 'answer': answer}
            output = root / '.runtime/local-llm-smoke.json'
            output.parent.mkdir(exist_ok=True)
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        process.terminate()
        process.wait(timeout=10)
