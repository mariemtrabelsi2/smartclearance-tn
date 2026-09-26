"""Niveau 3 de la boucle d'apprentissage : les retours des inspecteurs ajustent
la gravite de certaines alertes, dans des limites strictes.

GARDE-FOUS
1. Une alerte de NIVEAU 1 n'est jamais apprise ni attenuee : une contradiction
   entre documents est un fait, aucun nombre de retours ne la rend acceptable.
2. Aucun ajustement avant SEUIL_RETOURS retours sur le meme motif ; en dessous,
   on affiche le compteur sans rien modifier.
3. Facteur borne entre FACTEUR_MIN et FACTEUR_MAX : le systeme ne peut ni
   eteindre une alerte ni la faire exploser.
4. Tout est ecrit dans donnees/ajustements.json (lisible, horodate, avec les
   compteurs qui ont produit chaque facteur) ; reinitialisable sans toucher au
   feedback.
5. Chaque ajustement actif est ecrit dans la preuve de l'alerte : l'inspecteur
   le voit, avec son motif.

Sans ajustements.json (cas livre), le comportement est strictement inchange.
"""
import json
from datetime import datetime
from pathlib import Path

from agents import stockage
from agents.base import NIVEAU_CONTRADICTION

RACINE = Path(__file__).resolve().parent.parent
AJUSTEMENTS_DEFAUT = RACINE / "donnees" / "ajustements.json"

SEUIL_RETOURS = 10
FACTEUR_MIN, FACTEUR_MAX = 0.6, 1.4
CONFIRME, JUSTIFIE = "anomalie_confirmee", "justification_acceptee"


def motif(type_alerte, preuve):
    """(type d'alerte, justificatif present ?, fiabilite de la reference)."""
    preuve = preuve or {}
    return (type_alerte, bool(preuve.get("justificatif")), preuve.get("fiabilite_reference"))


def cle(m):
    return f"{m[0]}|justificatif={'oui' if m[1] else 'non'}|fiabilite={m[2] or '-'}"


def facteur(taux_confirmation):
    """0.6 + 0.8 x taux, borne : meme un taux hors [0, 1] ne sort pas des bornes."""
    return round(min(FACTEUR_MAX, max(FACTEUR_MIN, 0.6 + 0.8 * taux_confirmation)), 2)


def calculer(retours):
    """-> contenu de ajustements.json a partir d'une liste de retours."""
    compteurs, ignores_n1 = {}, 0
    for r in retours:
        if r.get("decision_inspecteur") not in (CONFIRME, JUSTIFIE):
            continue
        if r.get("niveau") == NIVEAU_CONTRADICTION:
            ignores_n1 += 1              # garde-fou 1 : jamais appris
            continue
        m = motif(r.get("type_alerte"), r.get("preuve"))
        c = compteurs.setdefault(cle(m), {"type_alerte": m[0], "presence_justificatif": m[1],
                                          "fiabilite_reference": m[2],
                                          "nb_confirmes": 0, "nb_justifies": 0})
        c["nb_confirmes" if r["decision_inspecteur"] == CONFIRME else "nb_justifies"] += 1

    motifs = {}
    for k, c in sorted(compteurs.items()):
        n = c["nb_confirmes"] + c["nb_justifies"]
        taux = c["nb_confirmes"] / n
        actif = n >= SEUIL_RETOURS          # garde-fou 2
        motifs[k] = {**c, "nb_retours": n, "taux_confirmation": round(taux, 3),
                     "facteur": facteur(taux) if actif else None,
                     "retours_utilises": n if actif else 0,
                     "statut": "actif" if actif else f"en attente ({n}/{SEUIL_RETOURS} retours)"}
    return {"calcule_le": datetime.now().isoformat(timespec="seconds"),
            "regle": f"facteur = 0.6 + 0.8 x taux de confirmation, borne [{FACTEUR_MIN}, "
                     f"{FACTEUR_MAX}], seulement a partir de {SEUIL_RETOURS} retours, "
                     "jamais sur une alerte de niveau 1",
            "nb_retours_lus": len(retours), "retours_niveau1_ignores": ignores_n1,
            "motifs": motifs}


def recalculer(source_feedback=None, cible=AJUSTEMENTS_DEFAUT):
    donnees = calculer(stockage.lire_feedback(source_feedback))
    donnees["source_feedback"] = str(source_feedback or "feedback du stockage actif")
    cible = Path(cible)
    cible.parent.mkdir(parents=True, exist_ok=True)
    cible.write_text(json.dumps(donnees, indent=2, ensure_ascii=False), encoding="utf-8")
    return donnees


def charger(chemin=AJUSTEMENTS_DEFAUT):
    """Absent, vide ou illisible : aucun ajustement (comportement inchange)."""
    try:
        return json.loads(Path(chemin).read_text(encoding="utf-8")).get("motifs") or {}
    except (FileNotFoundError, json.JSONDecodeError, AttributeError):
        return {}


def appliquer(rapports, chemin=AJUSTEMENTS_DEFAUT):
    """Ajuste la gravite des alertes de NIVEAU 2 dont le motif a un facteur actif,
    et l'ecrit dans la preuve. Les alertes de niveau 1 ne sont jamais lues ici."""
    motifs = charger(chemin)
    if not motifs:
        return
    date_calcul = json.loads(Path(chemin).read_text(encoding="utf-8")).get("calcule_le")
    for r in rapports:
        for a in r.alertes:
            if a.niveau == NIVEAU_CONTRADICTION:
                continue                     # garde-fou 1
            m = motifs.get(cle(motif(a.type, a.preuve)))
            if not m:
                continue
            if m["facteur"] is None:
                # Garde-fou 2 : on montre le compteur, on ne touche a rien.
                a.preuve["retours_inspecteurs"] = f"{m['nb_retours']} retour(s), aucun ajustement avant {SEUIL_RETOURS}"
                continue
            a.preuve.update({
                "ajustement_apprentissage": m["facteur"],
                "gravite_avant_ajustement": a.gravite,
                "fonde_sur": f"{m['nb_retours']} retours, {m['nb_confirmes']} confirmations",
                "calcule_le": date_calcul,
            })
            a.gravite = min(100, round(a.gravite * m["facteur"]))
