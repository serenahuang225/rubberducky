import importlib.util
from pathlib import Path
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

spec = importlib.util.spec_from_file_location("demo_access", Path(__file__).with_name("access.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
PASSWORD = "a-test-password-at-least-20-characters"

def test_password_and_cookie_gate():
    async def endpoint(request):
        return PlainTextResponse("ok")
    app = module.DemoAccess(Starlette(routes=[Route("/", endpoint), Route("/api/work", endpoint, methods=["POST"])]), PASSWORD)
    with TestClient(app, base_url="https://demo.test", follow_redirects=False) as client:
        assert client.get("/").status_code == 303
        assert client.post("/api/work").status_code == 401
        assert client.post("/demo-login", data={"password":"wrong"}).status_code == 401
        response = client.post("/demo-login", data={"password":PASSWORD})
        assert response.status_code == 303
        assert "HttpOnly" in response.headers["set-cookie"]
        assert "Secure" in response.headers["set-cookie"]
        assert client.get("/").status_code == 200
        for _ in range(10):
            assert client.post("/api/work").status_code == 200
        assert client.post("/api/work").status_code == 429
        client.cookies.clear()
        client.cookies.set("rubberducky_demo", "123.forged")
        assert client.get("/").status_code == 303

def test_cookie_expires():
    now = [100000]
    gate = module.DemoAccess(None, PASSWORD, lambda: now[0])
    value = str(now[0])
    cookie = value + "." + gate.signature(value)
    assert gate.valid_cookie(cookie)
    now[0] += 43201
    assert not gate.valid_cookie(cookie)

def test_preview_cannot_reach_protected_app():
    async def paid(request):
        return PlainTextResponse("paid")
    async def free(request):
        return PlainTextResponse("scripted")
    app = module.DemoAccess(Starlette(routes=[Route("/api/work", paid, methods=["POST"])]), PASSWORD,
                            preview=Starlette(routes=[Route("/api/work", free, methods=["POST"])]))
    with TestClient(app, base_url="https://demo.test", follow_redirects=False) as client:
        assert client.post("/api/work").status_code == 401
        assert client.post("/try-demo").status_code == 303
        assert client.post("/api/work").text == "scripted"
        client.cookies.set("rubberducky_demo", "123.forged")
        assert client.post("/api/work").text == "scripted"
        client.cookies.delete("rubberducky_demo")
        client.post("/demo-login", data={"password": PASSWORD})
        assert client.post("/api/work").text == "paid"
        client.post("/try-demo")
        assert client.post("/api/work").text == "scripted"
