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
            # First message should be a status payload.
            first = ws.receive_json()
            assert first["type"] in ("status", "eeg_frame")
            # Within a few messages we should see an eeg_frame.
            saw_frame = first["type"] == "eeg_frame"
            for _ in range(60):
                msg = ws.receive_json()
                if msg["type"] == "eeg_frame":
                    saw_frame = True
                    assert "normalized" in msg
                    assert "channels" in msg
                    break
            assert saw_frame
