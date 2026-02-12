import argparse
import os
import subprocess
import sys
import shutil
import re


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("suffix", nargs="?", default="")
    parser.add_argument("--obf", action="store_true")
    args = parser.parse_args()

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    try:
        if root not in sys.path:
            sys.path.insert(0, root)
    except Exception:
        pass
    spec_path = os.path.join(root, "build", "bird_picture_manager.spec")
    icon_gen = os.path.join(root, "build", "generate_icon.py")

    suffix = str(args.suffix or "").strip()

    try:
        subprocess.check_call([sys.executable, icon_gen], cwd=root)
    except Exception:
        pass

    try:
        import PyQt6.QtWebEngineWidgets
        import PyQt6.QtWebEngineCore
        import PyQt6.QtWebChannel
    except Exception as e:
        raise RuntimeError(
            "未检测到 PyQt6-WebEngine（或其依赖无法加载），打包后地图会不可用。\n"
            "请在用于打包的 Python 环境中安装：pip install -i https://mirrors.aliyun.com/pypi/simple PyQt6-WebEngine"
        ) from e

    env = os.environ.copy()
    env["BPM_PROJECT_ROOT"] = root
    env["BPM_BUILD_DIR"] = os.path.join(root, "build")
    if suffix:
        env["BPM_NAME_SUFFIX"] = suffix
    else:
        env.pop("BPM_NAME_SUFFIX", None)

    if args.obf:
        obf_dir = os.path.join(root, "build", "obf_src")
        if os.path.exists(obf_dir):
            shutil.rmtree(obf_dir, ignore_errors=True)
        os.makedirs(obf_dir, exist_ok=True)

        pyarmor_cmd = None
        for c in (["pyarmor"], [sys.executable, "-m", "pyarmor"]):
            try:
                subprocess.check_call(c + ["--version"], cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                pyarmor_cmd = c
                break
            except Exception:
                continue
        if pyarmor_cmd is None:
            raise RuntimeError("未找到 pyarmor（请先安装 pyarmor，或关闭 --obf）")

        targets = ["main.py", "cache", "core", "ui", "utils"]
        subprocess.check_call(pyarmor_cmd + ["gen", "-r", "-O", obf_dir] + targets, cwd=root)

        env["BPM_SOURCE_ROOT"] = obf_dir
        env["BPM_ENTRY"] = os.path.join(obf_dir, "main.py")

    try:
        from utils.system.app_info_manager import APP_NAME, APP_VERSION

        app_name = str(APP_NAME or "BirdPictureManager")
        app_version = str(APP_VERSION or "V0.0.1")
    except Exception:
        app_name = "BirdPictureManager"
        app_version = "V0.0.1"

    suffix_token = str(suffix or "").strip()
    if suffix_token:
        suffix_token = re.sub(r"[^0-9A-Za-z_\\-]+", "_", suffix_token)
        app_name = f"{app_name}_{suffix_token}"

    v_token = str(app_version or "").strip()
    if v_token:
        v_token = re.sub(r"[^0-9A-Za-z_.\\-]+", "_", v_token)

    dist_name = str(app_name)
    if v_token:
        dist_name = f"{dist_name}_{v_token}"

    dist_dir = os.path.join(root, "dist", dist_name)
    if os.path.isdir(dist_dir):
        try:
            shutil.rmtree(dist_dir)
        except Exception as e:
            raise RuntimeError(f"无法清理旧的打包目录：{dist_dir}\n请先关闭正在运行的程序/资源管理器占用后重试。") from e

    workpath = os.path.join(root, "build", "_pyi_work", dist_name)
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath",
        os.path.join(root, "dist"),
        "--workpath",
        workpath,
        spec_path,
    ]
    return subprocess.call(cmd, cwd=root, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
