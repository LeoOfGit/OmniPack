"""Register VS 18 Insiders in the registry for vswhere discovery.

Usage:
    python register_vs18_insiders.py          # Apply (HKCU if not admin)
    python register_vs18_insiders.py --admin  # Apply to HKLM (requires admin)
    python register_vs18_insiders.py --check  # Check if registered
    python register_vs18_insiders.py --remove # Remove registration
"""
import argparse
import ctypes
import sys
import winreg

INSTANCE_ID = "{e10b5fae-6a76-5ea9-bcc1-ae6ca0f491d3}"
INSTANCE_SUBKEY = rf"SOFTWARE\Microsoft\VisualStudio\Setup\Instances\{INSTANCE_ID}"

VALUES = {
    "installationPath": "C:\\Program Files\\Microsoft Visual Studio\\18\\Insiders\\",
    "installationVersion": "18.0.0.0",
    "displayName": "Visual Studio 18 Insiders",
    "instanceId": INSTANCE_ID,
}


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def get_key_root(force_hklm):
    if force_hklm:
        if not is_admin():
            print("ERROR: --admin requires elevation (Run as Administrator).")
            sys.exit(1)
        return winreg.HKEY_LOCAL_MACHINE
    return winreg.HKEY_LOCAL_MACHINE if is_admin() else winreg.HKEY_CURRENT_USER


def apply(force_hklm=False):
    root = get_key_root(force_hklm)
    scope = "HKLM" if root == winreg.HKEY_LOCAL_MACHINE else "HKCU"
    print(f"Writing to {scope}\\{INSTANCE_SUBKEY}")
    key = winreg.CreateKey(root, INSTANCE_SUBKEY)
    for name, value in VALUES.items():
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
    winreg.CloseKey(key)
    print("Done. VS 18 Insiders registered for vswhere.")


def remove():
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            key = winreg.OpenKey(root, INSTANCE_SUBKEY, 0,
                                 winreg.KEY_READ | winreg.KEY_WRITE)
            winreg.CloseKey(key)
            winreg.DeleteKey(root, INSTANCE_SUBKEY)
            scope = "HKLM" if root == winreg.HKEY_LOCAL_MACHINE else "HKCU"
            print(f"Removed from {scope}.")
        except FileNotFoundError:
            continue


def check():
    found = False
    for root, scope in [(winreg.HKEY_LOCAL_MACHINE, "HKLM"),
                         (winreg.HKEY_CURRENT_USER, "HKCU")]:
        try:
            key = winreg.OpenKey(root, INSTANCE_SUBKEY)
            path, _ = winreg.QueryValueEx(key, "installationPath")
            ver, _ = winreg.QueryValueEx(key, "installationVersion")
            print(f"[{scope}] VS {ver} at {path}")
            winreg.CloseKey(key)
            found = True
        except FileNotFoundError:
            print(f"[{scope}] not registered")
    return found


def main():
    parser = argparse.ArgumentParser(description="Register VS 18 Insiders for vswhere")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--admin", action="store_true",
                       help="Force write to HKLM (requires elevation)")
    group.add_argument("--remove", action="store_true",
                       help="Remove the registration")
    group.add_argument("--check", action="store_true",
                       help="Check if already registered (exit 0=yes)")
    args = parser.parse_args()

    if args.remove:
        remove()
    elif args.check:
        found = check()
        sys.exit(0 if found else 1)
    else:
        apply(force_hklm=args.admin)
        # Verify with vswhere
        import subprocess
        vswhere = r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe"
        result = subprocess.run([vswhere, "-all", "-format", "json"],
                                capture_output=True, text=True)
        if result.stdout.strip() not in ("[]", ""):
            import json
            data = json.loads(result.stdout)
            found_vs18 = any("18." in d.get("installationVersion", "")
                           for d in data)
            if found_vs18:
                print("vswhere verification: VS 18 found!")
            else:
                print("vswhere returned data but no VS 18 entry:")
                for d in data:
                    print(f"  VS {d.get('installationVersion', '?')}: {d.get('installationPath', '?')}")
        else:
            print("vswhere verification: no instances found yet (may need restart).")


if __name__ == "__main__":
    main()
