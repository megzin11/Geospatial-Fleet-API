import pytest
from fastapi.testclient import TestClient
from app.main import api, fleet_trajectories, last_known_state

client = TestClient(api)


@pytest.fixture(autouse=True)
def reset_edge_storage():
    """Ensure clean in-memory state before every test case."""
    fleet_trajectories.clear()
    last_known_state.clear()


def test_initial_registration_retains_point():
    payload = {
        "vehicle_id": "TEST-VESSEL-01",
        "timestamp": "2026-11-20T08:00:00Z",
        "latitude": 60.1116,
        "longitude": 20.3111,
        "speed_kmh": 10.0,
        "ai_anomaly_flag": False,
    }
    res = client.post("/telemetry", json=payload)
    assert res.status_code == 201
    assert res.json()["action"] == "RETAINED"
    assert res.json()["reason"] == "Initial Registration"


def test_dead_reckoning_drops_small_displacement():
    base = {
        "vehicle_id": "TEST-VESSEL-01",
        "timestamp": "2026-11-20T08:00:00Z",
        "latitude": 60.1116,
        "longitude": 20.3111,
        "speed_kmh": 5.0,
        "ai_anomaly_flag": False,
    }
    # ~11m north — well below the 50m threshold
    minor_move = {**base, "timestamp": "2026-11-20T08:00:05Z", "latitude": 60.1117}

    client.post("/telemetry", json=base)
    res = client.post("/telemetry", json=minor_move)

    assert res.status_code == 201
    assert res.json()["action"] == "COMPRESSED_AWAY"
    assert res.json()["deviation_m"] < 50.0


def test_anomaly_override_bypasses_compression_threshold():
    base = {
        "vehicle_id": "TEST-VESSEL-01",
        "timestamp": "2026-11-20T08:00:00Z",
        "latitude": 60.1116,
        "longitude": 20.3111,
        "speed_kmh": 5.0,
        "ai_anomaly_flag": False,
    }
    # 0m displacement, but flagged anomalous -> must be force-retained
    anomaly_ping = {**base, "timestamp": "2026-11-20T08:00:05Z", "ai_anomaly_flag": True}

    client.post("/telemetry", json=base)
    res = client.post("/telemetry", json=anomaly_ping)

    assert res.status_code == 201
    assert res.json()["action"] == "RETAINED"
    assert res.json()["reason"] == "Anomaly Override"

    traj = client.get("/fleet/TEST-VESSEL-01/trajectory").json()
    assert traj["total_retained_points"] == 2
    assert traj["anomalies_preserved"] == 1


def test_threshold_exceeded_retains_normal_movement():
    base = {
        "vehicle_id": "TEST-VESSEL-01",
        "timestamp": "2026-11-20T08:00:00Z",
        "latitude": 60.1116,
        "longitude": 20.3111,
        "speed_kmh": 25.0,
        "ai_anomaly_flag": False,
    }
    # ~1.1 km north -> exceeds 50m threshold
    far_move = {**base, "timestamp": "2026-11-20T08:02:00Z", "latitude": 60.1216}

    client.post("/telemetry", json=base)
    res = client.post("/telemetry", json=far_move)

    assert res.status_code == 201
    assert res.json()["action"] == "RETAINED"
    assert res.json()["reason"] == "Threshold Exceeded"


def test_unknown_vehicle_returns_404():
    res = client.get("/fleet/NON-EXISTENT/trajectory")
    assert res.status_code == 404