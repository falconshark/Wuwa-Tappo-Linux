#!/usr/bin/env python3
"""Work around a Wine crash in Tauri/wry apps (WuwaTappo.exe).

wry enumerates the WebView2 child windows (owned by msedgewebview2.exe, another
process) and calls RevokeDragDrop() on them. Wine's RevokeDragDrop() then calls
IDropTarget::Release() on a pointer that only exists in the other process, so it
crashes with an access violation.

This retargets the RevokeDragDrop import (by name) to CoFreeLibrary, which, given
an HWND, just fails harmlessly. The only effect is that dragging files into the
app may not work. Idempotent; keeps <exe>.orig as a backup.
"""
import shutil
import sys

OLD = b"\x00RevokeDragDrop\x00"
NEW = b"\x00CoFreeLibrary\x00\x00"  # same length
assert len(OLD) == len(NEW)


def main(path: str) -> int:
    data = open(path, "rb").read()
    if data.count(NEW) and not data.count(OLD):
        return 0  # already patched
    n = data.count(OLD)
    if n != 1:
        print(f"patch_dragdrop: expected 1 RevokeDragDrop import, found {n}; skipped", file=sys.stderr)
        return 1
    shutil.copy2(path, path + ".orig")
    open(path, "wb").write(data.replace(OLD, NEW))
    print(f"patch_dragdrop: patched {path} (backup: {path}.orig)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
