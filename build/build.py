import argparse
import os
import subprocess
import sys
import shutil
import re


def _prune_dist_tree(dist_dir: str):
    dist_dir = os.path.abspath(str(dist_dir or ""))
    if not dist_dir or not os.path.isdir(dist_dir):
        return

    remove_dirs = [
        os.path.join(dist_dir, "torch", "testing"),
        os.path.join(dist_dir, "torch", "_dynamo"),
        os.path.join(dist_dir, "torch", "_inductor"),
        os.path.join(dist_dir, "torch", "distributed"),
        os.path.join(dist_dir, "torch", "fx", "passes", "tests"),
        os.path.join(dist_dir, "torch", "__pycache__"),
        os.path.join(dist_dir, "__pycache__"),
    ]
    for p in remove_dirs:
        try:
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
        except Exception:
            pass

    torch_lib = os.path.join(dist_dir, "torch", "lib")
    if os.path.isdir(torch_lib):
        remove_files = [
            os.path.join(torch_lib, "nvperf_host.dll"),
        ]
        try:
            for name in os.listdir(torch_lib):
                low = str(name or "").lower()
                if low.startswith("cupti") and low.endswith(".dll"):
                    remove_files.append(os.path.join(torch_lib, name))
        except Exception:
            pass
        for p in remove_files:
            try:
                if os.path.isfile(p):
                    os.remove(p)
            except Exception:
                pass


def _write_build_flavor_marker(dist_dir: str, flavor: str):
    dist_dir = os.path.abspath(str(dist_dir or ""))
    if not dist_dir or not os.path.isdir(dist_dir):
        return
    try:
        v = str(flavor or "").strip().lower()
    except Exception:
        v = ""
    if v not in ("cpu", "gpu"):
        v = "cpu"
    marker = os.path.join(dist_dir, "build_flavor.txt")
    try:
        with open(marker, "w", encoding="utf-8") as f:
            f.write(v)
    except Exception:
        pass


def _walk_dist_files(root_dir: str) -> dict[str, tuple[str, int, int]]:
    root_dir = os.path.abspath(str(root_dir or ""))
    out: dict[str, tuple[str, int, int]] = {}
    if not root_dir or not os.path.isdir(root_dir):
        return out
    for base, dirs, files in os.walk(root_dir):
        try:
            rel_base = os.path.relpath(base, root_dir)
        except Exception:
            rel_base = "."
        if rel_base == ".":
            rel_base = ""
        try:
            parts = [p for p in rel_base.replace("\\", "/").split("/") if p]
        except Exception:
            parts = []
        if parts:
            top = str(parts[0] or "").lower()
            if top in ("data", "cache"):
                try:
                    dirs[:] = []
                except Exception:
                    pass
                continue
        for name in files:
            if not name:
                continue
            if str(name).lower() in ("thumbs.db", "desktop.ini"):
                continue
            abs_path = os.path.join(base, name)
            try:
                st = os.stat(abs_path)
                size = int(st.st_size)
                mtime_ns = int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)))
            except Exception:
                continue
            try:
                rel_path = os.path.relpath(abs_path, root_dir).replace("/", "\\")
            except Exception:
                rel_path = name
            out[rel_path] = (abs_path, size, mtime_ns)
    return out


def _hash_file(path: str, max_bytes: int = 64 * 1024 * 1024) -> str:
    import hashlib

    try:
        st = os.stat(path)
        if int(st.st_size) > int(max_bytes):
            return ""
    except Exception:
        return ""
    h = hashlib.sha1()
    try:
        with open(path, "rb") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def _compute_delta_files(old_dist_dir: str, new_dist_dir: str) -> list[str]:
    old_map = _walk_dist_files(old_dist_dir)
    new_map = _walk_dist_files(new_dist_dir)
    changed: list[str] = []
    for rel, (new_abs, new_size, new_mtime) in new_map.items():
        old = old_map.get(rel)
        if old is None:
            changed.append(rel)
            continue
        _, old_size, old_mtime = old
        if int(old_size) != int(new_size):
            changed.append(rel)
            continue
        if int(old_mtime) == int(new_mtime):
            continue
        old_hash = _hash_file(old[0])
        new_hash = _hash_file(new_abs)
        if old_hash and new_hash:
            if old_hash != new_hash:
                changed.append(rel)
            continue
        changed.append(rel)
    changed.sort()
    return changed


