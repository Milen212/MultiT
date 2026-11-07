#!/usr/bin/env python3
"""MultiT - dev multitool: build any project into an .exe, spin up VMs fast, plus small utilities.

  multit build [path]            autodetect language -> .exe in <project>/dist
  multit build [path] --venv     python: build inside a clean throwaway venv
  multit detect [path]           just show what build would do
  multit venv [path] [pkgs..]    create/update .venv + install requirements
  multit iso list | get OS       latest ISO of 20 popular OSes -> Downloads\\ISOs
  multit vm create NAME --iso X  X = .iso file or OS name from `iso list` (auto-downloaded)
                                 VirtualBox unattended install, or VMware (--vmware / auto)
  multit vm create ... --dev     + install Python, git, node, VS Code... inside the VM
  multit vm list|start|stop|delete|snap|restore NAME [--vmware]
  multit vm devtools NAME --user U --password P   install the dev essentials into an existing VM
  multit                         (no arguments) open the UI
  multit doctor | install TOOL   which toolchains are installed / install one
  multit ports [PORT] [--kill]   who listens on which port
  multit serve [DIR]             share a folder over HTTP on the LAN
  multit hash FILE [--check H]   sha256/sha1/md5
  multit clean [path] [--yes]    remove build junk (dry-run unless --yes)
  multit cleanup [KEY..|--all]   free disk space like Windows Disk Cleanup (+ dev caches)
  multit du [path]               biggest folders/files (system & program folders hidden)
  multit dupes PATH              duplicate files
  multit top                     CPU / RAM and the heaviest processes
  multit usb list|lock|unlock|passwd|speed [E:]   encrypt USB drives with your own password
  multit vault list|lock|unlock|passwd FOLDER     encrypt any folder
  multit boot list|setup|install E: --erase E:|add E: ubuntu   bootable USB (Ventoy)
  multit update [ID..|--all]     update installed apps (winget)
  multit backup list|add|run|remove ...           folder backups, optionally scheduled
  multit boost on --apps X.exe | off              game booster
  multit models [move DIR DEST|restore DIR]       AI models: sizes, duplicates, move to another drive
  multit video compress|trim|gif|mp3|mp4|batch FILE [--size 10]   ffmpeg helpers
  multit server list|add|start|stop|restart|log NAME              background servers
  multit create minecraft paper --name smp --accept-eula          new server: minecraft, fivem, steam, terraria, discord, web
  multit startup [enable|disable NAME]   startup apps, same switch as Task Manager
  multit path [--fix|--add DIR]  PATH doctor (dead / duplicate entries)
  multit repos [DIR] [--pull]    every git repo: branch, changes, ahead/behind
"""
import argparse, base64, ctypes, functools, glob, hashlib, http.server, json, os, re, secrets, shutil, socket, stat, subprocess, sys, tempfile
from collections import Counter
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse
from urllib.request import Request, urlopen

FROZEN = getattr(sys, "frozen", False)  # running as MultiT.exe -> sys.executable is not python
SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "env", "__pycache__", "dist", "build", "target", "bin", "obj", ".idea", ".vs"}
EXT = {".py": "python", ".pyw": "python", ".js": "node", ".cjs": "node", ".mjs": "node", ".go": "go", ".rs": "rust",
       ".c": "c", ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".cs": "csharp", ".java": "java"}
MARKERS = [("rust", "Cargo.toml"), ("go", "go.mod"), ("csharp", "*.csproj"), ("csharp", "*.sln"), ("cmake", "CMakeLists.txt"),
           ("maven", "pom.xml"), ("gradle", "build.gradle*"), ("node", "package.json")]
_PF, _PF86, _LA = r"%ProgramFiles%", r"%ProgramFiles(x86)%", r"%LOCALAPPDATA%"
# key: (name, category, winget id or download URL, detect). detect = exe names looked up on PATH, or paths (env vars + globs ok).
# `multit install <key>` installs via winget; "missing tool" messages point there too.
TOOLS = {
    # languages & runtimes
    "python": ("Python", "Languages", "Python.Python.3.13", ["python"]),
    "node": ("Node.js LTS", "Languages", "OpenJS.NodeJS.LTS", ["node"]),
    "bun": ("Bun", "Languages", "Oven-sh.Bun", ["bun"]),
    "deno": ("Deno", "Languages", "DenoLand.Deno", ["deno"]),
    "go": ("Go", "Languages", "GoLang.Go", ["go"]),
    "rust": ("Rust (rustup)", "Languages", "Rustlang.Rustup", ["cargo", r"%USERPROFILE%\.cargo\bin\cargo.exe"]),
    "dotnet": (".NET SDK", "Languages", "Microsoft.DotNet.SDK.10", []),
    "java": ("Java JDK", "Languages", "EclipseAdoptium.Temurin.21.JDK", ["javac"]),
    "kotlin": ("Kotlin", "Languages", "https://kotlinlang.org/docs/command-line.html", ["kotlinc"]),
    "gcc": ("GCC / G++ (MinGW)", "Languages", "BrechtSanders.WinLibs.POSIX.UCRT", ["gcc"]),
    "clang": ("LLVM / Clang", "Languages", "LLVM.LLVM", ["clang", _PF + r"\LLVM\bin\clang.exe"]),
    "zig": ("Zig", "Languages", "zig.zig", ["zig"]),
    "ruby": ("Ruby", "Languages", "RubyInstallerTeam.Ruby.3.3", ["ruby", r"C:\Ruby3*\bin\ruby.exe"]),
    "php": ("PHP", "Languages", "PHP.PHP.8.3", ["php"]),
    "perl": ("Strawberry Perl", "Languages", "StrawberryPerl.StrawberryPerl", ["perl", r"C:\Strawberry\perl\bin\perl.exe"]),
    "lua": ("Lua", "Languages", "DEVCOM.Lua", ["lua"]),
    "r": ("R", "Languages", "RProject.R", ["Rscript", _PF + r"\R\R-*\bin\R.exe"]),
    "julia": ("Julia", "Languages", "Julialang.Julia", ["julia", _LA + r"\Programs\Julia*\bin\julia.exe"]),
    "dart": ("Dart SDK", "Languages", "Google.DartSDK", ["dart"]),
    # python tooling
    "uv": ("uv (fast pip/venv)", "Python", "astral-sh.uv", ["uv"]),
    "pyinstaller": ("PyInstaller", "Python", None, []),
    "conda": ("Miniconda", "Python", "Anaconda.Miniconda3", ["conda", r"%USERPROFILE%\miniconda3\Scripts\conda.exe"]),
    # build tools & package managers
    "cmake": ("CMake", "Build", "Kitware.CMake", ["cmake", _PF + r"\CMake\bin\cmake.exe"]),
    "ninja": ("Ninja", "Build", "Ninja-build.Ninja", ["ninja"]),
    "make": ("GNU Make", "Build", "ezwinports.make", ["make"]),
    "maven": ("Maven", "Build", "https://maven.apache.org/download.cgi", ["mvn"]),
    "gradle": ("Gradle", "Build", "https://gradle.org/install/", ["gradle"]),
    "vsbuildtools": ("VS Build Tools (MSVC)", "Build", "Microsoft.VisualStudio.2022.BuildTools", [_PF86 + r"\Microsoft Visual Studio\2022\BuildTools"]),
    "yarn": ("Yarn", "Build", "Yarn.Yarn", ["yarn"]),
    "pnpm": ("pnpm", "Build", "pnpm.pnpm", ["pnpm"]),
    # editors & IDEs
    "vscode": ("VS Code", "Editors", "Microsoft.VisualStudioCode", ["code", _LA + r"\Programs\Microsoft VS Code\Code.exe"]),
    "cursor": ("Cursor", "Editors", "Anysphere.Cursor", ["cursor", _LA + r"\Programs\cursor\Cursor.exe"]),
    "vs": ("Visual Studio 2022 Community", "Editors", "Microsoft.VisualStudio.2022.Community", [_PF + r"\Microsoft Visual Studio\2022\Community\Common7\IDE\devenv.exe"]),
    "jbtoolbox": ("JetBrains Toolbox", "Editors", "JetBrains.Toolbox", [_LA + r"\JetBrains\Toolbox\bin\jetbrains-toolbox.exe"]),
    "intellij": ("IntelliJ IDEA Community", "Editors", "JetBrains.IntelliJIDEA.Community", [_PF + r"\JetBrains\IntelliJ IDEA Community*"]),
    "pycharm": ("PyCharm Community", "Editors", "JetBrains.PyCharm.Community", [_PF + r"\JetBrains\PyCharm Community*"]),
    "androidstudio": ("Android Studio", "Editors", "Google.AndroidStudio", [_PF + r"\Android\Android Studio"]),
    "notepadpp": ("Notepad++", "Editors", "Notepad++.Notepad++", [_PF + r"\Notepad++\notepad++.exe"]),
    "sublime": ("Sublime Text", "Editors", "SublimeHQ.SublimeText.4", ["subl", _PF + r"\Sublime Text\sublime_text.exe"]),
    "neovim": ("Neovim", "Editors", "Neovim.Neovim", ["nvim", _PF + r"\Neovim\bin\nvim.exe"]),
    "vim": ("Vim", "Editors", "vim.vim", ["vim", _PF + r"\Vim\vim*\vim.exe"]),
    # git
    "git": ("Git", "Git", "Git.Git", ["git"]),
    "gh": ("GitHub CLI", "Git", "GitHub.cli", ["gh"]),
    "githubdesktop": ("GitHub Desktop", "Git", "GitHub.GitHubDesktop", [_LA + r"\GitHubDesktop\GitHubDesktop.exe"]),
    "gitlfs": ("Git LFS", "Git", "GitHub.GitLFS", ["git-lfs"]),
    "lazygit": ("lazygit", "Git", "JesseDuffield.lazygit", ["lazygit"]),
    # containers & VMs
    "docker": ("Docker Desktop", "Containers & VMs", "Docker.DockerDesktop", ["docker", _PF + r"\Docker\Docker\Docker Desktop.exe"]),
    "podman": ("Podman", "Containers & VMs", "RedHat.Podman", ["podman"]),
    "kubectl": ("kubectl", "Containers & VMs", "Kubernetes.kubectl", ["kubectl"]),
    "helm": ("Helm", "Containers & VMs", "Helm.Helm", ["helm"]),
    "minikube": ("minikube", "Containers & VMs", "Kubernetes.minikube", ["minikube"]),
    "vagrant": ("Vagrant", "Containers & VMs", "Hashicorp.Vagrant", ["vagrant"]),
    "virtualbox": ("VirtualBox", "Containers & VMs", "Oracle.VirtualBox", ["VBoxManage", _PF + r"\Oracle\VirtualBox\VBoxManage.exe"]),
    "vmware": ("VMware Workstation", "Containers & VMs", "https://www.vmware.com/products/desktop-hypervisor/workstation-and-fusion",
               [_PF86 + r"\VMware\VMware Workstation\vmrun.exe", _PF + r"\VMware\VMware Workstation\vmrun.exe"]),
    # cloud & infra
    "aws": ("AWS CLI", "Cloud", "Amazon.AWSCLI", ["aws", _PF + r"\Amazon\AWSCLIV2\aws.exe"]),
    "azure": ("Azure CLI", "Cloud", "Microsoft.AzureCLI", ["az"]),
    "gcloud": ("Google Cloud SDK", "Cloud", "Google.CloudSDK", ["gcloud", _LA + r"\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"]),
    "terraform": ("Terraform", "Cloud", "Hashicorp.Terraform", ["terraform"]),
    # databases
    "postgres": ("PostgreSQL", "Databases", "PostgreSQL.PostgreSQL.17", ["psql", _PF + r"\PostgreSQL\*\bin\psql.exe"]),
    "mysql": ("MySQL", "Databases", "Oracle.MySQL", ["mysql", _PF + r"\MySQL\MySQL Server*\bin\mysql.exe"]),
    "mongodb": ("MongoDB Server", "Databases", "MongoDB.Server", ["mongod", _PF + r"\MongoDB\Server\*\bin\mongod.exe"]),
    "sqlite": ("SQLite", "Databases", "SQLite.SQLite", ["sqlite3"]),
    "dbeaver": ("DBeaver", "Databases", "DBeaver.DBeaver.Community", [_PF + r"\DBeaver\dbeaver.exe", _LA + r"\DBeaver\dbeaver.exe"]),
    "compass": ("MongoDB Compass", "Databases", "MongoDB.Compass.Full", [_LA + r"\MongoDBCompass\MongoDBCompass.exe"]),
    # API & network
    "postman": ("Postman", "API & Network", "Postman.Postman", [_LA + r"\Postman\Postman.exe"]),
    "insomnia": ("Insomnia", "API & Network", "Insomnia.Insomnia", [_LA + r"\insomnia\Insomnia.exe"]),
    "wireshark": ("Wireshark", "API & Network", "WiresharkFoundation.Wireshark", [_PF + r"\Wireshark\Wireshark.exe"]),
    "ngrok": ("ngrok", "API & Network", "Ngrok.Ngrok", ["ngrok"]),
    "putty": ("PuTTY", "API & Network", "PuTTY.PuTTY", ["putty", _PF + r"\PuTTY\putty.exe"]),
    "winscp": ("WinSCP", "API & Network", "WinSCP.WinSCP", [_PF86 + r"\WinSCP\WinSCP.exe", _LA + r"\Programs\WinSCP\WinSCP.exe"]),
    # terminal & CLI power tools
    "wt": ("Windows Terminal", "Terminal & CLI", "Microsoft.WindowsTerminal", ["wt"]),
    "pwsh": ("PowerShell 7", "Terminal & CLI", "Microsoft.PowerShell", ["pwsh"]),
    "ohmyposh": ("Oh My Posh", "Terminal & CLI", "JanDeDobbeleer.OhMyPosh", ["oh-my-posh"]),
    "ripgrep": ("ripgrep (rg)", "Terminal & CLI", "BurntSushi.ripgrep.MSVC", ["rg"]),
    "fzf": ("fzf", "Terminal & CLI", "junegunn.fzf", ["fzf"]),
    "bat": ("bat", "Terminal & CLI", "sharkdp.bat", ["bat"]),
    "fd": ("fd", "Terminal & CLI", "sharkdp.fd", ["fd"]),
    "jq": ("jq", "Terminal & CLI", "jqlang.jq", ["jq"]),
    "ffmpeg": ("FFmpeg", "Terminal & CLI", "Gyan.FFmpeg", ["ffmpeg"]),
    # utilities
    "7zip": ("7-Zip", "Utilities", "7zip.7zip", ["7z", _PF + r"\7-Zip\7z.exe"]),
    "powertoys": ("PowerToys", "Utilities", "Microsoft.PowerToys", [_LA + r"\PowerToys\PowerToys.exe", _PF + r"\PowerToys\PowerToys.exe"]),
    "everything": ("Everything (instant file search)", "Utilities", "voidtools.Everything", [_PF + r"\Everything\Everything.exe"]),
    "ventoy": ("Ventoy (bootable USB)", "Utilities", "Ventoy.Ventoy", [_LA + r"\Microsoft\WinGet\Packages\Ventoy.Ventoy*\*\Ventoy2Disk.exe"]),
    "winget": ("winget", "Utilities", None, ["winget"]),
}
HINTS = {k: v[2] for k, v in TOOLS.items() if v[2]}  # winget ids
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def run(cmd, cwd=None, check=True, capture=False, env=None):
    cmd = [str(c) for c in cmd]
    if capture:
        r = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, env=env, creationflags=NO_WINDOW)
    else:
        print(">", " ".join(f'"{c}"' if " " in c else c for c in cmd), flush=True)
        # pipe child output through our stdout: reaches the GUI console too, and no console windows pop up
        p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
        for chunk in iter(lambda: p.stdout.read1(65536), b""):
            sys.stdout.buffer.write(chunk)
            sys.stdout.flush()
        r = subprocess.CompletedProcess(cmd, p.wait())
    if check and r.returncode:
        sys.exit(f"command failed ({r.returncode})" + (f"\n{r.stdout}{r.stderr}" if capture else ""))
    return r


def need(*names, hint=""):
    for n in names:
        if p := shutil.which(n):
            return p
    sys.exit(f"missing tool: {' / '.join(names)}" + (f"\n  install: multit install {hint}" if hint in HINTS else ""))


def python_exe():
    return need("python", "py", hint="python") if FROZEN else sys.executable


# ---------------------------------------------------------------- detection

def source_files(root):
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS and not x.startswith(".")]
        for f in files:
            if Path(f).suffix.lower() in EXT:
                yield Path(d, f)


def find_entry(lang, root, files):
    top = [f for f in files if f.parent == root] or files
    names = {"python": ["main.py", "app.py", "__main__.py", "run.py", "cli.py"],
             "node": ["index.js", "main.js", "app.js", "server.js", "cli.js"],
             "go": ["main.go"], "rust": ["main.rs"], "c": ["main.c"], "cpp": ["main.cpp", "main.cc"],
             "csharp": ["Program.cs"], "java": ["Main.java"]}.get(lang, [])
    for n in names:
        for f in top:
            if f.name.lower() == n.lower():
                return f
    marker = {"python": "__main__", "java": "static void main", "csharp": "static void Main"}.get(lang)
    if marker:
        for f in files:
            if marker in f.read_text(errors="ignore"):
                return f
    return sorted(top)[0]


def detect(path):
    """-> (lang, root, entry). entry is the marker file or main source file."""
    p = Path(path).resolve()
    if p.is_file():
        lang = EXT.get(p.suffix.lower())
        if not lang:
            sys.exit(f"don't know how to build {p.suffix} files")
        return lang, p.parent, p
    if not p.is_dir():
        sys.exit(f"not found: {p}")
    for lang, pat in MARKERS:
        if hit := sorted(p.glob(pat)):
            return lang, p, hit[0]
    files = list(source_files(p))
    if not files:
        sys.exit(f"no source files found in {p}")
    lang = Counter(EXT[f.suffix.lower()] for f in files).most_common(1)[0][0]
    return lang, p, find_entry(lang, p, [f for f in files if EXT[f.suffix.lower()] == lang])


# ---------------------------------------------------------------- builders (each returns list of exe paths)

def project_venv(root):
    return next((p for d in (".venv", "venv", "env") if (p := root / d / "Scripts" / "python.exe").exists()), None)


def b_python(root, entry, out, name, a, tmp):
    # project venv > fresh throwaway venv (--venv) > system python
    py = project_venv(root)
    if py:
        print(f"using project venv: {py.parent.parent}")
    elif a.venv:
        run([python_exe(), "-m", "venv", tmp / "venv"])
        py = tmp / "venv" / "Scripts" / "python.exe"
    else:
        py = python_exe()
    if run([py, "-m", "PyInstaller", "--version"], check=False, capture=True).returncode:
        in_venv = run([py, "-c", "import sys; print(sys.prefix != sys.base_prefix)"], capture=True).stdout.strip() == "True"
        run([py, "-m", "pip", "install", *([] if in_venv else ["--user"]), "pyinstaller"])
    if (root / "requirements.txt").exists():
        run([py, "-m", "pip", "install", "-r", root / "requirements.txt"])
    cmd = [py, "-m", "PyInstaller", "--onefile", "--noconfirm", "--clean", "--name", name,
           "--distpath", out, "--workpath", tmp / "work", "--specpath", tmp, "--paths", root]
    if a.gui:
        cmd.append("--noconsole")
    if a.icon:
        cmd += ["--icon", Path(a.icon).resolve()]
    for d in a.data:  # bundled next to the code; read it via sys._MEIPASS
        cmd += ["--add-data", f"{Path(d).resolve()}{os.pathsep}{Path(d).name if Path(d).is_dir() else '.'}"]
    run(cmd + [entry], cwd=root)
    return [out / f"{name}.exe"]


def b_node(root, entry, out, name, a, tmp):
    npm, npx = need("npm", hint="node"), need("npx", hint="node")
    pj = root / "package.json"
    if pj.exists():
        data = json.loads(pj.read_text(encoding="utf-8"))
        if (data.get("dependencies") or data.get("devDependencies")) and not (root / "node_modules").exists():
            run([npm, "install"], cwd=root)
        if "build" in data.get("scripts", {}):
            run([npm, "run", "build"], cwd=root)
        bin_ = data.get("bin")
        bin_ = next(iter(bin_.values())) if isinstance(bin_, dict) else bin_
        entry = root / (bin_ or data.get("main") or "index.js")
    # ponytail: node22 base binary pinned; bump when @yao-pkg/pkg ships newer bases
    run([npx, "--yes", "@yao-pkg/pkg", entry, "--targets", "node22-win-x64", "--output", out / f"{name}.exe"], cwd=root)
    return [out / f"{name}.exe"]


def b_go(root, entry, out, name, a, tmp):
    go = need("go", hint="go")
    flags = "-s -w" + (" -H=windowsgui" if a.gui else "")
    target = [entry] if a.single else ["."] if (root / "go.mod").exists() else sorted(root.glob("*.go"))
    run([go, "build", "-ldflags", flags, "-o", out / f"{name}.exe", *target], cwd=root,
        env={**os.environ, "GOOS": "windows", "GOARCH": "amd64"})
    return [out / f"{name}.exe"]


def b_rust(root, entry, out, name, a, tmp):
    if entry.suffix == ".rs":  # lone .rs file, no Cargo
        run([need("rustc", hint="rust"), "-O", "-o", out / f"{name}.exe", entry], cwd=root)
        return [out / f"{name}.exe"]
    run([need("cargo", hint="rust"), "build", "--release", "--target-dir", tmp / "target"], cwd=root)
    exes = list((tmp / "target" / "release").glob("*.exe"))
    return [Path(shutil.copy2(e, out)) for e in exes]


def b_csharp(root, entry, out, name, a, tmp):
    dotnet = need("dotnet", hint="dotnet")
    if not run([dotnet, "--list-sdks"], capture=True).stdout.strip():
        sys.exit(f"only the .NET runtime is installed, need the SDK\n  install: multit install dotnet")
    # entry is a .csproj/.sln, or a lone .cs (file-based apps need .NET 10+)
    run([dotnet, "publish", entry, "-c", "Release", "-r", "win-x64", "--self-contained", "true",
         "-p:PublishSingleFile=true", "-p:IncludeNativeLibrariesForSelfExtract=true", "-o", out], cwd=root)
    return list(out.glob("*.exe"))


