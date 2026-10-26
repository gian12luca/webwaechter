"""Tests ohne Netz: python3 -m unittest test_waechter"""
import unittest
from unittest import mock

import waechter

WACHE = {
    "id": "test", "name": "Test", "titel": "Startplatz frei", "type": "raceresult-liste",
    "event": 1, "page": "boerse", "liste_id": "DF85F0", "wettbewerb": "Halbmarathon",
    "seite": "https://example.org/",
}
CONFIG = {
    "key": "k", "server": "my3.raceresult.com",
    "contests": {"1": "Marathon", "2": "Halbmarathon"},
    "TabConfig": {"Lists": [{"Name": "08_Liste", "Contest": "0", "ID": "DF85F0"}]},
}
FELDER = ["BIB", "ID", "FIRSTNAME", '"> Kaufen"', 'date("dd.mm.yyyy"; [ZeitStartplatz])',
          '"https://events.raceresult.com/registrations/?URLID="&[URLID]']


def liste(data):
    return {"data": data, "DataFields": FELDER}


def zeile(pid, datum="01.11.2026"):
    return ["", pid, "Vorname", "> Kaufen", datum, f"https://events.raceresult.com/registrations/?URLID={pid}"]


class RaceresultTest(unittest.TestCase):
    def lauf(self, data):
        with mock.patch.object(waechter, "hole_json", side_effect=[CONFIG, liste(data)]):
            return waechter.pruefe_raceresult(WACHE)

    def test_leer(self):
        self.assertEqual(self.lauf([]), ([], 0, False))

    def test_filtert_wettbewerb(self):
        data = {"#1_Marathon": [zeile(10)], "#2_Halbmarathon": [zeile(20), zeile(21)]}
        eintraege, roh, _ = self.lauf(data)
        self.assertEqual(roh, 3)
        self.assertEqual([e["link"][-2:] for e in eintraege], ["20", "21"])
        self.assertNotIn("Vorname", str(eintraege))  # keine Personendaten im Stand

    def test_verschachtelt(self):
        data = {"#1_Gruppe": {"#2_Halbmarathon": [zeile(30)]}}
        eintraege, _, _ = self.lauf(data)
        self.assertEqual(len(eintraege), 1)

    def test_neu_wird_gemeldet_und_gemerkt(self):
        data = {"#2_Halbmarathon": [zeile(40)]}
        with mock.patch.object(waechter, "hole_json", side_effect=[CONFIG, liste(data)] * 2), \
             mock.patch.object(waechter, "melde") as melde, \
             mock.patch.object(waechter, "lade_stand", return_value={"gesehen": []}), \
             mock.patch.object(waechter, "speichere_stand") as speichere:
            waechter.pruefe_wache(WACHE, dry_run=False)
            self.assertEqual(melde.call_count, 1)
            stand = speichere.call_args[0][1]
        with mock.patch.object(waechter, "hole_json", side_effect=[CONFIG, liste(data)]), \
             mock.patch.object(waechter, "melde") as melde, \
             mock.patch.object(waechter, "lade_stand", return_value=stand), \
             mock.patch.object(waechter, "speichere_stand"):
            waechter.pruefe_wache(WACHE, dry_run=False)
            melde.assert_not_called()


if __name__ == "__main__":
    unittest.main()
