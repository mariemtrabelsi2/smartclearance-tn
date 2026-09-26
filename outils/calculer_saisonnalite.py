"""Indices saisonniers par couple (code SH, pays), a partir de donnees/prix_mensuels.csv.

    py outils/calculer_saisonnalite.py

Seuils NON negociables (sinon aucun indice, comportement inchange) :
  - au moins 24 observations mensuelles, et au moins 2 pour CHAQUE mois :
    sur 12 mois, on ne distingue pas "decembre est cher" de "les prix ont monte
    cette annee-la" ; il faut deux cycles ;
  - tout indice hors [0.80, 1.25] fait ecarter le couple (bruit plus probable
    qu'une saison) ;
  - amplitude (max/min des indices) < 1.10 : produit non saisonnier, aucun indice.
Les poids estimes par Comtrade sont exclus : un prix au kilo sur un poids estime
est une estimation d'estimation.

Sorties : donnees/saisonnalite.csv (seulement les couples etablis) et
donnees/saisonnalite_rapport.csv (TOUS les couples, avec le motif).
"""
import csv
import json
import statistics
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
ENTREE = RACINE / "donnees" / "prix_mensuels.csv"
COLLECTE = RACINE / "donnees" / "collecte_mensuelle_rapport.json"
INDICES = RACINE / "donnees" / "saisonnalite.csv"
RAPPORT = RACINE / "donnees" / "saisonnalite_rapport.csv"

MIN_OBS, MIN_PAR_MOIS = 24, 2
BORNE_BASSE, BORNE_HAUTE = 0.80, 1.25
AMPLITUDE_MIN = 1.10


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    collecte = json.loads(COLLECTE.read_text(encoding="utf-8"))["couples"] if COLLECTE.exists() else {}
    series = {}
    estimes = {}
    if ENTREE.exists():
        with open(ENTREE, newline="", encoding="utf-8") as f:
            for l in csv.DictReader(f):
                cle = f"{l['code_sh']}/{l['pays']}"
                if l["poids_estime"] == "True":
                    estimes[cle] = estimes.get(cle, 0) + 1
                    continue
                series.setdefault(cle, []).append((int(l["mois"]), float(l["prix_kg"])))

    lignes_rapport, lignes_indices = [], []
    for cle in sorted(set(collecte) | set(series)):
        obs = series.get(cle, [])
        par_mois = {m: [p for mm, p in obs if mm == m] for m in range(1, 13)}
        min_mois = min(len(v) for v in par_mois.values())
        info = collecte.get(cle, {})
        ligne = {"couple": cle, "appels": info.get("appels", ""),
                 "mois_avec_donnees": info.get("mois_avec_donnees", len(obs)),
                 "poids_estimes_exclus": estimes.get(cle, 0), "nb_observations": len(obs),
                 "min_obs_par_mois": min_mois, "amplitude": "", "indice_etabli": "non", "motif": ""}
        if len(obs) < MIN_OBS or min_mois < MIN_PAR_MOIS:
            manque = [m for m, v in par_mois.items() if len(v) < MIN_PAR_MOIS]
            ligne["motif"] = (f"saisonnalite non etablie : {len(obs)} observation(s) (minimum {MIN_OBS}), "
                              f"{len(manque)} mois avec moins de {MIN_PAR_MOIS} observations")
        else:
            globale = statistics.median(p for _, p in obs)
            indices = {m: statistics.median(v) / globale for m, v in par_mois.items()}
            amplitude = max(indices.values()) / min(indices.values())
            ligne["amplitude"] = round(amplitude, 3)
            hors = {m: round(i, 2) for m, i in indices.items() if not BORNE_BASSE <= i <= BORNE_HAUTE}
            if hors:
                ligne["motif"] = f"ecarte : indice(s) hors [{BORNE_BASSE}, {BORNE_HAUTE}] {hors} (bruit probable)"
            elif amplitude < AMPLITUDE_MIN:
                ligne["motif"] = f"non saisonnier : amplitude {amplitude:.3f} < {AMPLITUDE_MIN}"
            else:
                ligne["indice_etabli"] = "oui"
                ligne["motif"] = "indice etabli"
                sh, pays = cle.split("/")
                for m, i in indices.items():
                    lignes_indices.append({"code_sh": sh, "pays": pays, "mois": m, "indice": round(i, 4),
                                           "nb_observations": len(obs), "amplitude": round(amplitude, 3)})
        lignes_rapport.append(ligne)

    with open(RAPPORT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(lignes_rapport[0]) if lignes_rapport else ["couple"])
        w.writeheader(); w.writerows(lignes_rapport)
    if lignes_indices:
        with open(INDICES, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(lignes_indices[0]))
            w.writeheader(); w.writerows(lignes_indices)
    elif INDICES.exists():
        INDICES.unlink()        # aucun indice etabli : pas de fichier, comportement inchange

    for l in lignes_rapport:
        print(f"{l['couple']:12} appels {str(l['appels']):>3} | mois avec donnees {str(l['mois_avec_donnees']):>3} "
              f"| obs retenues {l['nb_observations']:>3} (poids estimes exclus : {l['poids_estimes_exclus']}) "
              f"| min/mois {l['min_obs_par_mois']} | {l['motif']}")
    print(f"\nCouples interroges : {len(lignes_rapport)} | avec donnees : "
          f"{sum(1 for l in lignes_rapport if l['nb_observations'])} | >= {MIN_OBS} obs : "
          f"{sum(1 for l in lignes_rapport if l['nb_observations'] >= MIN_OBS)} | seuil complet (2/mois) : "
          f"{sum(1 for l in lignes_rapport if l['nb_observations'] >= MIN_OBS and l['min_obs_par_mois'] >= MIN_PAR_MOIS)} "
          f"| amplitude > {AMPLITUDE_MIN} : "
          f"{sum(1 for l in lignes_rapport if l['amplitude'] != '' and l['amplitude'] > AMPLITUDE_MIN)} "
          f"| indices etablis : {sum(1 for l in lignes_rapport if l['indice_etabli'] == 'oui')}")
    print(f"Rapport : {RAPPORT}" + (f" | Indices : {INDICES}" if lignes_indices else " | aucun indice ecrit"))


if __name__ == "__main__":
    main()