def b_c(root, entry, out, name, a, tmp, cpp=False):
    cc = need(*(["g++", "clang++"] if cpp else ["gcc", "clang"]), hint="gcc")
    exts = {".cpp", ".cc", ".cxx", ".c"} if cpp else {".c"}
    srcs = [entry] if a.single else [f for f in source_files(root) if f.suffix.lower() in exts]
    cmd = [cc, *srcs, "-O2", "-o", out / f"{name}.exe"]
    if Path(cc).stem.startswith("g"):  # gcc/g++: static so the exe runs without MinGW DLLs
        cmd.append("-static")
    run(cmd, cwd=root)
    return [out / f"{name}.exe"]


def b_cmake(root, entry, out, name, a, tmp):
    cm = need("cmake", hint="cmake")
    run([cm, "-S", root, "-B", tmp / "cm", "-DCMAKE_BUILD_TYPE=Release"])
    run([cm, "--build", tmp / "cm", "--config", "Release"])
    exes = [e for e in (tmp / "cm").rglob("*.exe") if "CMakeFiles" not in e.parts]
    return [Path(shutil.copy2(e, out)) for e in exes]


def jpackage():
    cands = [shutil.which("jpackage"), os.environ.get("JAVA_HOME") and Path(os.environ["JAVA_HOME"], "bin", "jpackage.exe")]
    cands += sorted(glob.glob(r"C:\Program Files\*\*\bin\jpackage.exe"), reverse=True)
    for c in cands:
        if c and Path(c).exists():
            return c
    sys.exit(f"jpackage not found (needs a JDK 14+)\n  install: multit install java")


def b_java(root, entry, out, name, a, tmp):
    jp = jpackage()
    bindir = Path(jp).parent
    jin = tmp / "in"
    jin.mkdir()
    if entry.name == "pom.xml":
        run([need("mvn", hint="maven"), "-q", "package", "-DskipTests"], cwd=root)
        jars = [j for j in (root / "target").glob("*.jar") if not re.search(r"(sources|javadoc|original)", j.name)]
    elif entry.name.startswith("build.gradle"):
        gw = root / "gradlew.bat"
        run([gw if gw.exists() else need("gradle", hint="gradle"), "build", "-x", "test"], cwd=root)
        jars = [j for j in (root / "build" / "libs").glob("*.jar") if "plain" not in j.name]
    else:  # plain .java sources
        srcs = [f for f in source_files(root) if f.suffix == ".java"]
        run([bindir / "javac.exe", "-d", tmp / "classes", *srcs])
        pkg = re.search(r"^\s*package\s+([\w.]+)\s*;", entry.read_text(errors="ignore"), re.M)
        main = (pkg.group(1) + "." if pkg else "") + entry.stem
        run([bindir / "jar.exe", "--create", "--file", jin / "app.jar", "--main-class", main, "-C", tmp / "classes", "."])
        jars = [jin / "app.jar"]
    if not jars:
        sys.exit("build produced no jar")
    jar = jars[0] if jars[0].parent == jin else Path(shutil.copy2(jars[0], jin))
    shutil.rmtree(out / name, ignore_errors=True)
    run([jp, "--type", "app-image", "--input", jin, "--main-jar", jar.name, "--name", name, "--dest", out]
        + ([] if a.gui else ["--win-console"]))
    return [out / name / f"{name}.exe"]


BUILDERS = {"python": b_python, "node": b_node, "go": b_go, "rust": b_rust, "csharp": b_csharp,
            "c": b_c, "cpp": functools.partial(b_c, cpp=True), "cmake": b_cmake,
            "java": b_java, "maven": b_java, "gradle": b_java}


def cmd_detect(a):
    lang, root, entry = detect(a.path)
    print(f"language: {lang}\nroot:     {root}\nentry:    {entry}")
    return lang, root, entry


def cmd_build(a):
    lang, root, entry = cmd_detect(a)
    a.single = Path(a.path).is_file()
    name = a.name or (entry.stem if a.single else root.name)
    out = Path(a.out).resolve() if a.out else root / "dist"
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="multit_") as tmp:
        exes = [e for e in BUILDERS[lang](root, entry, out, name, a, Path(tmp)) if e.exists()]
    if not exes:
        sys.exit("build finished but no .exe was found")
    for e in exes:
        print(f"\nOK  {e}  ({e.stat().st_size / 1e6:.1f} MB)")
    if lang in ("java", "maven", "gradle"):
        print("note: Java builds are a folder with a bundled runtime - ship the whole folder.")


# ---------------------------------------------------------------- VMs (VirtualBox; Win Home has no Hyper-V)

def vbox():
    p = shutil.which("VBoxManage") or r"C:\Program Files\Oracle\VirtualBox\VBoxManage.exe"
    if not Path(p).exists():
        sys.exit("VirtualBox is not installed. Run:  multit vm setup")
    return p


def vmrun():
    for d in (r"C:\Program Files (x86)\VMware\VMware Workstation", r"C:\Program Files\VMware\VMware Workstation"):
        if Path(d, "vmrun.exe").exists():
            return Path(d, "vmrun.exe")
    return shutil.which("vmrun") and Path(shutil.which("vmrun"))


def cmd_vm(a):
    if a.action == "setup":
        return winget(HINTS["vmware" if a.vmware else "virtualbox"])
    if a.action == "create":  # --iso may be a catalog name (or omitted when NAME is one): fetch it
        key = (a.iso or a.name or "").lower()
        if key in ISOS and not (a.iso and Path(a.iso).is_file()):
            a.os = a.os or ISOS[key][1]
            a.iso = str(fetch_iso(key))
    has_vbox = bool(shutil.which("VBoxManage")) or Path(r"C:\Program Files\Oracle\VirtualBox\VBoxManage.exe").exists()
    if a.vmware or (not a.vbox and not has_vbox and vmrun()):
        return cmd_vm_vmware(a)
    vb = vbox()
    if a.action == "list":
        print(run([vb, "list", "vms"], capture=True).stdout or "(no VMs)")
        print("running:\n" + (run([vb, "list", "runningvms"], capture=True).stdout or "(none)"))
        return
    if not a.name:
        sys.exit(f"vm {a.action} needs a NAME")
    n = a.name
    if a.action == "start":
        run([vb, "startvm", n, "--type", "headless" if a.headless else "gui"])
    elif a.action == "stop":
        run([vb, "controlvm", n, "poweroff" if a.force else "acpipowerbutton"])
    elif a.action == "snap":
        run([vb, "snapshot", n, "take", a.label or "snap"])
    elif a.action == "restore":
        run([vb, "snapshot", n, "restore", a.label or "snap"])
    elif a.action == "delete":
        if not a.yes and input(f"Delete VM '{n}' and its disk? type the name to confirm: ") != n:
            sys.exit("cancelled")
        run([vb, "controlvm", n, "poweroff"], check=False, capture=True)
        run([vb, "unregistervm", n, "--delete"])
    elif a.action == "create":
        vm_create(vb, a)
    elif a.action == "devtools":
        info = run([vb, "showvminfo", n, "--machinereadable"], capture=True).stdout
        win = bool(re.search(r'^ostype="Windows', info, re.M | re.I))
        auth = ["--username", a.user, "--password", dev_password(a)]
        local, gdir = dev_script(win, a.password)
        dest = gdir + ("\\" if win else "/") + local.name
        run([vb, "guestcontrol", n, "copyto", *auth, "--target-directory", gdir, local])
        if win:
            run([vb, "guestcontrol", n, "run", *auth, "--exe", PS_EXE, "--", "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", dest])
        else:
            run([vb, "guestcontrol", n, "run", *auth, "--exe", "/bin/sh", "--", "sh", dest])
        print("OK  dev tools installed")


# "coder essentials" installed inside a VM: python, pip/venv, git, node, compilers, editors, CLI basics
DEV_LINUX = r'''set -x
if command -v apt-get >/dev/null; then export DEBIAN_FRONTEND=noninteractive; apt-get update
  apt-get install -y python3 python3-pip python3-venv git curl wget build-essential nodejs npm vim htop unzip
elif command -v dnf >/dev/null; then dnf install -y python3 python3-pip git curl wget gcc gcc-c++ make nodejs npm vim htop unzip
elif command -v pacman >/dev/null; then pacman -Sy --noconfirm --needed python python-pip git curl wget base-devel nodejs npm vim htop unzip
elif command -v zypper >/dev/null; then zypper -n install python3 python3-pip git curl wget gcc gcc-c++ make nodejs npm vim htop unzip
elif command -v apk >/dev/null; then apk add python3 py3-pip git curl wget build-base nodejs npm vim htop unzip
fi
command -v snap >/dev/null && snap install code --classic
echo MULTIT-DEVTOOLS-DONE
'''
# ponytail: Chocolatey because winget doesn't work as SYSTEM (unattended post-install runs as SYSTEM)
DEV_WINDOWS = r'''$p = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) -and $PSCommandPath) {
  Start-Process powershell -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""; exit
}
Start-Transcript C:\multit-devtools.log -Append
if (-not (Get-Command choco -ErrorAction SilentlyContinue)) {
  Set-ExecutionPolicy Bypass -Scope Process -Force
  [Net.ServicePointManager]::SecurityProtocol = 3072
  Invoke-Expression ((New-Object Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))
  $env:Path += ";$env:ProgramData\chocolatey\bin"
}
choco install -y --no-progress python git vscode nodejs-lts 7zip
Write-Output MULTIT-DEVTOOLS-DONE
Stop-Transcript
'''
PS_EXE = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"


def dev_password(a):
    if not a.password:
        sys.exit("vm devtools needs the guest login: --user USER --password PASSWORD")
    return a.password


def dev_script(win, pw):
    """-> (local script file, guest folder to copy it into)"""
    local = Path(tempfile.mkdtemp(prefix="multit_")) / ("multit-dev.ps1" if win else "multit-run.sh")
    local.write_text(DEV_WINDOWS if win else dev_linux_wrapper(pw), encoding="utf-8", newline="\n")
    return local, (r"C:\Users\Public" if win else "/tmp")


def dev_linux_wrapper(pw):
    """Shell script copied into a Linux guest: runs DEV_LINUX as root (sudo with the guest password), logs, cleans up."""
    pw64 = base64.b64encode(pw.encode()).decode()
    return (f"#!/bin/sh\ncat > /tmp/multit-dev.sh <<'MTEOF'\n{DEV_LINUX}MTEOF\n"
            f'{{ if [ "$(id -u)" = 0 ]; then sh /tmp/multit-dev.sh; else echo {pw64} | base64 -d | sudo -S sh /tmp/multit-dev.sh; fi; }} '
            f"2>&1 | tee /tmp/multit-devtools.log\nrm -f /tmp/multit-dev.sh \"$0\"\n")


def vm_create(vb, a):
    n = a.name
    if not a.iso or not Path(a.iso).is_file():
        sys.exit("vm create needs --iso PATH_TO_ISO")
    iso = Path(a.iso).resolve()
    det = run([vb, "unattended", "detect", "--iso", iso, "--machine-readable"], check=False, capture=True).stdout
    m = re.search(r'OSTypeId="([^"]+)"', det)
    ostype = m.group(1) if m else "Other_64"
    print(f"detected OS type: {ostype}")
    run([vb, "createvm", "--name", n, "--ostype", ostype, "--register"])
    mods = ["--memory", a.mem, "--cpus", a.cpus, "--vram", "128", "--nic1", "nat", "--ioapic", "on",
            "--graphicscontroller", "vboxsvga" if ostype.startswith("Windows") else "vmsvga",
            "--clipboard-mode", "bidirectional", "--draganddrop", "bidirectional"]
    if ostype.startswith("Windows11"):
        mods += ["--firmware", "efi", "--tpm-type", "2.0"]
    run([vb, "modifyvm", n, *mods])
    cfg = re.search(r'CfgFile="([^"]+)"', run([vb, "showvminfo", n, "--machinereadable"], capture=True).stdout).group(1)
    disk = Path(cfg).parent / f"{n}.vdi"
    run([vb, "createmedium", "disk", "--filename", disk, "--size", a.disk * 1024])
    run([vb, "storagectl", n, "--name", "SATA", "--add", "sata", "--controller", "IntelAhci", "--portcount", "2"])
    run([vb, "storageattach", n, "--storagectl", "SATA", "--port", "0", "--device", "0", "--type", "hdd", "--medium", disk])
    start = "headless" if a.headless else "gui"
    if ostype == "Other_64" or a.manual:
        run([vb, "storageattach", n, "--storagectl", "SATA", "--port", "1", "--device", "0", "--type", "dvddrive", "--medium", iso])
        run([vb, "startvm", n, "--type", start])
        print("\nVM started from ISO - finish the OS install in the window.")
        return
    pw = a.password or secrets.token_urlsafe(9)
    post = []
    if a.dev:  # runs once at the end of the OS install, as SYSTEM / root
        if ostype.startswith("Windows"):
            enc = base64.b64encode(DEV_WINDOWS.encode("utf-16-le")).decode()
            post = [f"--post-install-command=powershell -NoProfile -ExecutionPolicy Bypass -EncodedCommand {enc}"]
        else:
            post = [f"--post-install-command=sh -c 'echo {base64.b64encode(DEV_LINUX.encode()).decode()} | base64 -d | sh > /var/log/multit-devtools.log 2>&1'"]
    run([vb, "unattended", "install", n, "--iso", iso, "--user", a.user, "--password", pw,
         "--install-additions", *post, f"--start-vm={start}"])
    print(f"\nVM '{n}' is installing unattended. Login:  {a.user} / {pw}")
    if a.dev:
        print("Python + dev essentials will be installed automatically at the end of the OS install.")


# ---------------------------------------------------------------- ISO catalog

ISO_DIR = Path.home() / "Downloads" / "ISOs"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) MultiT"}
_H = r're:href="({})"'
# key: (label, vmware guestOS, steps). Plain steps are joined onto the URL; "re:" steps are matched against the
# current page and the highest version wins, so new releases are picked up without code changes.
# ponytail: scraped from mirror listings; when a site changes layout, fix that one entry
ISOS = {
    "ubuntu": ("Ubuntu Desktop LTS", "ubuntu-64", ["https://releases.ubuntu.com/", _H.format(r"\d[02468]\.04/"), _H.format(r"ubuntu-[\d.]+-desktop-amd64\.iso")]),
    "ubuntu-server": ("Ubuntu Server LTS", "ubuntu-64", ["https://releases.ubuntu.com/", _H.format(r"\d[02468]\.04/"), _H.format(r"ubuntu-[\d.]+-live-server-amd64\.iso")]),
    "debian": ("Debian (netinst)", "debian12-64", ["https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/", _H.format(r"debian-[\d.]+-amd64-netinst\.iso")]),
    "fedora": ("Fedora Workstation", "fedora-64", ["https://mirrors.kernel.org/fedora/releases/", _H.format(r"\d+/"), "Workstation/x86_64/iso/", _H.format(r"Fedora-Workstation-Live[\w.-]*\.iso")]),
    "mint": ("Linux Mint Cinnamon", "ubuntu-64", ["https://mirrors.edge.kernel.org/linuxmint/stable/", _H.format(r"\d+(?:\.\d+)?/"), _H.format(r"linuxmint-[\d.]+-cinnamon-64bit\.iso")]),
    "kali": ("Kali Linux", "debian12-64", ["https://cdimage.kali.org/current/", _H.format(r"kali-linux-[\d.]+[a-z]?-installer-amd64\.iso")]),
    "arch": ("Arch Linux", "other6xlinux-64", ["https://geo.mirror.pkgbuild.com/iso/latest/", _H.format(r"archlinux-[\d.]+-x86_64\.iso")]),
    "manjaro": ("Manjaro KDE", "other6xlinux-64", ["https://manjaro.org/products/download/x86", r"re:(https://download\.manjaro\.org/kde/[^\"'\s]+?\.iso)"]),
    "opensuse": ("openSUSE Tumbleweed", "opensuse-64", ["https://download.opensuse.org/tumbleweed/iso/openSUSE-Tumbleweed-DVD-x86_64-Current.iso"]),
    "rocky": ("Rocky Linux (minimal)", "rhel9-64", ["https://download.rockylinux.org/pub/rocky/", _H.format(r"\d+/"), "isos/x86_64/", _H.format(r"Rocky-[\d.]+-x86_64-minimal\.iso")]),
    "alma": ("AlmaLinux (minimal)", "rhel9-64", ["https://repo.almalinux.org/almalinux/", _H.format(r"\d+/"), "isos/x86_64/", _H.format(r"AlmaLinux-[\d.]+-x86_64-minimal\.iso")]),
    "centos": ("CentOS Stream", "rhel9-64", ["https://mirror.stream.centos.org/", _H.format(r"\d+-stream/"), "BaseOS/x86_64/iso/", _H.format(r"CentOS-Stream-\d+-latest-x86_64-dvd1\.iso")]),
    "alpine": ("Alpine Linux", "other6xlinux-64", ["https://dl-cdn.alpinelinux.org/alpine/latest-stable/releases/x86_64/", _H.format(r"alpine-standard-[\d.]+-x86_64\.iso")]),
    "freebsd": ("FreeBSD", "freebsd-64", ["https://download.freebsd.org/releases/amd64/amd64/ISO-IMAGES/", _H.format(r"\d+\.\d+/"), _H.format(r"FreeBSD-[\d.]+-RELEASE-amd64-disc1\.iso")]),
    "popos": ("Pop!_OS", "ubuntu-64", ["https://api.pop-os.org/builds/24.04/generic", r're:"url":"([^"]+\.iso)"']),
    "nixos": ("NixOS Graphical", "other6xlinux-64", ["https://nixos.org/download/", r"re:(https://channels\.nixos\.org/nixos-[\d.]+/latest-nixos-graphical-x86_64-linux\.iso)"]),
    "proxmox": ("Proxmox VE", "debian12-64", ["https://enterprise.proxmox.com/iso/", r're:href="\./(proxmox-ve_[\d.-]+\.iso)"']),
    "windows11": ("Windows 11 Enterprise (90-day eval)", "windows11-64", ["https://go.microsoft.com/fwlink/?linkid=2289031&clcid=0x409&culture=en-us&country=us"]),
    "windows10": ("Windows 10 Enterprise (90-day eval)", "windows9-64", ["https://go.microsoft.com/fwlink/p/?LinkID=2208844&clcid=0x409&culture=en-us&country=US"]),
    "windows-server": ("Windows Server 2025 (180-day eval)", "windows2019srvnext-64", ["https://go.microsoft.com/fwlink/?linkid=2293312&clcid=0x409&culture=en-us&country=us"]),
}


def natkey(s):
    return tuple(int(x) for x in re.findall(r"\d+", s))


def iso_url(key):
    steps = ISOS[key][2]
    url = steps[0]
    for s in steps[1:]:
        if not s.startswith("re:"):
            url = urljoin(url, s)
            continue
        with urlopen(Request(url, headers=UA), timeout=30) as r:
            url, page = r.geturl(), r.read().decode("utf-8", "ignore")
        hits = set(re.findall(s[3:], page))
        if not hits:
            sys.exit(f"couldn't find the {key} download on {url} (site changed?) - pass --iso with a local file instead")
        url = urljoin(url if url.endswith("/") else url + "/", max(hits, key=natkey))
    return url


