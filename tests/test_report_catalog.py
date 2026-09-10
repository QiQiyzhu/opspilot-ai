import json
from fastapi.testclient import TestClient
import backend.app as application


def test_shipped_report_catalog_accepts_actual_container_array_and_keeps_benchmarks():
    client = TestClient(application.app)
    response = client.get("/api/evaluations/reports", headers={"Authorization": "Bearer demo-viewer"})
    assert response.status_code == 200
    items = {row["file"]: row for row in response.json()["items"]}
    assert items["rag-comparison.json"]["results"]
    assert items["agent-ablation.json"]["results"]
    assert isinstance(items["container-images.json"]["data"], list)
    assert items["container-images.json"]["data"][0]["ID"].startswith("sha256:")


def test_one_malformed_artifact_does_not_hide_valid_report(monkeypatch, tmp_path):
    (tmp_path / "valid.json").write_text(json.dumps({"results": [{"score": 1}]}), encoding="utf-8")
    (tmp_path / "incomplete.json").write_text('{"results":', encoding="utf-8")
    (tmp_path / "scalar.json").write_text("42", encoding="utf-8")
    monkeypatch.setattr(application, "REPORT_FOLDER", tmp_path)
    client = TestClient(application.app)
    response = client.get("/api/evaluations/reports", headers={"Authorization": "Bearer demo-viewer"})
    assert response.status_code == 200
    items = {row["file"]: row for row in response.json()["items"]}
    assert items["valid.json"]["results"] == [{"score": 1}]
    assert items["incomplete.json"]["artifact_type"] == "invalid_json"
    assert items["scalar.json"]["data"] == 42
