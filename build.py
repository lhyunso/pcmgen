"""
PCM Channel Config Generator - Cross-platform Build Script
Creates standalone executable using PyInstaller.
Supports: macOS (.app), Windows (.exe), Linux
(c) 2025 단암시스템즈 (Danam Systems)
"""
import os
import sys
import shutil
import subprocess
import platform


APP_NAME = "PCM_Generator"
MAIN_SCRIPT = "main.py"
UI_DIR = "ui"
ICON_MAC = None  # Set to .icns path if available
ICON_WIN = None  # Set to .ico path if available


def check_python():
    ver = sys.version_info
    if ver < (3, 9):
        print(f"[ERROR] Python 3.9+ required (found {ver.major}.{ver.minor})")
        sys.exit(1)
    print(f"[OK] Python {ver.major}.{ver.minor}.{ver.micro}")
    print(f"[OK] Platform: {platform.platform()}")
    print(f"[OK] Executable: {sys.executable}")


def install_deps():
    print("\n[1/4] Installing dependencies...")
    deps = ["pyinstaller", "pywebview>=4.0", "openpyxl>=3.1.0"]

    # Windows: pywebview needs EdgeChromium backend
    if sys.platform == "win32":
        deps.extend(["pythonnet", "clr-loader"])

    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--upgrade"] + deps,
            stdout=subprocess.DEVNULL if sys.platform != "win32" else None,
        )
        print("  Dependencies installed.")
    except subprocess.CalledProcessError as e:
        print(f"  [WARN] pip install returned error, continuing... ({e})")


def clean():
    print("\n[2/4] Cleaning previous build...")
    for d in ["build", "dist"]:
        if os.path.isdir(d):
            shutil.rmtree(d)
    for f in os.listdir("."):
        if f.endswith(".spec"):
            os.remove(f)
    print("  Clean complete.")


def build():
    print("\n[3/4] Building standalone application...")
    plat = sys.platform

    # Data separator: ; on Windows, : on Unix
    sep = ";" if plat == "win32" else ":"

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", APP_NAME,
        "--windowed",
        "--noconfirm",
        "--clean",
        f"--add-data={UI_DIR}{sep}{UI_DIR}",
    ]

    if plat == "darwin":
        cmd.append("--onedir")
        cmd.extend([
            "--osx-bundle-identifier", "com.danamsystems.pcmgenerator",
        ])
        if ICON_MAC and os.path.isfile(ICON_MAC):
            cmd.extend(["--icon", ICON_MAC])
        cmd.extend(["--collect-all", "webview"])

    elif plat == "win32":
        cmd.append("--onefile")
        if ICON_WIN and os.path.isfile(ICON_WIN):
            cmd.extend(["--icon", ICON_WIN])

        cmd.extend([
            "--collect-all", "webview",
            "--hidden-import", "clr_loader",
            "--hidden-import", "pythonnet",
            "--hidden-import", "webview.platforms.edgechromium",
            "--hidden-import", "webview.platforms.mshtml",
        ])

    else:
        cmd.append("--onefile")
        cmd.extend(["--collect-all", "webview"])

    cmd.append(MAIN_SCRIPT)

    print(f"  Command:")
    print(f"    {' '.join(cmd)}")
    print()

    subprocess.check_call(cmd)
    print("\n  Build complete.")


def post_build():
    print("\n[4/4] Post-build summary")
    plat = sys.platform

    if plat == "darwin":
        app_path = os.path.join("dist", f"{APP_NAME}.app")
        exe_path = os.path.join("dist", APP_NAME, APP_NAME)
        print(f"\n  macOS App Bundle: {app_path}")
        print(f"  Run:  open {app_path}")
        print(f"\n  DMG 생성:")
        print(f"    hdiutil create -volname {APP_NAME} -srcfolder dist/{APP_NAME}.app "
              f"-ov -format UDZO dist/{APP_NAME}.dmg")

    elif plat == "win32":
        exe_path = os.path.join("dist", f"{APP_NAME}.exe")
        if os.path.isfile(exe_path):
            size_mb = os.path.getsize(exe_path) / 1024 / 1024
            print(f"\n  Windows Executable: {exe_path}")
            print(f"  Size: {size_mb:.1f} MB")
            print(f"\n  배포: {APP_NAME}.exe 파일만 복사하면 됩니다.")
            print(f"  대상 PC에 Python 설치 불필요.")
        else:
            print(f"\n  [WARN] {exe_path} not found")

    else:
        exe_path = os.path.join("dist", APP_NAME)
        print(f"\n  Linux Executable: {exe_path}")

    # Total dist size
    total = 0
    for root, dirs, files in os.walk("dist"):
        for f in files:
            total += os.path.getsize(os.path.join(root, f))
    print(f"  Total dist size: {total / 1024 / 1024:.1f} MB")


def main():
    # Change to script directory (important for double-click on Windows)
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    print("=" * 50)
    print(f"  {APP_NAME} - Build")
    print(f"  (c) 2025 단암시스템즈 (Danam Systems)")
    print("=" * 50)

    if not os.path.isfile(MAIN_SCRIPT):
        print(f"\n[ERROR] {MAIN_SCRIPT} not found in {os.getcwd()}")
        print("  build.py must be in the project root directory.")
        sys.exit(1)

    if not os.path.isdir(UI_DIR):
        print(f"\n[ERROR] {UI_DIR}/ directory not found in {os.getcwd()}")
        sys.exit(1)

    check_python()
    install_deps()
    clean()
    build()
    post_build()

    print("\n" + "=" * 50)
    print("  BUILD SUCCESS")
    print("=" * 50)


if __name__ == "__main__":
    main()
