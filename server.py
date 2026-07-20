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
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nabd_data.db")
HOST = "0.0.0.0"
MAX_LOGIN_TRIES = 100      # Max login attempts
LOGIN_BLOCK_MINUTES = 1 # Block after exceeding
RATE_LIMIT_WINDOW = 60   # 1 minute window
MAX_REQUESTS_PER_MINUTE = 500
# ===============================================

# ==================== RATE LIMITING ====================
login_attempts = {}  # {ip: [timestamp, count, blocked_until]}
rate_tracker = {}    # {ip: [timestamps...]}

def check_rate_limit(ip, endpoint):
    now = time.time()
    if ip not in rate_tracker:
        rate_tracker[ip] = []
    rate_tracker[ip] = [t for t in rate_tracker[ip] if now - t < RATE_LIMIT_WINDOW]
    rate_tracker[ip].append(now)
    if len(rate_tracker[ip]) > MAX_REQUESTS_PER_MINUTE:
        return False
    return True

def check_login_rate(ip):
    now = time.time()
    if ip not in login_attempts:
        login_attempts[ip] = [now, 0, 0]
    data = login_attempts[ip]
    if data[2] > now:
        return False, f"Blocked for {int((data[2]-now)/60)+1} minutes"
    if now - data[0] > 300:
        data[0] = now; data[1] = 0
    data[1] += 1
    if data[1] > MAX_LOGIN_TRIES:
        data[2] = now + LOGIN_BLOCK_MINUTES * 60
        return False, f"Too many attempts — blocked {LOGIN_BLOCK_MINUTES} minutes"
    return True, None

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
        system_type TEXT DEFAULT 'SRAYAN',
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
    
    # Alarms
    c.execute('''CREATE TABLE IF NOT EXISTS alarms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        truck_id TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        code INTEGER,
        message TEXT,
        level TEXT DEFAULT 'warning',
        acknowledged INTEGER DEFAULT 0,
        FOREIGN KEY (truck_id) REFERENCES trucks(id)
    )''')
    
    # GPS tracking
    c.execute('''CREATE TABLE IF NOT EXISTS gps_data (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        truck_id TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        lat REAL,
        lng REAL,
        speed REAL,
        FOREIGN KEY (truck_id) REFERENCES trucks(id)
    )''')
    c.execute("SELECT COUNT(*) FROM users WHERE email = 'demo@vrox.com'")
    if c.fetchone()[0] == 0:
        password_hash = hashlib.sha256("demo123".encode()).hexdigest()
        c.execute("INSERT INTO users (email, password_hash, name, company) VALUES (?,?,?,?)",
                  ("demo@vrox.com", password_hash, "Demo Client", "Demo Company"))
        
        # Add demo trucks
        user_id = c.lastrowid
        for truck in [
            ("TRK-001", "SRAYAN Truck 01", "SRAYAN", 1),
            ("TRK-002", "Tricora Truck 02", "TRICORA", 14),
            ("TRK-003", "SRAYAN Truck 03", "SRAYAN", 1),
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
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
    
    def get_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length > 0 else {}
    
    def do_POST(self):
        path = urlparse(self.path).path
        
        if path == "/api/register":
            body = self.get_body()
            unit_id = body.get("id","")
            name = body.get("name","")
            unit_type = body.get("type","SRAYAN")
            plates = body.get("plates",1)
            email = body.get("email","")
            
            conn = sqlite3.connect(DB_FILE)
            c = conn.execute("SELECT id FROM users WHERE email = ?", (email,))
            user = c.fetchone()
            if not user:
                # Auto-create user
                pw = hashlib.sha256(("auto"+email).encode()).hexdigest()
                c.execute("INSERT INTO users (email, password_hash, name, company) VALUES (?,?,?,?)",
                          (email, pw, email.split("@")[0], "Auto Registered"))
                user_id = c.lastrowid
            else:
                user_id = user[0]
            
            c.execute("INSERT OR REPLACE INTO trucks (id, name, user_id, system_type, plate_count) VALUES (?,?,?,?,?)",
                      (unit_id, name, user_id, unit_type, plates))
            conn.commit()
            conn.close()
            self.send_json({"status":"registered","unit_id":unit_id})
            return
        
        if path == "/api/login":
            ip = self.client_address[0]
            allowed, msg = check_login_rate(ip)
            if not allowed:
                self.send_json({"error": msg}, 429)
                return
            
            body = self.get_body()
            email = body.get("email", "")
            password = body.get("password", "")
            
            conn = sqlite3.connect(DB_FILE)
            c = conn.execute("SELECT id, name, company, password_hash, role FROM users WHERE email = ?", (email,))
            row = c.fetchone()
            conn.close()
            
            if row and row[3] == hash_password(password):
                token = create_token(row[0])
                self.send_json({
                    "token": token,
                    "user": {"id": row[0], "name": row[1], "company": row[2], "email": email, "role": row[4] or "client"}
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
        ip = self.client_address[0]
        
        # Rate limit all API calls
        if path.startswith("/api/") and not check_rate_limit(ip, path):
            self.send_json({"error": "Rate limit exceeded"}, 429)
            return
        
        # API routes
        if path.startswith("/api/"):
            token = self.headers.get("Authorization", "").replace("Bearer ", "")
            user_id = verify_token(token)
            
            if path == "/api/trucks":
                if not user_id: self.send_json({"error": "Unauthorized"}, 401); return
                conn = sqlite3.connect(DB_FILE)
                # Admin sees all trucks, clients see only theirs
                c2 = conn.execute("SELECT role FROM users WHERE id = ?", (user_id,))
                role = c2.fetchone()
                if role and role[0] == 'admin':
                    c = conn.execute("SELECT id, name, system_type, plate_count FROM trucks")
                else:
                    c = conn.execute("SELECT id, name, system_type, plate_count FROM trucks WHERE user_id = ?", (user_id,))
                trucks = [{"id": r[0], "name": r[1], "type": r[2], "plates": r[3]} for r in c.fetchall()]
                conn.close()
                self.send_json(trucks)
                return
            
            if path == "/api/alarms":
                truck_id = parse_qs(urlparse(self.path).query).get("truck", [None])[0]
                conn = sqlite3.connect(DB_FILE)
                if truck_id:
                    c = conn.execute("SELECT a.timestamp, a.code, a.message, a.level, a.acknowledged, t.name FROM alarms a JOIN trucks t ON a.truck_id = t.id WHERE a.truck_id = ? ORDER BY a.timestamp DESC LIMIT 20", (truck_id,))
                else:
                    c = conn.execute("SELECT a.timestamp, a.code, a.message, a.level, a.acknowledged, t.name FROM alarms a JOIN trucks t ON a.truck_id = t.id ORDER BY a.timestamp DESC LIMIT 30")
                alarms = [{"timestamp": r[0], "code": r[1], "message": r[2], "level": r[3], "acknowledged": r[4], "truck_name": r[5]} for r in c.fetchall()]
                conn.close()
                self.send_json(alarms)
                return
            
            if path == "/api/gps/latest":
                truck_id = parse_qs(urlparse(self.path).query).get("id", [None])[0]
                if not truck_id: self.send_json({"error": "Missing id"}, 400); return
                conn = sqlite3.connect(DB_FILE)
                c = conn.execute("SELECT lat, lng, speed FROM gps_data WHERE truck_id = ? ORDER BY timestamp DESC LIMIT 1", (truck_id,))
                row = c.fetchone()
                conn.close()
                if row: self.send_json({"lat": row[0], "lng": row[1], "speed": row[2]})
                else: self.send_json({"error": "No GPS data"}, 404)
                return
            
            if path == "/api/predict":
                truck_id = parse_qs(urlparse(self.path).query).get("id", [None])[0]
                if not truck_id: self.send_json({"error": "Missing id"}, 400); return
                conn = sqlite3.connect(DB_FILE)
                c = conn.execute("SELECT t_box, t_plate, plate_soc, timestamp FROM truck_data WHERE truck_id = ? AND timestamp > datetime('now','-3 days') ORDER BY timestamp ASC", (truck_id,))
                rows = c.fetchall()
                conn.close()
                predictions = {}
                if len(rows) > 10:
                    # Analyze box temp trend over last 3 days
                    temps = [r[0] for r in rows if r[0]]
                    if len(temps) > 5:
                        trend = (temps[-1] - temps[0]) / len(temps)  # degrees per reading
                        if trend > 0.05:
                            hours_until_critical = abs((-18.0 - temps[-1]) / trend) if trend > 0 else 999
                            predictions["box_temp"] = {"trend": round(trend*100,2), "status": "warning", "message": f"Box temp rising {round(trend*100,2)}C/day — reaching critical in ~{int(hours_until_critical)}h"}
                        elif trend < -0.05:
                            predictions["box_temp"] = {"trend": round(trend*100,2), "status": "ok", "message": "Box temp trend: stable/cooling"}
                        else:
                            predictions["box_temp"] = {"trend": round(trend*100,2), "status": "ok", "message": "Box temp: stable"}
                    
                    # Plate SOC degradation
                    socs = [r[2] for r in rows if r[2]]
                    if len(socs) > 5:
                        plate_trend = (socs[-1] - socs[0]) / len(socs)
                        if plate_trend < -0.1:
                            predictions["plate_soc"] = {"trend": round(plate_trend*100,2), "status": "warning", "message": f"Plate SOC declining {abs(round(plate_trend*100,2))}% per cycle — check vacuum"}
                        else:
                            predictions["plate_soc"] = {"trend": round(plate_trend*100,2), "status": "ok", "message": "Plate SOC: healthy"}
                    
                    # Predict maintenance needs
                    predictions["maintenance"] = []
                    if temps and temps[-1] > -10:
                        predictions["maintenance"].append({"item": "Coil", "status": "warning", "message": "Coil icing risk — schedule defrost check"})
                    if len(socs) > 20 and sum(1 for s in socs[-20:] if s < 40) > 10:
                        predictions["maintenance"].append({"item": "Vacuum Seal", "status": "critical", "message": "Plate losing capacity — vacuum check recommended"})
                self.send_json(predictions if predictions else {"status": "insufficient_data"})
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
            
            if path == "/api/fleet/latest":
                if not user_id: self.send_json({"error": "Unauthorized"}, 401); return
                conn = sqlite3.connect(DB_FILE)
                c2 = conn.execute("SELECT role FROM users WHERE id = ?", (user_id,))
                role = c2.fetchone()
                if role and role[0] == 'admin':
                    c = conn.execute("SELECT id, name, system_type, plate_count FROM trucks")
                else:
                    c = conn.execute("SELECT id, name, system_type, plate_count FROM trucks WHERE user_id = ?", (user_id,))
                trucks = c.fetchall()
                result = []
                for t in trucks:
                    tid, name, stype, plates = t
                    d = conn.execute("SELECT t_box, t_plate, plate_soc, state, engine_rpm, fuel_saved, ambient FROM truck_data WHERE truck_id = ? ORDER BY timestamp DESC LIMIT 1", (tid,)).fetchone()
                    if d: result.append({"id":tid,"name":name,"type":stype,"plates":plates,"t_box":d[0],"t_plate":d[1],"plate_soc":d[2],"state":d[3],"engine_rpm":d[4],"fuel_saved":d[5],"ambient":d[6]})
                    else: result.append({"id":tid,"name":name,"type":stype,"plates":plates,"t_box":0,"t_plate":0,"plate_soc":0,"state":1,"engine_rpm":0,"fuel_saved":0,"ambient":0})
                conn.close()
                self.send_json(result)
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
            self.send_header("Cache-Control", "no-cache, no-store")
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



