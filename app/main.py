from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from geopy.distance import geodesic
from typing import List, Dict

api = FastAPI(
    title="FleetEdge: Anomaly-Aware Trajectory Compression API",
    description="Edge-native FastAPI microservice implementing BWC-DR-A trajectory compression for high-frequency fleet tracking.",
    version="2.0.0"
)

# --- IN-MEMORY EDGE WAREHOUSE ---
# fleet_trajectories stores the final compressed dataset.
fleet_trajectories: Dict[str, List[dict]] = {}
# last_known_state tracks the last retained coordinate for Dead Reckoning math.
last_known_state: Dict[str, dict] = {}

# --- BWC-DR-A CONFIGURATION ---
# Dead Reckoning Threshold: Discard telemetry if the vehicle moved less than 50 meters.
DR_DEVIATION_THRESHOLD_METERS = 50.0

# --- DATA VALIDATION MODELS ---
class TelemetryPayload(BaseModel):
    vehicle_id: str
    timestamp: str
    latitude: float
    longitude: float
    speed_kmh: float
    ai_anomaly_flag: bool  # Upstream edge anomaly detector flag

@api.post("/telemetry", status_code=201)
def ingest_and_compress(payload: TelemetryPayload):
    """
    Ingests high-frequency GNSS coordinates and applies BWC-DR-A compression.
    Prioritizes anomalous data points over strict bandwidth limits.
    """
    vid = payload.vehicle_id
    current_coords = (payload.latitude, payload.longitude)
    
    # 1. Initialize new vehicle trajectory
    if vid not in fleet_trajectories:
        fleet_trajectories[vid] = [payload.model_dump()]
        last_known_state[vid] = {"coords": current_coords}
        return {"action": "RETAINED", "reason": "Initial Registration"}

    last_coords = last_known_state[vid]["coords"]
    distance_moved = geodesic(last_coords, current_coords).meters
    
    # --- EDGE COMPRESSION ENGINE (BWC-DR-A) ---
    
    # RULE 1: Anomaly Priority Override
    # If the on-device ML model flags anomalous behavior, bypass bandwidth constraints and force-save the coordinate.
    if payload.ai_anomaly_flag:
        fleet_trajectories[vid].append(payload.model_dump())
        last_known_state[vid]["coords"] = current_coords
        return {"action": "RETAINED", "reason": "Anomaly Override", "deviation_m": round(distance_moved, 2)}
        
    # RULE 2: Bandwidth-Constrained Dead Reckoning
    # If the vehicle is operating normally and hasn't deviated beyond the threshold, drop the point to save bandwidth.
    if distance_moved < DR_DEVIATION_THRESHOLD_METERS:
        return {"action": "COMPRESSED_AWAY", "reason": "Within Dead Reckoning Threshold", "deviation_m": round(distance_moved, 2)}
        
    # RULE 3: Threshold Exceeded
    # The vehicle moved significantly. Retain the point to maintain trajectory accuracy.
    fleet_trajectories[vid].append(payload.model_dump())
    last_known_state[vid]["coords"] = current_coords
    return {"action": "RETAINED", "reason": "Threshold Exceeded", "deviation_m": round(distance_moved, 2)}

@api.get("/fleet/{vehicle_id}/trajectory")
def get_compressed_trajectory(vehicle_id: str):
    """Retrieves the finalized, compressed trajectory for a specific vehicle."""
    if vehicle_id not in fleet_trajectories:
        raise HTTPException(status_code=404, detail="Vehicle not found in edge storage.")
    
    data = fleet_trajectories[vehicle_id]
    return {
        "vehicle_id": vehicle_id,
        "total_retained_points": len(data),
        "anomalies_preserved": sum(1 for p in data if p["ai_anomaly_flag"]),
        "trajectory": data
    }