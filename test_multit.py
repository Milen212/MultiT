"""python test_multit.py -> checks language detection on throwaway projects."""
import tempfile
from pathlib import Path
from multit import detect, vmx_text, VMWARE_GUESTS

CASES = {
    "rust": {"Cargo.toml": "", "src/main.rs": ""},
    "go": {"go.mod": "", "main.go": ""},
    "node": {"package.json": "{}", "index.js": ""},
    "csharp": {"App.csproj": "", "Program.cs": ""},
    "maven": {"pom.xml": "", "src/Main.java": ""},
    "cmake": {"CMakeLists.txt": "", "main.cpp": ""},
    "python": {"util.py": "", "tool.py": "if __name__ == '__main__': pass", "node_modules/x.js": "", "node_modules/y.js": ""},
    "cpp": {"main.cpp": "", "a.cpp": "", "b.h": ""},
    "java": {"Foo.java": "class Foo { public static void main(String[] a){} }", "Bar.java": ""},
}

with tempfile.TemporaryDirectory() as t:
    for lang, files in CASES.items():
        root = Path(t, lang)
        for rel, body in files.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(body)
        got, _, entry = detect(root)
        assert got == lang, (lang, got)
        print(f"ok  {lang:7} -> {entry.name}")
    assert detect(Path(t, "python"))[2].name == "tool.py"  # __main__ heuristic, node_modules ignored
    assert detect(Path(t, "java"))[2].name == "Foo.java"
    assert detect(Path(t, "go", "main.go"))[0] == "go"   # single file
    vmx = vmx_text("w", Path(t, "Win11_24H2_x64.iso"), "windows11-64", 4096, 2)
    assert 'guestOS = "windows11-64"' in vmx and "autoAddVTPM" in vmx and 'nvme0:0.fileName = "w.vmdk"' in vmx
    assert next(g for k, g in VMWARE_GUESTS if k in "ubuntu-24.04-desktop-amd64.iso") == "ubuntu-64"
print("all good")

from multit import dev_linux_wrapper, DEV_LINUX
w = dev_linux_wrapper("p'a$s word")
assert "p'a$s word" not in w and DEV_LINUX in w and "sudo -S" in w  # password only travels base64-encoded
print("devtools script ok")

# cleanup must empty a folder but never follow a junction out of it
import os, stat, subprocess
from multit import _wipe, _size
with tempfile.TemporaryDirectory() as t:
    junk, outside = Path(t, "junk"), Path(t, "precious")
    (junk / "a" / "b").mkdir(parents=True); outside.mkdir()
    (junk / "a" / "b" / "x.tmp").write_bytes(b"1" * 1000)
    (junk / "ro.tmp").write_bytes(b"2" * 500); os.chmod(junk / "ro.tmp", stat.S_IREAD)  # read-only
    (outside / "keep.txt").write_text("do not delete")
    subprocess.run(["cmd", "/c", "mklink", "/J", str(junk / "link"), str(outside)], capture_output=True, check=True)
    assert _size(junk) == 1500  # junction not counted
    assert _wipe(junk) == 1500 and list(junk.iterdir()) == []
    assert (outside / "keep.txt").read_text() == "do not delete"
print("cleanup safety ok")

# disk map: protected paths, small-file merging, totals
from multit import is_protected, disk_map
H = Path.home()
for p in ["C:\\", r"C:\Windows", r"C:\Windows\System32\x.dll", r"C:\Program Files\App", r"C:\pagefile.sys",
          str(H.parent), str(H), str(H / "Documents"), str(H / "AppData")]:
    assert is_protected(p), p
for p in [str(H / "Documents" / "old.zip"), str(H / "Downloads" / "big.iso"), r"D:\Games\x"]:
    assert not is_protected(p), p
with tempfile.TemporaryDirectory() as t:
    (Path(t) / "sub").mkdir()
    (Path(t) / "big.iso").write_bytes(b"0" * 2_000_000)
    for i in range(5):
        (Path(t) / "sub" / f"s{i}.png").write_bytes(b"0" * 1000)
    r = disk_map(t)
    tree = r["tree"]
    assert tree["s"] == 2_005_000 and r["files"] == 6
    assert tree["c"][0] == {"n": "big.iso", "s": 2_000_000, "t": "g"}
    assert any(c.get("a") and c["t"] == "i" and c["s"] == 5000 for c in tree["c"][1].get("c", [tree["c"][1]]))
