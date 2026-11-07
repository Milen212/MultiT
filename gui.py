"""MultiT UI: a pywebview window (ui.html). Buttons run the multit CLI as a subprocess and stream its output back."""
import codecs, ctypes, json, os, re, shutil, subprocess, sys, threading, webbrowser
from pathlib import Path

import webview

import multit as m

HERE = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))  # ui.html lives here (bundled into the exe)


def cli(args):
    base = [sys.executable] if m.FROZEN else [sys.executable, str(Path(__file__).with_name("multit.py"))]
    return base + [str(a) for a in args]


class Api:
    """Every public method is callable from JS as window.pywebview.api.<name>()."""

    def __init__(self):
        self._proc = None
        self._win = None

    def meta(self):
        return {"isos": [{"key": k, "label": v[0]} for k, v in m.ISOS.items()], "iso_dir": str(m.ISO_DIR), "home": str(Path.home())}

    def run(self, args, secrets=None):
        """secrets: extra env vars (e.g. the USB password) - kept off the command line."""
        if self._proc and self._proc.poll() is None:
            return "busy"
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8",
               **{k: str(v) for k, v in (secrets or {}).items() if k.startswith("MULTIT_")}}
        self._proc = subprocess.Popen(cli(args), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                      env=env, creationflags=m.NO_WINDOW)
        threading.Thread(target=self._pump, args=(self._proc,), daemon=True).start()
        return "ok"

    def _pump(self, p):
        dec = codecs.getincrementaldecoder("utf-8")("replace")
        for chunk in iter(lambda: p.stdout.read1(65536), b""):
            self._js("term.write", dec.decode(chunk))
        self._js("term.exit", p.wait())

    def _js(self, fn, arg):
        self._win.run_js(f"{fn}({json.dumps(arg)})")

    def stop(self):
        if self._proc and self._proc.poll() is None:  # /T: also kill pyinstaller, servers, downloads... it spawned
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(self._proc.pid)], capture_output=True, creationflags=m.NO_WINDOW)

    def pick(self, kind):
        types = {"iso": ("Disk images (*.iso)",), "ico": ("Icons (*.ico)",)}.get(kind, ("All files (*.*)",))
        mode = webview.FileDialog.FOLDER if kind == "folder" else webview.FileDialog.OPEN
        r = self._win.create_file_dialog(mode, file_types=() if kind == "folder" else types)
        return r[0] if r else None

    def detect(self, path):
        try:
            lang, root, entry = m.detect(path)
            return {"lang": lang, "root": str(root), "entry": str(entry)}
        except SystemExit as e:
            return {"error": str(e)}

    def tools(self):
        st = m.tool_status()
        return [{"key": k, "name": v[0], "cat": v[1], "src": v[2] or "", "ok": st[k]} for k, v in m.TOOLS.items()]

    def vms(self):
        out = []
        if vr := m.vmrun():
            running = m.run([vr, "list"], check=False, capture=True).stdout.lower()
            out += [{"name": v.parent.name, "provider": "VMware", "running": str(v).lower() in running}
                    for v in sorted(m.VMWARE_DIR.glob("*/*.vmx"))]
        vb = shutil.which("VBoxManage") or r"C:\Program Files\Oracle\VirtualBox\VBoxManage.exe"
        if Path(vb).exists():
            on = set(re.findall(r'"(.+?)"', m.run([vb, "list", "runningvms"], check=False, capture=True).stdout))
            out += [{"name": n, "provider": "VirtualBox", "running": n in on}
                    for n in re.findall(r'"(.+?)"', m.run([vb, "list", "vms"], check=False, capture=True).stdout)]
        return out

    def open(self, url):
        webbrowser.open(url)

    def scan(self):
        return {"admin": m.is_admin(), "items": m.junk_scan()}

    def disks(self):
        out = []
        for d in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            if os.path.exists(f"{d}:\\"):
                try:
                    u = shutil.disk_usage(f"{d}:\\")
                    out.append({"drive": f"{d}:", "total": u.total, "free": u.free})
                except OSError:
                    pass  # empty card reader etc.
        return out

    def viz(self, path, show_system=False):
        """Scan for the disk map; streams progress to vizProgress() in the page."""
        r = m.disk_map(path, show_system, progress=lambda n, p: self._win.run_js(f"vizProgress({n}, {json.dumps(p)})"))
        if os.path.splitdrive(r["root"])[1] in ("\\", "/"):  # whole drive: report what's hidden / unreadable
            r["used"] = shutil.disk_usage(r["root"]).used
        return r

    def reveal(self, path):
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])

    def recycle(self, path):
        try:
            return {"ok": m.recycle(path)}
        except ValueError as e:
            return {"ok": False, "error": str(e)}

    # --- system monitor
    def stats(self):
        return m.sys_stats()

    def procs(self, sort="cpu"):
        return m.top_procs(sort)

    def kill(self, name):
        try:
            return {"ok": True, "n": m.kill_procs(name)}
        except ValueError as e:
            return {"ok": False, "error": str(e)}

    # --- startup apps / PATH doctor
    def startup(self):
        return m.startup_items()

    def set_startup(self, item_id, enabled):
        try:
            m.set_startup(item_id, enabled)
            return {"ok": True}
        except ValueError as e:
            return {"ok": False, "error": str(e)}

    def path_entries(self):
        return m.path_entries()

    def path_change(self, fix=False, add=None, remove=None):
        try:
            return {"ok": True, **m.path_change(fix, add, remove)}
        except OSError as e:
            return {"ok": False, "error": str(e)}

    # --- duplicates / git repos
    def dupes(self, path, min_mb=1):
        return m.find_dupes(path, int(float(min_mb) * (1 << 20)),
                            progress=lambda s, p: self._win.run_js(f"dupProgress({json.dumps(s)}, {json.dumps(p)})"))

    def repos(self, path, fetch=False):
        return m.repos_status(path, fetch)

    def code(self, path):
        exe = shutil.which("code") or os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe")
        if not os.path.exists(exe):
            return False
        subprocess.Popen([exe, path], creationflags=m.NO_WINDOW)
        return True

    # --- folder vaults / bootable USB / app updates
    def vaults(self):
        return m.vault_folders()

    def vault_check(self, path):
        return {"ok": not m.is_protected(path), "vault": os.path.exists(os.path.join(path, m.VAULT_FILE))}

    def boot_drives(self):
        return {"drives": m.boot_drives(), "ventoy": m.ventoy_exe()}

    def upgrades(self):
        return m.winget_upgrades()

    # --- backups
    def backups(self):
        return m.backup_jobs()

    def backup_save(self, job):
        if err := m.backup_check(job["src"], job["dst"], job.get("mirror")):
            return {"ok": False, "error": err}
        job = {**job, "src": os.path.abspath(job["src"]), "dst": os.path.abspath(job["dst"])}
        old = [j for j in m.backup_jobs() if j["name"] != job["name"]]
        m._save(m.BACKUPS_DB, old + [{**next((j for j in m.backup_jobs() if j["name"] == job["name"]), {}), **job}])
        try:
            m.backup_schedule(job)
        except ValueError as e:
            return {"ok": False, "error": f"saved, but scheduling failed: {e}"}
        return {"ok": True}

    def backup_remove(self, name):
        job = next((j for j in m.backup_jobs() if j["name"] == name), None)
        if job:
            m.backup_schedule({**job, "schedule": "off"})
            m._save(m.BACKUPS_DB, [j for j in m.backup_jobs() if j["name"] != name])
        return True

    # --- game booster
    def boost_info(self):
        prefs = m._load(m.STATE_DIR / "boost_prefs.json", [])
        return {"state": m._load(m.BOOST_STATE, None), "candidates": m.boost_candidates(), "prefs": prefs}

    def boost_prefs(self, apps):
        m._save(m.STATE_DIR / "boost_prefs.json", apps)
        return True

    # --- dashboard (fast bits only; junk/updates/models load separately)
    def dash(self):
        c = shutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\")
        jobs = m.backup_jobs()
        srv = [m.server_status(s["name"]) for s in m.servers()]
        return {"disk": {"total": c.total, "free": c.free}, "boost": m._load(m.BOOST_STATE, None), "backups": jobs,
                "usb": m.usb_drives(status=False), "vaults": len(m._load(m.VAULTS_DB, [])),
                "servers": {"total": len(srv), "running": sum(s["running"] for s in srv)}}

    # --- AI models / video
    def models(self, extra=None):
        return m.models_scan(extra)

    def video_info(self, path):
        try:
            return {"ok": True, **m.video_info(path)}
        except (ValueError, SystemExit) as e:
            return {"ok": False, "error": str(e)}

    # --- servers
    def servers(self):
        return [{**s, **m.server_status(s["name"])} for s in m.servers()]

    def server_save(self, cfg):
        if not cfg.get("name") or not cfg.get("cmd"):
            return {"ok": False, "error": "name and command are required"}
        cfg = {"name": cfg["name"], "cmd": cfg["cmd"], "cwd": cfg.get("cwd") or None, "restart": bool(cfg.get("restart"))}
        m._save(m.STATE_DIR / "servers.json", [s for s in m.servers() if s["name"] != cfg["name"]] + [cfg])
        return {"ok": True}

    def server_do(self, name, action):
        try:
            if action in ("stop", "restart"):
                m.server_stop(name)
            if action in ("start", "restart"):
                m.server_start(name)
            if action == "remove":
                if m.server_status(name)["running"]:
                    m.server_stop(name)
                m._save(m.STATE_DIR / "servers.json", [s for s in m.servers() if s["name"] != name])
            return {"ok": True}
        except (ValueError, SystemExit) as e:
            return {"ok": False, "error": str(e)}

    def server_log(self, name):
        return m.server_log_tail(name)

    def server_send(self, name, line):
        try:
            m.server_send(name, line)
            return {"ok": True}
        except ValueError as e:
            return {"ok": False, "error": str(e)}

    # --- server creator
    def platforms(self):
        return {"platforms": m.PLATFORMS, "default_dir": str(Path.home() / "Servers"),
                "java": [{"major": v, "path": p} for v, p in m.java_installs()]}

    def mc_versions(self, fw):
        try:
            return {"ok": True, "versions": m.mc_versions(fw)}
        except Exception as e:  # network trouble -> UI falls back to "newest"
            return {"ok": False, "error": str(e)}

    # --- USB encryption
    def usb_list(self):
        return m.usb_drives(status=False)

    def usb_status(self, root):
        return m.vault_status(root)

    def elevate(self):
        """Relaunch MultiT as administrator (UAC prompt), then close this window."""
        params = "" if m.FROZEN else f'"{Path(__file__).with_name("multit.py")}"'
        if ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1) > 32:
            self.stop()
            self._win.destroy()
            return True
        return False


def start():
    api = Api()
    api._win = webview.create_window("MultiT", str(HERE / "ui.html"), js_api=api, width=1280, height=840,
                                     min_size=(1000, 680), background_color="#050705")
    api._win.events.closed += api.stop
    webview.start()


if __name__ == "__main__":
    start()
