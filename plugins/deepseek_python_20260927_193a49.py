"""
n8n Bridge Plugin for MARK LIV
Exposes an HTTP endpoint so n8n can send commands to JARVIS.
"""
from flask import Flask, request, jsonify
import threading
import subprocess
import webbrowser
import os
import pyautogui
from datetime import datetime

# Flask app
app = Flask(__name__)

# ============ ALLOWED COMMANDS ============
ALLOWED_APPS = {
    "chrome": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "explorer": "explorer.exe",
    "vscode": "code",
    "edge": "msedge.exe",
    "whatsapp": "whatsapp:",
}

BLOCKED = ["format", "del /f", "rm -rf", "shutdown", "reg delete"]

# ============ PLUGIN INTERFACE ============
PLUGIN = {
    "name": "n8n_bridge",
    "description": "HTTP bridge for n8n — receive commands from n8n and execute on PC",
    "version": "1.0"
}

def run():
    """Called by MARK LIV at startup — starts HTTP server in background thread."""
    def start_server():
        app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
    t = threading.Thread(target=start_server, daemon=True)
    t.start()
    print("[n8n_bridge] HTTP server started on port 5000")
    return "n8n bridge plugin active"

# ============ HTTP ENDPOINTS ============
@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "online", "plugin": "n8n_bridge", "time": datetime.now().isoformat()})

@app.route('/execute', methods=['POST'])
def execute():
    data = request.json or {}
    action = data.get('action', '').lower()
    params = data.get('params', {})
    
    try:
        if action == 'open_app':
            name = params.get('name', '').lower()
            if name in ALLOWED_APPS:
                target = ALLOWED_APPS[name]
                if target.startswith('http') or target.endswith(':'):
                    webbrowser.open(target)
                else:
                    subprocess.Popen(target, shell=True)
                return jsonify({"success": True, "message": f"Opened {name}"})
            return jsonify({"success": False, "error": f"App not allowed. Allowed: {list(ALLOWED_APPS.keys())}"}), 403
        
        elif action == 'open_url':
            url = params.get('url', '')
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url
            webbrowser.open(url)
            return jsonify({"success": True, "message": f"Opened {url}"})
        
        elif action == 'run_command':
            cmd = params.get('command', '')
            for b in BLOCKED:
                if b in cmd.lower():
                    return jsonify({"success": False, "error": f"Blocked: {b}"}), 403
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
            return jsonify({"success": result.returncode == 0, "stdout": result.stdout[:2000], "stderr": result.stderr[:500]})
        
        elif action == 'screenshot':
            path = params.get('path', 'C:\\Jarvis\\screenshot.png')
            pyautogui.screenshot().save(path)
            return jsonify({"success": True, "path": path})
        
        elif action == 'system_info':
            import psutil
            return jsonify({"success": True, "cpu": psutil.cpu_percent(), "ram": psutil.virtual_memory().percent})
        
        elif action == 'type_text':
            pyautogui.typewrite(params.get('text', ''), interval=0.05)
            return jsonify({"success": True, "message": "Typed"})
        
        else:
            return jsonify({"success": False, "error": f"Unknown action: {action}"}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500