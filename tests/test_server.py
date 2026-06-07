from fastapi.testclient import TestClient

from eegvis.config import load_config
from eegvis.server.app import create_app


def _client():
    config = load_config()
    config.server.open_browser = False
    app = create_app(config, synthetic=True)
    return TestClient(app)


def test_status_endpoint():
    with _client() as client:
        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "synthetic"
        assert data["connected"] is True


def test_config_endpoint():
    with _client() as client:
        resp = client.get("/api/config")
        assert resp.status_code == 200
        assert resp.json()["server"]["port"] == 8765


def test_electrodes_endpoint():
    with _client() as client:
        resp = client.get("/api/electrodes")
        data = resp.json()
        names = [e["name"] for e in data["electrodes"]]
        assert "Cz" in names
        assert len(data["electrodes"][0]["position"]) == 3


def test_websocket_emits_frames():
    with _client() as client:
        with client.websocket_connect("/ws/eeg") as ws:
            # Messages are batches: {"type": "batch", "messages": [...]}.
            saw_status = False
            saw_frame = False
            for _ in range(60):
                msg = ws.receive_json()
                assert msg["type"] == "batch"
                for m in msg["messages"]:
                    if m["type"] == "status":
                        saw_status = True
                    if m["type"] == "eeg_frame":
                        saw_frame = True
                        assert "channels" in m
                        assert "raw" in m
                if saw_frame:
                    break
            assert saw_status
            assert saw_frame
