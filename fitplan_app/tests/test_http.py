import json
import os

os.environ["FITPLAN_MOCK"] = "1"

from fastapi.testclient import TestClient

from app.main import app


def test_http_endpoints():
    c = TestClient(app)
    assert c.get("/api/health").json()["mock_mode"] is True
    assert c.get("/").status_code == 200
    r = c.post("/api/plan", json=dict(goal="swim 1500 m", age=28))
    events = [json.loads(l[6:]) for l in r.text.split("\n\n") if l.startswith("data: ")]
    assert events[-1]["stage"] == "final"
    assert c.post("/api/plan", json=dict(goal="x", age=2)).status_code == 422
    a = c.post("/api/ask", json=dict(question="what if I miss a week?", plan="plan", age=30)).json()
    assert "answer" in a
    held = c.post("/api/ask", json=dict(question="I feel chest pain, can I still run?", plan="plan", age=30)).json()
    assert "doctor" in held["answer"].lower()
