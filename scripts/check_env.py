#!/usr/bin/env python3
"""Проверка готовности компьютера к спринту: программы, файл ключей, наборы. Ничего не ставит и не меняет.

  python3 scripts/check_env.py
"""
import os, re, shutil, subprocess, sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

NEED = [  # программа, команда версии, минимальная версия, зачем
    ("python3", [sys.executable, "--version"], (3, 10), "скрипты наборов"),
    ("node", ["node", "--version"], (22, 0), "HyperFrames и Remotion: видео кодом"),
    ("npm", ["npm", "--version"], (9, 0), "установка скиллов"),
    ("git", ["git", "--version"], (2, 0), "наборы клуба"),
    ("ffmpeg", ["ffmpeg", "-version"], (4, 0), "склейка и звук"),
    ("yt-dlp", ["yt-dlp", "--version"], (2024, 0), "скачать ролик-образец"),
    ("curl", ["curl", "--version"], (7, 0), "запросы к сервисам"),
]
KEYS_REQUIRED = ["ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID"]
KEYS_OPTIONAL = ["GRSAI_API_KEY", "SCAPI_KEY", "YICIYUANG_API_KEY", "GEMINI_API_KEY"]


def version(cmd):
    exe = cmd[0] if cmd[0] == sys.executable else shutil.which(cmd[0])  # на Windows npm — это npm.cmd
    if not exe:
        return None
    try:
        out = subprocess.run([exe] + cmd[1:], capture_output=True, text=True, timeout=20).stdout
    except Exception:
        return None
    m = re.search(r"(\d+)\.(\d+)", out)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def env_keys(path=".env"):
    found = {}
    if os.path.isfile(path):
        for line in open(path, encoding="utf-8"):
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.strip().split("=", 1)
                found[k.strip()] = bool(v.strip().strip("'\""))
    return found


def main():
    ok = True
    print("Программы:")
    for name, cmd, need, why in NEED:
        v = version(cmd)
        if v is None:
            ok = False; print(f"  НЕТ   {name:8} нужно для: {why}")
        elif v < need:
            ok = False; print(f"  СТАРО {name:8} {v[0]}.{v[1]}, нужно от {need[0]}.{need[1]} ({why})")
        else:
            print(f"  есть  {name:8} {v[0]}.{v[1]}")
    keys = env_keys()
    print("Файл .env:", "есть" if os.path.isfile(".env") else "НЕТ (скопируйте .env.example в .env)")
    for k in KEYS_REQUIRED:
        if not keys.get(k):
            ok = False
        print(f"  {'есть ' if keys.get(k) else 'ПУСТО'} {k} (обязательно)")
    for k in KEYS_OPTIONAL:
        print(f"  {'есть ' if keys.get(k) else 'пусто'} {k} (по желанию)")
    print("Наборы:")
    for kit in ("viral-reel-remake-kit", "omni-video-kit"):
        print(f"  {'есть ' if os.path.isdir(os.path.join('kits', kit)) else 'нет  '} kits/{kit}")
    print("ИТОГ:", "готово" if ok else "есть что доделать (см. строки НЕТ, СТАРО, ПУСТО)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
