import json
import uuid
from datetime import datetime, timezone
import requests
import paho.mqtt.client as mqtt

API_URL = "http://127.0.0.1:8000/telemetry"
MAX_VESSELS = 15  # Track 15 live ships concurrently for clean trajectory telemetry

tracked_mmsis = set()
stats = {"received": 0, "retained": 0, "compressed": 0, "anomalies": 0}


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print("Connected to Fintraffic Digitraffic Live AIS Broker (Baltic Sea).")
        print(f"Tracking up to {MAX_VESSELS} live vessels -> streaming to {API_URL}\n")
        client.subscribe("vessels-v2/+/location")
    else:
        print(f"Connection failed with code: {reason_code}")


def on_message(client, userdata, msg):
    parts = msg.topic.split("/")
    if len(parts) != 3 or parts[2] != "location":
        return

    mmsi = parts[1]

    # Cap tracked fleet size so individual vessel trajectories build cleanly
    if mmsi not in tracked_mmsis:
        if len(tracked_mmsis) >= MAX_VESSELS:
            return
        tracked_mmsis.add(mmsi)

    try:
        raw = json.loads(msg.payload.decode("utf-8"))
        lat = raw.get("lat")
        lon = raw.get("lon")
        if lat is None or lon is None:
            return

        sog_knots = float(raw.get("sog") or 0.0)
        rot_deg_min = float(raw.get("rot") or 0.0)
        epoch_ts = raw.get("time")

        iso_ts = (
            datetime.fromtimestamp(epoch_ts, tz=timezone.utc).isoformat()
            if epoch_ts
            else datetime.now(timezone.utc).isoformat()
        )
        # Ignore AIS sentinel value (-128 / 128 = ROT sensor unavailable)
        valid_rot = abs(rot_deg_min) < 127.0
        is_anomaly = (valid_rot and abs(rot_deg_min) > 15.0) or sog_knots > 20.0

        payload = {
            "vehicle_id": f"MMSI-{mmsi}",
            "timestamp": iso_ts,
            "latitude": float(lat),
            "longitude": float(lon),
            "speed_kmh": round(sog_knots * 1.852, 2),
            "ai_anomaly_flag": is_anomaly,
        }

        resp = requests.post(API_URL, json=payload, timeout=2)
        if resp.status_code == 201:
            result = resp.json()
            action = result.get("action")
            reason = result.get("reason")
            dev = result.get("deviation_m", 0.0)

            stats["received"] += 1
            if action == "COMPRESSED_AWAY":
                stats["compressed"] += 1
            else:
                stats["retained"] += 1
                if is_anomaly:
                    stats["anomalies"] += 1

            comp_ratio = (stats["compressed"] / stats["received"]) * 100
            print(
                f"[{payload['vehicle_id']}] {action:15} | {reason:30} | "
                f"Δ={dev:6.1f}m | {payload['speed_kmh']:5.1f} km/h | "
                f"Bandwidth Saved: {comp_ratio:5.1f}%"
            )

    except requests.exceptions.ConnectionError:
        print("Waiting for VesselEdge API on http://127.0.0.1:8000 ...")
    except Exception as e:
        print(f"Parse/Stream error: {e}")


if __name__ == "__main__":
    client_id = f"VesselEdge-DEAI-Portfolio;{uuid.uuid4()}"
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        transport="websockets",
        client_id=client_id,
    )
    client.ws_set_options(path="/mqtt")
    client.tls_set()
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect("meri.digitraffic.fi", 443, keepalive=60)
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print("\nStream stopped. Final Session Stats:", stats)