print("disk map ok")

# PATH doctor: drop dead folders + duplicates (incl. ones already in system PATH), keep %VARS% and order
from multit import clean_path
with tempfile.TemporaryDirectory() as t:
    a, b = str(Path(t, "a")), str(Path(t, "b"))
    os.mkdir(a); os.mkdir(b)
    kept, removed = clean_path([a, str(Path(t, "gone")), b + "\\", "%NOPE_VAR%\\bin", a.upper(), "", r"C:\Windows"], [r"C:\Windows", ""])
    assert kept == [a, b + "\\", "%NOPE_VAR%\\bin"], kept
    assert removed == [str(Path(t, "gone")), a.upper(), r"C:\Windows"], removed
print("path doctor ok")

# duplicates: same content found, different content / hardlink not
from multit import find_dupes
with tempfile.TemporaryDirectory() as t:
    data = os.urandom(200_000)
    for name in ("x1.bin", "sub/x2.bin", "sub/deep/x3.bin"):
        Path(t, name).parent.mkdir(parents=True, exist_ok=True); Path(t, name).write_bytes(data)
    Path(t, "same_size_diff.bin").write_bytes(data[:-1] + b"!")
    os.link(Path(t, "x1.bin"), Path(t, "x1_hardlink.bin"))
    r = find_dupes(t, min_size=1000)
    assert len(r["groups"]) == 1 and len(r["groups"][0]["files"]) == 3 and r["groups"][0]["wasted"] == 400_000, r
print("dupes ok")

# git repos: finds nested repos, reports changes
from multit import repos_status
with tempfile.TemporaryDirectory() as t:
    for name in ("one", "group/two"):
        p = Path(t, name); p.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(p)], check=True)
    Path(t, "one", "new.txt").write_text("hi")
    rows = repos_status(t)
    assert [r["name"] for r in rows] == ["one", "two"] and rows[0]["changed"] == 1 and rows[1]["changed"] == 0, rows
print("repos ok")

# startup switch writes the same bytes Task Manager does (dummy entry, removed afterwards)
import winreg
from multit import set_startup, _approved, _APPROVED
try:
    set_startup("HKCU|Run|MultiT-selftest", False); assert not _approved("HKCU", "Run", "MultiT-selftest")
    set_startup("HKCU|Run|MultiT-selftest", True); assert _approved("HKCU", "Run", "MultiT-selftest")
finally:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _APPROVED + r"\Run", 0, winreg.KEY_SET_VALUE) as k:
        winreg.DeleteValue(k, "MultiT-selftest")
print("startup ok")

# CPU % must work when every call comes from a new thread (that's how the UI calls in)
import threading, time
from multit import sys_stats
def burn(): t0 = time.time(); [0 for _ in iter(lambda: time.time() - t0 > 1.2, True)]
sys_stats(); b = threading.Thread(target=burn); b.start(); time.sleep(1)
r = []; t = threading.Thread(target=lambda: r.append(sys_stats())); t.start(); t.join(); b.join()
assert r[0]["cpu"] > 0 and max(r[0]["cores"]) > 20, r[0]["cpu"]
print("cpu monitor ok")

