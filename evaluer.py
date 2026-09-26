"""Mesure la chaine complete sur les 20 dossiers contre la verite terrain.

Le chiffre qui compte le plus : les alertes sur les dossiers propres.
Un outil qui crie sur tout finit ignore par les inspecteurs.
"""
import os

# Avant tout import de numpy (via pandas ou scikit-learn) : sinon OpenBLAS a deja
# reserve de la memoire par coeur, et sur un poste charge l'allocation echoue.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import json
import sys
from collections import defaultdict
from pathlib import Path

from agents import stockage
from agents.orchestrateur import analyser_dossier
from agents.profileur import TYPES as TYPES_PROFIL

RACINE = Path(__file__).resolve().parent

# La verite terrain ne connait qu'un type de sous-evaluation ; l'alerte via
# reclassement en est une forme (meme anomalie, detectee par un autre chemin).
EQUIVALENCES = {"sous_evaluation_via_reclassement": "sous_evaluation",
                "sous_evaluation_justifiee": "sous_evaluation",
                "sous_evaluation_justificatif_incoherent": "sous_evaluation"}


def evaluer(dossiers_dir=RACINE / "dossiers", registre=None):
    """registre : registre des references de facture. Par defaut, un registre
    temporaire VIDE a chaque mesure : sinon il garde les references d'une
    execution precedente (une autre graine, par exemple) et la mesure alerte
    sur tous les dossiers. Le registre reel de l'interface n'est pas touche."""
    verite = json.loads((Path(dossiers_dir) / "verite_terrain.json").read_text(encoding="utf-8"))
    par_type = defaultdict(lambda: {"posees": 0, "trouvees": 0, "emises": 0, "justes": 0})
    detail, propres = [], []
    posees = trouvees = emises = justes = 0
    if registre is None:
        registre = stockage.registre_temporaire()

    # Ordre des dossiers = ordre d'arrivee : c'est le SECOND dossier d'une
    # reference partagee qui doit alerter, comme le pose la verite terrain.
    for d in verite["dossiers"]:
        s = analyser_dossier(Path(dossiers_dir) / d["dossier"], registre=registre)
        attendus = [a["type"] for a in d["anomalies"]]
        # Les alertes a gravite 0 sont informatives : elles ne comptent pas comme emises.
        # Rappel et precision portent sur le dossier : la verite terrain ne
        # connait pas les profils, qu'on compte a part.
        obtenus = [EQUIVALENCES.get(a["type"], a["type"])
                   for a in s["alertes"] if a["gravite"] > 0 and a["type"] not in TYPES_PROFIL]
        profil = [a["type"] for a in s["alertes"] if a["type"] in TYPES_PROFIL]

        restants = list(attendus)
        for t in obtenus:
            par_type[t]["emises"] += 1
            emises += 1
            if t in restants:          # chaque anomalie posee ne peut etre validee qu'une fois
                restants.remove(t)
                par_type[t]["justes"] += 1
                justes += 1
        for t in attendus:
            par_type[t]["posees"] += 1
            posees += 1
        for t in set(attendus):
            n = min(attendus.count(t), obtenus.count(t))
            par_type[t]["trouvees"] += n
            trouvees += n

        ligne = {"dossier": d["dossier"], "propre": d["propre"], "attendues": attendus,
                 "obtenues": obtenus, "manquees": restants,
                 "en_trop": [t for t in obtenus if t not in attendus],
                 "alertes_profil": profil, "score": s["score"], "recommandation": s["recommandation"],
                 "analyse_partielle": bool(s["champs_non_lus"])}
        detail.append(ligne)
        if d["propre"]:
            propres.append(ligne)

    fp_propres = sum(len(p["obtenues"]) for p in propres)
    profil_tous = [t for l in detail for t in l["alertes_profil"]]
    return {
        "nb_dossiers": len(detail),
        "anomalies_posees": posees,
        "anomalies_trouvees": trouvees,
        "rappel": round(trouvees / posees, 3) if posees else None,
        "alertes_emises": emises,
        "alertes_justes": justes,
        "precision": round(justes / emises, 3) if emises else None,
        "propres": {
            "nb": len(propres),
            "alertes_emises": fp_propres,
            "dossiers_avec_alerte": [p["dossier"] for p in propres if p["obtenues"]],
            "non_liberes": [p["dossier"] for p in propres if p["recommandation"] != "LIBERATION"],
            "alertes_profil": sum(len(p["alertes_profil"]) for p in propres),
        },
        "profil": {"alertes_emises": len(profil_tous),
                   "par_type": {t: profil_tous.count(t) for t in sorted(set(profil_tous))},
                   "dossiers_physique_par_profil_seul": [
                       l["dossier"] for l in detail
                       if l["recommandation"] == "CONTROLE_PHYSIQUE" and not l["obtenues"]]},
        "par_type": dict(sorted(par_type.items())),
        "detail": detail,
    }


def afficher(r):
    print(f"Dossiers analyses : {r['nb_dossiers']}")
    print(f"RAPPEL    : {r['anomalies_trouvees']}/{r['anomalies_posees']} = {r['rappel']:.1%}")
    print(f"PRECISION : {r['alertes_justes']}/{r['alertes_emises']} = {r['precision']:.1%}")
    p = r["propres"]
    print(f"FAUX POSITIFS sur les {p['nb']} dossiers propres : {p['alertes_emises']} alerte(s) "
          f"{p['dossiers_avec_alerte'] or ''} ; non liberes : {p['non_liberes'] or 'aucun'}")
    pr = r["profil"]
    print(f"PROFIL (compte a part) : {pr['alertes_emises']} alerte(s) {pr['par_type']} ; "
          f"sur les propres : {p['alertes_profil']} ; "
          f"controle physique du au profil seul : {pr['dossiers_physique_par_profil_seul'] or 'aucun'}")
    print()
    print(f"{'type':24} {'posees':>6} {'trouvees':>8} {'emises':>6} {'justes':>6}")
    for t, v in r["par_type"].items():
        print(f"{t:24} {v['posees']:>6} {v['trouvees']:>8} {v['emises']:>6} {v['justes']:>6}")
    print()
    for l in r["detail"]:
        marque = "OK " if not l["manquees"] and not l["en_trop"] else "!! "
        extra = ""
        if l["manquees"]:
            extra += f" manquees={l['manquees']}"
        if l["en_trop"]:
            extra += f" en_trop={l['en_trop']}"
        if l["alertes_profil"]:
            extra += f" profil={l['alertes_profil']}"
        print(f"{marque}{l['dossier']} {'propre' if l['propre'] else '      '} "
              f"score={l['score']:>3} {l['recommandation']:21}{extra}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    # Usage : py evaluer.py [dossier_des_cas] [fichier_resultats]
    # Permet de mesurer un jeu independant sans ecraser les resultats principaux.
    entree = Path(sys.argv[1]) if len(sys.argv) > 1 else RACINE / "dossiers"
    sortie = Path(sys.argv[2]) if len(sys.argv) > 2 else RACINE / "resultats.json"
    res = evaluer(entree)
    afficher(res)
    sortie.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n{sortie.name} ecrit.")
