import webview
import subprocess, sys, time, os, socket

# Always look in the directory where this script/EXE lives
BASE = os.path.dirname(os.path.abspath(__file__))
SERVER_PY = os.path.join(BASE, "server.py")
PYTHON = sys.executable

# Kill any existing server on port 3000
def kill_port():
    try:
        s = socket.socket()
        s.connect(("127.0.0.1", 3000))
        s.close()
        subprocess.run(["taskkill", "/F", "/IM", "python.exe"], capture_output=True, creationflags=0x08000000)
        time.sleep(1)
    except:
        pass

kill_port()

# Start server
print("Starting server from:", SERVER_PY)
subprocess.Popen([PYTHON, SERVER_PY], creationflags=0x08000000)
time.sleep(3)

# Open window
webview.create_window("VROX KING - Nabd", "http://127.0.0.1:3000/client.html", width=480, height=800, resizable=True)
webview.start(gui='edgechromium')
