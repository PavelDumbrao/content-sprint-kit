#!/usr/bin/env python3
"""Batch of Google Omni clips on SCAPI from a JSON spec: at-most-once submit, resumable ledger, poll, download.

  python3 scripts/omni_clips.py spec.json [--only name,name] [--submit-only] [--poll-only] [--dry-run]

spec.json: {"assets": {"FACE": "https://.../face.jpg", ...}, "size": "720x1280", "duration": "10",
            "tasks": {"name": {"prompt": "...", "images": "{FACE}" | "{FACE},{HOODIE}", "line": "реплика для Whisper"}}}
Ledger ./ledger.json and results/<name>/out*.mp4 are written next to the spec; lines.json keeps the spoken line of every clip for checking the speech.
Key: $SCAPI_KEY or the line SCAPI_KEY=... in .env of the current folder. Omni 1.2 also takes "duration" 1-15 (spec or task; omitted = 10). Cost: ¥0.1 per second on video_google_omni (charged at submit even if the task fails), ¥0.2 per second on video_omni_flash_1.2.
For Omni 1.2 set "model": "video_omni_flash_1.2" in the spec or task; "resolution" (default "1080") and "ratio" ("2" = 9:16, "1" = 16:9); one image only.
Rules: submit each task exactly once (ledger persists intent before the call); network error at submit -> SUBMIT_UNCERTAIN, never retried
automatically; poll is free. Example spec: docs/omni_spec.example.json."""
import json, os, re, sys, time, urllib.request, urllib.error, hashlib

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE = "https://api.scapi.net"
OLD_MODEL = "video_google_omni"
FLASH_12 = "video_omni_flash_1.2"
PRICE_PER_SECOND = {OLD_MODEL: 0.1, FLASH_12: 0.2}


def load_key():
    k = os.environ.get("SCAPI_KEY")
    if not k:
        p = os.environ.get("SCAPI_ENV_FILE", ".env")
        if os.path.exists(p):
            for line in open(p):
                if line.startswith("SCAPI_KEY="):
                    k = line.split("=", 1)[1].strip().strip('"')
    if not k:
        sys.exit("SCAPI_KEY не найден: впишите SCAPI_KEY=... в .env")
    return k


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def http(key, method, url, payload=None, timeout=120):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Authorization": key, "Content-Type": "application/json", "User-Agent": "omni-batch/1.0"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body, code = r.read(), r.status
    except urllib.error.HTTPError as e:
        body, code = e.read(), e.code
    except Exception as e:
        return {"_http": None, "_error": repr(e)}
    try:
        js = json.loads(body.decode("utf-8", "replace"))
    except Exception:
        js = {"_raw": body[:2000].decode("utf-8", "replace")}
    if not isinstance(js, dict):
        js = {"_list": js}
    js["_http"] = code; js["_t"] = round(time.time() - t0, 2)
    return js


URL_RE = re.compile(r"https?://[^\s\"'<>]+")


def find_urls(obj, acc=None):
    acc = [] if acc is None else acc
    if isinstance(obj, dict):
        [find_urls(v, acc) for v in obj.values()]
    elif isinstance(obj, list):
        [find_urls(v, acc) for v in obj]
    elif isinstance(obj, str):
        acc += URL_RE.findall(obj)
    return acc


def download(results_dir, name, final, asset_urls):
    d = os.path.join(results_dir, name); os.makedirs(d, exist_ok=True)
    json.dump(final, open(os.path.join(d, "final.json"), "w"), ensure_ascii=False, indent=1)
    files = []
    for i, u in enumerate(dict.fromkeys(find_urls(final))):
        if any(u.startswith(a) for a in asset_urls):
            continue
        out = os.path.join(d, f"out{i}.mp4")
        for attempt in range(3):
            try:
                req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=300) as r, open(out, "wb") as f:
                    f.write(r.read())
                files.append({"url": u, "file": out, "size": os.path.getsize(out)}); break
            except Exception as e:
                if attempt == 2:
                    files.append({"url": u, "error": repr(e)})
                time.sleep(5)
    return files


