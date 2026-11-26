#!/usr/bin/env python3
"""Срез ниши на YouTube: самые просматриваемые ролики по вашим запросам за период, длинные и Shorts отдельно.

  python3 scripts/youtube_niche.py check
  python3 scripts/youtube_niche.py run "запрос 1" "запрос 2" --days 365 --out work/youtube-niche

Ключ: строка YOUTUBE_API_KEY=... в .env (бесплатно: Google Cloud, YouTube Data API v3, ключ API; по шагам в docs/services.md).
Квота бесплатная, 10 000 единиц в сутки. Один запрос стоит около 101 единицы: на срез хватает 10–20 запросов.
Пишет <out>.json (сырые данные) и <out>.md (отчёт). Выборка — самые просматриваемые ролики, то есть лидеры ниши, а не средний ролик.
Запросы пишите на языке своей аудитории. Английские названия (Claude Code, n8n) дополняйте словом на этом языке
(«Claude Code на русском», «n8n автоматизация»), иначе выдача будет почти вся англоязычная.
"""
import argparse, collections, datetime, json, os, re, statistics, sys, urllib.error, urllib.parse, urllib.request

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

API = "https://www.googleapis.com/youtube/v3/"
REASONS = {
    "keyInvalid": "ключ не подходит: проверьте строку YOUTUBE_API_KEY в .env",
    "API_KEY_INVALID": "ключ не подходит: проверьте строку YOUTUBE_API_KEY в .env",
    "accessNotConfigured": "в проекте Google не включён YouTube Data API v3: включите его в Google Cloud и подождите пару минут",
    "SERVICE_DISABLED": "в проекте Google не включён YouTube Data API v3: включите его в Google Cloud и подождите пару минут",
    "quotaExceeded": "закончилась суточная квота (10 000 единиц): продолжите завтра",
    "dailyLimitExceeded": "закончилась суточная квота: продолжите завтра",
    "API_KEY_SERVICE_BLOCKED": "у ключа стоит ограничение без YouTube Data API v3: добавьте его в ограничения ключа",
}


def load_auth():
    token = os.environ.get("YOUTUBE_ACCESS_TOKEN")
    if token:
        return {"header": token}
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key and os.path.isfile(".env"):
        for line in open(".env", encoding="utf-8"):
            if line.strip().startswith("YOUTUBE_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not key:
        sys.exit("YOUTUBE_API_KEY не найден: впишите YOUTUBE_API_KEY=... в .env (как получить: docs/services.md)")
    return {"key": key}


def get(auth, path, params):
    params = dict(params)
    headers = {}
    if "key" in auth:
        params["key"] = auth["key"]
    else:
        headers["Authorization"] = "Bearer " + auth["header"]
    url = API + path + "?" + urllib.parse.urlencode(params, safe=",")
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=40) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            err = json.load(e).get("error", {})
            reasons = [x.get("reason", "") for x in err.get("errors", [])] + [d.get("reason", "") for d in err.get("details", []) if isinstance(d, dict)]
        except Exception:
            reasons = []
        for r_ in reasons:
            if r_ in REASONS:
                sys.exit("YouTube API: " + REASONS[r_])
        sys.exit(f"YouTube API ответил {e.code}: {', '.join(r for r in reasons if r) or 'без причины'}")


