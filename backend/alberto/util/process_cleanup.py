"""Cross-platform process and lock cleanup utility for Alberto."""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def _kill_pid(pid: int) -> bool:
    """Kill a PID cleanly and aggressively across all operating systems."""
    if pid <= 0 or pid == os.getpid():
        return False
    try:
        if sys.platform == "win32":
            import ctypes
            kernel32 = ctypes.WinDLL("kernel32")
            h = kernel32.OpenProcess(0x0001, False, pid)  # PROCESS_TERMINATE
            if h:
                kernel32.TerminateProcess(h, 1)
                kernel32.CloseHandle(h)
                return True
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
            return True
        else:
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except Exception:
                os.kill(pid, signal.SIGKILL)
            return True
    except Exception:
        return False


def _get_pids_for_port(port: int) -> set[int]:
    """Find all PIDs listening on or bound to the given port."""
    pids: set[int] = set()
    if sys.platform == "win32":
        try:
            out = subprocess.check_output("netstat -ano -p tcp", shell=True, text=True, errors="ignore")
            for line in out.splitlines():
                parts = line.strip().split()
                if len(parts) >= 5 and (parts[0].upper() == "TCP"):
                    local_addr = parts[1]
                    if local_addr.endswith(f":{port}"):
                        try:
                            found_pid = int(parts[-1])
                            if found_pid > 0 and found_pid != os.getpid():
                                pids.add(found_pid)
                        except ValueError:
                            pass
        except Exception:
            pass
    else:
        try:
            out = subprocess.check_output(["lsof", "-ti", f":{port}"], text=True, errors="ignore")
            for line in out.splitlines():
                try:
                    pids.add(int(line.strip()))
                except ValueError:
                    pass
        except Exception:
            pass
    return pids


def _get_lock_holders(lock_path: Path) -> set[int]:
    """Find any PID holding the lock file."""
    holders: set[int] = set()
    if not lock_path.exists():
        return holders

    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class FILETIME(ctypes.Structure):
            _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

        class RM_UNIQUE_PROCESS(ctypes.Structure):
            _fields_ = [("dwProcessId", wintypes.DWORD), ("ProcessStartTime", FILETIME)]

        class RM_PROCESS_INFO(ctypes.Structure):
            _fields_ = [
                ("Process", RM_UNIQUE_PROCESS),
                ("strAppName", wintypes.WCHAR * 256),
                ("strServiceShortName", wintypes.WCHAR * 64),
                ("ApplicationType", wintypes.DWORD),
                ("AppStatus", wintypes.DWORD),
                ("TSSessionId", wintypes.DWORD),
                ("bRestartable", wintypes.BOOL),
            ]

        try:
            rstrtmgr = ctypes.WinDLL("rstrtmgr")
            session_handle = wintypes.DWORD()
            session_key = (wintypes.WCHAR * 256)()
            if rstrtmgr.RmStartSession(ctypes.byref(session_handle), 0, session_key) == 0:
                abs_p = str(lock_path.resolve())
                file_paths = (wintypes.LPCWSTR * 1)(abs_p)
                rstrtmgr.RmRegisterResources(session_handle, 1, file_paths, 0, None, 0, None)
                n_needed = wintypes.UINT()
                n_info = wintypes.UINT(10)
                info_arr = (RM_PROCESS_INFO * 10)()
                reboot = wintypes.DWORD()
                res = rstrtmgr.RmGetList(
                    session_handle,
                    ctypes.byref(n_needed),
                    ctypes.byref(n_info),
                    info_arr,
                    ctypes.byref(reboot),
                )
                rstrtmgr.RmEndSession(session_handle)
                if res == 0:
                    for i in range(n_info.value):
                        p = info_arr[i].Process.dwProcessId
                        if p > 0 and p != os.getpid():
                            holders.add(p)
        except Exception:
            pass
    else:
        try:
            out = subprocess.check_output(["lsof", "-ti", str(lock_path)], text=True, errors="ignore")
            for line in out.splitlines():
                try:
                    holders.add(int(line.strip()))
                except ValueError:
                    pass
        except Exception:
            pass

    return holders


def cleanup(ports: list[int], pids: list[int], lock_paths: list[str]) -> None:
    # 1. Kill explicit PIDs if passed
    for pid in pids:
        _kill_pid(pid)

    # 2. Kill lock holders
    for lp_str in lock_paths:
        lp = Path(lp_str)
        holders = _get_lock_holders(lp)
        for h in holders:
            _kill_pid(h)
        if lp.exists():
            time.sleep(0.05)
            try:
                lp.unlink(missing_ok=True)
            except Exception:
                pass

    # 3. Kill port holders
    for port in ports:
        port_pids = _get_pids_for_port(port)
        for p in port_pids:
            _kill_pid(p)

    # 4. Final verification and lock unlink
    for lp_str in lock_paths:
        lp = Path(lp_str)
        if lp.exists():
            try:
                lp.unlink(missing_ok=True)
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser(description="Alberto Process & Lock Cleanup")
    parser.add_argument("--ports", type=int, nargs="*", default=[])
    parser.add_argument("--pids", type=int, nargs="*", default=[])
    parser.add_argument("--lock-files", type=str, nargs="*", default=[])
    args = parser.parse_args()

    cleanup(args.ports, args.pids, args.lock_files)


if __name__ == "__main__":
    main()