def fetch_iso(key):
    """Download (or reuse) the latest ISO for a catalog key; resumes a broken download."""
    print(f"looking up latest {ISOS[key][0]} ...")
    url = iso_url(key)
    r = urlopen(Request(url, headers=UA), timeout=60)
    name = unquote(Path(urlparse(r.geturl()).path).name)
    dest = ISO_DIR / (name if name.lower().endswith(".iso") else f"{key}.iso")
    if dest.exists():
        r.close()
        print(f"already downloaded: {dest}")
        return dest
    ISO_DIR.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    done = part.stat().st_size if part.exists() else 0
    if done:
        final = r.geturl()
        r.close()
        r = urlopen(Request(final, headers={**UA, "Range": f"bytes={done}-"}), timeout=60)
        if r.status != 206:  # server ignored the range -> start over
            done = 0
    total = done + int(r.headers.get("Content-Length") or 0)
    print(f"downloading {dest.name}\n  from {r.geturl()}")
    with r, open(part, "ab" if done else "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
            done += len(chunk)
            print(f"\r  {done / 1e9:.2f} / {total / 1e9:.2f} GB  ({done * 100 // max(total, 1)}%)", end="", flush=True)
    print()
    part.rename(dest)
    return dest


def cmd_iso(a):
    if a.action == "list":
        for k, (label, _, _) in ISOS.items():
            print(f"  {k:<15} {label}")
        print(f"\ndownloads go to {ISO_DIR}")
    elif a.action == "url":
        print(iso_url(a.os))
    else:
        print(f"\nOK  {fetch_iso(a.os)}")


VMWARE_DIR = Path.home() / "Documents" / "Virtual Machines"
# ponytail: guest OS guessed from the ISO filename; pass --os <vmware guestOS id> when it guesses wrong
VMWARE_GUESTS = [("win11", "windows11-64"), ("windows11", "windows11-64"), ("win10", "windows9-64"), ("windows10", "windows9-64"),
                 ("ubuntu", "ubuntu-64"), ("mint", "ubuntu-64"), ("debian", "debian12-64"), ("kali", "debian12-64"),
                 ("fedora", "fedora-64"), ("rhel", "rhel9-64"), ("rocky", "rhel9-64"), ("alma", "rhel9-64"), ("linux", "other6xlinux-64")]


def vmx_text(name, iso, guest, mem, cpus):
    cfg = {".encoding": "UTF-8", "config.version": "8", "virtualHW.version": "19", "displayName": name, "guestOS": guest,
           "memsize": mem, "numvcpus": cpus, "firmware": "efi",
           "nvme0.present": "TRUE", "nvme0:0.present": "TRUE", "nvme0:0.fileName": f"{name}.vmdk",
           "sata0.present": "TRUE", "sata0:1.present": "TRUE", "sata0:1.deviceType": "cdrom-image", "sata0:1.fileName": iso,
           "sata0:1.startConnected": "TRUE",
           "ethernet0.present": "TRUE", "ethernet0.connectionType": "nat", "ethernet0.virtualDev": "e1000e",
           "ethernet0.addressType": "generated", "usb.present": "TRUE", "ehci.present": "TRUE", "usb_xhci.present": "TRUE",
           "sound.present": "TRUE", "sound.autoDetect": "TRUE", "sound.virtualDev": "hdaudio", "mks.enable3d": "TRUE",
           "tools.syncTime": "TRUE"}
    if guest.startswith("windows11"):
        cfg["managedvm.autoAddVTPM"] = "software"  # Win11 needs a TPM; Workstation 17.5+ adds one without full encryption
    return "".join(f'{k} = "{v}"\n' for k, v in cfg.items())


def cmd_vm_vmware(a):
    vr = vmrun()
    if not vr:
        sys.exit("VMware Workstation is not installed. Run:  multit vm setup --vmware")
    if a.action == "list":
        print("VMs in", VMWARE_DIR)
        for v in sorted(VMWARE_DIR.glob("*/*.vmx")):
            print("  " + v.stem)
        print(run([vr, "list"], capture=True).stdout)
        return
    if not a.name:
        sys.exit(f"vm {a.action} needs a NAME")
    vmx = Path(a.name) if a.name.endswith(".vmx") else VMWARE_DIR / a.name / f"{a.name}.vmx"
    if a.action != "create" and not vmx.exists():  # match existing VMs by folder or .vmx name
        vmx = next((v for v in VMWARE_DIR.glob("*/*.vmx") if a.name.lower() in (v.stem.lower(), v.parent.name.lower())), vmx)
    if a.action != "create" and not vmx.exists():
        sys.exit(f"no such VM: {vmx}")
    if a.action == "start":
        run([vr, "-T", "ws", "start", vmx, "nogui" if a.headless else "gui"])
    elif a.action == "stop":
        run([vr, "-T", "ws", "stop", vmx, "hard" if a.force else "soft"])
    elif a.action == "snap":
        run([vr, "-T", "ws", "snapshot", vmx, a.label or "snap"])
    elif a.action == "restore":
        run([vr, "-T", "ws", "revertToSnapshot", vmx, a.label or "snap"])
    elif a.action == "delete":
        if not a.yes and input(f"Delete VM '{vmx.stem}' and its disk? type the name to confirm: ") != vmx.stem:
            sys.exit("cancelled")
        run([vr, "-T", "ws", "stop", vmx, "hard"], check=False, capture=True)
        run([vr, "-T", "ws", "deleteVM", vmx])
    elif a.action == "create":
        if not a.iso or not Path(a.iso).is_file():
            sys.exit("vm create needs --iso PATH_TO_ISO")
        if vmx.exists():
            sys.exit(f"VM already exists: {vmx}")
        iso = Path(a.iso).resolve()
        guest = a.os or next((g for k, g in VMWARE_GUESTS if k in iso.name.lower()), "other-64")
        print(f"guest OS: {guest}")
        vmx.parent.mkdir(parents=True)
        run([vr.parent / "vmware-vdiskmanager.exe", "-c", "-s", f"{a.disk}GB", "-a", "lsilogic", "-t", "0", vmx.parent / f"{vmx.stem}.vmdk"])
        vmx.write_text(vmx_text(vmx.stem, iso, guest, a.mem, a.cpus), encoding="utf-8")
        run([vr, "-T", "ws", "start", vmx, "nogui" if a.headless else "gui"])
        print(f"\nVM '{vmx.stem}' booting from ISO - finish the OS install in the window.\n  {vmx}")
        if a.dev:
            print("\ndev tools: VMware can't inject them during a manual install. Once the OS is installed and you're\n"
                  f"logged in (with VMware Tools), click 'dev tools' on the VM or run:\n"
                  f"  multit vm devtools \"{vmx.parent.name}\" --vmware --user <guest user> --password <guest password>")
    elif a.action == "devtools":
        guest = re.search(r'guestOS\s*=\s*"([^"]*)"', vmx.read_text(errors="ignore"))
        win = bool(guest and guest.group(1).startswith("windows"))
        auth = [vr, "-T", "ws", "-gu", a.user, "-gp", dev_password(a)]
        local, gdir = dev_script(win, a.password)
        dest = gdir + ("\\" if win else "/") + local.name
        run([*auth, "CopyFileFromHostToGuest", vmx, local, dest])
        print("installing inside the VM - this takes a few minutes. Log in the guest: " +
              (r"C:\multit-devtools.log  (accept the admin prompt in the VM window)" if win else "/tmp/multit-devtools.log"), flush=True)
        if win:  # -interactive: on the user's desktop so the UAC prompt can be accepted
            run([*auth, "runProgramInGuest", vmx, "-interactive", PS_EXE, f"-NoProfile -ExecutionPolicy Bypass -File {dest}"])
        else:
            run([*auth, "runProgramInGuest", vmx, "/bin/sh", dest])
        print("OK  dev tools install finished (see the log in the guest)")


# ---------------------------------------------------------------- disk cleanup (like Windows Disk Cleanup + dev caches)

_E = lambda k, d="": Path(os.environ.get(k, d))
LOCAL, ROAM, PDATA, WINDIR, HOME = _E("LOCALAPPDATA"), _E("APPDATA"), _E("ProgramData", r"C:\ProgramData"), _E("SystemRoot", r"C:\Windows"), Path.home()
_CHROMIUM = [LOCAL / "Google/Chrome/User Data", LOCAL / "Microsoft/Edge/User Data", LOCAL / "BraveSoftware/Brave-Browser/User Data",
             LOCAL / "AVAST Software/Browser/User Data", LOCAL / "Vivaldi/User Data", LOCAL / "Opera Software/Opera Stable"]
# key: (label, group, on by default, needs admin, [folders/files, globs allowed]). Folder CONTENTS are deleted, the folder stays.
JUNK = {
    "temp": ("Temporary files", "System", True, False, [LOCAL / "Temp"]),
    "wintemp": ("Windows temp", "System", True, True, [WINDIR / "Temp"]),
    "update": ("Windows Update downloads", "System", True, True, [WINDIR / "SoftwareDistribution/Download"]),
    "delivery": ("Delivery Optimization cache", "System", True, True,
                 [WINDIR / "ServiceProfiles/NetworkService/AppData/Local/Microsoft/Windows/DeliveryOptimization/Cache"]),
    "crash": ("Crash dumps & error reports", "System", True, False,
              [LOCAL / "CrashDumps", WINDIR / "Minidump", PDATA / "Microsoft/Windows/WER/ReportArchive",
               PDATA / "Microsoft/Windows/WER/ReportQueue", LOCAL / "Microsoft/Windows/WER"]),
    "thumbs": ("Thumbnail & icon cache", "System", True, False,
               [LOCAL / "Microsoft/Windows/Explorer/thumbcache_*.db", LOCAL / "Microsoft/Windows/Explorer/iconcache_*.db"]),
    "shaders": ("GPU shader caches", "System", True, False,
                [LOCAL / "D3DSCache", LOCAL / "NVIDIA/DXCache", LOCAL / "NVIDIA/GLCache", LOCAL / "AMD/DxCache", LOCAL / "AMD/DxcCache"]),
    "recycle": ("Recycle Bin", "System", False, False, []),
    "browsers": ("Browser caches", "Apps", True, False,
                 [b / "*" / c for b in _CHROMIUM for c in ("Cache", "Code Cache", "GPUCache")]
                 + [b / c for b in _CHROMIUM for c in ("Cache", "Code Cache", "GPUCache")]  # Opera keeps them at the top level
                 + [LOCAL / "Mozilla/Firefox/Profiles/*/cache2"]),
    "apps": ("App caches (Discord, Spotify, Steam, Teams)", "Apps", True, False,
             [ROAM / "discord" / c for c in ("Cache", "Code Cache", "GPUCache")]
             + [LOCAL / "Spotify/Storage", LOCAL / "Steam/htmlcache", ROAM / "Microsoft/Teams/Cache", LOCAL / "Packages/MSTeams_8wekyb3d8bbwe/LocalCache"]),
    "pip": ("pip cache", "Dev", True, False, [LOCAL / "pip/cache"]),
    "npm": ("npm / yarn / pnpm caches", "Dev", True, False, [LOCAL / "npm-cache", LOCAL / "Yarn/Cache", LOCAL / "pnpm-cache"]),
    "gobuild": ("Go build cache", "Dev", True, False, [LOCAL / "go-build"]),
    "cargo": ("Cargo download cache", "Dev", True, False, [HOME / ".cargo/registry/cache"]),
    "nuget": ("NuGet HTTP cache", "Dev", True, False, [LOCAL / "NuGet/v3-cache", LOCAL / "NuGet/Cache"]),
    "pyinstaller": ("PyInstaller cache", "Dev", True, False, [LOCAL / "pyinstaller"]),
    "gradle": ("Gradle caches (re-downloads on next build)", "Dev", False, False, [HOME / ".gradle/caches"]),
    "isos": ("MultiT ISO downloads", "Other", False, False, [ISO_DIR]),
}
_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def _is_link(path):
    st = os.lstat(path)
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & _REPARSE)


def _targets(key):
    for pat in JUNK[key][4]:
        yield from glob.glob(str(pat))


def _size(path):
    try:
        if not os.path.isdir(path) or _is_link(path):
            return os.lstat(path).st_size if os.path.isfile(path) else 0
        return sum(_size(e.path) for e in os.scandir(path))
    except OSError:
        return 0


def _wipe(path):
    """Delete a file, or everything inside a folder. Never follows links/junctions, skips files in use. -> bytes freed"""
    if os.path.isfile(path) and not _is_link(path):
        size = os.path.getsize(path)
        try:
            os.unlink(path)
        except PermissionError:
            try:
                os.chmod(path, stat.S_IWRITE)
                os.unlink(path)
            except OSError:
                return 0
        except OSError:
            return 0
        return size
    freed = 0
    try:
        entries = list(os.scandir(path))
    except OSError:
        return 0
    for e in entries:
        try:
            if _is_link(e.path):  # unlink the link itself, never its target
                os.rmdir(e.path) if e.is_dir() else os.unlink(e.path)
            elif e.is_dir(follow_symlinks=False):
                freed += _wipe(e.path)
                os.rmdir(e.path)
            else:
                freed += _wipe(e.path)
        except OSError:
            pass  # in use / no permission: leave it
    return freed


class _RBInfo(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint32), ("i64Size", ctypes.c_int64), ("i64NumItems", ctypes.c_int64)]


def _recycle_size():
    info = _RBInfo(ctypes.sizeof(_RBInfo))
    return info.i64Size if ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info)) == 0 else 0


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def junk_scan():
    out = []
    for k, (label, group, default, admin, _) in JUNK.items():
        size = _recycle_size() if k == "recycle" else sum(_size(t) for t in _targets(k))
        out.append({"key": k, "label": label, "group": group, "default": default, "admin": admin, "size": size})
    return out


def human(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{n:.1f} {u}" if u != "B" else f"{n} B"
        n /= 1024


def cmd_cleanup(a):
    if not a.keys and not a.all:
        items = junk_scan()
        for i in items:
            print(f"  {'*' if i['default'] else ' '} {i['key']:<12} {human(i['size']):>10}  {i['label']}" + ("  [admin]" if i["admin"] else ""))
        print(f"\n  total {human(sum(i['size'] for i in items))}   (* = cleaned by --all)\n  clean: multit cleanup KEY [KEY...]  or  multit cleanup --all")
        return
    if bad := set(a.keys) - set(JUNK):
        sys.exit(f"unknown category: {', '.join(bad)}  (known: {', '.join(JUNK)})")
    keys = [k for k, v in JUNK.items() if v[2]] if a.all else a.keys
    if not is_admin() and any(JUNK[k][3] for k in keys):
        print("note: not running as admin - Windows-owned files will be skipped\n")
    total = 0
    for k in keys:
        if k == "recycle":
            before = _recycle_size()
            ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0x7)  # no confirm / progress / sound
            freed = before - _recycle_size()
        else:
            freed = sum(_wipe(t) for t in _targets(k))
            left = sum(_size(t) for t in _targets(k))
        total += freed
        print(f"  {JUNK[k][0]:<46} freed {human(freed):>10}" + (f"   ({human(left)} in use, skipped)" if k != "recycle" and left > 1 << 20 else ""), flush=True)
    free = shutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\").free
    print(f"\nOK  freed {human(total)}  ·  {human(free)} free on {os.environ.get('SystemDrive', 'C:')}")


# ---------------------------------------------------------------- disk map (WinDirStat-style treemap data)

# drive-root entries that belong to Windows / installed programs: hidden from the map and never deletable
PROTECTED = {"windows", "program files", "program files (x86)", "programdata", "recovery", "system volume information",
             "$recycle.bin", "boot", "perflogs", "$windows.~bt", "$windows.~ws", "$winreagent", "msocache", "config.msi",
             "documents and settings", "pagefile.sys", "hiberfil.sys", "swapfile.sys", "dumpstack.log.tmp", "bootmgr", "bootnxt"}
_FT = {"v": "mp4 mkv avi mov wmv webm flv m4v mpg mpeg ts", "i": "jpg jpeg png gif bmp webp tif tiff heic raw cr2 nef psd svg ico",
       "a": "mp3 wav flac aac ogg m4a wma opus", "z": "zip rar 7z tar gz tgz bz2 xz zst cab",
       "x": "exe dll msi sys ocx appx msix", "c": "py js ts jsx tsx c cpp h hpp cs java go rs rb php html css json xml yml yaml md sh ps1 bat ipynb",
       "d": "pdf doc docx xls xlsx ppt pptx txt rtf odt csv epub", "g": "iso img vhd vhdx vmdk vdi qcow2 vmem vmsn nvram wim esd",
       "m": "gguf safetensors ckpt pt pth onnx h5 tflite pb", "p": "pak bin dat db sqlite blob cache log tmp bak"}
FILE_TYPE = {e: t for t, exts in _FT.items() for e in exts.split()}  # anything else -> "o"
_SYSTEM_ATTR = 0x4
# sparse | compressed | offline | recall-on-open | recall-on-data-access (cloud placeholders): logical size lies
_SIZE_LIES = 0x200 | 0x800 | 0x1000 | 0x40000 | 0x400000


def disk_size(path, st):
    """Bytes the file really takes on disk (a sparse 550 GB emulator image may use 20 GB; OneDrive placeholders ~0)."""
    if not getattr(st, "st_file_attributes", 0) & _SIZE_LIES:
        return st.st_size
    f = ctypes.windll.kernel32.GetCompressedFileSizeW
    f.restype = ctypes.c_ulong  # DWORD; the default (signed int) turns 3.9 GB negative
    hi = ctypes.c_ulong(0)
    lo = f(str(path), ctypes.byref(hi))
    return st.st_size if lo == 0xFFFFFFFF and ctypes.GetLastError() else (hi.value << 32) + lo


def is_protected(path):
    """True for OS / program locations and for paths too broad to delete
    (drive roots, C:\\Users, any profile, and the profile's top folders like Desktop / Documents / AppData)."""
    p, home = Path(os.path.abspath(path)), Path.home()
    if len(p.parts) <= 1 or p == home.parent or p.parent == home.parent or p.parent == home:
        return True
    return len(p.parts) >= 2 and p.parts[1].lower() in PROTECTED


def disk_map(root, show_system=False, progress=None, small=1 << 20, max_nodes=30000):
    """Scan `root` -> nested {n: name, s: bytes, c: [children]} | leaf {n, s, t: type[, a: aggregated][, k: collapsed folder]}.
    Files < `small` are merged per folder & type; the finished tree is pruned to ~max_nodes for drawing."""
    import time
    root = os.path.abspath(root)
    stats = {"files": 0, "last": time.time()}

    def walk(path, name, top):
        node, agg = {"n": name, "s": 0, "c": []}, {}
        try:
            it = os.scandir(path)
        except OSError:
            return node
        with it:
            for e in it:
                try:
                    st = e.stat(follow_symlinks=False)
                    attrs = getattr(st, "st_file_attributes", 0)
                    if attrs & _REPARSE:
                        continue  # junctions/symlinks: would double count or loop
                    if not show_system and ((attrs & _SYSTEM_ATTR) or (top and e.name.lower() in PROTECTED)):
                        continue
                    if e.is_dir(follow_symlinks=False):
                        child = walk(e.path, e.name, False)
                    else:
                        stats["files"] += 1
                        t = FILE_TYPE.get(e.name.rsplit(".", 1)[-1].lower() if "." in e.name else "", "o")
                        size = disk_size(e.path, st)
                        if size < small:
                            c, s = agg.get(t, (0, 0))
                            agg[t] = (c + 1, s + size)
                            continue
                        child = {"n": e.name, "s": size, "t": t}
                except OSError:
                    continue
                node["c"].append(child)
                node["s"] += child["s"]
        for t, (c, s) in agg.items():
            node["c"].append({"n": f"{c:,} small file{'s' * (c > 1)}", "s": s, "t": t, "a": 1})
            node["s"] += s
        if progress and time.time() - stats["last"] > 0.25:
            stats["last"] = time.time()
            progress(stats["files"], path)
        return node

    tree = walk(root, root, Path(root).parent == Path(root))
    cutoff = tree["s"] / max_nodes

    def dominant(n, acc):
        if "c" in n:
            for ch in n["c"]:
                dominant(ch, acc)
        else:
            acc[n["t"]] = acc.get(n["t"], 0) + n["s"]
        return acc

    def prune(n):
        keep, merged = [], {}
        for ch in n["c"]:
            if ch["s"] >= cutoff:
                if "c" in ch:
                    prune(ch)
                keep.append(ch)
            elif "c" in ch and ch["s"] > 0:  # small folder -> one solid block, still a real path
                d = dominant(ch, {})
                keep.append({"n": ch["n"], "s": ch["s"], "t": max(d, key=d.get) if d else "o", "k": 1})
            elif ch["s"] > 0:
                c, s = merged.get(ch.get("t", "o"), (0, 0))
                merged[ch.get("t", "o")] = (c + 1, s + ch["s"])
        keep += [{"n": f"{c:,} more item{'s' * (c > 1)}", "s": s, "t": t, "a": 1} for t, (c, s) in merged.items()]
        n["c"] = sorted(keep, key=lambda x: -x["s"])

    prune(tree)
    return {"root": root, "tree": tree, "files": stats["files"]}


def recycle(path):
    """Move a file/folder to the Recycle Bin (undoable). Refuses OS/program locations."""
    if is_protected(path):
        raise ValueError(f"refusing to delete a protected location: {path}")
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
                    ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL), ("hNameMappings", ctypes.c_void_p),
                    ("lpszProgressTitle", wintypes.LPCWSTR)]
    # FO_DELETE + ALLOWUNDO | NOCONFIRMATION | SILENT | NOERRORUI; pFrom must be double-null terminated
    op = SHFILEOPSTRUCTW(wFunc=3, pFrom=os.path.abspath(path) + "\0", fFlags=0x40 | 0x10 | 0x4 | 0x400)
    return ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) == 0 and not op.fAnyOperationsAborted


def cmd_du(a):
    r = disk_map(a.path, a.system, progress=lambda n, p: print(f"\r  scanning... {n:,} files", end="", flush=True))
    print(f"\r  {r['files']:,} files, {human(r['tree']['s'])} in {r['root']}" + ("" if a.system else "  (system & program folders hidden)"))
    for ch in r["tree"]["c"][:a.top]:
        print(f"  {human(ch['s']):>10}  {ch['n']}{os.sep if 'c' in ch or 'k' in ch else ''}")


def cmd_venv(a):
    root = Path(a.path).resolve()
    py = project_venv(root)
    if not py:
        run([python_exe(), "-m", "venv", root / ".venv"])
        py = root / ".venv" / "Scripts" / "python.exe"
    run([py, "-m", "pip", "install", "-q", "--upgrade", "pip"])
    if (root / "requirements.txt").exists():
        run([py, "-m", "pip", "install", "-r", root / "requirements.txt"])
    elif (root / "pyproject.toml").exists():
        run([py, "-m", "pip", "install", "-e", root])
    if a.packages:
        run([py, "-m", "pip", "install", *a.packages])
    print(f"\nvenv ready: {py.parent.parent}\n  activate:  {py.parent / 'Activate.ps1'}   (cmd: {py.parent / 'activate.bat'})")


# ---------------------------------------------------------------- utilities

def refresh_path():
    """Merge the registry PATH into ours, so tools installed after MultiT started are found without a restart."""
    try:
        import winreg
        parts = os.environ.get("PATH", "").split(os.pathsep)
        for root, key in ((winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
                          (winreg.HKEY_CURRENT_USER, "Environment")):
            try:
                with winreg.OpenKey(root, key) as k:
                    parts += os.path.expandvars(winreg.QueryValueEx(k, "Path")[0]).split(os.pathsep)
            except OSError:
                pass
        os.environ["PATH"] = os.pathsep.join(dict.fromkeys(p for p in parts if p))
    except ImportError:
        pass


def _found(spec):
    if "\\" in spec or "/" in spec:
        return bool(glob.glob(os.path.expandvars(spec)))
    return bool(shutil.which(spec))


def tool_status():
    refresh_path()
    st = {k: any(_found(d) for d in v[3]) for k, v in TOOLS.items()}
    st["dotnet"] = bool(shutil.which("dotnet")) and bool(run(["dotnet", "--list-sdks"], check=False, capture=True).stdout.strip())
    st["pyinstaller"] = st["python"] and not run([python_exe(), "-m", "PyInstaller", "--version"], check=False, capture=True).returncode
    return st


def cmd_doctor(a):
    st, cat = tool_status(), None
    for k, (name, c, *_) in TOOLS.items():
        if c != cat:
            cat = c
            print(f"\n  {c}")
        print(f"    [{'x' if st[k] else ' '}] {k:<14} {name}")
    print(f"\n  {sum(st.values())}/{len(st)} installed   ·   install: multit install KEY [KEY...]")


def install_tool(key, upgrade=False):
    """-> True on success. winget id, pip for pyinstaller, or opens the download page for tools not on winget."""
    src = TOOLS[key][2]
    if key == "pyinstaller":
        return not run([python_exe(), "-m", "pip", "install", "--user", "--upgrade", "pyinstaller"], check=False).returncode
    if not src:
        print(f"{key}: nothing to install")
        return True
    if src.startswith("http"):
        import webbrowser
        print(f"{TOOLS[key][0]} isn't on winget - opening the official download page:\n  {src}")
        webbrowser.open(src)
        return True
    r = run([need("winget"), "upgrade" if upgrade else "install", "-e", "--id", src, "--silent",
             "--accept-package-agreements", "--accept-source-agreements", "--disable-interactivity"], check=False)
    if upgrade and r.returncode == -1978335189:  # APPINSTALLER_CLI_ERROR_UPDATE_NOT_APPLICABLE
        print(f"{key}: already up to date")
        return True
    return r.returncode == 0


def winget(pkg_id):  # kept for `vm setup`
    key = next(k for k, v in TOOLS.items() if v[2] == pkg_id)
    if not install_tool(key):
        sys.exit(f"install of {key} failed")


def cmd_install(a):
    if bad := set(a.tools) - set(TOOLS):
        sys.exit(f"unknown tool: {', '.join(bad)}  (see: multit doctor)")
    failed = []
    for i, k in enumerate(a.tools, 1):
        print(f"\n[{i}/{len(a.tools)}] {'updating' if a.update else 'installing'} {TOOLS[k][0]}", flush=True)
        if not install_tool(k, a.update):
            failed.append(k)
    if failed:
        sys.exit(f"\nfailed: {', '.join(failed)}")
    print(f"\nOK  {len(a.tools)} tool(s) {'updated' if a.update else 'installed'}. Open a new terminal to use them.")


def cmd_ports(a):
    names = {}
    for line in run(["tasklist", "/FO", "CSV", "/NH"], capture=True).stdout.splitlines():
        parts = line.strip('"').split('","')
        if len(parts) > 1:
            names[parts[1]] = parts[0]
    rows = set()
    for line in run(["netstat", "-ano"], capture=True).stdout.splitlines():
        f = line.split()
        if len(f) == 5 and f[3] == "LISTENING":
            port = f[1].rsplit(":", 1)[1]
            if a.port is None or port == str(a.port):
                rows.add((int(port), f[4]))
    if not rows:
        print("nothing listening" + (f" on {a.port}" if a.port else ""))
    for port, pid in sorted(rows):
        print(f"  {port:>6}  pid {pid:>6}  {names.get(pid, '?')}")
    if a.kill:
        if a.port is None:
            sys.exit("--kill needs a PORT")
        for pid in {pid for _, pid in rows}:
            run(["taskkill", "/PID", pid, "/F"], check=False)


def cmd_serve(a):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(Path(a.dir).resolve()))
    with http.server.ThreadingHTTPServer(("0.0.0.0", a.port), handler) as s:
        print(f"serving {Path(a.dir).resolve()}\n  http://localhost:{a.port}\n  http://{socket.gethostbyname(socket.gethostname())}:{a.port}  (LAN)\nCtrl+C to stop")
        try:
            s.serve_forever()
        except KeyboardInterrupt:
            pass


