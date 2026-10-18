"""Password gate for the shareable demo, independent of learner bearer credentials."""
import hashlib
import hmac
import os
import time
from collections import deque
from urllib.parse import parse_qs

from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse, RedirectResponse

LOGIN = '''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Rubberducky demo</title></head><body style="font:18px system-ui;max-width:420px;margin:15vh auto;padding:24px"><h1>Rubberducky demo</h1><p>Explore the scripted tutor for free, or enter the passcode to ask Claude your own questions.</p><form method="post" action="/try-demo"><button type="submit">Try the scripted demo</button></form><hr><p>Enter the demo password for Claude.</p><form method="post" action="/demo-login"><label>Password <input name="password" type="password" required autocomplete="current-password" maxlength="256"></label><p><button type="submit">Unlock Claude</button></p></form></body></html>'''


class DemoAccess:
    def __init__(self, app, password=None, clock=time.time, preview=None):
        self.app = app
        self.preview = preview
        self.password = password or os.environ.get("DEMO_ACCESS_PASSWORD", "")
        if len(self.password) < 20:
            raise ValueError("A strong DEMO_ACCESS_PASSWORD is required")
        self.key = self.password.encode()
        self.clock = clock
        self.login_attempts = deque()
        self.turns = deque()

    def signature(self, value):
        return hmac.new(self.key, value.encode(), hashlib.sha256).hexdigest()

    def valid_cookie(self, cookie):
        timestamp, separator, signature = cookie.partition(".")
        if not separator or not timestamp.isdigit():
            return False
        age = self.clock() - int(timestamp)
        return 0 <= age < 43200 and hmac.compare_digest(signature, self.signature(timestamp))

    def allowed(self, queue, seconds, limit):
        now = self.clock()
        while queue and now - queue[0] >= seconds:
            queue.popleft()
        if len(queue) >= limit:
            return False
        queue.append(now)
        return True

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive)
        if request.url.path == "/api/health" and request.method == "GET":
            await self.app(scope, receive, send)
            return
        if request.url.path == "/try-demo" and request.method == "POST":
            response = RedirectResponse("/", status_code=303)
            response.set_cookie("rubberducky_preview", "1", secure=True, httponly=True, samesite="strict", max_age=43200)
            response.delete_cookie("rubberducky_demo", secure=True, httponly=True, samesite="strict")
            await response(scope, receive, send)
            return
        if request.url.path == "/demo-login":
            if request.method == "GET":
                response = HTMLResponse(LOGIN, headers={"Cache-Control": "no-store"})
            elif request.method == "POST":
                if not self.allowed(self.login_attempts, 60, 20):
                    response = PlainTextResponse("Please try again in a minute.", status_code=429)
                else:
                    body = bytearray()
                    async for chunk in request.stream():
                        body.extend(chunk)
                        if len(body) > 2048:
                            break
                    supplied = parse_qs(body.decode(errors="replace")).get("password", [""])[0]
                    if len(body) > 2048 or not hmac.compare_digest(supplied.encode(), self.key):
                        response = HTMLResponse(LOGIN.replace("Enter the demo password", "Incorrect password. Enter the demo password"), status_code=401)
                    else:
                        timestamp = str(int(self.clock()))
                        response = RedirectResponse("/", status_code=303)
                        response.set_cookie("rubberducky_demo", timestamp + "." + self.signature(timestamp), max_age=43200, secure=True, httponly=True, samesite="strict")
            else:
                response = PlainTextResponse("Method not allowed", status_code=405)
            response.headers["Cache-Control"] = "no-store"
            await response(scope, receive, send)
            return
        if not self.valid_cookie(request.cookies.get("rubberducky_demo", "")):
            if self.preview is not None and request.cookies.get("rubberducky_preview") == "1":
                await self.preview(scope, receive, send)
                return
            response = (PlainTextResponse("Demo sign-in required", status_code=401)
                        if request.url.path.startswith("/api/") else RedirectResponse("/demo-login", status_code=303))
            await response(scope, receive, send)
            return
        if request.method == "POST" and request.url.path.endswith(("/check-in", "/work", "/help", "/voice/turn")):
            if not self.allowed(self.turns, 60, 10):
                await PlainTextResponse("Demo request limit reached. Try again in a minute.", status_code=429)(scope, receive, send)
                return
        await self.app(scope, receive, send)
