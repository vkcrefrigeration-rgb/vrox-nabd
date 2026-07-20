# Simulates PLC sending data to the Nabd server
# Run after server.py
# Usage: python simulate_plc.py

import time
import random
import requests

SERVER = "http://localhost:8080"
TOKEN = None  # Demo mode — no auth needed

truck_ids = ["TRK-001", "TRK-002", "TRK-003"]

print("Simulating 3 trucks sending data...")
print("Press Ctrl+C to stop\n")

cycle = 0
while True:
    for tid in truck_ids:
        data = {
            "truck_id": tid,
            "t_box": round(-16.8 + random.uniform(-2, 2), 1),
            "t_plate": round(-22.4 + random.uniform(-4, 4), 1),
            "plate_soc": random.randint(40, 90),
            "state": random.choice([1, 3, 2]),
            "engine_rpm": random.choice([0, 0, 0, 1200, 1400]),
            "fuel_saved": round(random.uniform(50, 200), 1),
            "ambient": round(random.uniform(30, 48), 1)
        }
        try:
            headers = {"Content-Type": "application/json"}
            if TOKEN:
                headers["Authorization"] = "Bearer " + TOKEN
            resp = requests.post(SERVER + "/api/data", json=data, headers=headers, timeout=3)
            if resp.status_code == 200:
                print(f"[{tid}] OK — Box: {data['t_box']}C — State: {data['state']}")
        except Exception as e:
            print(f"[{tid}] FAIL — {e}")
    
    cycle += 1
    time.sleep(5)  # Every 5 seconds