def cmd_hash(a):
    hs = {n: hashlib.new(n) for n in ("sha256", "sha1", "md5")}
    with open(a.file, "rb") as f:
        while chunk := f.read(1 << 20):
            for h in hs.values():
                h.update(chunk)
    for n, h in hs.items():
        print(f"{n:>7}  {h.hexdigest()}")
    if a.check:
        ok = a.check.lower().strip() in {h.hexdigest() for h in hs.values()}
        print("MATCH" if ok else "MISMATCH")
        sys.exit(0 if ok else 1)


def cmd_clean(a):
    root = Path(a.path).resolve()
    junk = []
    for d, dirs, files in os.walk(root):
        d = Path(d)
        for x in list(dirs):
            sib = set(os.listdir(d))
            if (x in {"__pycache__", ".pytest_cache", ".mypy_cache", "build", "dist"}
                    or (x == "target" and "Cargo.toml" in sib)
                    or (x in {"bin", "obj"} and any(s.endswith(".csproj") for s in sib))):
                junk.append(d / x)
                dirs.remove(x)
            elif x in {".git", "node_modules", "venv", ".venv"}:
                dirs.remove(x)
        junk += [d / f for f in files if f.endswith((".spec", ".pyc"))]
    if not junk:
        print("nothing to clean")
    for j in junk:
        print(("deleting " if a.yes else "would delete ") + str(j))
        if a.yes:
            shutil.rmtree(j) if j.is_dir() else j.unlink()
    if junk and not a.yes:
        print("\nrun again with --yes to delete")


# ---------------------------------------------------------------- system monitor (psutil)

# killing these blue-screens or logs out Windows
CRITICAL_PROCS = {"system", "system idle process", "registry", "secure system", "memory compression", "smss.exe", "csrss.exe",
                  "wininit.exe", "winlogon.exe", "services.exe", "lsass.exe", "lsaiso.exe", "svchost.exe", "fontdrvhost.exe", "dwm.exe"}


_LAST_CPU = None


def _cpu_percents():
    """Per-core busy % since the previous call. psutil.cpu_percent() keeps its baseline per *thread*,
    and the UI calls in from a fresh thread every second -> it would always say 0%."""
    import psutil
    global _LAST_CPU
    prev, _LAST_CPU = _LAST_CPU, psutil.cpu_times(percpu=True)
    if not prev:
        return [0.0] * len(_LAST_CPU)
    out = []
    for a, b in zip(prev, _LAST_CPU):
        total = sum(b) - sum(a)
        busy = total - (b.idle - a.idle)
        out.append(max(0.0, min(100.0, 100 * busy / total)) if total > 0 else 0.0)
    return out


def sys_stats():
    import psutil, time
    vm, d, n = psutil.virtual_memory(), psutil.disk_io_counters(), psutil.net_io_counters()
    cores = _cpu_percents()
    return {"t": time.time(), "cpu": sum(cores) / len(cores), "cores": cores, "ram": vm.percent, "ram_used": vm.used, "ram_total": vm.total,
            "disk_r": d.read_bytes if d else 0, "disk_w": d.write_bytes if d else 0, "net_rx": n.bytes_recv, "net_tx": n.bytes_sent,
            "uptime": time.time() - psutil.boot_time()}


def top_procs(sort="cpu", n=15):
    """Processes grouped by name (chrome.exe x 23 -> one row). CPU % is of the whole machine."""
    import psutil
    ncpu, groups = psutil.cpu_count() or 1, {}
    for p in psutil.process_iter(["pid", "name", "memory_info", "cpu_percent"]):  # psutil caches Process objects -> cpu% works from 2nd call
        i = p.info
        if not i["name"] or i["pid"] == 0:
            continue
        g = groups.setdefault(i["name"], {"name": i["name"], "pids": [], "cpu": 0.0, "mem": 0})
        g["pids"].append(i["pid"])
        g["cpu"] += (i["cpu_percent"] or 0) / ncpu
        g["mem"] += i["memory_info"].rss if i["memory_info"] else 0
    rows = sorted(groups.values(), key=lambda g: -g[sort])[:n]
    for r in rows:
        r["critical"] = r["name"].lower() in CRITICAL_PROCS
    return rows


def kill_procs(name):
    import psutil
    if name.lower() in CRITICAL_PROCS:
        raise ValueError(f"{name} is critical to Windows - killing it would crash or log you out")
    killed = 0
    for p in psutil.process_iter(["name"]):
        if p.info["name"] == name and p.pid != os.getpid():
            try:
                p.kill()
                killed += 1
            except psutil.Error:
                pass
    return killed


def cmd_top(a):
    import time
    top_procs()
    sys_stats()
    time.sleep(1)  # cpu% needs two samples
    s = sys_stats()
    print(f"  CPU {s['cpu']:.0f}%   RAM {s['ram']:.0f}% ({human(s['ram_used'])} / {human(s['ram_total'])})   up {s['uptime'] / 3600:.1f} h\n")
    for r in top_procs(a.sort, a.n):
        print(f"  {r['cpu']:5.1f}%  {human(r['mem']):>10}  {r['name']}" + (f" x{len(r['pids'])}" if len(r["pids"]) > 1 else ""))


# ---------------------------------------------------------------- startup apps (same switch as Task Manager's Startup tab)

_RUNKEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_APPROVED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved"


def _hive(name):
    import winreg
    return {"HKCU": winreg.HKEY_CURRENT_USER, "HKLM": winreg.HKEY_LOCAL_MACHINE}[name]


def _approved(hive, sub, name):
    import winreg
    try:
        with winreg.OpenKey(_hive(hive), f"{_APPROVED}\\{sub}") as k:
            v = winreg.QueryValueEx(k, name)[0]
            return not v or v[0] % 2 == 0  # 02/06 enabled, 03/07 disabled; no entry = enabled
    except OSError:
        return True


def startup_items():
    import winreg
    items = []
    for hive, key, sub, where in (("HKCU", _RUNKEY, "Run", "registry · you"), ("HKLM", _RUNKEY, "Run", "registry · all users"),
                                  ("HKLM", r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run", "Run32", "registry · all users")):
        try:
            with winreg.OpenKey(_hive(hive), key) as k:
                for i in range(winreg.QueryInfoKey(k)[1]):
                    name, cmd, _ = winreg.EnumValue(k, i)
                    items.append({"id": f"{hive}|{sub}|{name}", "name": name, "cmd": str(cmd), "where": where,
                                  "admin": hive == "HKLM", "enabled": _approved(hive, sub, name)})
        except OSError:
            pass
    for hive, folder, where in (("HKCU", ROAM / r"Microsoft\Windows\Start Menu\Programs\Startup", "startup folder · you"),
                                ("HKLM", PDATA / r"Microsoft\Windows\Start Menu\Programs\StartUp", "startup folder · all users")):
        for f in sorted(folder.glob("*")) if folder.is_dir() else []:
            if f.name.lower() != "desktop.ini":
                items.append({"id": f"{hive}|StartupFolder|{f.name}", "name": f.stem, "cmd": str(f), "where": where,
                              "admin": hive == "HKLM", "enabled": _approved(hive, "StartupFolder", f.name)})
    return items


def set_startup(item_id, enabled):
    import struct, time, winreg
    hive, sub, name = item_id.split("|", 2)
    filetime = int((time.time() + 11644473600) * 10 ** 7)
    data = b"\x02" + b"\x00" * 11 if enabled else b"\x03\x00\x00\x00" + struct.pack("<Q", filetime)
    try:
        with winreg.CreateKeyEx(_hive(hive), f"{_APPROVED}\\{sub}", 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_BINARY, data)
    except PermissionError:
        raise ValueError("this one is set for all users - restart MultiT as admin to change it")


def cmd_startup(a):
    items = startup_items()
    if a.action == "list":
        for i in items:
            print(f"  [{'on ' if i['enabled'] else 'off'}] {i['name']:<34} {i['where']}")
        return
    hit = [i for i in items if i["name"].lower() == (a.name or "").lower()]
    if not hit:
        sys.exit(f"no startup item named {a.name!r} (see: multit startup list)")
    for i in hit:
        set_startup(i["id"], a.action == "enable")
    print(f"OK  {a.name} {a.action}d - takes effect next sign-in")


# ---------------------------------------------------------------- PATH doctor

_ENV = {"user": ("HKCU", "Environment"), "system": ("HKLM", r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")}


def _read_path(scope):
    import winreg
    hive, key = _ENV[scope]
    try:
        with winreg.OpenKey(_hive(hive), key) as k:
            return winreg.QueryValueEx(k, "Path")
    except OSError:
        return "", winreg.REG_EXPAND_SZ


def _norm(entry):
    return os.path.normcase(os.path.expandvars(entry.strip().strip('"'))).rstrip("\\/")


def _is_dead(entry):
    """Folder is gone. Unresolved %VARS% and folders on drives that aren't plugged in count as alive (might come back)."""
    p = os.path.expandvars(entry.strip().strip('"'))
    return "%" not in p and os.path.exists(os.path.splitdrive(p)[0] + "\\") and not os.path.isdir(p)


def clean_path(user, system):
    """-> (kept, removed): user PATH without dead folders and entries already in system PATH / earlier in user PATH."""
    seen, kept, removed = {_norm(e) for e in system if e.strip()}, [], []
    for e in user:
        if not e.strip():
            continue
        if _is_dead(e) or _norm(e) in seen:
            removed.append(e)
        else:
            seen.add(_norm(e))
            kept.append(e)
    return kept, removed


def path_entries():
    out, seen = [], set()
    for scope in ("system", "user"):
        for e in _read_path(scope)[0].split(";"):
            if e.strip():
                out.append({"scope": scope, "raw": e, "dead": _is_dead(e), "dup": _norm(e) in seen})
                seen.add(_norm(e))
    return out


def write_user_path(entries):
    """Back up the old user PATH, write the new one, tell Windows (new terminals pick it up)."""
    import time, winreg
    old, kind = _read_path("user")
    backup = LOCAL / "MultiT" / f"path-backup-{time.strftime('%Y%m%d-%H%M%S')}.txt"
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_text(old, encoding="utf-8")
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, "Path", 0, kind if kind in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) else winreg.REG_EXPAND_SZ, ";".join(entries))
    res = ctypes.c_ulong()
    ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x1A, 0, "Environment", 2, 5000, ctypes.byref(res))  # WM_SETTINGCHANGE
    return str(backup)


def path_change(fix=False, add=None, remove=None):
    user = [e for e in _read_path("user")[0].split(";") if e.strip()]
    removed = []
    if fix:
        user, removed = clean_path(user, _read_path("system")[0].split(";"))
    if remove:
        removed += [e for e in user if e == remove]
        user = [e for e in user if e != remove]
    if add and _norm(add) not in {_norm(e) for e in user}:
        user.append(os.path.abspath(add))
    return {"removed": removed, "backup": write_user_path(user)}


def cmd_path(a):
    if a.fix or a.add or a.remove:
        r = path_change(a.fix, a.add, a.remove)
        for e in r["removed"]:
            print(f"  removed  {e}")
        print(f"OK  user PATH updated (open a new terminal). Backup: {r['backup']}")
        return
    for e in path_entries():
        flag = "DEAD" if e["dead"] else "DUP " if e["dup"] else "ok  "
        print(f"  {flag} {e['scope']:<6} {e['raw']}")
    print("\n  clean dead/duplicate user entries:  multit path --fix")


# ---------------------------------------------------------------- duplicate finder

def find_dupes(root, min_size=1 << 20, progress=None):
    """Identical files under root: group by size, then a 64 KB hash, then a full hash. Hardlinks aren't duplicates."""
    import time
    by_size, seen_ids, last, n = {}, set(), time.time(), 0
    root_is_drive = Path(os.path.abspath(root)).parent == Path(os.path.abspath(root))
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if not _is_link(os.path.join(d, x))
                   and not (root_is_drive and d.rstrip("\\") == os.path.abspath(root).rstrip("\\") and x.lower() in PROTECTED)]
        for f in files:
            p = os.path.join(d, f)
            try:
                st = os.stat(p, follow_symlinks=False)
            except OSError:
                continue
            n += 1
            if st.st_size >= min_size and (st.st_dev, st.st_ino) not in seen_ids:
                seen_ids.add((st.st_dev, st.st_ino))
                by_size.setdefault(st.st_size, []).append((p, st.st_mtime))
        if progress and time.time() - last > 0.25:
            last = time.time()
            progress(f"scanning… {n:,} files", d)

    def digest(path, limit=None):
        h = hashlib.blake2b(digest_size=20)
        with open(path, "rb") as fh:
            left = limit or float("inf")
            while left > 0 and (chunk := fh.read(min(1 << 20, left))):
                h.update(chunk)
                left -= len(chunk)
        return h.hexdigest()

    def split(files, limit):
        out = {}
        for p, m in files:
            try:
                out.setdefault(digest(p, limit), []).append((p, m))
            except OSError:
                pass
        return [g for g in out.values() if len(g) > 1]

    groups, cands = [], [(s, f) for s, f in by_size.items() if len(f) > 1]
    for i, (size, files) in enumerate(sorted(cands, key=lambda x: -x[0])):
        if progress and time.time() - last > 0.25:
            last = time.time()
            progress(f"comparing… {i:,}/{len(cands):,} size groups", files[0][0])
        for g in split(files, 65536):
            for full in (split(g, None) if size > 65536 else [g]):
                full.sort(key=lambda x: x[1])  # oldest first = the "original"
                groups.append({"size": size, "wasted": size * (len(full) - 1), "files": [{"path": p, "mtime": m} for p, m in full]})
    groups.sort(key=lambda g: -g["wasted"])
    return {"groups": groups, "files": n}


def cmd_dupes(a):
    r = find_dupes(a.path, int(a.min * (1 << 20)), progress=lambda s, p: print(f"\r  {s}", end="", flush=True))
    print(f"\r  {r['files']:,} files scanned, {len(r['groups'])} duplicate groups, {human(sum(g['wasted'] for g in r['groups']))} wasted")
    for g in r["groups"][:a.top]:
        print(f"\n  {human(g['size'])} x {len(g['files'])}")
        for f in g["files"]:
            print(f"    {f['path']}")


# ---------------------------------------------------------------- git repos dashboard

def find_repos(root, depth=4):
    out = []

    def walk(p, d):
        if (p / ".git").exists():
            out.append(p)
            return  # don't descend into a repo
        if d >= depth:
            return
        try:
            for e in os.scandir(p):
                if e.is_dir(follow_symlinks=False) and e.name not in SKIP_DIRS and not e.name.startswith((".", "$")):
                    walk(Path(e.path), d + 1)
        except OSError:
            pass

    walk(Path(root).resolve(), 0)
    return out


def repo_status(path, fetch=False):
    git = need("git", hint="git")
    g = lambda *a: run([git, "-C", path, *a], check=False, capture=True)
    if fetch:
        g("fetch", "--all", "--prune", "--quiet")
    ab = g("rev-list", "--left-right", "--count", "@{u}...HEAD")
    behind, ahead = map(int, ab.stdout.split()) if ab.returncode == 0 and ab.stdout.strip() else (None, None)
    last = g("log", "-1", "--format=%cr\x1f%s").stdout.strip().split("\x1f", 1)
    return {"path": str(path), "name": Path(path).name, "branch": g("rev-parse", "--abbrev-ref", "HEAD").stdout.strip() or "?",
            "changed": len([l for l in g("status", "--porcelain").stdout.splitlines() if l.strip()]),
            "ahead": ahead, "behind": behind, "when": last[0] if last[0] else "no commits", "msg": last[1] if len(last) > 1 else "",
            "remote": g("remote", "get-url", "origin").stdout.strip()}


def repos_status(root, fetch=False):
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(8) as ex:
        return sorted(ex.map(lambda p: repo_status(p, fetch), find_repos(root)), key=lambda r: r["name"].lower())


def cmd_repos(a):
    rows = repos_status(a.path, a.fetch or a.pull)
    if not rows:
        sys.exit(f"no git repos under {a.path}")
    for r in rows:
        sync = "no upstream" if r["ahead"] is None else f"↑{r['ahead']} ↓{r['behind']}"
        print(f"  {r['name']:<28} {r['branch']:<16} {('clean' if not r['changed'] else str(r['changed']) + ' changed'):<12} {sync:<12} {r['when']}")
    if a.pull:
        git = need("git", hint="git")
        print()
        for r in rows:
            if r["changed"] or not r["behind"]:
                continue  # never pull into uncommitted work; nothing to pull
            print(f"pulling {r['name']}...", flush=True)
            run([git, "-C", r["path"], "pull", "--ff-only"], check=False)
        print("OK  pulled every clean repo that was behind")


# ---------------------------------------------------------------- USB encryption (file-level; Windows Home has no BitLocker To Go)
#
# Password -> scrypt -> key-encryption-key, which unwraps a random 256-bit drive key stored in VAULT_FILE on the drive.
# Every file becomes <random>.mtlk: MAGIC | 7-byte nonce prefix | meta length | AES-GCM(meta json: name, mtime)
# | AES-GCM chunks of 1 MiB. Chunk nonce = prefix + counter + last-flag, so reordering/truncation is detected.
# Files are encrypted to a temp file, decrypted again and compared, and only then is the original deleted.

VAULT_FILE = "_MULTIT_VAULT_DO_NOT_DELETE.key"
LOCKED_EXT = ".mtlk"
_MAGIC, _CHUNK = b"MTLK\x01", 1 << 20
_USB_SKIP = {"system volume information", "$recycle.bin"}
_SCRYPT = {"n": 2 ** 17, "r": 8, "p": 1}  # ~128 MB, ~0.5 s per guess


def _b64(b):
    return base64.b64encode(b).decode()


def _kek(password, salt, n, r, p):
    return hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, maxmem=512 << 20, dklen=32)


def _vault_backup(root, text):
    """Keep a copy of the (password-protected) vault on this PC: if the file on the stick is deleted, files are still recoverable."""
    serial = ctypes.c_ulong()
    drive_root = os.path.splitdrive(os.path.abspath(root))[0] + "\\"
    ctypes.windll.kernel32.GetVolumeInformationW(drive_root, None, 0, ctypes.byref(serial), None, None, None, 0)
    is_drive = Path(os.path.abspath(root)).parent == Path(os.path.abspath(root))  # USB root: name by volume serial (letters change)
    tag = "" if is_drive else "-" + hashlib.sha1(os.path.normcase(os.path.abspath(root)).encode()).hexdigest()[:10]
    dst = LOCAL / "MultiT" / "vault-backups" / f"{serial.value:08X}{tag}.key"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(text, encoding="utf-8")
    return dst


def _write_vault(root, key, password):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt, nonce = os.urandom(16), os.urandom(12)
    wrapped = AESGCM(_kek(password, salt, **_SCRYPT)).encrypt(nonce, key, b"multit-vault")
    text = json.dumps({"v": 1, "kdf": "scrypt", **_SCRYPT, "salt": _b64(salt), "nonce": _b64(nonce), "wrapped": _b64(wrapped)}, indent=1)
    tmp = Path(root, VAULT_FILE + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, Path(root, VAULT_FILE))
    is_drive = Path(os.path.abspath(root)).parent == Path(os.path.abspath(root))
    Path(root, "HOW-TO-UNLOCK.txt").write_text(
        f"The files in this {'drive' if is_drive else 'folder'} are encrypted with MultiT (AES-256-GCM).\n"
        + (f"Unlock: open MultiT > USB encrypt > Unlock, or run:  multit usb unlock {os.path.splitdrive(str(root))[0]}\n" if is_drive else
           f"Unlock: open MultiT > Folder vaults > Unlock, or run:  multit vault unlock \"{os.path.abspath(root)}\"\n") +
        f"Never delete {VAULT_FILE} - without it (and your password) the files cannot be recovered.\n", encoding="utf-8")
    return _vault_backup(root, text)


