#!/usr/bin/env python3
"""
VROX Nabd â€” Client Server (Zero Cost)
=====================================
Serves the client dashboard, handles auth, stores data in SQLite
Runs on: Windows / Linux / Raspberry Pi
Start:   python server.py
Access:  http://localhost:8080
"""

import http.server
import json
import sqlite3
import hashlib
import secrets
import time
import os
from urllib.parse import urlparse, parse_qs

# ==================== CONFIG ====================
PORT = int(os.environ.get("PORT", 3000))
DB_FILE = "nabd_data.db"
HOST = "0.0.0.0"
# ===============================================

# ==================== DATABASE ====================
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # Users table (clients)
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        name TEXT NOT NULL,
        company TEXT,
        role TEXT DEFAULT 'client'
    )''')
    
    # Sessions (JWT-like tokens)
    c.execute('''CREATE TABLE IF NOT EXISTS sessions (
        token TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        expires_at REAL NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')
    
    # Trucks
    c.execute('''CREATE TABLE IF NOT EXISTS trucks (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        user_id INTEGER NOT NULL,
        system_type TEXT DEFAULT 'SARYAN',
        plate_count INTEGER DEFAULT 1,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')
    
    # Live data from PLC
    c.execute('''CREATE TABLE IF NOT EXISTS truck_data (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        truck_id TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        t_box REAL,
        t_plate REAL,
        plate_soc REAL,
        state INTEGER,
        engine_rpm REAL,
        fuel_saved REAL,
        ambient REAL,
        error_code INTEGER,
        FOREIGN KEY (truck_id) REFERENCES trucks(id)
    )''')
    
    # Add demo user if not exists
    c.execute("SELECT COUNT(*) FROM users WHERE email = 'demo@vrox.com'")
    if c.fetchone()[0] == 0:
        password_hash = hashlib.sha256("demo123".encode()).hexdigest()
        c.execute("INSERT INTO users (email, password_hash, name, company) VALUES (?,?,?,?)",
                  ("demo@vrox.com", password_hash, "Demo Client", "Demo Company"))
        
        # Add demo trucks
        user_id = c.lastrowid
        for truck in [
            ("TRK-001", "Saryan Truck 01", "SARYAN", 1),
            ("TRK-002", "Tricora Truck 02", "TRICORA", 14),
            ("TRK-003", "Saryan Truck 03", "SARYAN", 1),
        ]:
            c.execute("INSERT INTO trucks (id, name, user_id, system_type, plate_count) VALUES (?,?,?,?,?)",
                      (truck[0], truck[1], user_id, truck[2], truck[3]))
        
        # Add demo data
        import random
        for t_id in ["TRK-001", "TRK-002", "TRK-003"]:
            for h in range(24):
                ts = f"2026-07-18T{h:02d}:00:00"
                t_box = -16.8 + random.uniform(-2, 2)
                t_plate = -22.4 + random.uniform(-4, 4)
                c.execute("INSERT INTO truck_data (truck_id, timestamp, t_box, t_plate, plate_soc, state, engine_rpm, fuel_saved, ambient) VALUES (?,?,?,?,?,?,?,?,?)",
                          (t_id, ts, round(t_box,1), round(t_plate,1), random.randint(40,90), random.randint(1,3), random.randint(0,1400), round(random.uniform(50,200),1), round(random.uniform(30,48),1)))
    
    conn.commit()
    conn.close()

# ==================== AUTH ====================
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def create_token(user_id):
    token = secrets.token_hex(32)
    expires = time.time() + 7200  # 2 hours
    conn = sqlite3.connect(DB_FILE)
    conn.execute("INSERT INTO sessions (token, user_id, expires_at) VALUES (?,?,?)", (token, user_id, expires))
    conn.commit()
    conn.close()
    return token

def verify_token(token):
    conn = sqlite3.connect(DB_FILE)
    c = conn.execute("SELECT user_id, expires_at FROM sessions WHERE token = ?", (token,))
    row = c.fetchone()
    conn.close()
    if row and row[1] > time.time():
        return row[0]
    return None

# ==================== API HANDLER ====================
class APIHandler(http.server.SimpleHTTPRequestHandler):
    
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()
    
    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
    
    def get_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length > 0 else {}
    
    def do_POST(self):
        path = urlparse(self.path).path
        
        if path == "/api/login":
            body = self.get_body()
            email = body.get("email", "")
            password = body.get("password", "")
            
            conn = sqlite3.connect(DB_FILE)
            c = conn.execute("SELECT id, name, company, password_hash FROM users WHERE email = ?", (email,))
            row = c.fetchone()
            conn.close()
            
            if row and row[3] == hash_password(password):
                token = create_token(row[0])
                self.send_json({
                    "token": token,
                    "user": {"id": row[0], "name": row[1], "company": row[2], "email": email}
                })
            else:
                self.send_json({"error": "Invalid credentials"}, 401)
            return
        
        if path == "/api/data":
            # PLC sends data here
            body = self.get_body()
            token = self.headers.get("Authorization", "").replace("Bearer ", "")
            user_id = verify_token(token) if token else 1  # Demo: skip auth for data upload
            
            conn = sqlite3.connect(DB_FILE)
            conn.execute("INSERT INTO truck_data (truck_id, timestamp, t_box, t_plate, plate_soc, state, engine_rpm, fuel_saved, ambient) VALUES (?,datetime('now'),?,?,?,?,?,?,?)",
                        (body.get("truck_id"), body.get("t_box"), body.get("t_plate"), body.get("plate_soc"), body.get("state"), body.get("engine_rpm"), body.get("fuel_saved"), body.get("ambient")))
            conn.commit()
            conn.close()
            self.send_json({"status": "ok"})
            return
    
    def do_GET(self):
        path = urlparse(self.path).path
        
        # API routes
        if path.startswith("/api/"):
            token = self.headers.get("Authorization", "").replace("Bearer ", "")
            user_id = verify_token(token)
            
            if path == "/api/trucks":
                if not user_id: self.send_json({"error": "Unauthorized"}, 401); return
                conn = sqlite3.connect(DB_FILE)
                c = conn.execute("SELECT id, name, system_type, plate_count FROM trucks WHERE user_id = ?", (user_id,))
                trucks = [{"id": r[0], "name": r[1], "type": r[2], "plates": r[3]} for r in c.fetchall()]
                conn.close()
                self.send_json(trucks)
                return
            
            if path == "/api/truck/latest":
                truck_id = parse_qs(urlparse(self.path).query).get("id", [None])[0]
                if not truck_id: self.send_json({"error": "Missing id"}, 400); return
                conn = sqlite3.connect(DB_FILE)
                c = conn.execute("SELECT t_box, t_plate, plate_soc, state, engine_rpm, fuel_saved, ambient, error_code, timestamp FROM truck_data WHERE truck_id = ? ORDER BY timestamp DESC LIMIT 1", (truck_id,))
                row = c.fetchone()
                # Also get truck type and plate count
                c2 = conn.execute("SELECT system_type, plate_count, name FROM trucks WHERE id = ?", (truck_id,))
                truck_info = c2.fetchone()
                conn.close()
                if row:
                    resp = {"t_box": row[0], "t_plate": row[1], "plate_soc": row[2], "state": row[3], "engine_rpm": row[4], "fuel_saved": row[5], "ambient": row[6], "error_code": row[7], "timestamp": row[8]}
                    if truck_info:
                        resp["type"] = truck_info[0]
                        resp["plate_count"] = truck_info[1]
                        resp["name"] = truck_info[2]
                    self.send_json(resp)
                else:
                    self.send_json({"error": "No data"}, 404)
                return
            
            self.send_json({"error": "Unknown API"}, 404)
            return
        
        # Static files â€” serve from current directory
        if path == "/" or path == "":
            path = "/client.html"
        
        file_path = os.path.join(os.path.dirname(__file__), path.lstrip("/"))
        if os.path.exists(file_path):
            self.send_response(200)
            if file_path.endswith(".html"): self.send_header("Content-Type", "text/html; charset=utf-8")
            elif file_path.endswith(".js"): self.send_header("Content-Type", "application/javascript")
            elif file_path.endswith(".css"): self.send_header("Content-Type", "text/css")
            elif file_path.endswith(".json"): self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            with open(file_path, "rb") as f:
                self.wfile.write(f.read())
        else:
            self.send_json({"error": "Not found"}, 404)
    
    def log_message(self, format, *args):
        # Quieter logging
        pass

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    init_db()
    print(f"\n{'='*50}")
    print(f"  VROX Nabd Client Server")
    print(f"  Running at: http://localhost:{PORT}")
    print(f"  Demo login: demo@vrox.com / demo123")
    print(f"  Press Ctrl+C to stop")
    print(f"{'='*50}\n")
    
    server = http.server.HTTPServer((HOST, PORT), APIHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
        server.server_close()


