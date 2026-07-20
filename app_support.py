import webview
import subprocess, sys, time, os

server_dir = os.path.dirname(os.path.abspath(__file__))
python = sys.executable

# Start server
subprocess.Popen([python, os.path.join(server_dir, "server.py")], 
    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
time.sleep(2)

# Support app
webview.create_window(
    "VROX KING - Nabd Support",
    "http://127.0.0.1:3000/support.html",
    width=1100, height=700,
    resizable=True
)
webview.start()
