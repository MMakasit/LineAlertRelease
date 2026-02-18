import psutil
import pyautogui
import requests
import json
import time
import os
import sys
import threading
import tkinter as tk
from tkinter import scrolledtext, messagebox

# Constants
CONFIG_FILE = 'config.json'
ASSETS_DIR = 'assets'
LINE_API_URL = 'https://api.line.me/v2/bot/message/broadcast'

class LineAlertApp:
    def __init__(self, root):
        self.root = root
        self.root.title("LINE Alert Bot - Seal Online")
        self.root.geometry("400x450")
        self.root.resizable(False, False)

        # Configuration
        self.config = self.load_config()
        self.token = self.config.get('line_channel_access_token', '')
        self.interval = self.config.get('check_interval', 2.0)
        self.conf = self.config.get('confidence', 0.9)
        self.cooldown = self.config.get('cooldown_seconds', 60)
        self.msg_text = self.config.get('message', "Alert!")
        self.game_process_name = self.config.get('game_process_name', "")
        self.crash_msg_text = self.config.get('crash_message', "Game Crashed!")

        self.running = False
        self.monitor_thread = None
        self.last_alert_time = 0
        self.was_game_running = False

        # GUI Components
        self.create_widgets()
        
        # Auto-start monitoring
        self.start_monitoring()

    def load_config(self):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            messagebox.showerror("Config Error", f"Could not load config.json:\n{e}")
            return {}

    def create_widgets(self):
        # Title
        tk.Label(self.root, text="LINE Alert System", font=("Arial", 16, "bold")).pack(pady=10)

        # Status Frame
        status_frame = tk.LabelFrame(self.root, text="Status", padx=10, pady=10)
        status_frame.pack(fill="x", padx=10)

        self.lbl_monitoring = tk.Label(status_frame, text="Monitoring: STOPPED", fg="red", font=("Arial", 10))
        self.lbl_monitoring.pack(anchor="w")

        self.lbl_game_status = tk.Label(status_frame, text=f"Game Process ({self.game_process_name}): Not Detected", fg="gray")
        self.lbl_game_status.pack(anchor="w")

        self.lbl_last_detected = tk.Label(status_frame, text="Last Alert: None")
        self.lbl_last_detected.pack(anchor="w")

        # Test Button
        btn_frame = tk.Frame(self.root)
        btn_frame.pack(pady=10)
        
        tk.Button(btn_frame, text="Test Notification", command=self.send_test_message, bg="#00B900", fg="white", font=("Arial", 10, "bold"), padx=10).pack()

        # Log Area
        tk.Label(self.root, text="Logs:").pack(anchor="w", padx=10)
        self.log_area = scrolledtext.ScrolledText(self.root, height=10, state='disabled', font=("Consolas", 9))
        self.log_area.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def log(self, message):
        self.log_area.config(state='normal')
        self.log_area.insert(tk.END, f"[{time.strftime('%H:%M:%S')}] {message}\n")
        self.log_area.see(tk.END)
        self.log_area.config(state='disabled')

    def send_line_broadcast(self, message):
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.token}'
        }
        payload = {'messages': [{'type': 'text', 'text': message}]}
        
        try:
            response = requests.post(LINE_API_URL, headers=headers, json=payload, timeout=10)
            response.raise_for_status()
            self.log("Message sent successfully.")
            return True
        except Exception as err:
            self.log(f"Error sending message: {err}")
            return False

    def send_test_message(self):
        if not self.token:
            messagebox.showwarning("Config Error", "No Access Token found in config.json")
            return
        
        self.log("Sending test message...")
        threading.Thread(target=self.send_line_broadcast, args=("This is a TEST message from your LineBot.",)).start()

    def get_image_list(self, directory):
        images = []
        if not os.path.exists(directory):
            return images
        for filename in os.listdir(directory):
            if filename.lower().startswith("dead_state") and filename.lower().endswith((".png", ".jpg", ".jpeg")):
                 images.append(os.path.join(directory, filename))
        return images

    def check_for_death(self, image_paths):
        for img_path in image_paths:
            try:
                if pyautogui.locateOnScreen(img_path, confidence=self.conf):
                    return True, img_path
            except Exception:
                continue
        return False, None

    def check_process_running(self, process_name):
        if not process_name:
            return False
        for proc in psutil.process_iter(['name']):
            try:
                if process_name.lower() in proc.info['name'].lower():
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        return False

    def start_monitoring(self):
        if not self.running:
            self.running = True
            self.lbl_monitoring.config(text="Monitoring: RUNNING", fg="green")
            self.monitor_thread = threading.Thread(target=self.run_monitor_loop, daemon=True)
            self.monitor_thread.start()
            self.log("Monitoring started.")

    def run_monitor_loop(self):
        # Ensure assets directory exists
        if not os.path.exists(ASSETS_DIR):
            try:
                os.makedirs(ASSETS_DIR)
                self.log(f"Created '{ASSETS_DIR}' directory.")
            except Exception as e:
                self.log(f"Error creating assets dir: {e}")

        while self.running:
            current_time = time.time()
            
            # 1. Update Game Process Status
            if self.game_process_name:
                is_game_running = self.check_process_running(self.game_process_name)
                
                # Update UI label (using lambda/after is safer for thread-safety but simple config update often works in tk)
                # Ideally use self.root.after, but for simple label text update:
                status_text = "Detected (Running)" if is_game_running else "Not Detected"
                status_color = "green" if is_game_running else "red"
                self.lbl_game_status.config(text=f"Game Process ({self.game_process_name}): {status_text}", fg=status_color)

                if is_game_running:
                    if not self.was_game_running:
                        self.log(f"Game '{self.game_process_name}' started.")
                        self.was_game_running = True
                else:
                    if self.was_game_running:
                        self.log("GAME PROCESS LOST! Sending alert...")
                        self.send_line_broadcast(self.crash_msg_text)
                        self.was_game_running = False
            
            # 2. Death Detection
            # Only check if game is running (or if monitoring is disabled)
            should_check_death = True
            if self.game_process_name and not self.was_game_running:
                should_check_death = False

            image_paths = self.get_image_list(ASSETS_DIR)
            
            if not image_paths and should_check_death:
                 # Throttle "no images" log to avoid span
                 pass 

            if should_check_death and image_paths:
                if current_time - self.last_alert_time > self.cooldown:
                    is_dead, found_img = self.check_for_death(image_paths)
                    if is_dead:
                        filename = os.path.basename(found_img)
                        self.log(f"DEAD DETECTED! ({filename})")
                        self.lbl_last_detected.config(text=f"Last Alert: {time.strftime('%H:%M:%S')} ({filename})")
                        
                        self.send_line_broadcast(self.msg_text)
                        self.last_alert_time = current_time
                        self.log(f"Cooldown {self.cooldown}s started.")
            
            time.sleep(self.interval)

if __name__ == "__main__":
    if not os.path.exists(CONFIG_FILE):
        # Create default config if missing
        default_config = {
            "line_channel_access_token": "",
            "check_interval": 2.0,
            "confidence": 0.9,
            "cooldown_seconds": 60,
            "message": "Alert! Character Died.",
            "game_process_name": "SO3DPlus.exe",
            "crash_message": "Game Crashed/Closed!"
        }
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(default_config, f, indent=4)

    root = tk.Tk()
    app = LineAlertApp(root)
    root.mainloop()