def seconds(iso):
    m = re.match(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    d, h, mi, se = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + se


def collect(auth, queries, days, lang):
    after = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z")
    out = {}
    for q in queries:
        page = get(auth, "search", {"part": "id", "q": q, "type": "video", "order": "viewCount", "maxResults": 50,
                                    "relevanceLanguage": lang, "publishedAfter": after})
        ids = [it["id"]["videoId"] for it in page.get("items", []) if it.get("id", {}).get("videoId")]
        vids = []
        if ids:
            # maxHeight=720: API отдаёт размеры плеера, по ним видно вертикальный ролик (Shorts)
            v = get(auth, "videos", {"part": "snippet,contentDetails,statistics,player", "id": ",".join(ids), "maxHeight": 720})
            for it in v.get("items", []):
                sn, cd, st, pl = it["snippet"], it["contentDetails"], it.get("statistics", {}), it.get("player", {})
                w, h = int(pl.get("embedWidth") or 0), int(pl.get("embedHeight") or 0)
                sec = seconds(cd.get("duration"))
                title = sn.get("title", "")
                vids.append({"id": it["id"], "title": title, "channel": sn.get("channelTitle", ""),
                             "published": sn.get("publishedAt", "")[:10], "sec": sec,
                             "views": int(st.get("viewCount", 0) or 0), "likes": int(st.get("likeCount", 0) or 0),
                             "comments": int(st.get("commentCount", 0) or 0),
                             "cyr": bool(re.search("[а-яА-ЯёЁ]", title)),
                             "short": (h > w if (w and h) else False) and sec <= 180})
        out[q] = vids
        print(f"«{q}»: {len(vids)} роликов")
    return out


def report(data, lang):
    seen = {}
    for vids in data.values():
        for v in vids:
            if (v["cyr"] or lang != "ru") and v["id"] not in seen:
                seen[v["id"]] = v
    vs = list(seen.values())
    lg = [v for v in vs if not v["short"]]
    sh = [v for v in vs if v["short"]]
    med = lambda xs: int(statistics.median(xs)) if xs else 0
    mmss = lambda s: f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"
    esc = lambda t: t.replace("|", "/")
    L = ["# Срез ниши на YouTube", "", f"Запросы: {', '.join(data.keys())}.", "",
         "Выборка: самые просматриваемые ролики по запросам, то есть лидеры ниши. Shorts = вертикальный ролик до 3 минут.", "",
         f"- Роликов: {len(vs)}. Длинных {len(lg)}, медиана просмотров {med([v['views'] for v in lg]):,}. "
         f"Shorts {len(sh)}, медиана {med([v['views'] for v in sh]):,}.", "",
         "## Длина длинных роликов и просмотры", "", "| Длина | Роликов | Медиана просмотров |", "|---|---|---|"]
    for name, lo, hi in [("до 8 мин", 0, 480), ("8–15 мин", 480, 900), ("15–30 мин", 900, 1800), ("30–60 мин", 1800, 3600), ("60+ мин", 3600, 10 ** 9)]:
        xs = [v["views"] for v in lg if lo <= v["sec"] < hi]
        L.append(f"| {name} | {len(xs)} | {med(xs):,} |")
    L += ["", "## Топ-30 длинных", "", "| Просмотры | Длина | Дата | Канал | Заголовок |", "|---|---|---|---|---|"]
    for v in sorted(lg, key=lambda v: -v["views"])[:30]:
        L.append(f"| {v['views']:,} | {mmss(v['sec'])} | {v['published']} | {esc(v['channel'])} | [{esc(v['title'])}](https://youtu.be/{v['id']}) |")
    L += ["", "## Топ-20 Shorts", "", "| Просмотры | Длина | Дата | Канал | Заголовок |", "|---|---|---|---|---|"]
    for v in sorted(sh, key=lambda v: -v["views"])[:20]:
        L.append(f"| {v['views']:,} | {mmss(v['sec'])} | {v['published']} | {esc(v['channel'])} | [{esc(v['title'])}](https://youtu.be/{v['id']}) |")
    ch = collections.defaultdict(lambda: {"n": 0, "views": 0, "long": 0, "short": 0})
    for v in vs:
        c = ch[v["channel"]]
        c["n"] += 1; c["views"] += v["views"]; c["short" if v["short"] else "long"] += 1
    L += ["", "## Каналы, которые чаще всего в топах", "", "| Роликов | Длинных | Shorts | Сумма просмотров | Канал |", "|---|---|---|---|---|"]
    for name, c in sorted(ch.items(), key=lambda kv: (-kv[1]["n"], -kv[1]["views"]))[:25]:
        L.append(f"| {c['n']} | {c['long']} | {c['short']} | {c['views']:,} | {esc(name)} |")
    top = sorted(lg, key=lambda v: -v["views"])[:60]
    pat = {"цифра": r"\d", "вопрос": r"\?", "слово капсом": r"\b[А-ЯЁA-Z]{4,}\b", "«за N минут/часов»": r"за \d+ ?(мин|час|ден|дн)",
           "«как»": r"(?i)\bкак\b", "эмодзи": r"[\U0001F300-\U0001FAFF☀-➿]"}
    L += ["", f"## Приёмы в заголовках топ-{len(top)} длинных", ""]
    for k, rx in pat.items():
        L.append(f"- {k}: {sum(1 for v in top if re.search(rx, v['title']))} из {len(top)}")
    return "\n".join(L) + "\n", len(vs)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="проверить ключ (1 единица квоты)")
    r = sub.add_parser("run", help="собрать срез и отчёт")
    r.add_argument("queries", nargs="+")
    r.add_argument("--days", type=int, default=365)
    r.add_argument("--lang", default="ru")
    r.add_argument("--out", default="work/youtube-niche")
    a = p.parse_args()
    auth = load_auth()
    if a.cmd == "check":
        get(auth, "videos", {"part": "id", "id": "dQw4w9WgXcQ"})
        print("Ключ YouTube API работает.")
        return
    if len(a.queries) > 30:
        sys.exit("Больше 30 запросов за раз не нужно: это 3 000 единиц квоты. Оставьте самые важные.")
    data = collect(auth, a.queries, a.days, a.lang)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(data, open(a.out + ".json", "w", encoding="utf-8"), ensure_ascii=False)
    text, n = report(data, a.lang)
    open(a.out + ".md", "w", encoding="utf-8").write(text)
    print(f"Готово: {a.out}.md ({n} роликов), сырые данные: {a.out}.json")


if __name__ == "__main__":
    main()