def vault_open(root, password):
    """-> drive key. Raises ValueError on a wrong password."""
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    v = json.loads(Path(root, VAULT_FILE).read_text(encoding="utf-8"))
    try:
        kek = _kek(password, base64.b64decode(v["salt"]), v["n"], v["r"], v["p"])
        return AESGCM(kek).decrypt(base64.b64decode(v["nonce"]), base64.b64decode(v["wrapped"]), b"multit-vault")
    except InvalidTag:
        raise ValueError("wrong password") from None


def _nonce(prefix, i, last):
    return prefix + i.to_bytes(4, "big") + bytes([last])


def _encrypt_file(aes, src, dst):
    """-> plaintext byte count. fsync before returning: the original is deleted right after."""
    st, prefix, n = os.stat(src), os.urandom(7), 0
    meta = aes.encrypt(_nonce(prefix, 0, 0), json.dumps({"name": os.path.basename(src), "mtime": st.st_mtime}).encode(), _MAGIC)
    with open(src, "rb", buffering=0) as fi, open(dst, "wb", buffering=0) as fo:
        fo.write(_MAGIC + prefix + len(meta).to_bytes(4, "big") + meta)
        i, chunk = 1, fi.read(_CHUNK)
        while True:
            nxt = fi.read(_CHUNK) if len(chunk) == _CHUNK else b""
            n += len(chunk)
            fo.write(aes.encrypt(_nonce(prefix, i, not nxt), chunk, _MAGIC))
            if not nxt:
                break
            chunk, i = nxt, i + 1
        os.fsync(fo.fileno())
    return n


def _decrypt_file(aes, src, dst=None):
    """-> (meta, plaintext byte count). dst=None only verifies. Every chunk's GCM tag is checked, so a single
    flipped bit, a missing chunk or a cut-off file raises InvalidTag - no separate hash needed."""
    n = 0
    with open(src, "rb", buffering=0) as fi:
        if fi.read(5) != _MAGIC:
            raise ValueError("not a MultiT-encrypted file")
        prefix, mlen = fi.read(7), int.from_bytes(fi.read(4), "big")
        meta = json.loads(aes.decrypt(_nonce(prefix, 0, 0), fi.read(mlen), _MAGIC))
        fo = open(dst, "wb", buffering=0) if dst else None
        try:
            i, ct = 1, fi.read(_CHUNK + 16)
            while True:
                nxt = fi.read(_CHUNK + 16) if len(ct) == _CHUNK + 16 else b""
                pt = aes.decrypt(_nonce(prefix, i, not nxt), ct, _MAGIC)
                n += len(pt)
                if fo:
                    fo.write(pt)
                if not nxt:
                    break
                ct, i = nxt, i + 1
            if fo:
                os.fsync(fo.fileno())
        finally:
            if fo:
                fo.close()
    return meta, n


def _usb_files(root, locked):
    """Files to process: *.mtlk when unlocking, everything else when locking. Leftover temp files are removed."""
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x.lower() not in _USB_SKIP and not _is_link(os.path.join(d, x))]
        for f in files:
            p = os.path.join(d, f)
            if f.endswith((".mtlk.tmp", ".mtdec.tmp")):  # from an interrupted run: originals are still intact
                os.remove(p)
            elif f in (VAULT_FILE, "HOW-TO-UNLOCK.txt", VAULT_FILE + ".tmp") and d.rstrip("\\") == str(root).rstrip("\\"):
                continue
            elif f.endswith(LOCKED_EXT) == locked:
                yield p


def _rm(path):
    try:
        os.remove(path)
    except PermissionError:
        os.chmod(path, stat.S_IWRITE)
        os.remove(path)


USB_WORKERS = 3  # overlap read / encrypt / write+flush; more mostly makes USB sticks and HDDs seek


def _run_files(root, files, work, verb, log):
    """Run work(path) on a few threads with one live progress line (%, speed, time left). -> (done, skipped)"""
    import threading, time
    from concurrent.futures import ThreadPoolExecutor
    from cryptography.exceptions import InvalidTag
    sizes = {}
    for p in files:
        try:
            sizes[p] = os.path.getsize(p)
        except OSError:
            sizes[p] = 0
    total, lock, t0 = sum(sizes.values()) or 1, threading.Lock(), time.time()
    st = {"n": 0, "bytes": 0, "shown": 0.0, "done": 0, "skipped": []}

    def one(p):
        err = None
        try:
            work(p)
        except InvalidTag:
            err = "damaged or altered"
        except (OSError, ValueError) as e:
            err = getattr(e, "strerror", None) or str(e)
        with lock:
            st["n"] += 1
            st["bytes"] += sizes[p]
            if err:
                st["skipped"].append(p)
                log(f"\rSKIPPED {os.path.relpath(p, root)}  ({err})" + " " * 20)
            else:
                st["done"] += 1
            now = time.time()
            if now - st["shown"] > 0.4 or st["n"] == len(files):
                st["shown"] = now
                el = max(now - t0, 1e-6)
                speed = st["bytes"] / el
                left = (total - st["bytes"]) / speed if speed else 0
                log(f"\r  {st['bytes'] * 100 / total:5.1f}%   {st['n']:,}/{len(files):,} files   {human(st['bytes'])} / {human(total)}"
                    f"   {speed / 1e6:6.1f} MB/s   {int(left // 60)}:{int(left % 60):02d} left   ", end="")

    log(f"{verb} {len(files):,} files ({human(total)}) - don't unplug until this finishes")
    with ThreadPoolExecutor(USB_WORKERS) as ex:
        list(ex.map(one, files))
    el = time.time() - t0
    log(f"\n{verb} took {int(el // 60)}:{int(el % 60):02d}  ({total / max(el, 1e-6) / 1e6:.1f} MB/s)")
    return st["done"], st["skipped"]


def lock_tree(root, password, log=print):
    """Encrypt every file under root in place. Creates the vault on first use. -> (done, skipped)"""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if Path(root, VAULT_FILE).exists():
        key = vault_open(root, password)
    else:
        key = AESGCM.generate_key(256)
        log(f"new vault created - key backup kept at {_write_vault(root, key, password)}")
    aes = AESGCM(key)

    def work(p):
        tmp = os.path.join(os.path.dirname(p), secrets.token_hex(8) + LOCKED_EXT + ".tmp")
        try:
            n = _encrypt_file(aes, p, tmp)
            if _decrypt_file(aes, tmp)[1] != n:  # read it back: every GCM tag must check out
                raise OSError("verification failed")
            final = tmp[:-4]
            os.replace(tmp, final)
            try:
                _rm(p)
            except OSError:
                os.remove(final)  # couldn't remove the original (in use?) -> roll back, keep it plain
                raise
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    return _run_files(root, list(_usb_files(root, False)), work, "locking", log)


def unlock_tree(root, password, log=print):
    """Decrypt every .mtlk under root back to its original name. -> (done, skipped)"""
    import threading
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    aes, names = AESGCM(vault_open(root, password)), threading.Lock()

    def work(p):
        d = os.path.dirname(p)
        tmp = os.path.join(d, secrets.token_hex(8) + ".mtdec.tmp")
        try:
            meta, _ = _decrypt_file(aes, p, tmp)
            name = os.path.basename(meta["name"]) or "restored"
            base, ext = os.path.splitext(name)
            with names:  # two threads must not pick the same free name
                target, k = os.path.join(d, name), 1
                while os.path.exists(target):
                    target, k = os.path.join(d, f"{base} (restored{'' if k == 1 else ' ' + str(k)}){ext}"), k + 1
                os.replace(tmp, target)
            os.utime(target, (meta["mtime"], meta["mtime"]))
            _rm(p)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    return _run_files(root, list(_usb_files(root, True)), work, "unlocking", log)


def vault_status(root):
    locked = plain = 0
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x.lower() not in _USB_SKIP]
        for f in files:
            if f.endswith(LOCKED_EXT):
                locked += 1
            elif f not in (VAULT_FILE, "HOW-TO-UNLOCK.txt"):
                plain += 1
    return {"vault": Path(root, VAULT_FILE).exists(), "locked": locked, "plain": plain}


def usb_drives(status=True):
    """USB disks (sticks, external drives, card readers). Never the Windows drive."""
    ps = ("Get-Partition | ? DriveLetter | % { $d = Get-Disk -Number $_.DiskNumber; "
          "[pscustomobject]@{L=[string]$_.DriveLetter; Bus=[string]$d.BusType; Name=[string]$d.FriendlyName} } | ConvertTo-Json -Compress")
    out = run(["powershell", "-NoProfile", "-Command", ps], check=False, capture=True).stdout.strip()
    rows = json.loads(out) if out else []
    rows = [rows] if isinstance(rows, dict) else rows
    found = {r["L"].upper(): r["Name"] for r in rows if r["Bus"] == "USB"}
    for L in "DEFGHIJKLMNOPQRSTUVWXYZ":  # removable media without a partition table (some sticks / SD cards)
        if L not in found and ctypes.windll.kernel32.GetDriveTypeW(f"{L}:\\") == 2:
            found[L] = "Removable drive"
    found.pop(os.environ.get("SystemDrive", "C:")[0].upper(), None)
    drives = []
    for L, name in sorted(found.items()):
        root = f"{L}:\\"
        try:
            u = shutil.disk_usage(root)
        except OSError:
            continue  # empty card reader slot
        label = ctypes.create_unicode_buffer(261)
        ctypes.windll.kernel32.GetVolumeInformationW(root, label, 261, None, None, None, None, 0)
        drives.append({"drive": f"{L}:", "root": root, "name": name.strip(), "label": label.value, "total": u.total, "free": u.free,
                       **(vault_status(root) if status else {"vault": Path(root, VAULT_FILE).exists()})})
    return drives


def _usb_root(drive):
    d = drive.rstrip("\\/:").upper()[:1]
    if not any(x["drive"][0] == d for x in usb_drives(status=False)):
        sys.exit(f"{drive} is not a connected USB drive (see: multit usb list)")
    return f"{d}:\\"


def _usb_password(env, prompt, confirm=False):
    pw = os.environ.get(env)
    if not pw:
        import getpass
        pw = getpass.getpass(prompt)
        if confirm and getpass.getpass("repeat: ") != pw:
            sys.exit("passwords don't match")
    if len(pw) < 8:
        sys.exit("use at least 8 characters")
    return pw


def usb_speed(root, mb=128, log=None):
    """Real drive speed: write a test file (fsync'd, then deleted) and read back the biggest existing file.
    -> {"write": MB/s, "read": MB/s}. Lock/unlock time ~= size/read + size/write."""
    import time
    p, blob = os.path.join(root, f".multit-speedtest-{secrets.token_hex(4)}.tmp"), os.urandom(1 << 20)
    try:
        t0 = time.perf_counter()
        with open(p, "wb", buffering=0) as f:
            for i in range(mb):
                f.write(blob)
                if log and i % 16 == 15:
                    log(f"\r  writing test file... {i + 1}/{mb} MB   ", end="")
            os.fsync(f.fileno())
        write = mb / (time.perf_counter() - t0)
    finally:
        if os.path.exists(p):
            os.remove(p)
    # read speed: the biggest real file (a fresh test file would just come back from the RAM cache)
    biggest, size = None, 0
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x.lower() not in _USB_SKIP]
        for fn in files:
            try:
                s = os.path.getsize(os.path.join(d, fn))
            except OSError:
                continue
            if s > size:
                biggest, size = os.path.join(d, fn), s
    read = None
    if biggest and size > 8 << 20:
        if log:
            log(f"\r  reading {os.path.basename(biggest)}...                ", end="")
        t0, n = time.perf_counter(), 0
        with open(biggest, "rb", buffering=0) as f:
            while n < mb << 20 and (chunk := f.read(4 << 20)):
                n += len(chunk)
        read = n / (1 << 20) / (time.perf_counter() - t0)
    return {"write": write, "read": read}


def _live_log(s, end="\n"):
    print(s, end=end, flush=True)


def cmd_usb(a):
    if a.action == "list":
        ds = usb_drives()
        if not ds:
            print("no USB drives connected")
        for d in ds:
            state = f"LOCKED ({d['locked']} files)" if d["locked"] and not d["plain"] else \
                    f"partly locked ({d['locked']} locked, {d['plain']} plain)" if d["locked"] else "unlocked"
            print(f"  {d['drive']}  {d['label'] or '(no label)':<16} {d['name']:<24} {human(d['total']):>9}  {state}")
        return
    if not a.drive:
        sys.exit(f"usb {a.action} needs a DRIVE, e.g. multit usb {a.action} E:")
    root = _usb_root(a.drive)
    if a.action == "speed":
        s = usb_speed(root, log=_live_log)
        used = shutil.disk_usage(root).used
        secs = used / (1 << 20) / s["write"] + (used / (1 << 20) / s["read"] if s["read"] else 0)
        print(f"\r  write {s['write']:.1f} MB/s   read " + (f"{s['read']:.1f} MB/s" if s["read"] else "n/a") + " " * 20)
        print(f"OK  locking or unlocking the {human(used)} on {root} takes about {int(secs // 60)} min {int(secs % 60)} s"
              + ("\n    (a USB 2.0 stick tops out around 5-10 MB/s writing - a USB 3 stick is 10-50x faster)" if s["write"] < 15 else ""))
        return
    first = not Path(root, VAULT_FILE).exists()
    if a.action == "lock":
        pw = _usb_password("MULTIT_USB_KEY", "new drive password: " if first else "drive password: ", confirm=first)
        done, skipped = lock_tree(root, pw, log=_live_log)
        print(f"\nOK  {done} files encrypted" + (f", {len(skipped)} skipped (in use or unreadable)" if skipped else ""))
        print("note: on flash drives, deleted originals can linger in unused space until overwritten.")
    elif a.action == "unlock":
        if first:
            sys.exit(f"{root} has no MultiT vault - nothing to unlock")
        pw = _usb_password("MULTIT_USB_KEY", "drive password: ")
        try:
            done, skipped = unlock_tree(root, pw, log=_live_log)
        except ValueError as e:
            sys.exit(str(e))
        print(f"\nOK  {done} files decrypted" + (f", {len(skipped)} skipped" if skipped else ""))
    elif a.action == "passwd":
        if first:
            sys.exit(f"{root} has no MultiT vault yet - lock it first")
        try:
            key = vault_open(root, _usb_password("MULTIT_USB_KEY", "current password: "))
        except ValueError as e:
            sys.exit(str(e))
        _write_vault(root, key, _usb_password("MULTIT_USB_NEWKEY", "new password: ", confirm=True))
        print("OK  password changed (files didn't need re-encrypting)")


# ---------------------------------------------------------------- folder vaults (same engine as USB encryption)

STATE_DIR = Path(os.environ.get("MULTIT_STATE_DIR") or LOCAL / "MultiT")  # override lets tests use a temp dir
VAULTS_DB = STATE_DIR / "vaults.json"


