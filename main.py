import pyautogui
import requests
import json
import time
import os
import sys
import threading
import tkinter as tk
from tkinter import scrolledtext, messagebox
from pystray import MenuItem as item
import pystray
from PIL import Image, ImageDraw

# Constants
CONFIG_FILE = 'config.json'
ASSETS_DIR = 'assets'
LINE_API_URL = 'https://api.line.me/v2/bot/message/broadcast'

class LineAlertApp:
    def __init__(self, root):
        self.root = root
        self.root.title("LINE Alert Bot - Pixel Monitor")
        self.root.geometry("400x500")
        self.root.resizable(False, False)

        # Configuration
        self.config = self.load_config()
        self.token = self.config.get('line_channel_access_token', '')
        self.interval = self.config.get('check_interval', 2.0)
        self.conf = self.config.get('confidence', 0.9)
        self.cooldown = self.config.get('cooldown_seconds', 60)
        self.msg_text = self.config.get('message', "Alert!")
        
        # New Pixel Config
        self.desktop_color = tuple(self.config.get('desktop_color_rgb', [15, 15, 15]))
        self.game1_pos = tuple(self.config.get('game1_pos', [100, 100]))
        self.game2_pos = tuple(self.config.get('game2_pos', [500, 100]))
        self.game1_msg = self.config.get('game1_closed_msg', "เกมจอ 1 ถูกปิด!")
        self.game2_msg = self.config.get('game2_closed_msg', "เกมจอ 2 ถูกปิด!")

        # Independent Monitoring Flags
        self.monitoring_death = False
        self.monitoring_g1 = False
        self.monitoring_g2 = False

        self.running = True # Loop runs as long as app is open
        self.monitor_thread = None
        self.last_alert_time = 0

        # GUI Components
        self.create_widgets()
        
        # Start the background monitor loop (it will check flags inside)
        self.monitor_thread = threading.Thread(target=self.run_monitor_loop, daemon=True)
        self.monitor_thread.start()

        # Tray Icon setup
        self.tray_icon = None
        self.root.protocol("WM_DELETE_WINDOW", self.minimize_to_tray)

    def load_config(self):
        try:
            if not os.path.exists(CONFIG_FILE):
                return {}
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            messagebox.showerror("Config Error", f"Could not load config.json:\n{e}")
            return {}

    def save_config(self):
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            self.log(f"Error saving config: {e}")

    def create_widgets(self):
        # Title
        tk.Label(self.root, text="LINE Alert System", font=("Arial", 16, "bold")).pack(pady=10)

        # Status Frame
        status_frame = tk.LabelFrame(self.root, text="Status & Controls", padx=10, pady=10)
        status_frame.pack(fill="x", padx=10)

        # Desktop Color Row
        dt_frame = tk.Frame(status_frame)
        dt_frame.pack(fill="x", pady=2)
        tk.Label(dt_frame, text="Desktop RGB:").pack(side="left")
        self.lbl_desktop_color = tk.Label(dt_frame, text=str(self.desktop_color), fg="blue")
        self.lbl_desktop_color.pack(side="left", padx=5)
        tk.Button(dt_frame, text="Set Color", command=self.start_capture_desktop_color, font=("Arial", 8)).pack(side="right")

        # Death Monitor Row
        death_frame = tk.Frame(status_frame)
        death_frame.pack(fill="x", pady=5)
        self.lbl_death_status = tk.Label(death_frame, text="Death: STOPPED", fg="red", font=("Arial", 9, "bold"))
        self.lbl_death_status.pack(side="left")
        self.btn_death_toggle = tk.Button(death_frame, text="Start Death", command=self.toggle_death, font=("Arial", 8), width=10, bg="#e1f5fe")
        self.btn_death_toggle.pack(side="right", padx=2)

        # Window 1 Row
        g1_frame = tk.Frame(status_frame)
        g1_frame.pack(fill="x", pady=5)
        self.lbl_game1_status = tk.Label(g1_frame, text="Win 1: STOPPED", fg="red", font=("Arial", 9, "bold"))
        self.lbl_game1_status.pack(side="left")
        tk.Button(g1_frame, text="Set Pos 1", command=lambda: self.start_capture_pos(1), font=("Arial", 8)).pack(side="right", padx=2)
        self.btn_g1_toggle = tk.Button(g1_frame, text="Start Win 1", command=self.toggle_g1, font=("Arial", 8), width=10, bg="#e1f5fe")
        self.btn_g1_toggle.pack(side="right", padx=2)

        # Window 2 Row
        g2_frame = tk.Frame(status_frame)
        g2_frame.pack(fill="x", pady=5)
        self.lbl_game2_status = tk.Label(g2_frame, text="Win 2: STOPPED", fg="red", font=("Arial", 9, "bold"))
        self.lbl_game2_status.pack(side="left")
        tk.Button(g2_frame, text="Set Pos 2", command=lambda: self.start_capture_pos(2), font=("Arial", 8)).pack(side="right", padx=2)
        self.btn_g2_toggle = tk.Button(g2_frame, text="Start Win 2", command=self.toggle_g2, font=("Arial", 8), width=10, bg="#e1f5fe")
        self.btn_g2_toggle.pack(side="right", padx=2)

        self.lbl_last_detected = tk.Label(status_frame, text="Last Alert: None")
        self.lbl_last_detected.pack(anchor="w", pady=(5,0))

        # Test Button
        btn_frame = tk.Frame(self.root)
        btn_frame.pack(pady=10)
        tk.Button(btn_frame, text="Test Message", command=self.send_test_message, bg="#00B900", fg="white", font=("Arial", 10, "bold"), padx=10).pack()

        # Log Area
        tk.Label(self.root, text="Logs:").pack(anchor="w", padx=10)
        self.log_area = scrolledtext.ScrolledText(self.root, height=10, state='disabled', font=("Consolas", 9))
        self.log_area.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def log(self, message):
        def _log():
            self.log_area.config(state='normal')
            self.log_area.insert(tk.END, f"[{time.strftime('%H:%M:%S')}] {message}\n")
            self.log_area.see(tk.END)
            self.log_area.config(state='disabled')
        self.root.after(0, _log)

    def toggle_death(self):
        self.monitoring_death = not self.monitoring_death
        state = "RUNNING" if self.monitoring_death else "STOPPED"
        color = "green" if self.monitoring_death else "red"
        text = "Stop Death" if self.monitoring_death else "Start Death"
        self.lbl_death_status.config(text=f"Death: {state}", fg=color)
        self.btn_death_toggle.config(text=text)
        self.log(f"Death Monitoring {state}")

    def toggle_g1(self):
        self.monitoring_g1 = not self.monitoring_g1
        state = "RUNNING" if self.monitoring_g1 else "STOPPED"
        color = "green" if self.monitoring_g1 else "red"
        text = "Stop Win 1" if self.monitoring_g1 else "Start Win 1"
        self.lbl_game1_status.config(text=f"Win 1: {state}", fg=color)
        self.btn_g1_toggle.config(text=text)
        self.log(f"Window 1 Monitoring {state}")

    def toggle_g2(self):
        self.monitoring_g2 = not self.monitoring_g2
        state = "RUNNING" if self.monitoring_g2 else "STOPPED"
        color = "green" if self.monitoring_g2 else "red"
        text = "Stop Win 2" if self.monitoring_g2 else "Start Win 2"
        self.lbl_game2_status.config(text=f"Win 2: {state}", fg=color)
        self.btn_g2_toggle.config(text=text)
        self.log(f"Window 2 Monitoring {state}")

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
        threading.Thread(target=self.send_line_broadcast, args=("This is a TEST message from your LineBot.",), daemon=True).start()

    def start_capture_pos(self, window_num):
        self.log(f"Move mouse to Window {window_num} target pixel. Capturing in 3s...")
        def capture():
            time.sleep(3)
            x, y = pyautogui.position()
            color = pyautogui.pixel(x, y)
            pos = [x, y]
            if window_num == 1:
                self.game1_pos = tuple(pos)
                self.config['game1_pos'] = pos
            else:
                self.game2_pos = tuple(pos)
                self.config['game2_pos'] = pos
            self.save_config()
            self.log(f"Window {window_num} Set -> Pos: ({x}, {y}), Color: {color}")
        threading.Thread(target=capture, daemon=True).start()

    def start_capture_desktop_color(self):
        self.log("Move mouse to desktop area. Capturing in 3s...")
        def capture():
            time.sleep(3)
            x, y = pyautogui.position()
            color = pyautogui.pixel(x, y)
            self.desktop_color = color
            self.config['desktop_color_rgb'] = list(color)
            self.save_config()
            self.root.after(0, lambda: self.lbl_desktop_color.config(text=str(color)))
            self.log(f"Desktop Color set to: {color}")
        threading.Thread(target=capture, daemon=True).start()

    def get_image_list(self, directory):
        images = []
        if not os.path.exists(directory): return images
        for filename in os.listdir(directory):
            if filename.lower().startswith("dead_state") and filename.lower().endswith((".png", ".jpg", ".jpeg")):
                 images.append(os.path.join(directory, filename))
        return images

    def check_for_death(self, image_paths):
        for img_path in image_paths:
            try:
                if pyautogui.locateOnScreen(img_path, confidence=self.conf):
                    return True, img_path
            except Exception: continue
        return False, None

    def create_tray_icon(self):
        # Create a simple icon
        image = Image.new('RGB', (64, 64), color=(0, 128, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((16, 16, 48, 48), fill=(255, 255, 255))
        menu = (item('Show', self.show_window), item('Exit', self.quit_window))
        self.tray_icon = pystray.Icon("name", image, "Line Alert Bot", menu)
        self.tray_icon.run()

    def minimize_to_tray(self):
        self.root.withdraw()
        threading.Thread(target=self.create_tray_icon, daemon=True).start()

    def show_window(self, icon, item):
        self.tray_icon.stop()
        self.root.after(0, self.root.deiconify)

    def quit_window(self, icon, item):
        self.tray_icon.stop()
        self.root.destroy()
        sys.exit()

    def run_monitor_loop(self):
        # Ensure assets directory exists
        if not os.path.exists(ASSETS_DIR):
            try: os.makedirs(ASSETS_DIR)
            except Exception: pass

        while self.running:
            # 1. Window 1 Monitoring
            if self.monitoring_g1:
                try:
                    is_g1_desktop = pyautogui.pixelMatchesColor(self.game1_pos[0], self.game1_pos[1], self.desktop_color, tolerance=20)
                    if is_g1_desktop:
                        self.log(f"Window 1 closed! Sent alert and stopping.")
                        if self.send_line_broadcast(self.game1_msg):
                            self.root.after(0, self.toggle_g1) # Stop after success
                except Exception as e:
                    self.log(f"W1 Err: {e}")

            # 2. Window 2 Monitoring
            if self.monitoring_g2:
                try:
                    is_g2_desktop = pyautogui.pixelMatchesColor(self.game2_pos[0], self.game2_pos[1], self.desktop_color, tolerance=20)
                    if is_g2_desktop:
                        self.log(f"Window 2 closed! Sent alert and stopping.")
                        if self.send_line_broadcast(self.game2_msg):
                            self.root.after(0, self.toggle_g2) # Stop after success
                except Exception as e:
                    self.log(f"W2 Err: {e}")
            
            # 3. Death Detection
            if self.monitoring_death:
                image_paths = self.get_image_list(ASSETS_DIR)
                if image_paths:
                    is_dead, found_img = self.check_for_death(image_paths)
                    if is_dead:
                        filename = os.path.basename(found_img)
                        self.log(f"DEAD DETECTED! ({filename}). Sent alert and stopping.")
                        self.root.after(0, lambda: self.lbl_last_detected.config(text=f"Last Alert: {time.strftime('%H:%M:%S')} ({filename})"))
                        if self.send_line_broadcast(self.msg_text):
                            self.root.after(0, self.toggle_death) # Stop after success
            
            time.sleep(self.interval)

if __name__ == "__main__":
    if not os.path.exists(CONFIG_FILE):
        # Create default config if missing
        default_config = {
            "line_channel_access_token": "",
            "check_interval": 2.0,
            "confidence": 0.9,
            "cooldown_seconds": 60,
            "message": "ตัวละครของคุณตายแล้ว!",
            "desktop_color_rgb": [15, 15, 15],
            "game1_pos": [100, 100],
            "game2_pos": [500, 100],
            "game1_closed_msg": "เกมจอ 1 ถูกปิด!",
            "game2_closed_msg": "เกมจอ 2 ถูกปิด!"
        }
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(default_config, f, indent=4)

    root = tk.Tk()
    app = LineAlertApp(root)
    root.mainloop()

