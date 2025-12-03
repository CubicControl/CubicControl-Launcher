import os
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from src.config.config_file_handler import ConfigFileHandler
from src.minecraft.server_properties import parse_server_properties, write_server_properties


def _force_var_uppercase(var):
    value = var.get()
    if value != value.upper():
        var.set(value.upper())


class InitialSetupGUI:
    def __init__(self):
        self.cfg_handler = ConfigFileHandler()

        # Create root window
        self.root = tk.Tk()
        self.root.title("Minecraft Server - First Run Setup")
        self.root.geometry("600x400")

        # Load initial values
        self._load_initial_values()

        # Build all widgets
        self._setup_widgets()

        # Start GUI loop
        self.root.mainloop()

    # ---------- Data loading ----------

    def _load_initial_values(self):
        # Run.bat location from config
        try:
            self.initial_server_folder = self.cfg_handler.get_value('Run.bat location', allow_empty=True)
        except Exception:
            self.initial_server_folder = ""

        # Env vars
        self.initial_rcon_password_env = os.environ.get('RCON_PASSWORD', '')
        self.initial_authkey = os.environ.get('AUTHKEY_SERVER_WEBSITE', '')
        self.initial_shutdown_key = os.environ.get('SHUTDOWN_AUTH_KEY', '')

        # server.properties (if present)
        self.props = {}
        if self.initial_server_folder:
            props_path_guess = os.path.join(self.initial_server_folder, 'server.properties')
            if os.path.exists(props_path_guess):
                self.props = parse_server_properties(props_path_guess)

        # Defaults with fallback to env where appropriate
        # We don't care what enable-rcon / enable-query *were*, we will force them to true.
        rcon_password_prop = self.props.get('rcon.password', self.initial_rcon_password_env)
        rcon_port_val = self.props.get('rcon.port', '27001')
        query_port_val = self.props.get('query.port', '27002')

        # Tkinter variables
        self.server_folder_var = tk.StringVar(value=self.initial_server_folder)

        self.rcon_password_env_var = tk.StringVar(value=self.initial_rcon_password_env)
        self.rcon_password_env_var.trace_add("write", lambda name, index, mode: _force_var_uppercase(self.rcon_password_env_var))
        self.authkey_var = tk.StringVar(value=self.initial_authkey)
        self.authkey_var.trace_add("write", lambda name, index, mode: _force_var_uppercase(self.authkey_var))
        self.shutdown_key_var = tk.StringVar(value=self.initial_shutdown_key)
        self.shutdown_key_var.trace_add("write", lambda name, index, mode: _force_var_uppercase(self.shutdown_key_var))

        # Checkboxes will be displayed as always enabled & locked
        self.enable_rcon_bool = tk.BooleanVar(value=True)
        self.enable_query_bool = tk.BooleanVar(value=True)

        self.rcon_password_prop_var = tk.StringVar(value=rcon_password_prop)
        self.rcon_port_var = tk.StringVar(value=rcon_port_val)
        self.query_port_var = tk.StringVar(value=query_port_val)

    # ---------- UI building ----------

    def _setup_widgets(self):
        mainframe = ttk.Frame(self.root, padding=10)
        mainframe.grid(row=0, column=0, sticky="nsew")

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        # ---- Server folder section ----
        ttk.Label(
            mainframe,
            text="Server folder (contains run.bat & server.properties):"
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 2))

        server_folder_entry = ttk.Entry(mainframe, textvariable=self.server_folder_var, width=50)
        server_folder_entry.grid(row=1, column=0, columnspan=2, sticky="ew")

        browse_button = ttk.Button(mainframe, text="Browse...", command=self._browse_folder)
        browse_button.grid(row=1, column=2, padx=(5, 0), sticky="ew")

        # ---- Environment variables section ----
        ttk.Label(
            mainframe,
            text="Environment variables",
            font=("TkDefaultFont", 10, "bold")
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(10, 2))

        ttk.Label(mainframe, text="RCON_PASSWORD:").grid(row=3, column=0, sticky="w")
        rcon_password_env_entry = ttk.Entry(
            mainframe,
            textvariable=self.rcon_password_env_var,
            width=40
        )
        rcon_password_env_entry.grid(row=3, column=1, columnspan=2, sticky="ew")

        ttk.Label(mainframe, text="AUTHKEY_SERVER_WEBSITE:").grid(row=4, column=0, sticky="w")
        authkey_entry = ttk.Entry(mainframe, textvariable=self.authkey_var, width=40)
        authkey_entry.grid(row=4, column=1, columnspan=2, sticky="ew")

        ttk.Label(mainframe, text="SHUTDOWN_AUTH_KEY:").grid(row=5, column=0, sticky="w")
        shutdown_key_entry = ttk.Entry(mainframe, textvariable=self.shutdown_key_var, width=40)
        shutdown_key_entry.grid(row=5, column=1, columnspan=2, sticky="ew")

        # ---- server.properties section ----
        ttk.Label(
            mainframe,
            text="server.properties (RCON & Query)",
            font=("TkDefaultFont", 10, "bold")
        ).grid(row=6, column=0, columnspan=3, sticky="w", pady=(10, 2))

        # Displayed as always-on options to make it clear they're enabled
        ttk.Checkbutton(
            mainframe,
            text="Enable RCON (enable-rcon) - forced ON",
            variable=self.enable_rcon_bool,
            state="disabled"
        ).grid(row=7, column=0, columnspan=3, sticky="w")

        ttk.Label(mainframe, text="RCON password (rcon.password):").grid(row=8, column=0, sticky="w")
        self.rcon_password_prop_var.set("Will match the RCON_PASSWORD environment variable")
        rcon_password_prop_entry = ttk.Entry(
            mainframe,
            textvariable=self.rcon_password_prop_var,
            width=40,
            state="disabled"
        )
        rcon_password_prop_entry.grid(row=8, column=1, columnspan=2, sticky="ew")

        ttk.Label(mainframe, text="RCON port (rcon.port):").grid(row=9, column=0, sticky="w")
        rcon_port_entry = ttk.Entry(mainframe, textvariable=self.rcon_port_var, width=10)
        rcon_port_entry.grid(row=9, column=1, sticky="w")

        ttk.Checkbutton(
            mainframe,
            text="Enable Query (enable-query) - forced ON",
            variable=self.enable_query_bool,
            state="disabled"
        ).grid(row=10, column=0, columnspan=3, sticky="w")

        ttk.Label(mainframe, text="Query port (query.port):").grid(row=11, column=0, sticky="w")
        query_port_entry = ttk.Entry(mainframe, textvariable=self.query_port_var, width=10)
        query_port_entry.grid(row=11, column=1, sticky="w")

        # ---- Buttons ----
        button_frame = ttk.Frame(mainframe)
        button_frame.grid(row=12, column=0, columnspan=3, pady=(20, 0), sticky="e")

        save_button = ttk.Button(button_frame, text="Save and continue", command=self._on_save)
        save_button.grid(row=0, column=0, padx=5)

        cancel_button = ttk.Button(button_frame, text="Cancel", command=self._on_cancel)
        cancel_button.grid(row=0, column=1, padx=5)

        # Make the layout stretch nicely
        for col in range(3):
            mainframe.columnconfigure(col, weight=1)

    # ---------- Callbacks ----------

    def _browse_folder(self):
        folder = filedialog.askdirectory(title="Select server folder")
        if folder:
            self.server_folder_var.set(folder)

    def _on_save(self):
        server_folder = self.server_folder_var.get().strip()
        if not server_folder or not os.path.isdir(server_folder):
            messagebox.showerror("Error", "Please select a valid server folder.")
            return

        run_bat_path = os.path.join(server_folder, "run.bat")
        if not os.path.exists(run_bat_path):
            messagebox.showerror("Error", "run.bat not found in the selected folder.")
            return

        # Env vars - RCON password and auth key required
        rcon_pass_env = self.rcon_password_env_var.get().strip()
        if not rcon_pass_env:
            messagebox.showerror("Error", "RCON_PASSWORD cannot be empty.")
            return

        authkey = self.authkey_var.get().strip()
        if not authkey:
            messagebox.showerror("Error", "AUTHKEY_SERVER_WEBSITE cannot be empty.")
            return

        shutdown_key = self.shutdown_key_var.get().strip()

        # Ports
        rcon_port_text = self.rcon_port_var.get().strip() or "27001"
        query_port_text = self.query_port_var.get().strip() or "27002"

        if not rcon_port_text.isdigit() or not query_port_text.isdigit():
            messagebox.showerror("Error", "Ports must be numeric.")
            return

        # Save Run.bat location
        self.cfg_handler.set_value('Run.bat location', server_folder)

        # Update environment variables for this process
        setx_cmds = [
            f'setx RCON_PASSWORD "{rcon_pass_env}" >NUL',
            f'setx AUTHKEY_SERVER_WEBSITE "{authkey}" >NUL'
        ]
        if shutdown_key:
            setx_cmds.append(f'setx SHUTDOWN_AUTH_KEY "{shutdown_key}" >NUL')

        full_cmd = " && ".join(setx_cmds)
        subprocess.run(full_cmd, shell=True)

        # Update server.properties
        props_path = os.path.join(server_folder, 'server.properties')
        if not os.path.exists(props_path):
            # create an empty file if missing
            with open(props_path, 'w', encoding='utf-8') as f:
                f.write("# Minecraft server properties\n")

        # Always set rcon.password in server.properties to the env var value
        new_values = {
            'enable-rcon': 'true',
            'rcon.password': rcon_pass_env,
            'rcon.port': rcon_port_text,
            'enable-query': 'true',
            'query.port': query_port_text,
        }
        write_server_properties(props_path, new_values)

        messagebox.showinfo("Saved", "Configuration saved successfully.")
        self.root.destroy()

    def _on_cancel(self):
        # You can sys.exit(1) here instead if you want to *force* configuration
        self.root.destroy()


if __name__ == "__main__":
    InitialSetupGUI()
