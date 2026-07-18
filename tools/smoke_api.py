"""v3 R0 gate: drive every API endpoint end-to-end on the TESTCO
fixture, fully offline. Exit 0 = PASS.

    python tools/smoke_api.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

import matplotlib
matplotlib.use("Agg")

from fastapi.testclient import TestClient           # noqa: E402

from test_api_contract import fixture_pipeline      # noqa: E402
from webui.server import create_app                 # noqa: E402

TOKEN = "smoke"


def main() -> int:
    app = create_app(pipeline=fixture_pipeline, token=TOKEN)
    client = TestClient(app,
                        headers={"Authorization": f"Bearer {TOKEN}"})
    steps = 0

    def check(label, ok):
        nonlocal steps
        steps += 1
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        if not ok:
            raise SystemExit(1)

    check("health", client.get("/api/health").json().get("ok") is True)
    check("auth rejects bare",
          TestClient(app).get("/api/health").status_code == 401)

    events = []
    with client.stream("POST", "/api/run/TESTCO") as r:
        for line in r.iter_lines():
            if line.startswith("event: "):
                events.append(line[7:])
    check("run streams progress + done",
          "progress" in events and events[-1] == "done")

    data = client.get("/api/data/TESTCO").json()
    check("data serialized (schema 1, fy_labels)",
          data["schema"] == 1 and data["data"]["fy_labels"])

    val = client.post("/api/valuation", json={
        "ticker": "TESTCO", "method": "dcf", "discount_rate": 0.09,
        "cases": {"Bear": {"g0": 0.02, "g_term": 0.02},
                  "Base": {"g0": 0.05, "g_term": 0.025},
                  "Bull": {"g0": 0.09, "g_term": 0.03}}})
    check("valuation + verdict",
          val.status_code == 200
          and val.json()["data"]["verdict"]["fv_avg"] is not None)

    sb = client.post("/api/sandbox", json={
        "base": 5e8, "wacc": 0.09, "g0": 0.05, "g_term": 0.02,
        "bridge": 6e8, "shares": 100e6, "price": 80.0})
    check("sandbox", sb.status_code == 200
          and sb.json()["data"]["fv_ps"] is not None)

    check("ledger", client.get("/api/ledger").status_code == 200)

    out = Path(tempfile.mkdtemp(prefix="bhf_smoke_"))
    for kind in ("model", "csv", "pdf"):
        r = client.post(f"/api/export/{kind}",
                        json={"ticker": "TESTCO", "out_dir": str(out)})
        path = Path(r.json()["data"]["path"])
        check(f"export {kind} -> {path.name}",
              r.status_code == 200 and path.exists()
              and path.stat().st_size > 0)

    print(f"SMOKE PASS — {steps} checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
