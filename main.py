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

        self.running = False
        self.monitor_thread = None
        self.last_alert_time = 0
        self.game1_was_closed = False
        self.game2_was_closed = False

        # GUI Components
        self.create_widgets()
        
        # Auto-start monitoring
        self.start_monitoring()

        # Tray Icon setup
        self.tray_icon = None
        self.root.protocol("WM_DELETE_WINDOW", self.minimize_to_tray)

    def load_config(self):
        try:
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

        self.lbl_monitoring = tk.Label(status_frame, text="Monitoring: STOPPED", fg="red", font=("Arial", 10))
        self.lbl_monitoring.pack(anchor="w")

        # Desktop Color Row
        dt_frame = tk.Frame(status_frame)
        dt_frame.pack(fill="x", pady=2)
        tk.Label(dt_frame, text="Target Desktop Color:").pack(side="left")
        self.lbl_desktop_color = tk.Label(dt_frame, text=str(self.desktop_color), fg="blue")
        self.lbl_desktop_color.pack(side="left", padx=5)
        tk.Button(dt_frame, text="Set Desktop Color", command=self.start_capture_desktop_color, font=("Arial", 8)).pack(side="right")

        # Window 1 Row
        g1_frame = tk.Frame(status_frame)
        g1_frame.pack(fill="x", pady=2)
        self.lbl_game1_status = tk.Label(g1_frame, text=f"Window 1: Checking...", fg="gray")
        self.lbl_game1_status.pack(side="left")
        tk.Button(g1_frame, text="Set Pos 1", command=lambda: self.start_capture_pos(1), font=("Arial", 8)).pack(side="right")

        # Window 2 Row
        g2_frame = tk.Frame(status_frame)
        g2_frame.pack(fill="x", pady=2)
        self.lbl_game2_status = tk.Label(g2_frame, text=f"Window 2: Checking...", fg="gray")
        self.lbl_game2_status.pack(side="left")
        tk.Button(g2_frame, text="Set Pos 2", command=lambda: self.start_capture_pos(2), font=("Arial", 8)).pack(side="right")

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

    def start_capture_pos(self, window_num):
        self.log(f"Setting Position for Window {window_num}...")
        self.log("Move mouse to target pixel. Capturing in 3s...")
        
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
        self.log("Setting Desktop Color...")
        self.log("Move mouse to a clean area of your desktop. Capturing in 3s...")
        
        def capture():
            time.sleep(3)
            x, y = pyautogui.position()
            color = pyautogui.pixel(x, y)
            self.desktop_color = color
            self.config['desktop_color_rgb'] = list(color)
            self.save_config()
            self.lbl_desktop_color.config(text=str(color))
            self.log(f"Desktop Color set to: {color}")

        threading.Thread(target=capture, daemon=True).start()

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



    def create_tray_icon(self):
        # Create a simple icon (green square)
        image = Image.new('RGB', (64, 64), color=(0, 128, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((16, 16, 48, 48), fill=(255, 255, 255))
        
        menu = (item('Show', self.show_window), item('Exit', self.quit_window))
        self.tray_icon = pystray.Icon("name", image, "Line Alert Bot", menu)
        self.tray_icon.run()

    def minimize_to_tray(self):
        self.root.withdraw()
        self.create_tray_icon()

    def show_window(self, icon, item):
        self.tray_icon.stop()
        self.root.after(0, self.root.deiconify)

    def quit_window(self, icon, item):
        self.tray_icon.stop()
        self.root.destroy()
        sys.exit()

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
            
            # 1. Pixel Monitoring for 2 Windows
            try:
                # Check Window 1
                current_c1 = pyautogui.pixel(self.game1_pos[0], self.game1_pos[1])
                is_g1_desktop = pyautogui.pixelMatchesColor(self.game1_pos[0], self.game1_pos[1], self.desktop_color, tolerance=15)
                
                status1_text = "Closed (Desktop)" if is_g1_desktop else "Active (Game)"
                status1_color = "red" if is_g1_desktop else "green"
                self.lbl_game1_status.config(text=f"Window 1: {status1_text} {current_c1}", fg=status1_color)

                if is_g1_desktop:
                    if not self.game1_was_closed:
                        self.log(f"Window 1 closed! (Current: {current_c1} matched Desktop: {self.desktop_color})")
                        self.send_line_broadcast(self.game1_msg)
                        self.game1_was_closed = True
                else:
                    self.game1_was_closed = False

                # Check Window 2
                current_c2 = pyautogui.pixel(self.game2_pos[0], self.game2_pos[1])
                is_g2_desktop = pyautogui.pixelMatchesColor(self.game2_pos[0], self.game2_pos[1], self.desktop_color, tolerance=15)
                
                status2_text = "Closed (Desktop)" if is_g2_desktop else "Active (Game)"
                status2_color = "red" if is_g2_desktop else "green"
                self.lbl_game2_status.config(text=f"Window 2: {status2_text} {current_c2}", fg=status2_color)

                if is_g2_desktop:
                    if not self.game2_was_closed:
                        self.log(f"Window 2 closed! (Current: {current_c2} matched Desktop: {self.desktop_color})")
                        self.send_line_broadcast(self.game2_msg)
                        self.game2_was_closed = True
                else:
                    self.game2_was_closed = False

            except Exception as e:
                self.log(f"Pixel match error: {e}")
            
            # 2. Death Detection
            image_paths = self.get_image_list(ASSETS_DIR)
            
            if image_paths:
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

