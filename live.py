#!/usr/bin/env python3
import requests, json, gzip, zlib, time, os, sys, shutil, base64
from datetime import datetime, timezone
from pathlib import Path
from threading import Thread
from flask import Flask
app = Flask(__name__)
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO", "dng-ui/live-bot")
GITHUB_PATH = "data/short_football_totals.csv"
def github_headers():
    return {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"} if GITHUB_TOKEN else {}
def pull_from_github():
    if not GITHUB_TOKEN or SAVE_PATH.exists(): return
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_PATH}"
        r = requests.get(url, headers=github_headers(), timeout=10)
        if r.status_code == 200:
            content = base64.b64decode(r.json()["content"])
            SAVE_PATH.parent.mkdir(parents=True, exist_ok=True)
            SAVE_PATH.write_bytes(content)
            print(f"[GH] Pull OK")
    except Exception as e: print(f"[GH] Pull fail: {e}")
def push_to_github():
    if not GITHUB_TOKEN: return
    try:
        if not SAVE_PATH.exists(): return
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_PATH}"
        with open(SAVE_PATH, "rb") as f: b64 = base64.b64encode(f.read()).decode()
        r = requests.get(url, headers=github_headers(), timeout=10)
        sha = r.json().get("sha") if r.status_code == 200 else None
        data = {"message": f"auto: {len(SAVED)} matchs", "content": b64}
        if sha: data["sha"] = sha
        requests.put(url, headers=github_headers(), json=data, timeout=15)
    except: pass
def send_csv_to_telegram():
    if not BOT_TOKEN or not CHAT_ID: return
    if not SAVE_PATH.exists(): return
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
        with open(SAVE_PATH, 'rb') as f:
            requests.post(url, data={"chat_id": CHAT_ID, "caption": f"CSV {datetime.now().strftime('%H:%M')} UTC - {len(SAVED)} sauves"}, files={"document": f}, timeout=30)
    except: pass
@app.route("/")
def home(): return f"bot STRICT - tracked:{len(TRACKED)} saved:{len(SAVED)} ignores:{IGNORED_LATE}"
def run_web():
    port = int(os.environ.get("PORT", "10000")); app.run(host="0.0.0.0", port=port)
MIGRATION_DOMAINS = ["1xbet.cm","1xbet.ci","1xbet.sn","1xbet.cd","1x-bet.cm"]
GAME_URL_TMPL = "https://{dom}/service-api/LiveFeed/GetGameZip?id={gid}&lng=fr&cfview=0&isSubGames=true&GroupEvents=true&countevents=1000&grMode=4"
FAIL_STREAK_LIMIT = 15; current_domain_idx = 0; fail_streak = 0
def fetch_by_id_persistent(session, gid, headers_base):
    for dom in MIGRATION_DOMAINS:
        try:
            url = GAME_URL_TMPL.format(dom=dom, gid=gid)
            h = headers_base.copy(); h["Referer"] = f"https://{dom}/fr/live/"; h["Origin"] = f"https://{dom}"
            r = session.get(url, headers=h, timeout=6)
            if r.status_code!=200: continue
            v = r.json().get("Value")
            if not v: continue
            sc = v.get("SC",{}) or {}; sec = int(sc.get("TS",0) or 0); s1 = int(sc.get("FS",{}).get("S1",0) or 0); s2 = int(sc.get("FS",{}).get("S2",0) or 0)
            return {"id": str(v.get("I", gid)), "type": (v.get("LE","") or "").strip(), "team1": v.get("O1",""), "team2": v.get("O2",""), "sec": sec, "score1": s1, "score2": s2, "total": s1+s2}
        except: continue
    return None
