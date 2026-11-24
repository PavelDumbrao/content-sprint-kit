#!/usr/bin/env python3
"""
nano_banana.py — генератор изображений Nano Banana 2.1 через Grsai API.
Поддерживает:
- Выбор живого узла (grsai.dakka.com.cn / grsaiapi.com)
- Преобразование локальных файлов в Data URI (base64)
- Множественные референсы (--image ref1.jpg --image ref2.png ...)
- Пропорции (--aspect 1:1, 4:5, 9:16, 16:9, 21:9, auto)
- Разрешение (--size 1K, 2K, 4K; по умолчанию 2K)
- Журнал в .ledger/<case>.json (at-most-once защита от повторных списаний)
- Мгновенное скачивание готовой картинки в указанную папку
"""

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

NODES = ["https://grsai.dakka.com.cn", "https://grsaiapi.com"]
PROBE_ID = "1-00000000-0000-0000-0000-000000000000"
MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


def load_api_key():
    key = os.environ.get("GRSAI_API_KEY")
    if key and key.strip():
        return key.strip()

    env_path = os.path.expanduser(os.environ.get("GRSAI_ENV_FILE", ".env"))
    if os.path.isfile(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("GRSAI_API_KEY="):
                        return line.split("=", 1)[1].strip().strip("'\"")
        except Exception as e:
            print(f"Предупреждение при чтении {env_path}: {e}", file=sys.stderr)

    sys.exit(f"ОШИБКА: Ключ Grsai не найден. Задайте GRSAI_API_KEY или добавьте GRSAI_API_KEY=... в {env_path}")


def media_to_ref(item):
    """Преобразует локальный путь к файлу в Data URI. Если передан URL/data URI — оставляет как есть."""
    if not item:
        return item
    if item.startswith("http://") or item.startswith("https://") or item.startswith("data:"):
        return item

    path = os.path.expanduser(item)
    if not os.path.isfile(path):
        sys.exit(f"ОШИБКА: Файл референса не найден: {path}")

    ext = os.path.splitext(path)[1].lower()
    mime = MIME_TYPES.get(ext)
    if not mime:
        sys.exit(f"ОШИБКА: Неподдерживаемый формат файла {path}. Поддерживаются: {', '.join(MIME_TYPES.keys())}")

    with open(path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("utf-8")
        return f"data:{mime};base64,{encoded}"


def curl_request(url, timeout, data=None, auth=True):
    args = [
        "curl", "-sS", "--http1.1", "--max-time", str(timeout), "-K", "-",
        "-w", "\n__HTTP__%{http_code}"
    ]
    tmp_path = None
    if data is not None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            f.write(data)
            tmp_path = f.name
        args += ["-H", "Content-Type: application/json", "--data-binary", "@" + tmp_path]

    cfg = f'header = "Authorization: Bearer {load_api_key()}"\n' if auth else ""
    try:
        p = subprocess.run(args + [url], input=cfg, capture_output=True, text=True)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)

    body, _, code = p.stdout.rpartition("\n__HTTP__")
    return p.returncode, code, body


def is_node_alive(base_url):
    rc, code, body = curl_request(f"{base_url}/v1/api/result?id={PROBE_ID}", timeout=10, auth=False)
    return rc == 0 and ("result not exist" in body or code == "200")


def select_best_node():
    forced = os.environ.get("GRSAI_BASE")
    if forced:
        return forced.rstrip("/")

    for node in NODES:
        if is_node_alive(node):
            return node

    sys.exit("ОШИБКА: Ни один рабочий узел Grsai не отвечает. Проверьте интернет-соединение.")


def ledger_filepath(out_dir, case_id):
    return os.path.join(out_dir, ".ledger", f"{case_id}.json")


def submit_job(args):
    if args.prompt:
        prompt_text = args.prompt.strip()
    elif args.prompt_file and os.path.isfile(args.prompt_file):
        with open(args.prompt_file, "r", encoding="utf-8") as f:
            prompt_text = f.read().strip()
    else:
        sys.exit("ОШИБКА: Укажите текст промпта через аргумент или файл (--prompt-file).")

    # Преобразование референсов
    refs = [media_to_ref(img) for img in (args.image or [])]

    req_payload = {
        "model": args.model,
        "prompt": prompt_text,
        "aspectRatio": args.aspect,
        "imageSize": args.size,
        "replyType": "async",
        "images": refs
    }

    canon_json = json.dumps(req_payload, ensure_ascii=False, sort_keys=True)
    summary_request = {
        "model": args.model,
        "aspectRatio": args.aspect,
        "imageSize": args.size,
        "images_count": len(refs),
        "prompt_length": len(prompt_text),
        "image_paths": args.image or []
    }

    if args.dry_run:
        print("\n=== DRY RUN MODE ===")
        print(json.dumps({
            "dry_run": True,
            "request_summary": summary_request,
            "payload_bytes": len(canon_json.encode("utf-8")),
            "prompt_sample": prompt_text[:300] + ("..." if len(prompt_text) > 300 else "")
        }, indent=2, ensure_ascii=False))
        return None

    out_dir = os.path.expanduser(args.out_dir)
    lp = ledger_filepath(out_dir, args.case)
    os.makedirs(os.path.dirname(lp), exist_ok=True)
    if os.path.exists(lp) and not args.force:
        sys.exit(f"ОШИБКА: Задача {args.case} уже отправлялась ({lp}). Повторный submit заблокирован.")

    node_url = select_best_node()
    record = {
        "case_id": args.case,
        "provider": "grsai",
        "model": args.model,
        "node": node_url,
        "request": summary_request,
        "fingerprint": "sha256:" + hashlib.sha256(canon_json.encode("utf-8")).hexdigest(),
        "state": "SUBMITTING",
        "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")
    }

    with open(lp, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)

    t0 = time.time()
    rc, http_code, body = curl_request(f"{node_url}/v1/api/generate", timeout=240, data=canon_json)
    latency = round(time.time() - t0, 2)
    record.update(submit_latency_s=latency, submit_http=http_code)

    try:
        data = json.loads(body)
    except Exception:
        data = None

    if data and data.get("id") and data.get("status") not in ("failed", "violation"):
        record.update(task_id=data["id"], state="POLLING")
        print(f"✅ Задача принята Grsai! ID: {data['id']} (задержка submit: {latency}s)")
    elif data and data.get("status") in ("failed", "violation"):
        record.update(task_id=data.get("id"), state=data["status"].upper(), error=data.get("error"))
        print(f"❌ Ошибка Grsai: {data.get('error')}", file=sys.stderr)
    else:
        uncertain = (rc != 0 or not str(http_code).startswith("4"))
        record.update(
            state="SUBMIT_UNCERTAIN" if uncertain else "SUBMIT_REJECTED",
            error=(body or "")[:400]
        )
        print(f"❌ Неопределенный ответ ({http_code}): {body[:300]}", file=sys.stderr)

    with open(lp, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)

    if record["state"] == "SUBMIT_UNCERTAIN":
        print("ВНИМАНИЕ: SUBMIT_UNCERTAIN. Не отправляйте повторно вслепую, сверьте Task Log в кабинете.", file=sys.stderr)
        sys.exit(3)

    if record["state"] != "POLLING":
        sys.exit(2)

    return record


