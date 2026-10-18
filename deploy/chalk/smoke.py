"""Exercise the protected Claude demo with a new fictional learner; never print credentials."""
import sys
import uuid
from pathlib import Path
from dotenv import dotenv_values
import httpx

if __name__ == "__main__":
    base = sys.argv[1].rstrip("/")
    with httpx.Client(timeout=90) as client:
        response = client.get(base + "/")
        assert response.status_code == 303
        assert client.post(base + "/api/demo/bootstrap", json={}).status_code == 401
        password = dotenv_values(Path(__file__).resolve().parents[2] / ".env.demo-access")["DEMO_ACCESS_PASSWORD"]
        response = client.post(base + "/demo-login", data={"password": password})
        assert response.status_code == 303
        print("PASS: public access blocked; demo sign-in accepted")
        for path in ("/", "/api/health"):
            response = client.get(base + path)
            response.raise_for_status()
            print(path, response.status_code)
        response = client.post(base + "/api/demo/bootstrap", json={})
        response.raise_for_status()
        headers = {"Authorization": "Bearer " + response.json()["access_token"]}
        response = client.post(base + "/api/sessions", json={}, headers=headers)
        response.raise_for_status()
        session_id = response.json()["id"]
        headers["Idempotency-Key"] = "deployment-" + uuid.uuid4().hex
        response = client.post(base + f"/api/sessions/{session_id}/check-in",
                               json={"expected_revision": 0, "question_text": "How do I solve 3(x + 2) = 18? Please help me understand the first step."}, headers=headers)
        if response.status_code >= 400:
            try:
                payload = response.json()
                print("Tutor error (sanitized):", payload)
            except ValueError:
                print("Tutor response HTTP", response.status_code)
        response.raise_for_status()
        assert response.json()["status"] == "committed"
        assert response.json()["provider"]["is_mock"] is False
        print("PASS: fictional learner, session, and committed own-question Claude turn")