def _load(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _save(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def vault_folders():
    out = []
    for p in _load(VAULTS_DB, []):
        if os.path.isdir(p):
            out.append({"path": p, "name": os.path.basename(p.rstrip("\\")), **vault_status(p)})
    return out


def _vault_folder(path):
    p = os.path.abspath(path)
    if not os.path.isdir(p):
        sys.exit(f"not a folder: {p}")
    if is_protected(p):
        sys.exit(f"refusing to lock {p} - pick a folder inside it (Windows, program folders, drive roots and your top profile folders are off limits)")
    return p


def cmd_vault(a):
    if a.action == "list":
        vs = vault_folders()
        for v in vs:
            print(f"  {'LOCKED ' if v['locked'] and not v['plain'] else 'partial' if v['locked'] else 'open   '}  {v['path']}  ({v['locked']} locked, {v['plain']} open)")
        print("" if vs else "  no folder vaults yet - multit vault lock <folder>")
        return
    if not a.path:
        sys.exit(f"vault {a.action} needs a FOLDER")
    p = _vault_folder(a.path)
    first = not Path(p, VAULT_FILE).exists()
    if a.action == "forget":
        _save(VAULTS_DB, [x for x in _load(VAULTS_DB, []) if os.path.normcase(x) != os.path.normcase(p)])
        print(f"OK  {p} removed from the list (files untouched)")
        return
    if a.action == "lock":
        pw = _usb_password("MULTIT_USB_KEY", "new vault password: " if first else "vault password: ", confirm=first)
        try:
            done, skipped = lock_tree(p, pw, log=_live_log)
        except ValueError as e:
            sys.exit(str(e))
        db = _load(VAULTS_DB, [])
        if not any(os.path.normcase(x) == os.path.normcase(p) for x in db):
            _save(VAULTS_DB, db + [p])
        print(f"\nOK  {done} files encrypted" + (f", {len(skipped)} skipped (in use?)" if skipped else ""))
    elif a.action == "unlock":
        if first:
            sys.exit(f"{p} is not a MultiT vault")
        try:
            done, skipped = unlock_tree(p, _usb_password("MULTIT_USB_KEY", "vault password: "), log=_live_log)
        except ValueError as e:
            sys.exit(str(e))
        print(f"\nOK  {done} files decrypted" + (f", {len(skipped)} skipped" if skipped else ""))
    elif a.action == "passwd":
        if first:
            sys.exit(f"{p} is not a MultiT vault")
        try:
            key = vault_open(p, _usb_password("MULTIT_USB_KEY", "current password: "))
        except ValueError as e:
            sys.exit(str(e))
        _write_vault(p, key, _usb_password("MULTIT_USB_NEWKEY", "new password: ", confirm=True))
        print("OK  password changed")


# ---------------------------------------------------------------- bootable USB (Ventoy: install once, then just copy ISOs)

def ventoy_exe():
    for pat in (LOCAL / "Microsoft/WinGet/Packages/Ventoy.Ventoy*/**/Ventoy2Disk.exe", Path(r"C:\Program Files\Ventoy*\Ventoy2Disk.exe")):
        hits = sorted(glob.glob(str(pat), recursive=True))
        if hits:
            return hits[-1]
    return None


def boot_drives():
    out = []
    for d in usb_drives(status=False):
        out.append({**d, "ventoy": d["label"].lower() == "ventoy",
                    "isos": sorted(f.name for f in Path(d["root"]).glob("*.iso")) if d["label"].lower() == "ventoy" else []})
    return out


def cmd_boot(a):
    if a.action == "list":
        for d in boot_drives():
            print(f"  {d['drive']}  {d['label'] or '(no label)':<14} {d['name']:<24} {human(d['total']):>9}  "
                  + (f"Ventoy ready, {len(d['isos'])} ISO(s)" if d["ventoy"] else "not bootable"))
        print(f"  Ventoy: {ventoy_exe() or 'not installed (multit boot setup)'}")
        return
    if a.action == "setup":
        return install_tool("ventoy")
    drives = {d["drive"][0]: d for d in boot_drives()}
    d = drives.get((a.drive or "?")[0].upper())
    if not d:
        sys.exit(f"{a.drive} is not a connected USB drive (see: multit boot list)")
    if a.action == "install":
        if (a.erase or "").rstrip(":").upper() != d["drive"][0]:
            sys.exit(f"this ERASES everything on {d['drive']} ({d['label']}, {human(d['total'])}).\n"
                     f"  confirm with:  multit boot install {d['drive']} --erase {d['drive']}")
        if vault_status(d["root"])["locked"]:
            sys.exit(f"{d['drive']} holds MultiT-encrypted files - unlock or copy them off first")
        exe = ventoy_exe() or sys.exit("Ventoy isn't installed yet:  multit boot setup")
        done = Path(exe).parent / "cli_done.txt"
        done.unlink(missing_ok=True)
        # Ventoy2Disk needs admin -> Windows asks (UAC). No /NOUSBCheck: Ventoy itself also refuses non-USB disks.
        print(f"installing Ventoy on {d['drive']} - accept the Windows admin prompt", flush=True)
        run(["powershell", "-NoProfile", "-Command",
             f"Start-Process -FilePath '{exe}' -ArgumentList 'VTOYCLI /I /Drive:{d['drive']}' -Verb RunAs -Wait"], check=False)
        result = done.read_text(errors="ignore").strip() if done.exists() else ""
        if result != "0":
            log = Path(exe).parent / "log.txt"
            sys.exit("Ventoy install failed or was cancelled" + (f" - see {log}" if log.exists() else ""))
        print(f"OK  {d['drive']} is now bootable. Add ISOs with:  multit boot add {d['drive']} ubuntu")
    elif a.action == "add":
        if not d["ventoy"]:
            sys.exit(f"{d['drive']} isn't a Ventoy stick yet:  multit boot install {d['drive']} --erase {d['drive']}")
        src = Path(a.iso) if a.iso and Path(a.iso).is_file() else fetch_iso(a.iso.lower()) if a.iso and a.iso.lower() in ISOS else None
        if not src:
            sys.exit("give an .iso file or an OS name from `multit iso list`")
        if src.stat().st_size > shutil.disk_usage(d["root"]).free:
            sys.exit(f"not enough space on {d['drive']} for {src.name} ({human(src.stat().st_size)})")
        dst, tmp = Path(d["root"], src.name), Path(d["root"], src.name + ".part")
        total, n = src.stat().st_size, 0
        with open(src, "rb") as fi, open(tmp, "wb") as fo:
            while chunk := fi.read(8 << 20):
                fo.write(chunk)
                n += len(chunk)
                print(f"\r  copying {src.name}  {n * 100 // max(total, 1)}%  ({human(n)} / {human(total)})   ", end="", flush=True)
            os.fsync(fo.fileno())
        os.replace(tmp, dst)
        print(f"\nOK  {src.name} is on {d['drive']} - boot from the stick and pick it from the Ventoy menu")


# ---------------------------------------------------------------- app updater (winget upgrade)

def winget_upgrades():
    """Parse `winget upgrade`: column positions come from the header line, since names can contain spaces."""
    out = run([need("winget", hint="winget"), "upgrade", "--include-unknown", "--accept-source-agreements", "--disable-interactivity"],
              check=False, capture=True).stdout
    lines = [l.split("\r")[-1] for l in out.splitlines()]
    hi = next((i for i, l in enumerate(lines) if re.match(r"\s*Name\s+Id\s+Version\s+Available", l)), None)
    if hi is None:
        return []
    h = lines[hi]
    c_id, c_ver, c_av, c_src = (h.index(x) for x in ("Id", "Version", "Available", "Source"))
    rows = []
    for l in lines[hi + 2:]:
        if not l.strip() or re.match(r"\s*\d+ (upgrade|package)", l) or len(l) < c_av:
            break
        rows.append({"name": l[:c_id].strip(), "id": l[c_id:c_ver].strip(), "version": l[c_ver:c_av].strip(),
                     "available": l[c_av:c_src].strip()})
    return [r for r in rows if r["id"]]


def cmd_update(a):
    if not a.ids and not a.all:
        rows = winget_upgrades()
        for r in rows:
            print(f"  {r['name'][:40]:<40} {r['version'][:16]:>16} -> {r['available']}")
        print(f"\n  {len(rows)} updates   ·   multit update ID [ID...]   or   multit update --all" if rows else "  everything is up to date")
        return
    flags = ["--silent", "--accept-package-agreements", "--accept-source-agreements", "--disable-interactivity"]
    if a.all:
        r = run([need("winget"), "upgrade", "--all", "--include-unknown", *flags], check=False)
        print("\nOK  all updates applied" if r.returncode == 0 else f"\nsome updates failed (winget exit {r.returncode}) - see above")
        return
    failed = []
    for i, pid in enumerate(a.ids, 1):
        print(f"\n[{i}/{len(a.ids)}] updating {pid}", flush=True)
        if run([need("winget"), "upgrade", "-e", "--id", pid, *flags], check=False).returncode not in (0, -1978335189):
            failed.append(pid)
    if failed:
        sys.exit(f"\nfailed: {', '.join(failed)} (an open app can block its own update - close it and retry)")
    print(f"\nOK  {len(a.ids)} app(s) updated")


# ---------------------------------------------------------------- backup jobs (robocopy + Task Scheduler)

BACKUPS_DB = STATE_DIR / "backups.json"
_MARKER = ".multit-backup"


def _job_task(name):
    return "MultiT\\backup-" + re.sub(r"[^\w-]", "_", name)


def _self_cmd():
    return f'"{sys.executable}"' if FROZEN else f'"{Path(sys.executable).with_name("pythonw.exe")}" "{Path(__file__).resolve()}"'


def backup_jobs():
    return _load(BACKUPS_DB, [])


def backup_check(src, dst, mirror):
    s, d = os.path.normcase(os.path.abspath(src)), os.path.normcase(os.path.abspath(dst))
    if not os.path.isdir(s):
        return f"source folder doesn't exist: {src}"
    if d == s or d.startswith(s.rstrip("\\") + "\\") or s.startswith(d.rstrip("\\") + "\\"):
        return "source and destination can't be inside each other"
    if len(Path(d).parts) <= 1:
        return "pick a folder on the target drive (e.g. D:\\Backups\\Photos), not the drive root"
    if is_protected(d):
        return f"refusing to write into {dst}"
    if mirror and os.path.isdir(d) and any(os.scandir(d)) and not os.path.exists(os.path.join(d, _MARKER)):
        return "mirror mode deletes files that aren't in the source - use an empty folder, or one MultiT created"
    return None


def backup_run(job, log=print):
    err = backup_check(job["src"], job["dst"], job.get("mirror"))
    if err:
        raise ValueError(err)
    os.makedirs(job["dst"], exist_ok=True)
    Path(job["dst"], _MARKER).write_text(f"MultiT backup of {job['src']}\n", encoding="utf-8")
    cmd = ["robocopy", job["src"], job["dst"], "/MIR" if job.get("mirror") else "/E", "/XF", _MARKER,
           "/R:1", "/W:1", "/MT:8", "/XJ", "/FFT", "/NP", "/NDL", "/NFL"]
    r = run(cmd, check=False)
    ok = r.returncode < 8  # robocopy: 0-7 = success (1 = copied files), 8+ = failures
    jobs = backup_jobs()
    for j in jobs:
        if j["name"] == job["name"]:
            import time
            j["last"], j["last_ok"] = time.time(), ok
    _save(BACKUPS_DB, jobs)
    return ok


def backup_schedule(job):
    task = _job_task(job["name"])
    run(["schtasks", "/delete", "/f", "/tn", task], check=False, capture=True)
    sched = job.get("schedule", "off")
    if sched == "off":
        return
    when = {"daily": ["/sc", "DAILY", "/st", job.get("at") or "20:00"], "hourly": ["/sc", "HOURLY"], "logon": ["/sc", "ONLOGON"]}[sched]
    r = run(["schtasks", "/create", "/f", "/tn", task, "/tr", f'{_self_cmd()} backup run "{job["name"]}"', *when], check=False, capture=True)
    if r.returncode:
        raise ValueError((r.stderr or r.stdout).strip())


def cmd_backup(a):
    jobs = backup_jobs()
    if a.action == "list":
        import time
        for j in jobs:
            last = time.strftime("%Y-%m-%d %H:%M", time.localtime(j["last"])) + (" ok" if j.get("last_ok") else " FAILED") if j.get("last") else "never"
            print(f"  {j['name']:<16} {'mirror' if j.get('mirror') else 'copy':<6} {j.get('schedule', 'off'):<7} last: {last}\n      {j['src']}  ->  {j['dst']}")
        print("" if jobs else "  no backup jobs - multit backup add NAME SRC DST")
        return
    if a.action == "add":
        if not (a.name and a.src and a.dst):
            sys.exit("usage: multit backup add NAME SRC DST [--mirror] [--schedule daily --at 20:00]")
        if err := backup_check(a.src, a.dst, a.mirror):
            sys.exit(err)
        job = {"name": a.name, "src": os.path.abspath(a.src), "dst": os.path.abspath(a.dst), "mirror": a.mirror,
               "schedule": a.schedule, "at": a.at}
        _save(BACKUPS_DB, [j for j in jobs if j["name"] != a.name] + [job])
        try:
            backup_schedule(job)
        except ValueError as e:
            sys.exit(f"job saved, but scheduling failed: {e}")
        print(f"OK  backup job '{a.name}' saved" + ("" if a.schedule == "off" else f", runs {a.schedule}" + (f" at {a.at}" if a.schedule == "daily" else "")))
    elif a.action == "remove":
        job = next((j for j in jobs if j["name"] == a.name), None) or sys.exit(f"no job named {a.name}")
        backup_schedule({**job, "schedule": "off"})
        _save(BACKUPS_DB, [j for j in jobs if j["name"] != a.name])
        print(f"OK  job '{a.name}' removed (backup files untouched)")
    elif a.action == "run":
        todo = jobs if a.name in (None, "--all", "all") else [j for j in jobs if j["name"] == a.name]
        if not todo:
            sys.exit(f"no job named {a.name}")
        bad = []
        for j in todo:
            print(f"\n== {j['name']}: {j['src']} -> {j['dst']}", flush=True)
            try:
                if not backup_run(j):
                    bad.append(j["name"])
            except ValueError as e:
                print(f"skipped: {e}")
                bad.append(j["name"])
        if bad:
            sys.exit(f"\nfailed: {', '.join(bad)}")
        print(f"\nOK  {len(todo)} backup(s) done")


# ---------------------------------------------------------------- game booster

BOOST_STATE = STATE_DIR / "boost.json"
_NEVER_CLOSE = CRITICAL_PROCS | {"explorer.exe", "multit.exe", "python.exe", "pythonw.exe", "python3.11.exe", "msedgewebview2.exe",
                                  "searchhost.exe", "startmenuexperiencehost.exe", "shellexperiencehost.exe", "textinputhost.exe",
                                  "ctfmon.exe", "sihost.exe", "taskhostw.exe", "runtimebroker.exe", "audiodg.exe", "conhost.exe"}


def _active_plan():
    m = re.search(r"([0-9a-f]{8}-[0-9a-f-]{27})", run(["powercfg", "/getactivescheme"], check=False, capture=True).stdout, re.I)
    return m.group(1) if m else None


def boost_candidates():
    """Running apps you could close for a boost, heaviest first (Windows essentials excluded)."""
    return [r for r in top_procs("mem", 60) if r["name"].lower() not in _NEVER_CLOSE and not r["critical"]][:30]


def boost_on(apps, log=print):
    import psutil, time
    if BOOST_STATE.exists():
        raise ValueError("boost is already on - turn it off first")
    state = {"plan": _active_plan(), "closed": [], "time": time.time()}
    if run(["powercfg", "/setactive", "SCHEME_MIN"], check=False, capture=True).returncode == 0:  # SCHEME_MIN = High performance
        log("power plan -> High performance")
    else:
        log("High performance plan not available on this PC - power plan unchanged")
    wanted = {a.lower() for a in apps} - _NEVER_CLOSE
    procs = [p for p in psutil.process_iter(["name", "exe", "cmdline", "ppid"]) if (p.info["name"] or "").lower() in wanted]
    for name in sorted(wanted):
        group = [p for p in procs if p.info["name"].lower() == name]
        if not group:
            continue
        pids = {p.pid for p in group}
        roots = [p for p in group if p.info["ppid"] not in pids] or group[:1]  # the main process, to reopen it later
        r = roots[0].info
        state["closed"].append({"name": r["name"], "exe": r["exe"], "args": (r["cmdline"] or [])[1:]})
        for p in group:
            try:
                p.terminate()
            except psutil.Error:
                pass
        gone, alive = psutil.wait_procs(group, timeout=4)
        for p in alive:
            try:
                p.kill()
            except psutil.Error:
                pass
        log(f"closed {r['name']}" + (f" ({len(group)} processes)" if len(group) > 1 else ""))
    _save(BOOST_STATE, state)
    return state


def boost_off(reopen=True, log=print):
    state = _load(BOOST_STATE, None)
    if not state:
        raise ValueError("boost isn't on")
    if state.get("plan"):
        run(["powercfg", "/setactive", state["plan"]], check=False, capture=True)
        log("power plan restored")
    if reopen:
        for c in state["closed"]:
            if c.get("exe") and os.path.exists(c["exe"]):
                subprocess.Popen([c["exe"], *c["args"]], cwd=os.path.dirname(c["exe"]), creationflags=0x8 | 0x200)  # detached
                log(f"reopened {c['name']}")
    BOOST_STATE.unlink(missing_ok=True)


def cmd_boost(a):
    try:
        if a.action == "on":
            if not a.apps:
                print("apps you could close (heaviest first):")
                for r in boost_candidates():
                    print(f"  {human(r['mem']):>10}  {r['name']}")
                sys.exit("\npick some:  multit boost on --apps Discord.exe chrome.exe ...   (unsaved work in them is lost)")
            boost_on(a.apps, log=_live_log)
            print("OK  boost on - run `multit boost off` when you're done gaming")
        elif a.action == "off":
            boost_off(not a.no_reopen, log=_live_log)
            print("OK  boost off")
        else:
            s = _load(BOOST_STATE, None)
            print(f"boost is ON - closed: {', '.join(c['name'] for c in s['closed']) or 'nothing'}" if s else "boost is off")
    except ValueError as e:
        sys.exit(str(e))


# ---------------------------------------------------------------- AI model manager

MODEL_EXT = {".gguf", ".safetensors", ".ckpt", ".pt", ".pth", ".onnx", ".bin", ".ggml"}
MODEL_ROOTS = [("LM Studio", HOME / ".lmstudio/models"), ("LM Studio", HOME / ".cache/lm-studio/models"),
               ("Hugging Face", HOME / ".cache/huggingface/hub"), ("GPT4All", LOCAL / "nomic.ai/GPT4All"),
               ("Jan", HOME / "jan/models"), ("Ollama", HOME / ".ollama/models")]


def _real(p):
    """Follow a junction we made (models moved to another drive) - os.path.realpath does that on Windows."""
    return os.path.realpath(p)


def models_scan(extra=None):
    """Model files >= 50 MB in the known app folders (+ an extra folder), with duplicates (same size + same 64 KB hash)."""
    roots = [(app, Path(p)) for app, p in MODEL_ROOTS if Path(p).exists()] + ([("Folder", Path(extra))] if extra else [])
    files, apps = [], []
    for app, root in roots:
        total = 0
        for d, dirs, fs in os.walk(root, followlinks=True):  # follow our own junctions so moved models still count
            for f in fs:
                p = os.path.join(d, f)
                try:
                    size = os.path.getsize(p)
                except OSError:
                    continue
                total += size
                ollama_blob = app == "Ollama" and f.startswith("sha256-")
                if size >= 50 << 20 and (Path(f).suffix.lower() in MODEL_EXT or ollama_blob):
                    rel = Path(p).relative_to(root)
                    folder = root / rel.parts[0] if app == "Hugging Face" else root / Path(*rel.parts[:2]) if app in ("LM Studio", "Jan") and len(rel.parts) > 2 else None
                    label = (folder.name.removeprefix("models--").replace("--", "/") if app == "Hugging Face" and folder
                             else f"{folder.parent.name}/{folder.name}" if folder else f)
                    files.append({"path": p, "name": f, "label": label, "size": size, "app": app, "folder": str(folder) if folder else None,
                                  "moved": bool(folder and _is_link(folder)), "lives_on": _real(p)[:2].upper()})
        apps.append({"app": app, "root": str(root), "size": total})
    # duplicates across apps: same size, then same first 64 KB
    by_size = {}
    for f in files:
        by_size.setdefault(f["size"], []).append(f)
    gid = 0
    for group in (g for g in by_size.values() if len(g) > 1):
        by_head = {}
        for f in group:
            try:
                with open(f["path"], "rb") as fh:
                    by_head.setdefault(hashlib.blake2b(fh.read(65536), digest_size=16).hexdigest(), []).append(f)
            except OSError:
                pass
        for same in (s for s in by_head.values() if len(s) > 1 and len({_real(x["path"]) for x in s}) > 1):
            gid += 1
            for f in same:
                f["dup"] = gid
    files.sort(key=lambda f: -f["size"])
    return {"apps": apps, "files": files}


def model_move(folder, dest_dir, log=print, allow_same_drive=False):  # allow_same_drive: tests only
    """Move a model folder to another drive and leave a junction behind, so the app still finds it.
    Copy -> verify sizes -> rename original aside -> junction -> delete original. Any failure leaves the original in place."""
    src = Path(os.path.abspath(folder))
    if _is_link(src):
        raise ValueError("already moved (it's a link)")
    if not any(Path(r) in src.parents for _, r in MODEL_ROOTS):
        raise ValueError("only model folders inside LM Studio / Hugging Face / GPT4All / Jan can be moved")
    dst = Path(os.path.abspath(dest_dir)) / src.name
    if dst.exists():
        raise ValueError(f"{dst} already exists")
    if not allow_same_drive and os.path.splitdrive(str(dst))[0].upper() == os.path.splitdrive(str(src))[0].upper():
        raise ValueError("pick a folder on a different drive - moving within the same drive frees nothing")
    need_bytes = sum(f.stat().st_size for f in src.rglob("*") if f.is_file())
    if shutil.disk_usage(dst.anchor).free < need_bytes + (1 << 30):
        raise ValueError(f"not enough space on {dst.anchor} ({human(need_bytes)} needed)")
    tmp = dst.with_name(dst.name + ".multit-partial")
    log(f"copying {human(need_bytes)} to {dst} ...")
    shutil.copytree(src, tmp)
    got = sum(f.stat().st_size for f in tmp.rglob("*") if f.is_file())
    if got != need_bytes:
        shutil.rmtree(tmp, ignore_errors=True)
        raise ValueError("copy verification failed - nothing changed")
    os.replace(tmp, dst)
    aside = src.with_name(src.name + ".multit-old")
    try:
        os.replace(src, aside)  # fails if the app has the files open -> undo the copy
    except OSError:
        shutil.rmtree(dst, ignore_errors=True)
        raise ValueError("the model is in use - close the app (LM Studio etc.) and try again")
    r = run(["cmd", "/c", "mklink", "/J", str(src), str(dst)], check=False, capture=True)
    if r.returncode or not src.exists():
        os.replace(aside, src)
        shutil.rmtree(dst, ignore_errors=True)
        raise ValueError(f"couldn't create the link: {(r.stdout + r.stderr).strip()}")
    shutil.rmtree(aside)
    log(f"moved - {src} now points to {dst}")
    return str(dst)


def model_restore(folder, log=print):
    """Undo model_move: bring the folder back and remove the junction."""
    src = Path(os.path.abspath(folder))
    if not _is_link(src):
        raise ValueError("that folder wasn't moved")
    target = Path(_real(src))
    tmp = src.with_name(src.name + ".multit-partial")
    log(f"copying back from {target} ...")
    shutil.copytree(target, tmp)
    os.rmdir(src)  # removes the junction only, never the target
    os.replace(tmp, src)
    shutil.rmtree(target)
    log("restored")


def cmd_models(a):
    try:
        if a.action == "move":
            return model_move(a.path, a.dest or sys.exit("models move FOLDER DEST_DIR"), log=_live_log)
        if a.action == "restore":
            return model_restore(a.path, log=_live_log)
    except ValueError as e:
        sys.exit(str(e))
    r = models_scan(a.path)
    for x in r["apps"]:
        print(f"  {x['app']:<14} {human(x['size']):>10}  {x['root']}")
    print()
    for f in r["files"]:
        print(f"  {human(f['size']):>10}  {f['app']:<13} {f['label']}  ({f['name']})" + ("  [DUPLICATE]" if f.get("dup") else "") + ("  (moved)" if f["moved"] else ""))


# ---------------------------------------------------------------- video tools (ffmpeg)

def _ff(tool):
    return need(tool, hint="ffmpeg")


def video_info(path):
    out = run([_ff("ffprobe"), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path], check=False, capture=True)
    if out.returncode:
        raise ValueError("not a video ffmpeg can read")
    d = json.loads(out.stdout)
    v = next((s for s in d["streams"] if s["codec_type"] == "video"), {})
    fps = v.get("avg_frame_rate", "0/1").split("/")
    return {"duration": float(d["format"].get("duration", 0)), "size": int(d["format"].get("size", 0)),
            "width": v.get("width"), "height": v.get("height"), "codec": v.get("codec_name"),
            "fps": round(int(fps[0]) / int(fps[1]), 2) if len(fps) == 2 and int(fps[1]) else None,
            "audio": any(s["codec_type"] == "audio" for s in d["streams"])}


def _tsec(t):
    """'1:05' / '00:01:05.5' / '65' -> seconds"""
    if t in (None, ""):
        return None
    secs = 0.0
    for part in str(t).split(":"):
        secs = secs * 60 + float(part)
    return secs


def _cut(t0, dur, end):
    """Input-side seek + duration (-t), so the result is exactly [start, end)."""
    return (["-ss", t0] if t0 else []) + (["-t", dur] if end else [])


def _ffmpeg(args, duration, label):
    """Run ffmpeg with a live % line parsed from -progress."""
    p = subprocess.Popen([_ff("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error", "-progress", "pipe:1", "-nostats", *map(str, args)],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, creationflags=NO_WINDOW)
    for line in p.stdout:
        if line.startswith("out_time_us=") and duration:
            done = int(line.split("=")[1] or 0) / 1e6
            print(f"\r  {label}  {min(100, done * 100 / duration):5.1f}%   ", end="", flush=True)
    err = p.stderr.read()
    if p.wait():
        raise ValueError(err.strip()[-500:] or f"ffmpeg failed ({p.returncode})")
    print(f"\r  {label}  100.0%   ")


def _out(src, suffix, ext):
    s = Path(src)
    out, k = s.with_name(f"{s.stem}{suffix}{ext}"), 2
    while out.exists():
        out, k = s.with_name(f"{s.stem}{suffix} ({k}){ext}"), k + 1
    return out


def video_compress(src, target_mb, start=None, end=None):
    """Two-pass H.264 sized to fit target_mb (e.g. Discord's 10 MB). Lower bitrates also scale down to keep it watchable."""
    info = video_info(src)
    t0, t1 = _tsec(start) or 0, _tsec(end) or info["duration"]
    dur = max(t1 - t0, 0.1)
    audio_kbps = 96 if info["audio"] else 0
    video_kbps = int(target_mb * 8 * 1024 * 0.96 / dur) - audio_kbps  # 4% container overhead
    if video_kbps < 100:
        raise ValueError(f"{target_mb} MB is too small for {dur:.0f} s of video - trim it or pick a bigger size")
    height = 480 if video_kbps < 900 else 720 if video_kbps < 2500 else 1080 if video_kbps < 6000 else None
    vf = ["-vf", f"scale=-2:'min({height},ih)'"] if height else []
    cut = _cut(t0, dur, end)
    out, log = _out(src, f"_{target_mb:g}MB", ".mp4"), Path(tempfile.mkdtemp(prefix="multit_ff_")) / "pass"
    common = [*cut, "-i", src, *vf, "-c:v", "libx264", "-preset", "medium", "-b:v", f"{video_kbps}k", "-passlogfile", log]
    _ffmpeg([*common, "-pass", "1", "-an", "-f", "mp4", "NUL"], dur, "pass 1/2")
    _ffmpeg([*common, "-pass", "2", *(["-c:a", "aac", "-b:a", f"{audio_kbps}k"] if audio_kbps else ["-an"]), "-movflags", "+faststart", out], dur, "pass 2/2")
    shutil.rmtree(log.parent, ignore_errors=True)
    return out


def video_convert(src, kind, start=None, end=None, width=480, fps=15):
    info = video_info(src)
    t0, t1 = _tsec(start) or 0, _tsec(end) or info["duration"]
    dur = max(t1 - t0, 0.1)
    cut = _cut(t0, dur, end)
    if kind == "trim":  # re-encode: frame-exact (stream copy can only cut on keyframes, which may be seconds apart)
        out = _out(src, "_trim", ".mp4")
        _ffmpeg([*cut, "-i", src, "-c:v", "libx264", "-crf", "18", "-preset", "veryfast", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out], dur, "trimming")
    elif kind == "gif":
        out = _out(src, "", ".gif")
        _ffmpeg([*cut, "-i", src, "-vf", f"fps={fps},scale={width}:-1:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse", out], dur, "making gif")
    elif kind == "mp3":
        out = _out(src, "", ".mp3")
        _ffmpeg([*cut, "-i", src, "-vn", "-c:a", "libmp3lame", "-q:a", "2", out], dur, "extracting audio")
    elif kind == "mp4":
        out = _out(src, "_h264", ".mp4")
        _ffmpeg([*cut, "-i", src, "-c:v", "libx264", "-crf", "21", "-preset", "medium", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", out], dur, "converting")
    else:
        raise ValueError(kind)
    return out


VIDEO_EXT = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".wmv", ".flv"}


def cmd_video(a):
    try:
        if a.action == "info":
            i = video_info(a.path)
            print(f"  {i['width']}x{i['height']} {i['codec']} {i['fps']} fps · {i['duration']:.1f} s · {human(i['size'])}" + (" · audio" if i["audio"] else ""))
            return
        if a.action == "batch":
            vids = sorted(p for p in Path(a.path).iterdir() if p.suffix.lower() in VIDEO_EXT and "_" + f"{a.size:g}MB" not in p.stem)
            for n, v in enumerate(vids, 1):
                print(f"\n[{n}/{len(vids)}] {v.name}", flush=True)
                try:
                    out = video_compress(v, a.size)
                    print(f"  -> {out.name}  {human(out.stat().st_size)}")
                except ValueError as e:
                    print(f"  skipped: {e}")
            print(f"\nOK  {len(vids)} video(s) processed")
            return
        out = video_compress(a.path, a.size, a.start, a.end) if a.action == "compress" else video_convert(a.path, a.action, a.start, a.end, a.width, a.fps)
        print(f"OK  {out}  ({human(out.stat().st_size)})")
    except ValueError as e:
        sys.exit(str(e))


# ---------------------------------------------------------------- server panel (background servers with auto-restart)

def _slug(name):
    return re.sub(r"[^\w-]", "_", name)


def _srv_dir():
    d = STATE_DIR / "servers"
    d.mkdir(parents=True, exist_ok=True)
    return d


def servers():
    return _load(STATE_DIR / "servers.json", [])


def _srv(name):
    return next((s for s in servers() if s["name"] == name), None) or sys.exit(f"no server named {name}")


def _srv_state(name, **upd):
    path = _srv_dir() / f"{_slug(name)}.state.json"
    st = _load(path, {})
    if upd:
        st.update(upd)
        _save(path, st)
    return st


def _srv_log(name):
    return _srv_dir() / f"{_slug(name)}.log"


def _alive(pid):
    import psutil
    return bool(pid) and psutil.pid_exists(pid)


def server_status(name):
    import psutil, time
    st = _srv_state(name)
    pid, sup = st.get("pid"), st.get("sup")
    running = _alive(pid) and _alive(sup)
    out = {"name": name, "running": running, "restarts": st.get("restarts", 0), "status": st.get("status", "stopped") if running or st.get("status") == "gave up" else "stopped"}
    if running:
        try:
            procs = [psutil.Process(pid)] + psutil.Process(pid).children(recursive=True)
            out.update(uptime=time.time() - st.get("started", time.time()), pid=pid,
                       mem=sum(p.memory_info().rss for p in procs), cpu=sum(_proc_cpu(p) for p in procs) / (psutil.cpu_count() or 1))
        except psutil.Error:
            pass
    return out


_PCACHE = {}


def _proc_cpu(p):
    """cpu% needs the same Process object across calls (UI polls from fresh threads)."""
    import psutil
    key = (p.pid, p.create_time())
    proc = _PCACHE.setdefault(key, p)
    try:
        return proc.cpu_percent(None)
    except psutil.Error:
        return 0.0


def server_supervise(name):
    """Runs detached: starts the server, restarts it if it crashes (max 5 times in 10 minutes), logs everything."""
    import time
    import threading
    cfg, stop_flag, restarts = _srv(name), _srv_dir() / f"{_slug(name)}.stop", []
    queue = _srv_dir() / f"{_slug(name)}.cmd"
    stop_flag.unlink(missing_ok=True)
    queue.unlink(missing_ok=True)

    def feed(p):
        """Forward console commands from the UI, and the graceful stop command (e.g. Minecraft `stop`) when asked to stop."""
        sent_stop = False
        while p.poll() is None:
            try:
                if queue.exists():
                    lines = queue.read_text(encoding="utf-8")
                    queue.unlink()
                    p.stdin.write(lines.encode())
                    p.stdin.flush()
                if stop_flag.exists() and cfg.get("stop_cmd") and not sent_stop:
                    p.stdin.write((cfg["stop_cmd"] + "\n").encode())
                    p.stdin.flush()
                    sent_stop = True
            except OSError:
                pass
            time.sleep(0.3)

    with open(_srv_log(name), "ab", buffering=0) as log:
        while True:
            log.write(f"\n[multit {time.strftime('%Y-%m-%d %H:%M:%S')}] starting: {cfg['cmd']}\n".encode())
            p = subprocess.Popen(cfg["cmd"], cwd=cfg.get("cwd") or None, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.PIPE,
                                 creationflags=NO_WINDOW)
            threading.Thread(target=feed, args=(p,), daemon=True).start()
            _srv_state(name, pid=p.pid, sup=os.getpid(), started=time.time(), status="running", restarts=len(restarts))
            code = p.wait()
            log.write(f"[multit {time.strftime('%H:%M:%S')}] server exited with code {code}\n".encode())
            if stop_flag.exists() or not cfg.get("restart"):
                _srv_state(name, pid=None, sup=None, status="stopped")
                break
            restarts = [t for t in restarts if time.time() - t < 600] + [time.time()]
            if len(restarts) > 5:
                log.write(b"[multit] crashed 5 times in 10 minutes - giving up\n")
                _srv_state(name, pid=None, sup=None, status="gave up")
                break
            log.write(f"[multit] crashed - restarting in {cfg.get('delay', 3)} s (restart {len(restarts)})\n".encode())
            time.sleep(cfg.get("delay", 3))
    stop_flag.unlink(missing_ok=True)


def server_start(name):
    if server_status(name)["running"]:
        raise ValueError(f"{name} is already running")
    _srv(name)
    me = [sys.executable] if FROZEN else [sys.executable, str(Path(__file__).resolve())]
    subprocess.Popen([*me, "server", "supervise", name], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=NO_WINDOW | 0x200, close_fds=True)  # 0x200: own process group, survives MultiT closing


def server_send(name, line):
    """Type a command into a running server's console (picked up by its supervisor)."""
    if not server_status(name)["running"]:
        raise ValueError(f"{name} isn't running")
    with open(_srv_dir() / f"{_slug(name)}.cmd", "a", encoding="utf-8") as f:
        f.write(line.rstrip("\r\n") + "\n")


def server_stop(name, grace=45):
    """Graceful first (the server's own stop command, so worlds get saved), hard kill after `grace` seconds."""
    import psutil, time
    st, cfg = _srv_state(name), next((s for s in servers() if s["name"] == name), {})
    (_srv_dir() / f"{_slug(name)}.stop").write_text("stop")
    if cfg.get("stop_cmd") and _alive(st.get("pid")):
        print(f"asking {name} to shut down cleanly ({cfg['stop_cmd']})...", flush=True)
        t0 = time.time()
        while _alive(st.get("pid")) and time.time() - t0 < grace:
            time.sleep(0.5)
    if _alive(st.get("pid")):
        procs = [psutil.Process(st["pid"])] + psutil.Process(st["pid"]).children(recursive=True)
        for p in procs:
            try:
                p.terminate()
            except psutil.Error:
                pass
        _, alive = psutil.wait_procs(procs, timeout=8)
        for p in alive:
            try:
                p.kill()
            except psutil.Error:
                pass
    for _ in range(50):  # let the supervisor notice and record "stopped"
        if not _alive(_srv_state(name).get("sup")):
            break
        time.sleep(0.1)
    _srv_state(name, pid=None, sup=None, status="stopped")


def server_log_tail(name, max_bytes=64 << 10):
    p = _srv_log(name)
    if not p.exists():
        return ""
    with open(p, "rb") as f:
        f.seek(max(0, p.stat().st_size - max_bytes))
        return f.read().decode("utf-8", "replace")


def cmd_server(a):
    if a.action == "supervise":
        return server_supervise(a.name)
    if a.action == "list":
        for s in servers():
            st = server_status(s["name"])
            extra = f"  pid {st['pid']}  up {st['uptime'] / 60:.0f} min  {human(st.get('mem', 0))}" if st["running"] else ""
            print(f"  {s['name']:<16} {st['status']:<9}{extra}\n      {s['cmd']}" + (f"   (in {s['cwd']})" if s.get("cwd") else ""))
        print("" if servers() else '  no servers - multit server add NAME "command" --cwd DIR [--restart]')
        return
    if a.action == "add":
        if not (a.name and a.cmd):
            sys.exit('usage: multit server add NAME "command line" [--cwd DIR] [--restart]')
        _save(STATE_DIR / "servers.json", [s for s in servers() if s["name"] != a.name] +
              [{"name": a.name, "cmd": a.cmd, "cwd": os.path.abspath(a.cwd) if a.cwd else None, "restart": a.restart}])
        return print(f"OK  server '{a.name}' saved")
    if a.action == "remove":
        if server_status(a.name)["running"]:
            server_stop(a.name)
        _save(STATE_DIR / "servers.json", [s for s in servers() if s["name"] != a.name])
        return print(f"OK  '{a.name}' removed")
    try:
        if a.action in ("stop", "restart"):
            server_stop(a.name)
            print(f"stopped {a.name}")
        if a.action in ("start", "restart"):
            server_start(a.name)
            print(f"OK  {a.name} started in the background - log: {_srv_log(a.name)}")
        if a.action == "log":
            print(server_log_tail(a.name)[-8000:])
        if a.action == "send":
            server_send(a.name, a.cmd or sys.exit('usage: multit server send NAME "command"'))
            print("sent")
    except ValueError as e:
        sys.exit(str(e))


# ---------------------------------------------------------------- server creator (platform -> framework -> download + config + Server panel)

def _getjson(url):
    with urlopen(Request(url, headers={**UA, "Accept": "application/json"}), timeout=30) as r:
        return json.load(r)


def download(url, dest, label=None):
    """Stream a URL to a file with a live % line. Writes to .part first, so a half download never looks finished."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    with urlopen(Request(url, headers=UA), timeout=60) as r, open(tmp, "wb") as f:
        total, n = int(r.headers.get("Content-Length") or 0), 0
        while chunk := r.read(1 << 20):
            f.write(chunk)
            n += len(chunk)
            print(f"\r  {label or dest.name}  " + (f"{n * 100 // total}%  " if total else "") + f"{human(n)}" + (f" / {human(total)}" if total else "") + "   ",
                  end="", flush=True)
    os.replace(tmp, dest)
    print()
    return dest


def _unzip(archive, into, strip_top=False):
    """Extract a zip. strip_top: drop the single top-level folder GitHub source zips have."""
    import zipfile
    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
        top = names[0].split("/")[0] + "/" if strip_top and all(n.startswith(names[0].split("/")[0] + "/") for n in names) else ""
        for m in z.infolist():
            rel = m.filename[len(top):]
            if not rel or ".." in Path(rel).parts:
                continue
            out = Path(into, rel)
            if m.is_dir():
                out.mkdir(parents=True, exist_ok=True)
            else:
                out.parent.mkdir(parents=True, exist_ok=True)
                with z.open(m) as src, open(out, "wb") as dst:
                    shutil.copyfileobj(src, dst)


# --- Java (Minecraft 26.x needs Java 25)

def java_installs():
    """-> [(major, path to java.exe)], newest first."""
    cands = {shutil.which("java")} | set(glob.glob(r"C:\Program Files\*\jdk-*\bin\java.exe")) | set(glob.glob(r"C:\Program Files\*\*\jdk-*\bin\java.exe")) \
        | set(glob.glob(r"C:\Program Files\Java\*\bin\java.exe"))
    out = {}
    for c in filter(None, cands):
        r = run([c, "-version"], check=False, capture=True)
        m = re.search(r'version "(\d+)(?:\.(\d+))?', r.stderr + r.stdout)
        if m:
            major = int(m.group(2)) if m.group(1) == "1" else int(m.group(1))  # "1.8.0" -> 8
            out[os.path.realpath(c)] = major
    return sorted(((v, k) for k, v in out.items()), reverse=True)


def java_for(major, install=False):
    """A java.exe that can run Minecraft needing `major`. Optionally installs Temurin <major> via winget."""
    ok = [p for v, p in java_installs() if v >= major]
    if ok:
        return ok[-1] if len(ok) > 1 else ok[0]
    if not install:
        raise ValueError(f"this Minecraft version needs Java {major}+ (newest installed: "
                         f"{java_installs()[0][0] if java_installs() else 'none'}) - tick 'install Java' or run: winget install EclipseAdoptium.Temurin.{major}.JDK")
    print(f"installing Java {major} (Eclipse Temurin)...", flush=True)
    run([need("winget"), "install", "-e", "--id", f"EclipseAdoptium.Temurin.{major}.JDK", "--silent",
         "--accept-package-agreements", "--accept-source-agreements", "--disable-interactivity"], check=False)
    ok = [p for v, p in java_installs() if v >= major]
    if not ok:
        raise ValueError(f"Java {major} install didn't work - install it from Toolchains and retry")
    return ok[0]


# --- Minecraft

def _mojang_version(mc):
    man = _getjson("https://piston-meta.mojang.com/mc/game/version_manifest_v2.json")
    v = next((x for x in man["versions"] if x["id"] == mc), None)
    if not v:
        raise ValueError(f"unknown Minecraft version {mc}")
    return _getjson(v["url"])


def mc_versions(fw):
    """Newest-first versions for a Minecraft framework (what the version dropdown shows)."""
    stable = lambda s: not re.search(r"(rc|pre|snapshot|beta|alpha)", s, re.I)
    if fw == "vanilla":
        return [v["id"] for v in _getjson("https://piston-meta.mojang.com/mc/game/version_manifest_v2.json")["versions"] if v["type"] == "release"][:25]
    if fw == "paper":
        return [v for group in _getjson("https://fill.papermc.io/v3/projects/paper")["versions"].values() for v in group if stable(v)][:25]
    if fw == "purpur":
        return list(reversed(_getjson("https://api.purpurmc.org/v2/purpur")["versions"]))[:25]
    if fw == "fabric":
        return [v["version"] for v in _getjson("https://meta.fabricmc.net/v2/versions/game") if v["stable"]][:25]
    if fw == "forge":
        promos, seen = _getjson("https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json")["promos"], []
        for k in reversed(list(promos)):
            mc = k.rsplit("-", 1)[0]
            if mc not in seen:
                seen.append(mc)
        return seen[:25]
    if fw == "neoforge":
        return [v for v in reversed(_getjson("https://maven.neoforged.net/api/maven/versions/releases/net/neoforged/neoforge")["versions"]) if stable(v)][:25]
    raise ValueError(fw)


def _neoforge_mc(nf):
    """NeoForge 21.1.77 -> MC 1.21.1 ; 26.3.0.86 -> MC 26.3 (new year-based numbering)."""
    p = nf.split(".")
    if int(p[0]) >= 26:
        return f"{p[0]}.{p[1]}" + (f".{p[2]}" if p[2] != "0" else "")
    return f"1.{p[0]}" + (f".{p[1]}" if p[1] != "0" else "")


def _mc_create(dest, fw, version, ram, eula, install_java):
    version = version or mc_versions(fw)[0]
    mc = _neoforge_mc(version) if fw == "neoforge" else version
    need_java = _mojang_version(mc).get("javaVersion", {}).get("majorVersion", 21)
    java = java_for(need_java, install_java)
    print(f"Minecraft {mc} · {fw} {version if fw in ('forge', 'neoforge') else ''} · Java {need_java}+ -> {java}", flush=True)
    jar = "server.jar"
    if fw == "vanilla":
        download(_mojang_version(mc)["downloads"]["server"]["url"], dest / jar)
    elif fw == "paper":
        builds = _getjson(f"https://fill.papermc.io/v3/projects/paper/versions/{mc}/builds")
        b = next((x for x in builds if x.get("channel") == "STABLE"), builds[0])
        download(b["downloads"]["server:default"]["url"], dest / jar)
    elif fw == "purpur":
        download(f"https://api.purpurmc.org/v2/purpur/{mc}/latest/download", dest / jar)
    elif fw == "fabric":
        loader = next(x["version"] for x in _getjson("https://meta.fabricmc.net/v2/versions/loader") if x["stable"])
        inst = next(x["version"] for x in _getjson("https://meta.fabricmc.net/v2/versions/installer") if x["stable"])
        download(f"https://meta.fabricmc.net/v2/versions/loader/{mc}/{loader}/{inst}/server/jar", dest / jar)
    elif fw in ("forge", "neoforge"):
        if fw == "forge":
            promos = _getjson("https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json")["promos"]
            fv = promos.get(f"{mc}-recommended") or promos[f"{mc}-latest"]
            url = f"https://maven.minecraftforge.net/net/minecraftforge/forge/{mc}-{fv}/forge-{mc}-{fv}-installer.jar"
        else:
            url = f"https://maven.neoforged.net/releases/net/neoforged/neoforge/{version}/neoforge-{version}-installer.jar"
        inst = download(url, dest / "installer.jar")
        print("running the installer (downloads libraries)...", flush=True)
        r = run([java, "-jar", inst, "--installServer"], cwd=dest, check=False)
        if r.returncode or not (dest / "run.bat").exists():
            raise ValueError("the Forge/NeoForge installer failed - see above")
        inst.unlink(missing_ok=True)
        # their run.bat ends with `pause` (would hang on stop) and uses whatever `java` is on PATH: write our own line
        line = next(l for l in (dest / "run.bat").read_text().splitlines() if l.strip().lower().startswith("java "))
        launch = f'"{java}" -Xms1G -Xmx{ram}G' + line.strip()[4:].replace("%*", "") + " nogui"
    (dest / "eula.txt").write_text(f"# accepted in MultiT on {__import__('time').strftime('%Y-%m-%d')}: https://aka.ms/MinecraftEULA\neula={'true' if eula else 'false'}\n")
    (dest / "server.properties").write_text("motd=\\u00a7aMultiT \\u00a77server\nserver-port=25565\n")
    if fw not in ("forge", "neoforge"):
        launch = f'"{java}" -Xms1G -Xmx{ram}G -jar {jar} nogui'
    return {"launch": launch, "stop_cmd": "stop", "port": 25565,
            "notes": [] if eula else ["Minecraft won't start until you accept the EULA: set eula=true in eula.txt"]}


# --- FiveM

def _fivem_create(dest, fw, license_key):
    v = _getjson("https://changelogs-live.fivem.net/api/changelog/versions/win32/server")
    print(f"FiveM server build {v['recommended']} (recommended)", flush=True)
    art = download(v["recommended_download"], dest / "artifacts.zip", "FXServer")
    _unzip(art, dest / "server")
    art.unlink()
    exe = dest / "server" / "FXServer.exe"
    if fw == "txadmin":  # txAdmin's web wizard deploys ESX / QBCore / Qbox recipes incl. the database
        return {"launch": f'"{exe}"', "stop_cmd": "quit", "port": 30120, "open": "http://localhost:40120",
                "notes": ["Start it, then open http://localhost:40120 - the PIN is shown in the log.",
                          "In the txAdmin setup pick a recipe: ESX Legacy, QBCore or Qbox. It installs the framework and its database."]}
    data = dest / "server-data"
    _unzip(download("https://github.com/citizenfx/cfx-server-data/archive/refs/heads/master.zip", dest / "data.zip", "cfx-server-data"), data, strip_top=True)
    (dest / "data.zip").unlink()
    ensure = ["mapmanager", "chat", "spawnmanager", "sessionmanager", "basic-gamemode", "hardcap"]
    if fw in ("esx", "qbcore", "qbox"):
        fwdir = data / "resources" / "[framework]"
        for repo, asset in (("overextended/oxmysql", "oxmysql.zip"), ("overextended/ox_lib", "ox_lib.zip")):
            _unzip(download(f"https://github.com/{repo}/releases/latest/download/{asset}", dest / asset), fwdir)
            (dest / asset).unlink()
        src = {"esx": f"https://github.com/esx-framework/esx_core/archive/refs/tags/{_getjson('https://api.github.com/repos/esx-framework/esx_core/releases/latest')['tag_name']}.zip",
               "qbcore": "https://github.com/qbcore-framework/qb-core/archive/refs/heads/main.zip",
               "qbox": "https://github.com/Qbox-project/qbx_core/releases/latest/download/qbx_core.zip"}[fw]
        z = download(src, dest / "fw.zip", fw)
        _unzip(z, fwdir / ({"qbcore": "qb-core", "qbox": ""}.get(fw, "esx_core")), strip_top=fw != "qbox")
        z.unlink()
        ensure += ["oxmysql", "ox_lib"] + {"esx": ["es_extended"], "qbcore": ["qb-core"], "qbox": ["qbx_core"]}[fw]
    cfg = [
        "# generated by MultiT", 'endpoint_add_tcp "0.0.0.0:30120"', 'endpoint_add_udp "0.0.0.0:30120"',
        *[f"ensure {r}" for r in ensure],
        'sv_hostname "MultiT FiveM server"', "sv_maxclients 32", "sv_enforceGameBuild 3258",
        f'sv_licenseKey "{license_key or "PUT_YOUR_KEY_FROM_portal.cfx.re_HERE"}"',
        "set onesync on",
    ]
    if fw in ("esx", "qbcore", "qbox"):
        cfg += ['set mysql_connection_string "mysql://root@localhost/fivem?charset=utf8mb4"']
    (data / "server.cfg").write_text("\n".join(cfg) + "\n")
    notes = [] if license_key else ["Add your free license key from https://portal.cfx.re to server-data\\server.cfg (sv_licenseKey)."]
    if fw in ("esx", "qbcore", "qbox"):
        notes.append("Core only: needs a MySQL/MariaDB database (winget install MariaDB.Server) - import the framework's .sql, then add the rest of its resources. txAdmin does all of this automatically.")
    return {"launch": f'cd /d "{data}" && "{exe}" +exec server.cfg', "stop_cmd": "quit", "port": 30120, "notes": notes}


# --- Steam dedicated servers (SteamCMD, anonymous login)

STEAM_GAMES = {  # key: (name, app id, exe relative to install dir, launch args)
    "valheim": ("Valheim", 896660, "valheim_server.exe", '-nographics -batchmode -name "MultiT Valheim" -port 2456 -world "Dedicated" -password "changeme123" -public 1'),
    "rust": ("Rust", 258550, "RustDedicated.exe", '-batchmode +server.port 28015 +server.hostname "MultiT Rust" +server.identity multit +server.maxplayers 50 +server.worldsize 3000 +rcon.port 28016 +rcon.password "changeme123"'),
    "palworld": ("Palworld", 2394010, "PalServer.exe", "-useperfthreads -NoAsyncLoadingThread -UseMultithreadForDS"),
    "cs2": ("Counter-Strike 2", 730, r"game\bin\win64\cs2.exe", "-dedicated +map de_dust2 +game_type 0 +game_mode 1"),
    "7dtd": ("7 Days to Die", 294420, "7DaysToDieServer.exe", "-quit -batchmode -nographics -configfile=serverconfig.xml -dedicated"),
    "gmod": ("Garry's Mod", 4020, "srcds.exe", "-console -game garrysmod +maxplayers 16 +map gm_construct"),
    "ark": ("ARK: Survival Ascended", 2430930, r"ShooterGame\Binaries\Win64\ArkAscendedServer.exe", "TheIsland_WP?listen?SessionName=MultiT -NoBattlEye"),
}


def _steam_create(dest, game):
    name, appid, exe, args = STEAM_GAMES[game]
    sc = dest / "steamcmd"
    _unzip(download("https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip", sc / "steamcmd.zip", "SteamCMD"), sc)
    (sc / "steamcmd.zip").unlink()
    print(f"downloading the {name} dedicated server with SteamCMD (can be several GB)...", flush=True)
    for attempt in (1, 2):  # SteamCMD updates itself on first run and sometimes exits early once
        run([sc / "steamcmd.exe", "+force_install_dir", dest / "server", "+login", "anonymous", "+app_update", appid, "validate", "+quit"], check=False)
        if (dest / "server" / exe).exists():
            break
    else:
        raise ValueError(f"SteamCMD didn't install {name} - see the output above")
    (dest / "update.bat").write_text(f'"{sc / "steamcmd.exe"}" +force_install_dir "{dest / "server"}" +login anonymous +app_update {appid} validate +quit\n')
    return {"launch": f'cd /d "{dest / "server"}" && "{dest / "server" / exe}" {args}', "stop_cmd": None, "port": None,
            "notes": ["Passwords and names in start.bat are placeholders - edit them.", "update.bat updates the server later."]}


# --- Terraria

def _terraria_create(dest, fw):
    world = dest / "worlds" / "MultiT.wld"
    cfg = f"world={world}\nautocreate=2\nworldname=MultiT\ndifficulty=0\nmaxplayers=8\nport=7777\npassword=\nworldpath={dest / 'worlds'}\n"
    (dest / "worlds").mkdir(parents=True, exist_ok=True)
    (dest / "serverconfig.txt").write_text(cfg)
    if fw == "vanilla":
        zipname = _getjson("https://terraria.org/api/get/dedicated-servers-names")[0]
        _unzip(download(f"https://terraria.org/api/download/pc-dedicated-server/{zipname}", dest / zipname), dest / "terraria")
        (dest / zipname).unlink()
        exe = next((dest / "terraria").rglob("Windows/TerrariaServer.exe"), None) or sys.exit("TerrariaServer.exe not found in the download")
        launch = f'"{exe}" -config "{dest / "serverconfig.txt"}"'
    else:
        _unzip(download("https://github.com/tModLoader/tModLoader/releases/latest/download/tModLoader.zip", dest / "tml.zip", "tModLoader"), dest / "tModLoader")
        (dest / "tml.zip").unlink()
        launch = f'cd /d "{dest / "tModLoader"}" && call start-tModLoaderServer.bat -nosteam -config "{dest / "serverconfig.txt"}"'
    return {"launch": launch, "stop_cmd": "exit", "port": 7777, "notes": ["A medium world called MultiT is created on first start."]}


# --- Discord bots / web apps (templates)

BOT_JS = """require('dotenv').config();
const { Client, GatewayIntentBits } = require('discord.js');
const client = new Client({ intents: [GatewayIntentBits.Guilds, GatewayIntentBits.GuildMessages, GatewayIntentBits.MessageContent] });
client.once('ready', () => console.log(`logged in as ${client.user.tag}`));
client.on('messageCreate', m => { if (m.content === '!ping') m.reply('pong 🏓'); });
client.login(process.env.DISCORD_TOKEN);
"""
BOT_PY = """import os
import discord
from dotenv import load_dotenv

load_dotenv()
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)


@client.event
async def on_ready():
    print(f"logged in as {client.user}", flush=True)


@client.event
async def on_message(m):
    if m.content == "!ping":
        await m.reply("pong 🏓")

client.run(os.environ["DISCORD_TOKEN"])
"""
EXPRESS_JS = """const express = require('express');
const app = express();
app.get('/', (req, res) => res.send('<h1>Hello from MultiT 🚀</h1>'));
app.get('/api/health', (req, res) => res.json({ ok: true, time: new Date() }));
const port = process.env.PORT || 3000;
app.listen(port, () => console.log(`listening on http://localhost:${port}`));
"""
FASTAPI_PY = """from fastapi import FastAPI

app = FastAPI(title="MultiT app")


@app.get("/")
def home():
    return {"hello": "from MultiT"}


@app.get("/api/health")
def health():
    return {"ok": True}
"""


def _node_project(dest, deps, main, code, env=None):
    (dest / main).write_text(code, encoding="utf-8")
    (dest / "package.json").write_text(json.dumps({"name": dest.name.lower().replace(" ", "-"), "version": "1.0.0", "main": main, "private": True,
                                                   "scripts": {"start": f"node {main}"}}, indent=2))
    if env:
        (dest / ".env").write_text(env)
        (dest / ".gitignore").write_text("node_modules/\n.env\n")
    print("npm install " + " ".join(deps), flush=True)
    r = run([need("npm", hint="node"), "install", "--no-fund", "--no-audit", *deps], cwd=dest, check=False)
    if r.returncode:
        raise ValueError("npm install failed - see above")
    return f'cd /d "{dest}" && "{need("node", hint="node")}" {main}'


def _py_project(dest, deps, main, code, env=None):
    (dest / main).write_text(code, encoding="utf-8")
    (dest / "requirements.txt").write_text("\n".join(deps) + "\n")
    if env:
        (dest / ".env").write_text(env)
        (dest / ".gitignore").write_text(".venv/\n.env\n__pycache__/\n")
    run([python_exe(), "-m", "venv", dest / ".venv"])
    run([dest / ".venv" / "Scripts" / "python.exe", "-m", "pip", "install", "-q", *deps])
    return dest / ".venv" / "Scripts" / "python.exe"


def _app_create(dest, platform, fw):
    if platform == "discord":
        env = "# paste your bot token from https://discord.com/developers/applications\nDISCORD_TOKEN=\n"
        if fw == "discordjs":
            launch = _node_project(dest, ["discord.js", "dotenv"], "index.js", BOT_JS, env)
        else:
            launch = f'cd /d "{dest}" && "{_py_project(dest, ["discord.py", "python-dotenv"], "bot.py", BOT_PY, env)}" bot.py'
        return {"launch": launch, "stop_cmd": None, "port": None, "notes": ["Paste your bot token into .env, then start it. Try !ping in your server."]}
    if fw == "express":
        return {"launch": _node_project(dest, ["express"], "server.js", EXPRESS_JS), "stop_cmd": None, "port": 3000, "open": "http://localhost:3000", "notes": []}
    py = _py_project(dest, ["fastapi", "uvicorn[standard]"], "main.py", FASTAPI_PY)
    return {"launch": f'cd /d "{dest}" && "{py}" -m uvicorn main:app --host 0.0.0.0 --port 8000', "stop_cmd": None, "port": 8000,
            "open": "http://localhost:8000/docs", "notes": []}


# --- the catalog the UI renders as cards

PLATFORMS = {
    "minecraft": {"name": "Minecraft", "tag": "Java Edition", "frameworks": {
        "paper": "Paper (fast, plugins)", "vanilla": "Vanilla", "purpur": "Purpur (Paper + extras)",
        "fabric": "Fabric (mods)", "forge": "Forge (mods)", "neoforge": "NeoForge (mods)"}},
    "fivem": {"name": "FiveM", "tag": "GTA V roleplay", "frameworks": {
        "txadmin": "txAdmin setup - ESX / QBCore / Qbox with database (recommended)", "vanilla": "Vanilla (cfx-server-data)",
        "esx": "ESX Legacy - core only", "qbcore": "QBCore - core only", "qbox": "Qbox - core only"}},
    "steam": {"name": "Steam games", "tag": "SteamCMD dedicated servers", "frameworks": {k: v[0] for k, v in STEAM_GAMES.items()}},
    "terraria": {"name": "Terraria", "tag": "dedicated server", "frameworks": {"vanilla": "Vanilla", "tmodloader": "tModLoader (mods)"}},
    "discord": {"name": "Discord bot", "tag": "bot template", "frameworks": {"discordjs": "discord.js (Node)", "discordpy": "discord.py (Python)"}},
    "web": {"name": "Web app", "tag": "API / website", "frameworks": {"express": "Express (Node)", "fastapi": "FastAPI (Python)"}},
}


def create_server(platform, fw, parent, name, version=None, ram=4, eula=False, install_java=False, license_key=None):
    if platform not in PLATFORMS or fw not in PLATFORMS[platform]["frameworks"]:
        raise ValueError(f"unknown platform/framework: {platform}/{fw}")
    if not name or re.search(r'[<>:"/\\|?*]', name):
        raise ValueError("give the server a simple name (no \\ / : * ? \" < > |)")
    dest = Path(os.path.abspath(parent)) / name
    if dest.exists() and any(dest.iterdir()):
        raise ValueError(f"{dest} already exists and isn't empty - pick another name or folder")
    if is_protected(dest) or any(n.lower() in PROTECTED for n in dest.parts[1:2]):
        raise ValueError(f"can't create a server in {dest}")
    if any(s["name"] == name for s in servers()):
        raise ValueError(f"a server called {name} already exists in the Server panel")
    dest.mkdir(parents=True, exist_ok=True)
    try:
        r = (_mc_create(dest, fw, version, ram, eula, install_java) if platform == "minecraft"
             else _fivem_create(dest, fw, license_key) if platform == "fivem"
             else _steam_create(dest, fw) if platform == "steam"
             else _terraria_create(dest, fw) if platform == "terraria"
             else _app_create(dest, platform, fw))
    except BaseException:
        if not any(p for p in dest.rglob("*") if p.is_file() and p.stat().st_size > 50 << 20):  # keep big finished downloads for a retry
            shutil.rmtree(dest, ignore_errors=True)
        raise
    (dest / "start.bat").write_text("@echo off\n" + r["launch"] + "\n")  # text mode turns \n into \r\n
    cfg = {"name": name, "cmd": f'"{dest / "start.bat"}"', "cwd": str(dest), "restart": platform != "discord",
           "stop_cmd": r.get("stop_cmd"), "platform": platform, "framework": fw, "port": r.get("port"), "open": r.get("open")}
    _save(STATE_DIR / "servers.json", [s for s in servers() if s["name"] != name] + [cfg])
    return {"dest": str(dest), **r}


def cmd_create(a):
    if a.platform == "list":
        for k, p in PLATFORMS.items():
            print(f"  {k:<10} {p['name']:<14} " + ", ".join(p["frameworks"]))
        return
    try:
        r = create_server(a.platform, a.framework, a.dir, a.name, a.version, a.ram, a.accept_eula, a.install_java, os.environ.get("MULTIT_FIVEM_KEY"))
    except ValueError as e:
        sys.exit(str(e))
    print(f"\nOK  {a.name} is ready in {r['dest']} and added to the Server panel" + (f" (port {r['port']})" if r.get("port") else ""))
    for n in r.get("notes", []):
        print(f"  · {n}")


# ---------------------------------------------------------------- cli

def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:  # no arguments (e.g. double-clicked MultiT.exe) -> open the UI
        from gui import start
        return start()
    p = argparse.ArgumentParser(prog="multit", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="build a project/file into an .exe (language autodetected)")
    b.add_argument("path", nargs="?", default=".")
    b.add_argument("-o", "--out", help="output folder (default: <project>/dist)")
    b.add_argument("-n", "--name", help="exe name (default: folder/file name)")
    b.add_argument("--gui", action="store_true", help="no console window (python/go/java)")
    b.add_argument("--icon", help=".ico file (python)")
    b.add_argument("--data", action="append", default=[], help="python: extra file/folder to bundle (repeatable)")
    b.add_argument("--venv", action="store_true", help="python: build in a fresh isolated venv (project .venv is always used if present)")
    b.set_defaults(fn=cmd_build)

    e = sub.add_parser("venv", help="create/update a project .venv and install its requirements")
    e.add_argument("path", nargs="?", default=".")
    e.add_argument("packages", nargs="*", help="extra packages to install")
    e.set_defaults(fn=cmd_venv)

    d = sub.add_parser("detect", help="show detected language/entry without building")
    d.add_argument("path", nargs="?", default=".")
    d.set_defaults(fn=cmd_detect)

    v = sub.add_parser("vm", help="VirtualBox/VMware VMs: setup|create|list|start|stop|snap|restore|delete")
    v.add_argument("action", choices=["setup", "create", "list", "start", "stop", "snap", "restore", "delete", "devtools"])
    v.add_argument("--dev", action="store_true", help="create: also install Python + coder essentials in the VM")
    v.add_argument("name", nargs="?")
    v.add_argument("label", nargs="?", help="snapshot name for snap/restore")
    v.add_argument("--iso")
    v.add_argument("--mem", type=int, default=4096, help="MB (default 4096)")
    v.add_argument("--cpus", type=int, default=2)
    v.add_argument("--disk", type=int, default=50, help="GB (default 50, grows on demand)")
    v.add_argument("--user", default="user")
    v.add_argument("--password", help="default: random, printed at the end")
    v.add_argument("--manual", action="store_true", help="skip unattended install, just boot the ISO")
    v.add_argument("--headless", action="store_true")
    v.add_argument("--force", action="store_true", help="stop: hard power off")
    v.add_argument("--yes", action="store_true", help="delete: skip confirmation")
    v.add_argument("--vmware", action="store_true", help="use VMware Workstation (auto if VirtualBox isn't installed)")
    v.add_argument("--vbox", action="store_true", help="force VirtualBox")
    v.add_argument("--os", help="VMware guestOS id override, e.g. windows11-64, ubuntu-64")
    v.set_defaults(fn=cmd_vm)

    i = sub.add_parser("iso", help="download the latest ISO of 20 popular OSes")
    i.add_argument("action", choices=["list", "get", "url"])
    i.add_argument("os", nargs="?", choices=list(ISOS), metavar="OS", help="see: multit iso list")
    i.set_defaults(fn=cmd_iso)

    sub.add_parser("doctor", help="list installed toolchains").set_defaults(fn=cmd_doctor)

    ins = sub.add_parser("install", help="install dev tools via winget (see `multit doctor` for keys)")
    ins.add_argument("tools", nargs="+", metavar="TOOL")
    ins.add_argument("--update", action="store_true", help="upgrade instead of install")
    ins.set_defaults(fn=cmd_install)

    po = sub.add_parser("ports", help="list listening ports / kill what holds one")
    po.add_argument("port", nargs="?", type=int)
    po.add_argument("--kill", action="store_true")
    po.set_defaults(fn=cmd_ports)

    s = sub.add_parser("serve", help="share a folder over HTTP")
    s.add_argument("dir", nargs="?", default=".")
    s.add_argument("-p", "--port", type=int, default=8000)
    s.set_defaults(fn=cmd_serve)

    h = sub.add_parser("hash", help="sha256/sha1/md5 of a file")
    h.add_argument("file")
    h.add_argument("--check", help="expected hash; exit 1 on mismatch")
    h.set_defaults(fn=cmd_hash)

    cu = sub.add_parser("cleanup", help="free disk space: temp, caches, update leftovers, dev caches (scan only without args)")
    cu.add_argument("keys", nargs="*", metavar="KEY", help="categories to clean (see scan)")
    cu.add_argument("--all", action="store_true", help="clean every category marked *")
    cu.set_defaults(fn=cmd_cleanup)

    md = sub.add_parser("models", help="AI models: list (with duplicates), move to another drive, restore")
    md.add_argument("action", nargs="?", choices=["list", "move", "restore"], default="list")
    md.add_argument("path", nargs="?", help="list: extra folder to scan · move/restore: the model folder")
    md.add_argument("dest", nargs="?", help="move: destination folder on another drive")
    md.set_defaults(fn=cmd_models)

    vd = sub.add_parser("video", help="ffmpeg helpers: compress to a size, trim, gif, mp3, mp4, batch")
    vd.add_argument("action", choices=["info", "compress", "trim", "gif", "mp3", "mp4", "batch"])
    vd.add_argument("path", help="video file (batch: folder)")
    vd.add_argument("--size", type=float, default=10, help="compress/batch: target MB (Discord: 10, Nitro Basic: 50)")
    vd.add_argument("--start", help="from, e.g. 0:05")
    vd.add_argument("--end", help="to, e.g. 0:20")
    vd.add_argument("--width", type=int, default=480, help="gif width")
    vd.add_argument("--fps", type=int, default=15, help="gif fps")
    vd.set_defaults(fn=cmd_video)

    cr = sub.add_parser("create", help="create a game/app server: download + config + add to the Server panel")
    cr.add_argument("platform", choices=[*PLATFORMS, "list"])
    cr.add_argument("framework", nargs="?")
    cr.add_argument("--dir", default=str(Path.home() / "Servers"), help="parent folder (default ~/Servers)")
    cr.add_argument("--name")
    cr.add_argument("--version", help="minecraft: game version (default newest)")
    cr.add_argument("--ram", type=int, default=4, help="minecraft: GB of RAM")
    cr.add_argument("--accept-eula", action="store_true", help="minecraft: you accept https://aka.ms/MinecraftEULA")
    cr.add_argument("--install-java", action="store_true", help="minecraft: install the Java it needs if missing")
    cr.set_defaults(fn=cmd_create)

    sv = sub.add_parser("server", help="run servers in the background with logs and auto-restart")
    sv.add_argument("action", choices=["list", "add", "remove", "start", "stop", "restart", "log", "send", "supervise"])
    sv.add_argument("name", nargs="?")
    sv.add_argument("cmd", nargs="?", help='add: the command line, quoted')
    sv.add_argument("--cwd", help="add: working folder")
    sv.add_argument("--restart", action="store_true", help="add: restart automatically if it crashes")
    sv.set_defaults(fn=cmd_server)

    va = sub.add_parser("vault", help="encrypt any folder with your own password (same engine as usb)")
    va.add_argument("action", choices=["list", "lock", "unlock", "passwd", "forget"])
    va.add_argument("path", nargs="?")
    va.set_defaults(fn=cmd_vault)

    bo = sub.add_parser("boot", help="bootable USB via Ventoy: install once, then add ISOs")
    bo.add_argument("action", choices=["list", "setup", "install", "add"])
    bo.add_argument("drive", nargs="?")
    bo.add_argument("iso", nargs="?", help="add: .iso file or OS name from `iso list`")
    bo.add_argument("--erase", metavar="DRIVE", help="install: repeat the drive letter to confirm wiping it")
    bo.set_defaults(fn=cmd_boot)

    up = sub.add_parser("update", help="update installed apps via winget (lists them without args)")
    up.add_argument("ids", nargs="*", metavar="ID")
    up.add_argument("--all", action="store_true")
    up.set_defaults(fn=cmd_update)

    bk = sub.add_parser("backup", help="folder backup jobs (robocopy), optionally scheduled")
    bk.add_argument("action", choices=["list", "add", "run", "remove"])
    bk.add_argument("name", nargs="?")
    bk.add_argument("src", nargs="?")
    bk.add_argument("dst", nargs="?")
    bk.add_argument("--mirror", action="store_true", help="also delete files from the backup that were deleted from the source")
    bk.add_argument("--schedule", choices=["off", "daily", "hourly", "logon"], default="off")
    bk.add_argument("--at", default="20:00", help="time for daily jobs (HH:MM)")
    bk.set_defaults(fn=cmd_backup)

    bs = sub.add_parser("boost", help="game booster: High performance power plan + close apps you pick")
    bs.add_argument("action", choices=["on", "off", "status"])
    bs.add_argument("--apps", nargs="*", default=[], help="process names to close, e.g. Discord.exe chrome.exe")
    bs.add_argument("--no-reopen", action="store_true", help="off: don't reopen the closed apps")
    bs.set_defaults(fn=cmd_boost)

    us = sub.add_parser("usb", help="encrypt / decrypt USB drives with your own password (AES-256-GCM)")
    us.add_argument("action", choices=["list", "lock", "unlock", "passwd", "speed"])
    us.add_argument("drive", nargs="?", help="e.g. E:")
    us.set_defaults(fn=cmd_usb)

    tp = sub.add_parser("top", help="CPU / RAM and the heaviest processes")
    tp.add_argument("--sort", choices=["cpu", "mem"], default="cpu")
    tp.add_argument("-n", type=int, default=15)
    tp.set_defaults(fn=cmd_top)

    su = sub.add_parser("startup", help="list / enable / disable startup apps (like Task Manager)")
    su.add_argument("action", nargs="?", choices=["list", "enable", "disable"], default="list")
    su.add_argument("name", nargs="?")
    su.set_defaults(fn=cmd_startup)

    pa = sub.add_parser("path", help="PATH doctor: show dead/duplicate entries, clean or edit your user PATH")
    pa.add_argument("--fix", action="store_true", help="remove dead & duplicate user PATH entries (backed up first)")
    pa.add_argument("--add", metavar="DIR")
    pa.add_argument("--remove", metavar="ENTRY")
    pa.set_defaults(fn=cmd_path)

    dp = sub.add_parser("dupes", help="find duplicate files")
    dp.add_argument("path")
    dp.add_argument("--min", type=float, default=1, help="minimum size in MB (default 1)")
    dp.add_argument("--top", type=int, default=20)
    dp.set_defaults(fn=cmd_dupes)

    rp = sub.add_parser("repos", help="status of every git repo under a folder")
    rp.add_argument("path", nargs="?", default=str(Path.home() / "Documents"))
    rp.add_argument("--fetch", action="store_true", help="git fetch first (accurate ahead/behind)")
    rp.add_argument("--pull", action="store_true", help="fast-forward pull every clean repo that's behind")
    rp.set_defaults(fn=cmd_repos)

    du = sub.add_parser("du", help="what's using space in a folder/drive (system & program folders hidden)")
    du.add_argument("path", nargs="?", default=os.environ.get("SystemDrive", "C:") + "\\")
    du.add_argument("--system", action="store_true", help="include Windows / Program Files / system files")
    du.add_argument("--top", type=int, default=20)
    du.set_defaults(fn=cmd_du)

    c = sub.add_parser("clean", help="remove build junk (dry run unless --yes)")
    c.add_argument("path", nargs="?", default=".")
    c.add_argument("--yes", action="store_true")
    c.set_defaults(fn=cmd_clean)

    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