def poll_job(args, task_record=None):
    out_dir = os.path.expanduser(args.out_dir)
    lp = ledger_filepath(out_dir, args.case)
    if not task_record:
        if not os.path.exists(lp):
            sys.exit(f"ОШИБКА: Запись о задаче {args.case} не найдена в {lp}")
        with open(lp, "r", encoding="utf-8") as f:
            task_record = json.load(f)

    task_id = task_record.get("task_id")
    node_url = task_record.get("node") or select_best_node()
    if not task_id:
        sys.exit(f"ОШИБКА: В записи {args.case} отсутствует task_id.")

    print(f"⏳ Ожидание генерации Nano Banana 2.1 (ID: {task_id})...")
    t0 = time.time()
    result_data = {}

    while time.time() - t0 < args.timeout:
        rc, http_code, body = curl_request(f"{node_url}/v1/api/result?id={task_id}", timeout=30)
        try:
            result_data = json.loads(body)
        except Exception:
            result_data = {}

        status = result_data.get("status")
        if status in ("succeeded", "failed", "violation"):
            break

        time.sleep(5)

    final_status = result_data.get("status") or "POLL_TIMEOUT"
    elapsed = int(time.time() - t0)
    task_record.update(poll_elapsed_s=elapsed, final_status=final_status, error=result_data.get("error"))

    if final_status == "succeeded" and result_data.get("results"):
        img_url = result_data["results"][0].get("url")
        ext = os.path.splitext(img_url.split("?")[0])[1] or ".png"
        out_filename = f"{args.case}{ext}"
        out_path = os.path.join(out_dir, out_filename)
        os.makedirs(out_dir, exist_ok=True)

        print(f"📥 Скачивание результата ({img_url[:60]}...)...")
        subprocess.run(["curl", "-sSL", "--http1.1", "--max-time", "120", "-o", out_path, img_url], check=True)
        task_record.update(result_file=os.path.abspath(out_path), state="DOWNLOADED")
        print(f"🎉 Готово! Файл сохранен: {out_path} (время: {elapsed}с)")
    else:
        task_record["state"] = final_status.upper()
        print(f"❌ Генерация не удалась: статус {final_status}, ошибка: {result_data.get('error')}", file=sys.stderr)

    with open(lp, "w", encoding="utf-8") as f:
        json.dump(task_record, f, indent=2, ensure_ascii=False)

    if task_record["state"] != "DOWNLOADED":
        sys.exit(2)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="Отправить задачу и дождаться скачивания")
    r.add_argument("case", help="Уникальный идентификатор задачи (case_id)")
    r.add_argument("prompt_file", nargs="?", default=None, help="Файл с текстом промпта")
    r.add_argument("--prompt", default=None, help="Текст промпта напрямую из аргумента")
    r.add_argument("--model", default="nano-banana-2.1", help="ID модели (по умолчанию nano-banana-2.1)")
    r.add_argument("--aspect", default="4:5", help="Пропорция: 1:1, 4:5, 9:16, 16:9, 21:9, auto")
    r.add_argument("--size", default="2K", choices=["1K", "2K", "4K"], help="Разрешение (1K, 2K, 4K)")
    r.add_argument("--image", action="append", help="Путь к фото-референсу (можно указывать несколько раз)")
    r.add_argument("--out-dir", default="~/output_nano_banana", help="Папка для сохранения результата")
    r.add_argument("--timeout", type=int, default=600, help="Таймаут ожидания в секундах")
    r.add_argument("--dry-run", action="store_true", help="Проверить параметры без сетевого запроса")
    r.add_argument("--force", action="store_true", help="Перезаписать ранее выполненный case_id")

    sub_poll = sub.add_parser("poll", help="Опросить существующую задачу по case_id")
    sub_poll.add_argument("case", help="Идентификатор задачи")
    sub_poll.add_argument("--out-dir", default="~/output_nano_banana")
    sub_poll.add_argument("--timeout", type=int, default=600)

    nodes_cmd = sub.add_parser("nodes", help="Проверить доступность узлов Grsai")

    args = p.parse_args()

    if args.cmd == "nodes":
        for n in NODES:
            alive = is_node_alive(n)
            print(f"Node {n}: {'[OK] ДОСТУПЕН' if alive else '[FAIL] НЕДОСТУПЕН'}")
    elif args.cmd == "run":
        rec = submit_job(args)
        if rec and not args.dry_run:
            poll_job(args, task_record=rec)
    elif args.cmd == "poll":
        poll_job(args)


if __name__ == "__main__":
    main()
