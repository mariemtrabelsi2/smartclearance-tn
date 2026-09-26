"""Registre des references de facture deja vues : une meme facture ne doit
couvrir qu'une seule declaration.

Le fichier s'accumule d'une analyse a l'autre : c'est voulu en exploitation,
mais une mesure doit partir d'un registre vide (voir evaluer.py), sinon la
deuxieme execution alerterait sur tous les dossiers.
"""
from agents import stockage
from agents.base import RapportAgent, NIVEAU_CONTRADICTION

_cle = stockage.cle_reference


def analyser(ddm: dict, facture: dict, registre=None) -> RapportAgent:
    """registre : source du registre (None = registre par defaut du backend)."""
    r = RapportAgent(agent="Registre des references")
    # La reference lue sur la facture fait foi ; a defaut, celle declaree en DDM.
    ref = (facture or {}).get("reference") or ddm.get("reference_facture")
    numero = ddm.get("numero_ddm")
    if not ref or not numero:
        r.non_lus.append("Référence de facture ou numéro de DDM absent : doublon non vérifié")
        r.statut = "INCOMPLET"
        return r

    memes = stockage.chercher_reference(ref, registre) or []
    autres = sorted((l for l in memes if _cle(l["numero_ddm"]) != _cle(numero)),
                    key=lambda l: l["date_analyse"])
    if autres:
        p = autres[0]
        r.ajouter(
            type="reference_facture_dupliquee", niveau=NIVEAU_CONTRADICTION, gravite=85,
            message="Cette référence de facture couvre déjà une autre déclaration.",
            preuve={"reference": ref, "ddm_actuelle": numero, "ddm_precedente": p["numero_ddm"],
                    "date_precedente": p["date"], "importateur_precedent": p["importateur"],
                    "nb_declarations_avec_cette_reference": len({_cle(l["numero_ddm"]) for l in memes}) + 1},
            source=f"registre {stockage.nom_source('references')} / facture : ligne 'Ref'",
        )

    # Meme reference + meme DDM : simple reanalyse, le stockage n'ajoute rien.
    stockage.enregistrer_reference(ref, numero, ddm.get("importateur"),
                                   (facture or {}).get("date"), registre)
    return r