# USB encryption: round trip, wrong password, tamper + truncation detection, password change. Temp folder only.
import multit
from multit import lock_tree, unlock_tree, vault_open, _write_vault, VAULT_FILE, _CHUNK
multit._vault_backup = lambda root, text: None  # don't write key backups from tests
with tempfile.TemporaryDirectory() as t:
    files = {"a.txt": b"hello", "empty.bin": b"", "exact.bin": os.urandom(_CHUNK), "big.bin": os.urandom(int(_CHUNK * 2.5)),
             "sub/deep/ünïcode ✓.txt": "kirilica: здравей".encode(), "ro.txt": b"read only"}
    for rel, data in files.items():
        Path(t, rel).parent.mkdir(parents=True, exist_ok=True); Path(t, rel).write_bytes(data)
    os.chmod(Path(t, "ro.txt"), stat.S_IREAD)
    quiet = lambda *a, **k: None
    done, skipped = lock_tree(t, "correct horse 1", quiet)
    assert done == 6 and not skipped
    on_disk = [p for p in Path(t).rglob("*") if p.is_file()]
    assert all(p.suffix == ".mtlk" or p.name in (VAULT_FILE, "HOW-TO-UNLOCK.txt") for p in on_disk), on_disk  # names hidden too
    assert not any(b"hello" in p.read_bytes() for p in on_disk)
    try:
        unlock_tree(t, "wrong password", quiet); raise AssertionError("wrong password accepted")
    except ValueError:
        pass
    # tamper with one file, cut another short: both must be refused and left locked
    locked = sorted(Path(t).rglob("*.mtlk"), key=lambda p: p.stat().st_size)
    victim, cut = locked[-1], locked[-2]
    raw = bytearray(victim.read_bytes()); raw[200] ^= 1; victim.write_bytes(raw)
    cut.write_bytes(cut.read_bytes()[:-(_CHUNK // 2)])
    key = vault_open(t, "correct horse 1")
    _write_vault(t, key, "new pass 2")  # change password: same files, new wrapper
    done, skipped = unlock_tree(t, "new pass 2", quiet)
    assert done == 4 and len(skipped) == 2 and victim.exists() and cut.exists(), (done, skipped)
    for rel, data in files.items():
        if len(data) < _CHUNK:  # the two damaged ones were the largest files
            assert Path(t, rel).read_bytes() == data, rel
print("usb encryption ok")

# the CLI path the UI uses: password via env var, never on the command line (temp folder stands in for the drive)
import contextlib, io
with tempfile.TemporaryDirectory() as t:
    Path(t, "doc.txt").write_text("secret plans")
    real_root, multit._usb_root = multit._usb_root, lambda d: t
    try:
        os.environ["MULTIT_USB_KEY"] = "env password 9"
        with contextlib.redirect_stdout(io.StringIO()):
            multit.main(["usb", "lock", "X:"])
        assert not Path(t, "doc.txt").exists() and len(list(Path(t).glob("*.mtlk"))) == 1
        os.environ["MULTIT_USB_KEY"] = "not it 12345"
        try:
            multit.main(["usb", "unlock", "X:"]); raise AssertionError("wrong password accepted")
        except SystemExit as e:
            assert "wrong password" in str(e)
        os.environ["MULTIT_USB_KEY"] = "env password 9"
        with contextlib.redirect_stdout(io.StringIO()):
            multit.main(["usb", "unlock", "X:"])
        assert Path(t, "doc.txt").read_text() == "secret plans"
    finally:
        multit._usb_root = real_root
        os.environ.pop("MULTIT_USB_KEY", None)
print("usb cli ok")

# ---- top-5 features. Nothing here touches real settings: state files go to a temp dir, powercfg is intercepted.
scratch = Path(tempfile.mkdtemp())
multit.VAULTS_DB, multit.BACKUPS_DB, multit.BOOST_STATE = scratch / "v.json", scratch / "b.json", scratch / "boost.json"

def expect_exit(argv, text):
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            multit.main(argv)
    except SystemExit as e:
        assert text in str(e), (argv, str(e)); return
    raise AssertionError(f"{argv} should have refused")

# folder vault: protected folders refused, temp folder round-trips and is remembered
expect_exit(["vault", "lock", str(Path.home())], "refusing")
expect_exit(["vault", "lock", str(Path.home() / "Documents")], "refusing")
with tempfile.TemporaryDirectory() as t:
    Path(t, "notes.txt").write_text("vault me")
    os.environ["MULTIT_USB_KEY"] = "folder pass 77"
    with contextlib.redirect_stdout(io.StringIO()):
        multit.main(["vault", "lock", t])
    assert not Path(t, "notes.txt").exists() and multit.vault_folders()[0]["locked"] == 1
    assert "vault unlock" in Path(t, "HOW-TO-UNLOCK.txt").read_text()
    with contextlib.redirect_stdout(io.StringIO()):
        multit.main(["vault", "unlock", t])
    assert Path(t, "notes.txt").read_text() == "vault me"
    os.environ.pop("MULTIT_USB_KEY")
print("folder vault ok")

# bootable USB: refuses non-USB drives (never runs Ventoy here)
expect_exit(["boot", "install", "C:", "--erase", "C:"], "not a connected USB drive")
print("boot guards ok")

# app updater: header-based parsing copes with names containing spaces and a name that fills its column
sample = ("Name                          Id                      Version     Available   Source\n"
          "-------------------------------------------------------------------------------------\n"
          "7-Zip 26.02 (x64)             7zip.7zip               26.02       26.04       winget\n"
          "GNU Midnight Commander v4.8.3 GNU.MidnightCommander   4.8.33 (b)  4.8.33.236  winget\n"
          "FiveM                         Cfx.re.FiveM            Unknown     2.0.0.257   winget\n"
          "3 upgrades available.\n")
real_run = multit.run
multit.run = lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=sample, stderr="")
try:
    ups = multit.winget_upgrades()
finally:
    multit.run = real_run
assert [u["id"] for u in ups] == ["7zip.7zip", "GNU.MidnightCommander", "Cfx.re.FiveM"], ups
assert ups[1]["version"] == "4.8.33 (b)" and ups[2]["available"] == "2.0.0.257"
print("updater parse ok")

# backups: guards, copy run, mirror only into empty / MultiT-made folders
with tempfile.TemporaryDirectory() as t:
    src, dst, other = Path(t, "src"), Path(t, "dst"), Path(t, "someone_elses")
    (src / "sub").mkdir(parents=True); other.mkdir()
    (src / "a.txt").write_text("1"); (src / "sub" / "b.txt").write_text("2"); (other / "keep.txt").write_text("x")
    assert multit.backup_check(str(src), str(src / "inside"), False)        # nested
    assert multit.backup_check(str(src), "D:\\", False)                      # drive root
    assert multit.backup_check(str(src), str(other), True)                   # mirror into a foreign, non-empty folder
    assert multit.backup_check(str(src), str(other), False) is None          # plain copy there is fine
    job = {"name": "t", "src": str(src), "dst": str(dst), "mirror": True}
    multit._save(multit.BACKUPS_DB, [job])
    with contextlib.redirect_stdout(io.TextIOWrapper(io.BytesIO())):  # run() streams via .buffer
        assert multit.backup_run(job, log=lambda *a, **k: None)
    assert (dst / "sub" / "b.txt").read_text() == "2" and (dst / ".multit-backup").exists()
    (src / "a.txt").unlink()
    with contextlib.redirect_stdout(io.TextIOWrapper(io.BytesIO())):
        assert multit.backup_run(job)                                         # mirror: deletion propagates, marker survives
    assert not (dst / "a.txt").exists() and (dst / ".multit-backup").exists()
    assert multit.backup_jobs()[0]["last_ok"] is True
print("backup ok")

# game booster: closes a process we started ourselves; power plan calls are intercepted
pinger = subprocess.Popen(["ping", "-n", "120", "127.0.0.1"], stdout=subprocess.DEVNULL, creationflags=multit.NO_WINDOW)
calls = []
multit.run = lambda cmd, *a, **k: (calls.append(cmd), subprocess.CompletedProcess(cmd, 0, stdout="Power Scheme GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  (Balanced)", stderr=""))[1]
try:
    time.sleep(0.5)
    st = multit.boost_on(["PING.EXE", "explorer.exe"], log=lambda *a, **k: None)
    assert pinger.wait(timeout=10) is not None and [c["name"].lower() for c in st["closed"]] == ["ping.exe"]  # explorer is never closed
    try:
        multit.boost_on(["PING.EXE"], log=lambda *a, **k: None); raise AssertionError("double boost allowed")
    except ValueError:
        pass
    multit.boost_off(reopen=False, log=lambda *a, **k: None)
    assert ["powercfg", "/setactive", "SCHEME_MIN"] in calls and ["powercfg", "/setactive", "381b4222-f694-41f0-9685-ff5bb260df2e"] in calls
    assert not multit.BOOST_STATE.exists()
finally:
    multit.run = real_run
    if pinger.poll() is None:
        pinger.kill()
print("boost ok")

# ---- AI models: duplicates across apps, move + junction + restore (temp folders stand in for app folders)
with tempfile.TemporaryDirectory() as t:
    lm, hf, dest = Path(t, "lm"), Path(t, "hf"), Path(t, "otherdrive")
    real_roots, multit.MODEL_ROOTS = multit.MODEL_ROOTS, [("LM Studio", lm), ("Hugging Face", hf)]
    try:
        blob = os.urandom(60 << 20)
        (lm / "pub" / "qwen").mkdir(parents=True); (lm / "pub" / "qwen" / "qwen.gguf").write_bytes(blob)
        (hf / "models--org--qwen").mkdir(parents=True); (hf / "models--org--qwen" / "copy.gguf").write_bytes(blob)
        (lm / "pub" / "other").mkdir(); (lm / "pub" / "other" / "other.gguf").write_bytes(os.urandom(60 << 20))
        r = multit.models_scan()
        dups = [f for f in r["files"] if f.get("dup")]
        assert len(r["files"]) == 3 and len(dups) == 2 and {f["app"] for f in dups} == {"LM Studio", "Hugging Face"}, r["files"]
        for bad, why in ((lm / "pub" / "qwen", "different drive"), (Path(t), "only model folders")):
            try:
                multit.model_move(bad, dest, log=lambda *a, **k: None); raise AssertionError("should refuse")
            except ValueError as e:
                assert why in str(e), e
        dest.mkdir()
        multit.model_move(lm / "pub" / "qwen", dest, log=lambda *a, **k: None, allow_same_drive=True)
        assert multit._is_link(lm / "pub" / "qwen") and (lm / "pub" / "qwen" / "qwen.gguf").read_bytes() == blob  # app still sees it
        assert (dest / "qwen" / "qwen.gguf").exists() and not (lm / "pub" / "qwen.multit-old").exists()
        assert any(f["moved"] for f in multit.models_scan()["files"])
        multit.model_restore(lm / "pub" / "qwen", log=lambda *a, **k: None)
        assert not multit._is_link(lm / "pub" / "qwen") and (lm / "pub" / "qwen" / "qwen.gguf").read_bytes() == blob and not (dest / "qwen").exists()
    finally:
        multit.MODEL_ROOTS = real_roots
print("models ok")

# ---- video tools on a generated 8 s 720p test clip
with tempfile.TemporaryDirectory() as t:
    clip = Path(t, "clip.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30", "-f", "lavfi", "-i", "sine=f=440",
                    "-t", "8", "-c:v", "libx264", "-crf", "10", "-c:a", "aac", "-shortest", str(clip)], check=True, creationflags=multit.NO_WINDOW)
    info = multit.video_info(clip)
    assert info["width"] == 1280 and info["audio"] and 7.5 < info["duration"] < 8.5, info
    sink = io.TextIOWrapper(io.BytesIO())
    with contextlib.redirect_stdout(sink):
        small = multit.video_compress(clip, 1)                 # 1 MB target
        gif = multit.video_convert(clip, "gif", "0:01", "0:03")
        mp3 = multit.video_convert(clip, "mp3")
        cut = multit.video_convert(clip, "trim", "2", "5")
    assert small.stat().st_size <= 1.08 * (1 << 20), small.stat().st_size
    assert gif.suffix == ".gif" and mp3.suffix == ".mp3" and 2 <= multit.video_info(cut)["duration"] <= 4.5
    try:
        multit.video_compress(clip, 0.01); raise AssertionError("absurd size accepted")
    except ValueError:
        pass
print("video ok")

# ---- server panel: background start, log capture, stop; crash -> restarts -> gives up
import sys
srv_state = Path(tempfile.mkdtemp())
os.environ["MULTIT_STATE_DIR"] = str(srv_state)  # the supervisor subprocess reads this
real_state, multit.STATE_DIR = multit.STATE_DIR, srv_state
try:
    py = f'"{sys.executable}"'
    multit._save(srv_state / "servers.json", [
        {"name": "web", "cmd": f'{py} -c "import time; print(\'listening\', flush=True); time.sleep(120)"', "cwd": None, "restart": True},
        {"name": "crashy", "cmd": f'{py} -c "print(\'boom\'); raise SystemExit(3)"', "cwd": None, "restart": True, "delay": 0.2}])
    multit.server_start("web"); multit.server_start("crashy")
    for _ in range(100):
        if multit.server_status("web")["running"] and "listening" in multit.server_log_tail("web"):
            break
        time.sleep(0.2)
    st = multit.server_status("web")
    assert st["running"] and st["mem"] > 0, st
    try:
        multit.server_start("web"); raise AssertionError("double start allowed")
    except ValueError:
        pass
    multit.server_stop("web")
    assert not multit.server_status("web")["running"]
    for _ in range(100):
        if multit.server_status("crashy")["status"] == "gave up":
            break
        time.sleep(0.2)
    assert multit.server_status("crashy")["status"] == "gave up" and multit.server_log_tail("crashy").count("exited with code 3") == 6
finally:
    multit.STATE_DIR = real_state
    os.environ.pop("MULTIT_STATE_DIR", None)
print("servers ok")

# ---- console input + graceful stop: the "server" reads stdin, answers commands, saves on `stop`
srv_state = Path(tempfile.mkdtemp())
os.environ["MULTIT_STATE_DIR"] = str(srv_state)
real_state, multit.STATE_DIR = multit.STATE_DIR, srv_state
try:
    script = srv_state / "fake_mc.py"
    script.write_text("import sys\nprint('Done! ready', flush=True)\nfor line in sys.stdin:\n"
                      "    line = line.strip()\n    if line == 'stop':\n        print('Saving worlds... saved', flush=True); break\n"
                      "    print('got ' + line, flush=True)\n")
    multit._save(srv_state / "servers.json", [{"name": "mc", "cmd": f'"{sys.executable}" "{script}"', "cwd": None, "restart": True, "stop_cmd": "stop"}])
    multit.server_start("mc")
    for _ in range(100):
        if "Done!" in multit.server_log_tail("mc"):
            break
        time.sleep(0.2)
    multit.server_send("mc", "say hello")
    for _ in range(50):
        if "got say hello" in multit.server_log_tail("mc"):
            break
        time.sleep(0.2)
    assert "got say hello" in multit.server_log_tail("mc"), multit.server_log_tail("mc")
    with contextlib.redirect_stdout(io.StringIO()):
        multit.server_stop("mc")
    log = multit.server_log_tail("mc")
    assert "saved" in log and "exited with code 0" in log and not multit.server_status("mc")["running"], log  # clean exit, no kill, no restart
finally:
    multit.STATE_DIR = real_state
    os.environ.pop("MULTIT_STATE_DIR", None)
print("server console + graceful stop ok")

# ---- server creator: real Minecraft download into a temp folder (never started); Java check; bad names
crt_state = Path(tempfile.mkdtemp())
real_state, multit.STATE_DIR = multit.STATE_DIR, crt_state
try:
    with tempfile.TemporaryDirectory() as t:
        for bad in ("a/b", "x:y", ""):
            try:
                multit.create_server("minecraft", "vanilla", t, bad); raise AssertionError("bad name accepted")
            except ValueError:
                pass
        newest_needs = multit._mojang_version(multit.mc_versions("vanilla")[0])["javaVersion"]["majorVersion"]
        if newest_needs > multit.java_installs()[0][0]:  # this PC lacks the Java the newest MC needs -> clear error, folder cleaned up
            try:
                multit.create_server("minecraft", "vanilla", t, "too-new"); raise AssertionError("missing Java not caught")
            except ValueError as e:
                assert f"Java {newest_needs}" in str(e) and not Path(t, "too-new").exists(), e
        with contextlib.redirect_stdout(io.TextIOWrapper(io.BytesIO())):
            r = multit.create_server("minecraft", "vanilla", t, "smp", version="1.21.11", ram=3, eula=True)  # needs Java 21
        d = Path(r["dest"])
        assert (d / "server.jar").stat().st_size > 30 << 20 and "eula=true" in (d / "eula.txt").read_text()
        assert "-Xmx3G -jar server.jar nogui" in (d / "start.bat").read_text()
        entry = multit.servers()[0]
        assert entry["name"] == "smp" and entry["stop_cmd"] == "stop" and entry["platform"] == "minecraft"
        try:
            multit.create_server("minecraft", "vanilla", t, "smp"); raise AssertionError("duplicate accepted")
        except ValueError:
            pass
        for fw in ("paper", "purpur", "fabric", "forge", "neoforge"):
            assert multit.mc_versions(fw), fw
        assert multit._neoforge_mc("21.1.77") == "1.21.1" and multit._neoforge_mc("26.3.0.86") == "26.3" and multit._neoforge_mc("20.4.237") == "1.20.4"
finally:
    multit.STATE_DIR = real_state
print("server creator ok")