def main():
    args = sys.argv[1:]
    if not args or args[0].startswith("--"):
        sys.exit(__doc__)
    spec_path = os.path.abspath(args[0]); spec = json.load(open(spec_path, encoding="utf-8"))
    only = set(args[args.index("--only") + 1].split(",")) if "--only" in args else None
    dry = "--dry-run" in args
    here = os.path.dirname(spec_path)
    ledger_path = os.path.join(here, "ledger.json"); results_dir = os.path.join(here, "results"); os.makedirs(results_dir, exist_ok=True)
    assets = spec.get("assets", {})
    def fill(s):
        for k, v in assets.items():
            s = s.replace("{" + k + "}", v)
        return s
    tasks = {}
    models = {}
    for name, t in spec["tasks"].items():
        if only and name not in only:
            continue
        tasks[name] = {"prompt": fill(t["prompt"]), "images": fill(t.get("images", "{FACE}")), "size": t.get("size", spec.get("size", "720x1280")), "duration": str(t.get("duration", spec.get("duration", "10")))}
        if t.get("video"):
            tasks[name]["video"] = fill(t["video"])
        models[name] = t.get("model", spec.get("model", OLD_MODEL))
        if models[name] == FLASH_12:
            media = [u for u in tasks[name]["images"].split(",") if u.strip()]
            if len(media) > 1:
                sys.exit(f"{name}: {FLASH_12} принимает одну картинку в media, передано {len(media)}")
            res_norm = str(t.get("resolution", spec.get("resolution", "1080"))).rstrip("pP")
            tasks[name] = {"prompt": tasks[name]["prompt"], "resolution": res_norm,
                           "ratio": str(t.get("ratio", spec.get("ratio", "2"))), "media": media}
            dur = t.get("duration", spec.get("duration"))  # doc 90 от 11.11.2026: 1-15, по умолчанию 10
            if dur is not None:
                if not 1 <= int(dur) <= 15:
                    sys.exit(f"{name}: {FLASH_12} принимает duration от 1 до 15, передано {dur}")
                tasks[name]["duration"] = str(int(dur))
    json.dump({n: spec["tasks"][n].get("line", "") for n in tasks}, open(os.path.join(here, "lines.json"), "w"), ensure_ascii=False, indent=1)
    if dry:
        for n, p in tasks.items():
            shown = {k: v for k, v in p.items() if k != "prompt"}
            print(f"{n}: model={models[n]} {shown} prompt[{len(p['prompt'])} chars]={p['prompt'][:90]}…")
        cost = sum(int(p.get("duration", 10)) * PRICE_PER_SECOND[models[n]] for n, p in tasks.items())
        print(f"dry run: {len(tasks)} tasks, estimated ¥{cost:.1f}")
        return
    key = load_key()
    led = json.load(open(ledger_path)) if os.path.exists(ledger_path) else {}
    if "--poll-only" not in args:
        for name, payload in tasks.items():
            e = led.get(name)
            if e and (e.get("task_id") or e.get("submit_uncertain")):
                log(f"[skip] {name}: already submitted"); continue
            e = led.setdefault(name, {"payload": payload, "fingerprint": hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16], "attempts": 0})
            e["attempts"] += 1; e["submitted_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            json.dump(led, open(ledger_path, "w"), ensure_ascii=False, indent=1)  # persist intent before the call
            log(f"[submit] {name}")
            js = http(key, "POST", f"{BASE}/api/async/{models[name]}", payload); e["submit_response"] = js
            if js.get("_http") is None:
                e["submit_uncertain"] = True; e["status"] = "SUBMIT_UNCERTAIN"; log(f"  !! {name}: network error -> SUBMIT_UNCERTAIN, not retrying")
            else:
                d = js.get("data") if isinstance(js.get("data"), dict) else {}; tid = d.get("id")
                log(f"  <- code={js.get('code')} msg={str(js.get('msg'))[:60]} id={tid} count={d.get('count')}")
                if js.get("code") == 200 and tid:
                    e["task_id"] = tid; e["status"] = "pending"; e["count"] = d.get("count")
                else:
                    e["status"] = "submit_rejected"
            json.dump(led, open(ledger_path, "w"), ensure_ascii=False, indent=1); time.sleep(1.5)
    if "--submit-only" in args:
        return
    asset_urls = list(assets.values())
    deadline = time.time() + 75 * 60
    while time.time() < deadline:
        pending = [n for n, e in led.items() if e.get("task_id") and e.get("status") == "pending" and n in tasks]
        if not pending:
            break
        for name in pending:
            e = led[name]; js = http(key, "GET", f"{BASE}/api/async/detail?id={e['task_id']}", timeout=60); e["polls"] = e.get("polls", 0) + 1
            d = js.get("data") if isinstance(js.get("data"), dict) else {}; st = d.get("status")
            if str(st) in ("2", "3"):
                e["status"] = "done" if str(st) == "2" else "failed"; e["final"] = js; e["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                log(f"[{e['status']}] {name} after {e['polls']} polls; msg={str(d.get('message') or js.get('msg'))[:80]}")
                if e["status"] == "done":
                    e["files"] = download(results_dir, name, js, asset_urls)
            elif js.get("code") not in (200, None) and st is None:
                e["poll_error_count"] = e.get("poll_error_count", 0) + 1
                if e["poll_error_count"] >= 8:
                    e["status"] = "poll_failed"; e["final"] = js
            json.dump(led, open(ledger_path, "w"), ensure_ascii=False, indent=1); time.sleep(1)
        time.sleep(20)
    for n in tasks:
        e = led.get(n, {}); log(f"SUMMARY {n:18s} {e.get('status', '-'):16s} id={e.get('task_id', '-')} files={len(e.get('files') or [])}")


if __name__ == "__main__":
    main()