DOMAIN = "1xbet.cm"; BASE = f"https://{DOMAIN}"
HEADERS = {"User-Agent": "Mozilla/5.0","Accept": "application/json","Accept-Language": "fr-FR,fr;q=0.9","Accept-Encoding": "gzip, deflate","Referer": f"{BASE}/fr/live/","Origin": BASE}
URL = f"{BASE}/service-api/LiveFeed/Get1x2_Zip?sports=1&count=1000&lng=fr&mode=4&getEmpty=true"
POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL", "1.0"))
TARGET_130, TARGET_300, MISSING_LIMIT = 130, 300, 30
TYPE_KEYWORDS = [k.strip().lower() for k in os.environ.get("TYPE_KEYWORDS", "short,subsoccer").split(",") if k.strip()]
SAVE_PATH = Path(os.environ.get("SAVE_PATH", "./data/short_football_totals.csv")).expanduser()
SAVE_PATH.parent.mkdir(parents=True, exist_ok=True)
TRACKED, SAVED = {}, []; IGNORED_LATE = 0
def now_str(): return datetime.now(timezone.utc).strftime("%H:%M:%S")
def fmt_mmss(sec): return f"{int(sec)//60:02d}:{int(sec)%60:02d}"
def decode(r):
    try: return r.json()
    except:
        try: return json.loads(gzip.decompress(r.content).decode())
        except:
            try: return json.loads(zlib.decompress(r.content, 16+zlib.MAX_WBITS).decode())
            except: return {}
def parse_score(sc):
    try: s1 = int(sc.get("FS",{}).get("S1",0) or 0)
    except: s1=0
    try: s2 = int(sc.get("FS",{}).get("S2",0) or 0)
    except: s2=0
    return s1,s2
def fetch_live_matches(session):
    global DOMAIN,BASE,URL,current_domain_idx,fail_streak
    r = session.get(URL, headers=HEADERS, timeout=8); data = decode(r); raw_events = data.get("Value",[]) or []
    if not raw_events:
        fail_streak+=1
        if fail_streak>=FAIL_STREAK_LIMIT:
            current_domain_idx=(current_domain_idx+1)%len(MIGRATION_DOMAINS); DOMAIN=MIGRATION_DOMAINS[current_domain_idx]; BASE=f"https://{DOMAIN}"; URL=f"{BASE}/service-api/LiveFeed/Get1x2_Zip?sports=1&count=1000&lng=fr&mode=4&getEmpty=true"; HEADERS["Referer"]=f"{BASE}/fr/live/"; HEADERS["Origin"]=BASE; fail_streak=0
    else: fail_streak=0
    matches=[]
    for ev in raw_events:
        sc=ev.get("SC",{}) or {}; sec=int(sc.get("TS",0) or 0); team1,team2=ev.get("O1",""),ev.get("O2","")
        type_exact=(ev.get("LE","") or "").strip()
        if not any(kw in type_exact.lower() for kw in TYPE_KEYWORDS): continue
        s1,s2=parse_score(sc); ev_id=ev.get("I", f"{type_exact}_{team1}_{team2}")
        matches.append({"id":str(ev_id),"type":type_exact,"team1":team1,"team2":team2,"sec":sec,"score1":s1,"score2":s2,"total":s1+s2})
    for mid in list(TRACKED.keys()):
        if mid not in [m["id"] for m in matches] and TRACKED[mid]["missing"]>0 and TRACKED[mid]["missing"]<MISSING_LIMIT:
            rescued=fetch_by_id_persistent(session,mid,HEADERS)
            if rescued: matches.append(rescued); TRACKED[mid]["missing"]=0
    return matches,len(raw_events)
def load_existing_csv():
    if not SAVE_PATH.exists(): return
    try:
        with open(SAVE_PATH,"r",encoding="utf-8") as f:
            import csv as _csv
            for row in _csv.DictReader(f):
                SAVED.append({"date":row.get("date_utc",""),"type_short":row.get("type",""),"match_str":row.get("match",""),"t130":row.get("total_2m10") or None,"t300":row.get("total_5m00") or None,"last_score_str":row.get("score",""),"last_sec":0,"last_total":0,"missing":99})
    except: pass
def flush_to_csv():
    import csv as _csv
    tmp=SAVE_PATH.with_suffix(SAVE_PATH.suffix+".tmp")
    with open(tmp,"w",newline="",encoding="utf-8") as f:
        w=_csv.writer(f); w.writerow(["date_utc","type","match","total_2m10","total_5m00","score"])
        for rec in sorted(SAVED,key=lambda x:x["date"]): w.writerow([rec["date"],rec["type_short"],rec["match_str"],rec["t130"] if rec["t130"] is not None else "",rec["t300"] if rec["t300"] is not None else "",rec["last_score_str"]])
    tmp.replace(SAVE_PATH); Thread(target=send_csv_to_telegram, daemon=True).start(); Thread(target=push_to_github, daemon=True).start()
