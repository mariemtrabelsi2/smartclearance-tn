"""Collecte des exportations mensuelles des partenaires vers la Tunisie (UN Comtrade).

    py outils/collecter_mensuel.py

La Tunisie ne declare pas a Comtrade (isReported=false) : on passe par le cote
PARTENAIRE, qui declare mensuellement ses exportations (flowCode X) vers la
Tunisie (partnerCode 788), pour les couples (code SH, pays) du bareme.

Apercu public sans cle : UNE periode par appel, ~1 requete/s. Resultat ecrit au
fil de l'eau dans donnees/prix_mensuels.csv (une collecte interrompue reste
exploitable) et donnees/collecte_mensuelle_rapport.json.

Aucune substitution : ni d'un partenaire par un autre, ni d'un code par un autre
(851712 en SH 2017 couvre tous les telephones cellulaires, 851713 en SH 2022
les seuls smartphones : ce ne sont pas les memes series).
"""
import csv
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agents import stockage  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent
SORTIE = RACINE / "donnees" / "prix_mensuels.csv"
RAPPORT = RACINE / "donnees" / "collecte_mensuelle_rapport.json"
URL = ("https://comtradeapi.un.org/public/v1/preview/C/M/HS?reporterCode={pays}"
       "&partnerCode=788&flowCode=X&cmdCode={sh}&period={periode}")
CODES_PAYS = {"CN": 156, "ES": 724, "IT": 380, "TR": 792, "EG": 818}
PERIODES = [f"{a}{m:02d}" for a in (2021, 2022, 2023) for m in range(1, 13)]
PAUSE_S = 1.1


def appeler(url):
    """-> (liste d'enregistrements, erreur). Un seul nouvel essai, sur limite de debit."""
    for essai in (1, 2):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "smartclearance-hackathon"})
            with urllib.request.urlopen(req, timeout=30) as r:
                rep = json.loads(r.read())
            return rep.get("data") or [], rep.get("error") or None
        except urllib.error.HTTPError as e:
            if e.code == 429 and essai == 1:
                time.sleep(5)
                continue
            return [], f"HTTP {e.code}"
        except Exception as e:
            return [], type(e).__name__
    return [], "echec"


def main():
    """--reprendre : ne reinterroge que les mois ABSENTS du fichier, pour les seuls
    couples qui ont eu des erreurs (quota de l'API publique). Rien n'est ecrase."""
    sys.stdout.reconfigure(encoding="utf-8")
    reprise = "--reprendre" in sys.argv and SORTIE.exists() and RAPPORT.exists()
    couples = sorted({(l["code_sh"], l["pays_origine"]) for l in stockage.lire_bareme() or []})
    SORTIE.parent.mkdir(exist_ok=True)
    deja = set()
    if reprise:
        rapport = json.loads(RAPPORT.read_text(encoding="utf-8"))
        with open(SORTIE, newline="", encoding="utf-8") as f:
            deja = {(l["code_sh"], l["pays"], l["annee"] + l["mois"]) for l in csv.DictReader(f)}
        couples = [(sh, p) for sh, p in couples if rapport["couples"].get(f"{sh}/{p}", {}).get("erreurs")]
        print("Reprise pour :", [f"{sh}/{p}" for sh, p in couples])
    else:
        rapport = {"periodes_interrogees": f"{PERIODES[0]}..{PERIODES[-1]}", "couples": {}}
    with open(SORTIE, "a" if reprise else "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if not reprise:
            w.writerow(["code_sh", "pays", "annee", "mois", "valeur", "poids", "prix_kg",
                        "poids_estime", "classification"])
        for sh, pays in couples:
            info = rapport["couples"].get(f"{sh}/{pays}") if reprise else None
            info = info or {"appels": 0, "mois_avec_donnees": 0, "erreurs": {}}
            if reprise:
                info["erreurs"] = {}           # on ne garde que les erreurs de ce passage
            rapport["couples"][f"{sh}/{pays}"] = info
            if pays not in CODES_PAYS:
                info["erreurs"]["pays sans code Comtrade"] = 1
                continue
            for periode in PERIODES:
                if (sh, pays, periode) in deja:
                    continue
                donnees, erreur = appeler(URL.format(pays=CODES_PAYS[pays], sh=sh, periode=periode))
                info["appels"] += 1
                if erreur:
                    info["erreurs"][erreur] = info["erreurs"].get(erreur, 0) + 1
                # Le total du flux : pas de ventilation par mode de transport ni regime.
                lignes = [d for d in donnees if d.get("cmdCode") == sh and d.get("partner2Code") == 0
                          and d.get("motCode") == 0 and d.get("customsCode") == "C00"]
                for d in lignes:
                    v, p = d.get("primaryValue"), d.get("netWgt")
                    if v and p:
                        w.writerow([sh, pays, periode[:4], periode[4:], v, p, round(v / p, 4),
                                    bool(d.get("isNetWgtEstimated")), d.get("classificationCode")])
                        info["mois_avec_donnees"] += 1
                f.flush()
                time.sleep(PAUSE_S)
            print(f"{sh}/{pays} : {info['mois_avec_donnees']}/{info['appels']} mois avec donnees"
                  + (f" | erreurs : {info['erreurs']}" if info["erreurs"] else ""), flush=True)
            RAPPORT.write_text(json.dumps(rapport, indent=2, ensure_ascii=False), encoding="utf-8")
    RAPPORT.write_text(json.dumps(rapport, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Ecrit : {SORTIE} et {RAPPORT}")


if __name__ == "__main__":
    main()
