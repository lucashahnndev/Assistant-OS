
import tkinter as tk
from tkinter import font as tkfont
import threading
import queue
import pystray
from PIL import Image, ImageDraw
import sys
import os
import time
from utils.logging_config import get_logger

logger = get_logger("AssistantInterface")

# Colors
BG_COLOR = "#121212"      # Very dark grey
TEXT_COLOR = "#E0E0E0"    # Off-white
ACCENT_COLOR = "#00ADB5"  # Cyan/Teal
LISTENING_COLOR = "#FF5722" # Orange
SPEAKING_COLOR = "#4CAF50"  # Green
IDLE_COLOR = "#757575"    # Grey

class FloatingGUI:
    def __init__(self, name='Assistant'):
        self.name = name
        self.root = None
        self.queue = queue.Queue()
        self.running = False
        self.drag_data = {"x": 0, "y": 0}
        self.icon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), 'images', 'logo.png')
        self.tray_icon = None
        
        # State
        self.current_status = "idle" # idle, listening, speaking
        self.user_text = ""
        self.assistant_text = ""
        
        # UI Elements
        self.canvas = None
        self.status_circle = None
        self.text_label = None
        
    def start(self):
        """Starts the Tkinter main loop."""
        self.running = True
        
        # Setup Pystray in a separate thread because Tkinter needs main thread of this process
        # But wait, VoiceDriver calls this in a thread. 
        # So this Function is running in Thread-X. Tkinter will own Thread-X.
        # Pystray needs to run in yet another thread or handle loop carefully.
        # We'll put tray in a thread.
        threading.Thread(target=self._setup_tray, daemon=True).start()

        self._setup_window()
        self._animate()
        self._process_queue()
        
        try:
            self.root.mainloop()
        except Exception as e:
            logger.error(f"UI Loop Error: {e}")

    def stop(self):
        self.running = False
        if self.root:
            self.root.quit()
        if self.tray_icon:
            self.tray_icon.stop()

    def _setup_window(self):
        self.root = tk.Tk()
        self.root.title(self.name)
        
        # Window Settings
        self.root.geometry("400x120+100+100")
        self.root.overrideredirect(True) # Frameless
        self.root.attributes('-topmost', True) # Always on top
        self.root.attributes('-alpha', 0.85) # Transparency
        self.root.configure(bg=BG_COLOR)
        
        # Drag Logic
        self.root.bind("<Button-1>", self._start_drag)
        self.root.bind("<B1-Motion>", self._do_drag)
        self.root.bind("<Button-3>", self._minimize_to_tray) # Right click to minimize
        
        # Layout
        main_frame = tk.Frame(self.root, bg=BG_COLOR, padx=15, pady=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Status Indicator (Canvas for Circle)
        self.canvas = tk.Canvas(main_frame, width=20, height=20, bg=BG_COLOR, highlightthickness=0)
        self.canvas.pack(side=tk.LEFT, anchor=tk.N)
        self.status_circle = self.canvas.create_oval(2, 2, 18, 18, fill=IDLE_COLOR, outline="")

        # Text Area
        text_frame = tk.Frame(main_frame, bg=BG_COLOR, padx=10)
        text_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Assistant Name / Status Text
        self.status_label = tk.Label(text_frame, text=self.name, font=("Segoe UI", 10, "bold"), fg=ACCENT_COLOR, bg=BG_COLOR, anchor="w")
        self.status_label.pack(fill=tk.X)
        
        # Content Text
        self.text_label = tk.Label(
            text_frame, 
            text="Aguardando comando...", 
            font=("Segoe UI", 11), 
            fg=TEXT_COLOR, 
            bg=BG_COLOR, 
            anchor="w", 
            justify=tk.LEFT,
            wraplength=320
        )
        self.text_label.pack(fill=tk.X, pady=(5, 0))
        
        # Close Button (Small X)
        close_btn = tk.Label(main_frame, text="×", font=("Arial", 14), fg="#757575", bg=BG_COLOR, cursor="hand2")
        close_btn.pack(side=tk.RIGHT, anchor=tk.N)
        close_btn.bind("<Button-1>", lambda e: self._minimize_to_tray(None))
        
        # Round corners hack (optional, skipped for simplicity/compatibility)

    def _start_drag(self, event):
        self.drag_data["x"] = event.x
        self.drag_data["y"] = event.y

    def _do_drag(self, event):
        x = self.root.winfo_x() - self.drag_data["x"] + event.x
        y = self.root.winfo_y() - self.drag_data["y"] + event.y
        self.root.geometry(f"+{x}+{y}")

    def _minimize_to_tray(self, event):
        self.root.withdraw() # Hide window
        # Show notification via tray could be added here

    def _restore_from_tray(self):
        self.root.deiconify()
        self.root.attributes('-topmost', True)

    def _setup_tray(self):
        image = Image.open(self.icon_path) if os.path.exists(self.icon_path) else self._create_default_icon()
        
        menu = pystray.Menu(
            pystray.MenuItem("Abrir", self._restore_from_tray),
            pystray.MenuItem("Sair", self._quit_app)
        )
        
        self.tray_icon = pystray.Icon(self.name, image, self.name, menu)
        self.tray_icon.run()

    def _create_default_icon(self):
        # Fallback if image missing
        img = Image.new('RGB', (64, 64), color=(73, 109, 137))
        d = ImageDraw.Draw(img)
        d.text((10,10), "AI", fill=(255,255,0))
        return img

    def _quit_app(self, icon, item):
        icon.stop()
        self.root.quit()
        sys.exit(0)

    # Queue Processing
    def _process_queue(self):
        try:
            while True:
                task = self.queue.get_nowait()
                action = task.get("action")
                data = task.get("data")
                
                if action == "update_text":
                    self.text_label.config(text=data)
                elif action == "update_status":
                    self.status_label.config(text=data)
                elif action == "set_color":
                    self.canvas.itemconfig(self.status_circle, fill=data)
                    
                self.queue.task_done()
        except queue.Empty:
            pass
        
        self.root.after(100, self._process_queue)

    def _animate(self):
        # Simple breathing effect for listening mode
        # Implementation skipped to keep it simple and robust first
        # Could toggle color brightness or size
        self.root.after(500, self._animate)

    # Public Methods called by Driver
    def update_user_text(self, text):
        self.queue.put({"action": "update_text", "data": f'"{text}"'})
        self.queue.put({"action": "set_color", "data": LISTENING_COLOR})
        self.queue.put({"action": "update_status", "data": "Ouvindo..."})

    def update_assistant_text(self, text):
        self.queue.put({"action": "update_text", "data": text})
        self.queue.put({"action": "set_color", "data": SPEAKING_COLOR})
        self.queue.put({"action": "update_status", "data": "Assistant says:"})

    def assistant_color(self):
        self.queue.put({"action": "set_color", "data": SPEAKING_COLOR})

    def user_color(self):
        self.queue.put({"action": "set_color", "data": LISTENING_COLOR})
        
# Backward compatibility alias
AssistantInterface = FloatingGUI