def _rewrite_inno_files_section(iss_path: str, new_dist_dir: str, rel_files: list[str]):
    iss_path = os.path.abspath(str(iss_path or ""))
    if not iss_path or not os.path.isfile(iss_path):
        raise FileNotFoundError(iss_path)
    new_dist_dir = os.path.abspath(str(new_dist_dir or ""))
    if not new_dist_dir or not os.path.isdir(new_dist_dir):
        raise FileNotFoundError(new_dist_dir)
    try:
        with open(iss_path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except Exception:
        with open(iss_path, "r", encoding="gbk", errors="ignore") as f:
            lines = f.read().splitlines()

    files_start = -1
    files_end = -1
    for i, line in enumerate(lines):
        if str(line).strip().lower() == "[files]":
            files_start = i
            continue
        if files_start >= 0 and i > files_start:
            if str(line).startswith("[") and str(line).endswith("]"):
                files_end = i
                break
    if files_start < 0:
        raise RuntimeError("未在 .iss 中找到 [Files] 段")
    if files_end < 0:
        files_end = len(lines)

    new_block: list[str] = []
    for rel in rel_files:
        rel = str(rel or "").strip().lstrip("\\/").replace("/", "\\")
        if not rel:
            continue
        abs_src = os.path.join(new_dist_dir, rel)
        if not os.path.isfile(abs_src):
            continue
        dest_sub = os.path.dirname(rel).replace("/", "\\")
        if dest_sub:
            dest = r"{app}\\" + dest_sub
        else:
            dest = r"{app}"
        src = r"{#MyAppDistDir}\\" + rel
        new_block.append(f'Source: "{src}"; DestDir: "{dest}"; Flags: ignoreversion')

    lines_out = lines[: files_start + 1] + new_block + lines[files_end:]
    try:
        with open(iss_path, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines_out) + "\n")
    except Exception:
        with open(iss_path, "w", encoding="gbk", errors="ignore", newline="\n") as f:
            f.write("\n".join(lines_out) + "\n")


def _validate_torch_flavor(flavor: str):
    v = str(flavor or "").strip().lower()
    if v not in ("cpu", "gpu"):
        return
    try:
        import torch  # type: ignore
    except Exception as e:
        raise RuntimeError(f"未检测到 torch，无法打包 {v.upper()} 版本：{e}") from e
    try:
        cuda_ver = getattr(getattr(torch, "version", None), "cuda", None)
    except Exception:
        cuda_ver = None
    try:
        ver_txt = str(getattr(torch, "__version__", "") or "")
    except Exception:
        ver_txt = ""
    is_cpu_build = (cuda_ver is None) and ("+cpu" in ver_txt.lower())
    is_cuda_build = (cuda_ver is not None)
    if v == "cpu":
        if is_cuda_build:
            raise RuntimeError(
                "当前环境的 torch 是 CUDA 版，打包 CPU 安装包会把 CUDA 依赖整套打进去，导致体积暴涨。\n"
                "请使用 CPU 版 torch 的 Python 环境再执行构建。"
            )
        return
    if v == "gpu":
        if not is_cuda_build:
            raise RuntimeError(
                "当前环境的 torch 不是 CUDA 版，打包 GPU 安装包无法获得 GPU 加速。\n"
                "请使用 CUDA 版 torch 的 Python 环境再执行构建。"
            )
        return


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("suffix", nargs="?", default="")
    parser.add_argument("--obf", action="store_true")
    parser.add_argument("--flavor", choices=["cpu", "gpu"], default="")
    parser.add_argument("--delta-from", dest="delta_from", default="")
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
    flavor = str(getattr(args, "flavor", "") or "").strip().lower()
    if flavor and not suffix:
        suffix = flavor
    try:
        _validate_torch_flavor(flavor)
    except Exception:
        raise

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
    code = subprocess.call(cmd, cwd=root, env=env)
    if int(code) == 0:
        try:
            _prune_dist_tree(dist_dir)
        except Exception:
            pass
        try:
            _write_build_flavor_marker(dist_dir, flavor or "cpu")
        except Exception:
            pass
        delta_from = str(getattr(args, "delta_from", "") or "").strip()
        if delta_from:
            try:
                rel_files = _compute_delta_files(delta_from, dist_dir)
                iss = os.path.join(root, "build", "installer", "newinstaller.iss")
                _rewrite_inno_files_section(iss, dist_dir, rel_files)
            except Exception:
                pass
    return code


if __name__ == "__main__":
    raise SystemExit(main())
