"""Small Tkinter desktop chat UI for selfagent. Run: python chat_ui.py"""
import os
import pathlib
import queue
import threading
import tkinter as tk
from tkinter import scrolledtext, messagebox

ROOT = pathlib.Path(__file__).resolve().parent
os.chdir(ROOT)


def load_env():
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            if value.strip():
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


load_env()
from core.agent import run_chat_agent  # noqa: E402
from core.router import Router  # noqa: E402

SYSTEM = (
    "You are a helpful desktop AI assistant. Chat naturally and concisely. "
    "Use tools when useful. File tools operate inside the selfagent project folder only. "
    "Ask before overwriting important existing files if the request is ambiguous. "
    "Never say an action succeeded unless its tool result confirms it."
)


class ChatUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Selfagent Chat")
        self.root.geometry("860x640")
        self.root.minsize(620, 460)
        self.events = queue.Queue()
        self.messages = []
        self.busy = False
        self.router = None

        outer = tk.Frame(root, padx=12, pady=12)
        outer.pack(fill="both", expand=True)
        tk.Label(outer, text="Selfagent", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        tk.Label(outer, text="Chat + project files · shell and package-install tools disabled",
                 fg="#666666").pack(anchor="w", pady=(0, 8))

        self.transcript = scrolledtext.ScrolledText(
            outer, wrap="word", state="disabled", font=("Segoe UI", 10), padx=8, pady=8
        )
        self.transcript.pack(fill="both", expand=True)
        self.transcript.tag_configure("you", foreground="#1756a9", spacing1=8)
        self.transcript.tag_configure("agent", foreground="#187344", spacing1=8)
        self.transcript.tag_configure("tool", foreground="#806000", spacing1=4)
        self.transcript.tag_configure("error", foreground="#b42318", spacing1=4)

        self.status = tk.StringVar(value="Ready")
        tk.Label(outer, textvariable=self.status, anchor="w", fg="#666666").pack(fill="x", pady=(6, 4))
        bottom = tk.Frame(outer)
        bottom.pack(fill="x")
        self.entry = tk.Text(bottom, height=3, wrap="word", font=("Segoe UI", 10))
        self.entry.pack(side="left", fill="both", expand=True)
        self.entry.bind("<Control-Return>", self._ctrl_enter)
        self.send_button = tk.Button(bottom, text="Send", width=10, command=self.send)
        self.send_button.pack(side="left", fill="y", padx=(8, 0))
        self.root.bind("<Control-l>", lambda _e: self.clear_chat())
        self.root.after(100, self.poll_events)
        self.write("agent", "Hi! Tell me what you want to do. Example: ‘Create hello.txt containing 1234.’")
        self.entry.focus_set()

    def write(self, kind, text):
        self.transcript.configure(state="normal")
        prefix = {"you": "You", "agent": "Selfagent", "tool": "Tool", "error": "Error"}.get(kind, kind)
        self.transcript.insert("end", f"{prefix}: {text}\n\n", kind)
        self.transcript.see("end")
        self.transcript.configure(state="disabled")

    def _ctrl_enter(self, _event):
        self.send()
        return "break"

    def send(self):
        if self.busy:
            return
        prompt = self.entry.get("1.0", "end").strip()
        if not prompt:
            return
        self.entry.delete("1.0", "end")
        self.write("you", prompt)
        self.messages.append({"role": "user", "content": prompt})
        self.busy = True
        self.send_button.configure(state="disabled")
        self.entry.configure(state="disabled")
        self.status.set("Thinking…")
        threading.Thread(target=self.worker, daemon=True).start()

    def worker(self):
        try:
            if self.router is None:
                self.router = Router()
            answer = run_chat_agent(
                self.router,
                self.messages,
                system=SYSTEM,
                on_tool=lambda name, args, result: self.events.put(("tool", name, args, result)),
            )
            self.events.put(("answer", answer))
        except Exception as exc:
            self.events.put(("fatal", f"{type(exc).__name__}: {exc}"))

    def poll_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "tool":
                    _, name, args, result = event
                    if result is None:
                        self.write("tool", f"Running {name}({args})…")
                    else:
                        preview = result.replace("\n", " ")
                        self.write("tool", f"{name}: {preview[:500]}")
                elif event[0] == "answer":
                    self.write("agent", event[1])
                    self.finish_turn("Ready")
                elif event[0] == "fatal":
                    self.write("error", event[1])
                    self.finish_turn("Error — check .env and provider configuration")
        except queue.Empty:
            pass
        self.root.after(100, self.poll_events)

    def finish_turn(self, status):
        self.busy = False
        self.send_button.configure(state="normal")
        self.entry.configure(state="normal")
        self.status.set(status)
        self.entry.focus_set()

    def clear_chat(self):
        if self.busy:
            return
        self.messages.clear()
        self.transcript.configure(state="normal")
        self.transcript.delete("1.0", "end")
        self.transcript.configure(state="disabled")
        self.write("agent", "Chat cleared. The next message starts a new conversation context.")


if __name__ == "__main__":
    root = tk.Tk()
    ChatUI(root)
    root.mainloop()
