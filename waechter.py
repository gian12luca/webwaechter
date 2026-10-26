#!/usr/bin/env python3
"""Webwächter: prüft die Wächter aus watches.json und meldet Neues per ntfy-Push.

Aufruf:
  python3 waechter.py                 alle aktiven Wächter prüfen, Neues melden, Stand speichern
  python3 waechter.py --dry-run       nur anzeigen, nichts melden, nichts speichern
  python3 waechter.py --test-notify   Testnachricht an den ntfy-Kanal schicken
  python3 waechter.py --watch ID      nur diesen Wächter prüfen

Umgebung: NTFY_TOPIC (geheimer Kanalname, Pflicht ausser bei --dry-run), NTFY_SERVER (Standard https://ntfy.sh).
Nur Python-Standardbibliothek, damit es in GitHub Actions ohne Installation läuft.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE_DIR = ROOT / "state"
UA = "Mozilla/5.0 (webwaechter; private Startplatz-Benachrichtigung)"
FEHLER_MELDEN_AB = 6  # so viele Fehlversuche in Folge (bei 5-Min-Takt ca. 30 Min.), dann eine Störungsmeldung


# ---------- Hilfen ----------

def hole_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def kurz_hash(*teile):
    """Stabile Kennung ohne Klartext: im Repo stehen keine Personendaten."""
    return hashlib.sha256(":".join(str(t) for t in teile).encode()).hexdigest()[:16]


def lade_stand(watch_id):
    p = STATE_DIR / f"{watch_id}.json"
    if p.exists():
        return json.loads(p.read_text())
    return {"gesehen": [], "fehler": 0, "strukturwarnung": False}


def speichere_stand(watch_id, stand):
    STATE_DIR.mkdir(exist_ok=True)
    p = STATE_DIR / f"{watch_id}.json"
    neu = json.dumps(stand, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if not p.exists() or p.read_text() != neu:
        p.write_text(neu)


def melde(titel, text, link=None, prio=4, tags=None, dry_run=False):
    if dry_run:
        print(f"  [dry-run] Meldung: {titel} | {text} | {link or ''}")
        return
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        raise SystemExit("NTFY_TOPIC fehlt (GitHub Secret bzw. Umgebungsvariable).")
    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    nachricht = {"topic": topic, "title": titel, "message": text, "priority": prio, "tags": tags or []}
    if link:
        nachricht["click"] = link
        nachricht["actions"] = [{"action": "view", "label": "Öffnen", "url": link, "clear": True}]
    req = urllib.request.Request(
        server + "/",
        data=json.dumps(nachricht).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": UA},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        r.read()
    print(f"  Meldung gesendet: {titel}")


# ---------- Wächter-Typ: raceresult-liste ----------
# race|result (RRPublish) lädt Listen als JSON: zuerst /<event>/<page>/config (Schlüssel, Server, Listenname),
# dann /<event>/<page>/list. Der Teil «#0_DF85F0» in der Browser-URL ist nur Anzeige (Wettbewerb 0, Listen-ID)
# und ändert sich nicht. Gruppen in "data" heissen z.B. "#2_Halbmarathon" (Wettbewerb-ID 2).

def zeilen_ablaufen(knoten, pfad=()):
    """Liefert (Gruppenpfad, Zeile) für alle Zeilen, egal wie tief race|result gruppiert."""
    if isinstance(knoten, dict):
        for k, v in knoten.items():
            yield from zeilen_ablaufen(v, pfad + (str(k),))
    elif isinstance(knoten, list):
        if knoten and all(isinstance(z, list) for z in knoten):
            for z in knoten:
                yield pfad, z


def gruppe_passt(pfad, wettbewerb, wettbewerb_id):
    if not pfad:
        return True  # ohne Gruppierung lässt sich nicht filtern: lieber melden als verpassen
    for teil in pfad:
        m = re.match(r"#(\d+)_(.*)", teil)
        name = (m.group(2) if m else teil).strip().lower()
        if name == wettbewerb.lower():
            return True
        if m and wettbewerb_id is not None and m.group(1) == str(wettbewerb_id):
            return True
    return False


def pruefe_raceresult(w):
    """Gibt (eintraege, roh_anzahl) zurück; eintraege = Liste von dicts mit id, datum, link, gruppe."""
    basis = f"https://my.raceresult.com/{w['event']}/{w['page']}"
    cfg = hole_json(f"{basis}/config?lang=de")
    listen = cfg["TabConfig"]["Lists"]
    liste = next((l for l in listen if l.get("ID") == w.get("liste_id")), listen[0])
    wettbewerb_id = next(
        (k for k, v in cfg.get("contests", {}).items() if v.lower() == w["wettbewerb"].lower()), None
    )
    params = {
        "key": cfg["key"], "listname": liste["Name"], "page": w["page"],
        "contest": liste.get("Contest", "0"), "r": "all", "l": "0", "openedGroups": "{}", "term": "",
    }
    server = cfg.get("server") or "my.raceresult.com"
    daten = hole_json(f"https://{server}/{w['event']}/{w['page']}/list?" + urllib.parse.urlencode(params))

    felder = daten.get("DataFields", [])
    i_id = felder.index("ID") if "ID" in felder else None
    i_link = next((i for i, f in enumerate(felder) if f.startswith('"http')), None)
    i_datum = next((i for i, f in enumerate(felder) if f.startswith("date(")), None)

    roh = list(zeilen_ablaufen(daten.get("data")))
    eintraege = []
    for pfad, z in roh:
        if not gruppe_passt(pfad, w["wettbewerb"], wettbewerb_id):
            continue
        roh_id = z[i_id] if i_id is not None and i_id < len(z) else json.dumps(z)
        eintraege.append({
            "id": kurz_hash(w["event"], roh_id),
            "datum": z[i_datum] if i_datum is not None and i_datum < len(z) else "",
            "link": z[i_link] if i_link is not None and i_link < len(z) else w["seite"],
            "gruppe": " / ".join(re.sub(r"^#\d+_", "", p) for p in pfad),
        })
    hat_daten = bool(daten.get("data"))
    return eintraege, len(roh), hat_daten


TYPEN = {"raceresult-liste": pruefe_raceresult}


# ---------- Ablauf ----------

def pruefe_wache(w, dry_run):
    print(f"Wächter {w['id']}: {w['name']}")
    stand = lade_stand(w["id"])
    try:
        eintraege, roh_anzahl, hat_daten = TYPEN[w["type"]](w)
    except Exception as e:  # Netzwerk, geänderte Struktur …
        stand["fehler"] = stand.get("fehler", 0) + 1
        print(f"  Fehler ({stand['fehler']}. in Folge): {e!r}")
        if stand["fehler"] == FEHLER_MELDEN_AB:
            melde(f"Wächter gestört: {w['name']}",
                  f"Seit {FEHLER_MELDEN_AB} Versuchen Fehler: {e!r}. Bitte Seite selbst prüfen.",
                  w.get("seite"), prio=3, tags=["warning"], dry_run=dry_run)
        if not dry_run:
            speichere_stand(w["id"], stand)
        return False

    if stand.get("fehler"):
        print("  wieder erreichbar")
    stand["fehler"] = 0
    print(f"  {roh_anzahl} Einträge in der Liste, {len(eintraege)} für «{w['wettbewerb']}»")

    # Daten da, aber keine Zeile erkannt: Struktur hat sich geändert → einmal warnen
    if hat_daten and roh_anzahl == 0:
        if not stand.get("strukturwarnung"):
            melde(f"Prüfen: {w['name']}",
                  "Die Liste hat Einträge, der Wächter kann sie aber nicht lesen. Bitte selbst nachsehen.",
                  w.get("seite"), prio=4, tags=["warning"], dry_run=dry_run)
            stand["strukturwarnung"] = True
    else:
        stand["strukturwarnung"] = False

    gesehen = set(stand.get("gesehen", []))
    neu = [e for e in eintraege if e["id"] not in gesehen]
    for e in neu:
        datum = f" (eingestellt {e['datum']})" if e["datum"] else ""
        melde(w["titel"], f"{w['name']}: neuer Eintrag{datum}. Schnell sein!", e["link"],
              prio=5, tags=w.get("tags", []), dry_run=dry_run)
    # Gemerkt wird nur, was aktuell gelistet ist: verschwindet ein Platz und kommt wieder, gibt es erneut eine Meldung.
    stand["gesehen"] = sorted(e["id"] for e in eintraege)
    if not dry_run:
        speichere_stand(w["id"], stand)
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--test-notify", action="store_true")
    ap.add_argument("--watch")
    args = ap.parse_args()

    if args.test_notify:
        melde("Webwächter: Test", "Wenn du das liest, kommen die Meldungen an.", tags=["white_check_mark"])
        return 0

    watches = json.loads((ROOT / "watches.json").read_text())["watches"]
    heute = datetime.date.today().isoformat()
    ok = True
    for w in watches:
        if args.watch and w["id"] != args.watch:
            continue
        if not w.get("aktiv", True) or (w.get("aktiv_bis") and heute > w["aktiv_bis"]):
            print(f"Wächter {w['id']}: inaktiv, übersprungen")
            continue
        ok = pruefe_wache(w, args.dry_run) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
