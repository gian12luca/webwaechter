# Webwächter

Überwacht Webseiten bzw. die Daten dahinter und schickt bei Neuem einen Push aufs Handy (ntfy). Läuft alle 5 Minuten als GitHub Action.

## Aktive Wächter

| ID | Was | bis |
| --- | --- | --- |
| `freiburg-2027-halbmarathon` | Startplatzbörse Freiburg Marathon 2027, nur Halbmarathon | 4.4.2027 |

## Wie es funktioniert

- `watches.json` listet die Wächter. Jeder hat einen `type`; `waechter.py` kennt bisher `raceresult-liste`.
- `raceresult-liste`: Die Startplatzbörse ist ein race|result-Widget. Es lädt die Liste als JSON von `my.raceresult.com/<event>/<page>/config` und `…/list`. Der Wächter fragt genau diese Daten ab, nicht die HTML-Seite. Das `#0_DF85F0` in der Browser-URL ist nur die Anzeige (Wettbewerb 0 = alle, Liste DF85F0) und bleibt gleich.
- Neue Einträge (verglichen mit `state/<id>.json`) lösen eine ntfy-Meldung mit Link zum Kaufformular aus. Im Stand stehen nur Hash-Kennungen, keine Namen.
- Bei 6 Fehlern in Folge kommt eine Störungsmeldung; kann der Wächter Einträge nicht lesen, warnt er einmal.

## Einrichten

1. ntfy-App aufs iPhone (App Store, «ntfy»), Kanal (Topic) mit einem langen, zufälligen Namen abonnieren. Wer den Namen kennt, bekommt die Meldungen.
2. GitHub-Secret `NTFY_TOPIC` mit diesem Namen setzen.
3. Lokal testen: `NTFY_TOPIC=<kanal> python3 waechter.py --test-notify`, Probelauf ohne Meldung: `python3 waechter.py --dry-run`.
4. Tests: `python3 -m unittest test_waechter`.

## Neuen Wächter hinzufügen

Eintrag in `watches.json` ergänzen. Für einen neuen Seitentyp eine Funktion `pruefe_<typ>(w)` in `waechter.py` schreiben und in `TYPEN` eintragen. Sie gibt `(eintraege, roh_anzahl, hat_daten)` zurück; jeder Eintrag hat `id` (Hash), `datum`, `link`, `gruppe`.