def update_tracking(matches):
    global IGNORED_LATE
    now_ids=set(); changed=False
    for m in matches:
        mid=m["id"]; now_ids.add(mid); match_str=f"{m['team1']} vs {m['team2']}"; type_short=m["type"].replace("Short Football ","").replace("Short football ","")
        if mid not in TRACKED:
            if m["sec"] > TARGET_130: IGNORED_LATE+=1; continue
            TRACKED[mid]={"date":datetime.now(timezone.utc).isoformat(),"type_short":type_short,"match_str":match_str,"t130":None,"t300":None,"last_total":m["total"],"last_score_str":f"{m['score1']}-{m['score2']}","last_sec":m["sec"],"missing":0}
        rec=TRACKED.get(mid)
        if not rec: continue
        rec["last_total"]=m["total"]; rec["last_score_str"]=f"{m['score1']}-{m['score2']}"; rec["last_sec"]=m["sec"]; rec["missing"]=0
        if rec["t130"] is None and m["sec"]>=TARGET_130: rec["t130"]=m["total"]; changed=True
        if rec["t300"] is None and m["sec"]>=TARGET_300: rec["t300"]=m["total"]; changed=True
    for mid in list(TRACKED.keys()):
        if mid not in now_ids:
            TRACKED[mid]["missing"]+=1
            if TRACKED[mid]["missing"]>=MISSING_LIMIT:
                if TRACKED[mid]["t130"] is not None: SAVED.append(TRACKED[mid])
                del TRACKED[mid]; changed=True
    if changed: flush_to_csv()
def render_table(matches,total_events,last_error):
    cols=shutil.get_terminal_size((80,24)).columns
    live_list=sorted(TRACKED.values(),key=lambda x:x["date"])
    saved_list=sorted(SAVED,key=lambda x:x["date"])
    lines=[]
    lines.append(f"LIVE Short Football STRICT — {now_str()} UTC — {len(matches)} live | {len(live_list)} EN SUIVI | {len(saved_list)} SAUVES | {IGNORED_LATE} ignores >130s | {DOMAIN}")
    if last_error: lines.append(f"Erreur: {last_error}")
    lines.append("-"*cols)
    lines.append(f"EN SUIVI ({len(live_list)}):")
    for rec in live_list[-10:]:
        lines.append(f" {rec['type_short'][:6]:6} {rec['match_str'][:28]:28} | {fmt_mmss(rec['last_sec'])} | {rec['last_score_str']:5} | t130={str(rec['t130']):4} t300={str(rec['t300']):4}")
    lines.append("-"*cols)
    lines.append(f"SAUVES ({len(saved_list)}):")
    for rec in saved_list[-10:]:
        lines.append(f" {rec['date'][11:19]} {rec['type_short'][:6]:6} {rec['match_str'][:24]:24} | 2m10={rec['t130']} 5m00={rec['t300']} score={rec['last_score_str']}")
    lines.append("-"*cols)
    return "\n".join(lines)
def main():
    Thread(target=run_web, daemon=True).start()
    pull_from_github()
    session=requests.Session(); load_existing_csv()
    last_error=None
    print(f"Demarrage STRICT - {len(SAVED)} deja sauves",flush=True)
    while True:
        t0=time.monotonic()
        try: matches,total=fetch_live_matches(session); update_tracking(matches); last_error=None
        except Exception as e: last_error=str(e); matches,total=[],0
        os.system("cls" if os.name=="nt" else "clear")
        print(render_table(matches,total,last_error))
        time.sleep(max(0.0,POLL_INTERVAL-(time.monotonic()-t0)))
if __name__=="__main__":
    try: main()
    except KeyboardInterrupt:
        flush_to_csv(); print(f"\nArret: {SAVE_PATH}")
