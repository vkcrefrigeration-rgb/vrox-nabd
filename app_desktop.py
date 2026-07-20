import webview
import subprocess, sys, time, os

# Start the Python server
server_dir = os.path.dirname(os.path.abspath(__file__))
server_path = os.path.join(server_dir, "server.py")
python = sys.executable

subprocess.Popen([python, server_path], creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
time.sleep(2)

# Open as desktop app
webview.create_window(
    "VROX KING - Nabd Control",
    "http://127.0.0.1:3000/client.html",
    width=480, height=800,
    resizable=True
)
webview.start()
