import os

_env_setup_done = False

NEEDED_LIBS = {
    "libgbm.so.1": "mesa-libgbm",
    "libxkbcommon.so.0": "libxkbcommon",
}


def setup_browser_env():
    global _env_setup_done
    if _env_setup_done:
        return
    _env_setup_done = True

    extra_lib_dirs = {}
    found_all = set()
    try:
        for entry in os.scandir("/nix/store"):
            if len(found_all) == len(NEEDED_LIBS):
                break
            name = entry.name
            for lib_file, pkg_hint in NEEDED_LIBS.items():
                if lib_file in found_all:
                    continue
                if pkg_hint in name and "dev" not in name:
                    lib = os.path.join(entry.path, "lib")
                    if os.path.exists(os.path.join(lib, lib_file)):
                        extra_lib_dirs[lib_file] = lib
                        found_all.add(lib_file)
    except Exception:
        pass

    if extra_lib_dirs:
        dirs = list(extra_lib_dirs.values())
        ld = os.environ.get("LD_LIBRARY_PATH", "")
        os.environ["LD_LIBRARY_PATH"] = ":".join(dirs) + ":" + ld
        print(f"[browser-env] Added to LD_LIBRARY_PATH: {dirs}")
