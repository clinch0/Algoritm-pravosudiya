"""Playwright scenario with a fresh synthetic data directory and actual backend."""
import json, os, shutil, socket, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright
root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="vo-browser-") as tmp:
    data=Path(tmp)
    for p in (root/"data").glob("*.json"):shutil.copy2(p,data/p.name)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1",0));port=sock.getsockname()[1]
    env=dict(os.environ,VO_DATA_DIR=str(data),VO_LLM_BASE_URL="",VO_LLM_MODEL="")
    proc=subprocess.Popen([os.environ.get("VO_TEST_PYTHON",sys.executable),"-m","uvicorn","app.main:app","--port",str(port)],cwd=root,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    try:
        for _ in range(100):
            try:urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health",timeout=1);break
            except OSError:time.sleep(.1)
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True,**({"channel":"msedge"} if os.name=="nt" else {}))
            page=browser.new_page(viewport={"width":1350,"height":900})
            errors=[];page.on("pageerror",lambda e:errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}")
            page.locator("#login-form button").click()
            page.locator("#new-project").wait_for(state="visible")
            page.once("dialog",lambda d:d.accept("Демонстрационное дело"))
            page.locator("#new-project").click()
            page.locator("#project-content").wait_for(state="visible")
            page.locator('[data-tab="documents"]').click()
            page.locator("#upload").set_input_files({"name":"sample.txt","mimeType":"text/plain","buffer":"Иванов Иван Иванович. Почта: demo@example.test".encode()})
            page.locator("#document-list .card").wait_for()
            page.locator('[data-tab="chat"]').click()
            page.locator("#message").fill("Иванов Иван Иванович: какие права на частную жизнь?")
            page.locator("#prepare").click()
            page.locator("#preview").wait_for(state="visible")
            text=page.locator("#safe-json").inner_text()
            assert "Иванов" not in text and "Гражданин" in text
            page.locator("#reviewed").check();page.locator("#send").click()
            page.locator("#restore").wait_for(state="visible")
            page.locator("#restore").click()
            page.wait_for_function("document.querySelector('#safe-json').textContent.includes('Иванов')")
            page.locator('[data-tab="laws"]').click()
            page.locator("#law-query").fill("частной")
            page.locator("#law-form button").click()
            page.locator("#law-list .card").wait_for()
            assert "статья 23" in page.locator("#law-list").inner_text()
            assert not errors,errors
            output=root/"docs/verification/projects-ui.png";output.parent.mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(output),full_page=True)
            browser.close()
            print("Playwright: login, project, upload, dictionary, JSON, send, restore, law search passed")
    finally:
        proc.terminate();proc.wait(timeout=10)
