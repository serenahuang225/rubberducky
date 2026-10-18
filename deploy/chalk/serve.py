"""Single-replica public demo; SQLite runs locally and checkpoints to a Chalk Volume."""
import asyncio
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from app.config import get_settings

DATA = Path(os.environ.get("DEMO_DATA_DIR", "/data"))
LOCAL = Path(os.environ.get("DEMO_LOCAL_DB", "/tmp/rubberducky/tutor.db"))
DATA.mkdir(parents=True, exist_ok=True)
LOCAL.parent.mkdir(parents=True, exist_ok=True)
SNAPSHOT = DATA / "tutor.db"
if SNAPSHOT.exists():
    shutil.copyfile(SNAPSHOT, LOCAL)
os.environ["DATABASE_URL"] = f"sqlite:///{LOCAL}"
subprocess.run([sys.executable, "-m", "app.cli", "migrate"], check=True)

subprocess.run([sys.executable, "-m", "app.cli", "seed"], check=True)

from app.main import create_app


def checkpoint():
    temporary = DATA / "tutor.next.db"
    with sqlite3.connect(LOCAL) as source, sqlite3.connect(temporary) as target:
        source.backup(target)
    os.replace(temporary, SNAPSHOT)
    commit = DATA / ".chalk-volume" / "commit"
    if commit.exists():
        subprocess.run([str(commit)], check=True, timeout=60)


checkpoint()
api = create_app()
site = FastAPI(lifespan=api.router.lifespan_context)
site.mount("/api", api)
WEB = Path(os.environ.get("DEMO_WEB_DIR", "/app/web"))

def mount_web(target, mode):
    @target.get("/", response_class=HTMLResponse)
    def home():
        # Keep separate browser credentials when changing tutor modes.
        script = """<script>(function(){const mode=MODE;const key='rubberducky.credentials.v1';const old=localStorage.getItem('rubberducky.demo-mode')||'claude';if(old!==mode){const value=localStorage.getItem(key);if(value)localStorage.setItem(key+'.'+old,value);const next=localStorage.getItem(key+'.'+mode);if(next)localStorage.setItem(key,next);else localStorage.removeItem(key);}localStorage.setItem('rubberducky.demo-mode',mode);})();</script>""".replace("MODE", repr(mode))
        link = '<a href="/demo-login" style="position:fixed;right:12px;bottom:8px;z-index:99999;background:white;color:#1452b0;padding:8px;border-radius:8px;font:14px system-ui">' + ("Scripted demo · Unlock Claude" if mode == "scripted" else "Claude · Demo options") + '</a>'
        return HTMLResponse((WEB / "index.html").read_text().replace("<head>", "<head>" + script).replace("</body>", link + "</body>"), headers={"Cache-Control": "no-store"})
    target.mount("/", StaticFiles(directory=WEB, html=True), name="web")

mount_web(site, "claude")
preview_db = LOCAL.parent / "preview.db"
preview_url = f"sqlite:///{preview_db}"
for command in ("migrate", "seed"):
    subprocess.run([sys.executable, "-m", "app.cli", "--database-url", preview_url, command], check=True)
preview_settings = get_settings().model_copy(update={"tutor_provider": "mock", "external_integrations_enabled": False, "database_url": preview_url, "anthropic_api_key": None, "xai_speech_enabled": False, "xai_api_key": None})
preview_api = create_app(preview_settings)
preview_site = FastAPI()
preview_site.mount("/api", preview_api)
mount_web(preview_site, "scripted")


class DurableDemo:
    def __init__(self, inner):
        self.inner = inner
        self.lock = asyncio.Lock()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] in {"GET", "HEAD", "OPTIONS"}:
            await self.inner(scope, receive, send)
            return
        # Checkpoint before returning any mutation response. One replica / one worker only.
        async with self.lock:
            messages = []
            async def buffer(message):
                messages.append(message)
            await self.inner(scope, receive, buffer)
            await asyncio.to_thread(checkpoint)
            for message in messages:
                await send(message)


from demo_access import DemoAccess

app = DemoAccess(DurableDemo(site), preview=preview_site)
