"""Foret d'isolation : signal SECONDAIRE de confirmation, jamais une alerte.

Elle sait dire qu'une operation est atypique, pas pourquoi. Or une alerte
doit etre motivee au sens de la Decision 6.1 : c'est l'ecart a la reference
qui porte l'alerte, la foret ne fait que majorer (x1.15 au plus) la gravite
d'une alerte de prix deja emise quand elle la confirme.
"""
import math
from functools import lru_cache
from pathlib import Path

from agents.profileur import HISTORIQUE_DEFAUT, lire_historique

# Score d'anomalie de Liu et al. (2008), entre 0 et 1 : proche de 1 = isole,
# nettement sous 0,5 = normal. Seuil fixe a priori, pas ajuste sur les tests.
SEUIL_CONFIRMATION = 0.6
FACTEUR_MAX = 1.15
MIN_OBSERVATIONS = 20          # en dessous, une foret par code SH n'apprend rien
# Variables de la foret. Mesure sur les 3 graines : avec valeur et poids, la
# foret reagit a la TAILLE du lot (l'historique va de 200 a 20 000 kg, les
# dossiers de 10 kg a 1 650 t) et ne separe pas les sous-evaluations (0,60-0,74)
# des dossiers propres (0,67-0,73). Avec ("prix_kg",) seul, separation nette :
# 0,60-0,71 contre 0,45-0,56.
VARIABLES = ("prix_kg", "valeur", "poids")
GRAVITE_MAX = 90
TYPES_PRIX = {"sous_evaluation", "sous_evaluation_via_reclassement",
              "sous_evaluation_justifiee", "sous_evaluation_justificatif_incoherent"}


def _variables(prix_kg, valeur, poids):
    brut = {"prix_kg": prix_kg, "valeur": valeur, "poids": poids}
    return [math.log(brut[v]) for v in VARIABLES]


@lru_cache(maxsize=4)
def _forets(historique_csv):
    """Une foret par code SH : les prix au kilo vont de 1 a 180 USD selon le
    produit, une foret globale trouverait normal un smartphone brade."""
    from sklearn.ensemble import IsolationForest
    par_sh = {}
    for l in lire_historique(historique_csv):
        v, p = float(l["valeur"]), float(l["poids"])
        if v > 0 and p > 0:
            par_sh.setdefault(l["code_sh"], []).append(_variables(l["prix_kg"], v, p))
    return {sh: IsolationForest(n_estimators=200, random_state=0).fit(X)
            for sh, X in par_sh.items() if len(X) >= MIN_OBSERVATIONS}


def score_isolation(ddm, historique_csv=HISTORIQUE_DEFAUT):
    """None si pas de foret pour ce code SH ou donnees manquantes : pas d'avis."""
    if not Path(historique_csv).exists():
        return None
    try:
        foret = _forets(str(historique_csv)).get(str(ddm.get("code_sh")))
    except ImportError:
        return None
    v, p = ddm.get("valeur_cif_usd"), ddm.get("poids_net_kg")
    if foret is None or not v or not p:
        return None
    # score_samples renvoie l'oppose du score de Liu et al.
    return round(float(-foret.score_samples([_variables(v / p, v, p)])[0]), 3)


def confirmer(alertes, ddm, historique_csv=HISTORIQUE_DEFAUT):
    """Majore les alertes de prix que la foret confirme. Ne cree jamais d'alerte."""
    prix = [a for a in alertes if a.type in TYPES_PRIX]
    if not prix:
        return None
    s = score_isolation(ddm, historique_csv)
    if s is None:
        return None
    for a in prix:
        a.preuve.update({"score_isolation": s, "role": "signal secondaire de confirmation"})
        if s >= SEUIL_CONFIRMATION:
            a.gravite = min(GRAVITE_MAX, round(a.gravite * FACTEUR_MAX))
    return s
