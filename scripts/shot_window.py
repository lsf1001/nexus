#!/usr/bin/env python3
"""列 Nexus 窗口 + 截屏(window id 指定)。无需辅助访问权限。"""
import subprocess
import sys


def list_windows():
    out = subprocess.run(
        ["osascript", "-e",
         'tell application "System Events"\n'
         '  repeat with p in application processes\n'
         '    set pname to name of p\n'
         '    if pname contains "nexus" then\n'
         '      return pname\n'
         '    end if\n'
         '  end repeat\n'
         'end tell'],
        capture_output=True, text=True, timeout=5,
    ).stdout.strip()
    return out


if __name__ == "__main__":
    print(f"matching: {list_windows()}")
