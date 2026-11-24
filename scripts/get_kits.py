#!/usr/bin/env python3
"""Скачать или обновить наборы клуба в папку kits/. Повторный запуск безопасен.

  python3 scripts/get_kits.py            # обязательный набор
  python3 scripts/get_kits.py --all      # и набор «говорящий из фото»
"""
import os, subprocess, sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

KITS = [("viral-reel-remake-kit", True), ("omni-video-kit", False)]
BASE = "https://github.com/PavelDumbrao/"

os.makedirs("kits", exist_ok=True)
for name, required in KITS:
    if not required and "--all" not in sys.argv:
        continue
    path = os.path.join("kits", name)
    if os.path.isdir(os.path.join(path, ".git")):
        r = subprocess.run(["git", "-C", path, "pull", "--ff-only", "-q"])
        print(("обновлён " if r.returncode == 0 else "НЕ обновлён ") + path)
    else:
        r = subprocess.run(["git", "clone", "-q", "--depth", "1", BASE + name + ".git", path])
        print(("скачан " if r.returncode == 0 else "НЕ скачан ") + path)
