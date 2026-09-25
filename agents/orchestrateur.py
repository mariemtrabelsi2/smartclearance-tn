"""Coordinateur : rassemble les rapports des agents et produit une recommandation pour l'inspecteur.

Il ne tranche pas : il ordonne les doutes et dit quelles pieces reclamer.
"""
import json
from pathlib import Path

from agents.base import RapportAgent, NIVEAU_CONTRADICTION
from agents import inspecteur_documentaire, analyste_prix, profileur

# Une contradiction entre documents est un fait ; un ecart de prix ou de
# poids est une hypothese. D'ou le poids double du niveau 1.
POIDS_NIVEAU = {1: 1.0, 2: 0.5}

SEUIL_DOCUMENTAIRE = 30
SEUIL_PHYSIQUE = 65

# Un profil n'est pas une preuve : la part du profileur dans le score est
# plafonnee, et elle ne peut jamais faire franchir seule le seuil physique.
PLAFOND_PROFIL = 40

PIECES = {
    "ecart_quantite": ["contrat commercial", "liste de colisage rectifiee"],
    "ecart_poids": ["ticket de pesee", "liste de colisage rectifiee"],
    "ecart_valeur": ["preuve de paiement (avis SWIFT, releve bancaire)", "contrat commercial"],
    "ecart_origine": ["certificat d'origine"],
    "erreur_arithmetique": ["facture commerciale rectifiee"],
    "ecart_conteneur": ["connaissement original"],
    "ecart_reference": ["facture commerciale originale"],
    "poids_invraisemblable": ["fiche technique du produit", "ticket de pesee"],
    "designation_vs_sh": ["fiche technique du produit", "catalogue fournisseur"],
    "designation_vague": ["fiche technique du produit", "designation detaillee (marque, modele, reference)"],
    "sous_evaluation_via_reclassement": ["fiche technique du produit", "contrat commercial",
                                         "preuve de paiement (avis SWIFT, releve bancaire)"],
    "anciennete_importateur": ["extrait du registre de commerce"],
    "fournisseur_inconnu": ["contrat commercial", "coordonnees et registre du fournisseur"],
    "changement_secteur": ["justification de la nouvelle activite (registre de commerce, agrement)"],
    "derive_prix": ["factures d'achats anterieurs", "justification de l'evolution des prix"],
    "fournisseur_partage": ["contrat commercial", "preuve de paiement (avis SWIFT, releve bancaire)"],
    "sous_evaluation": ["contrat commercial", "preuve de paiement (avis SWIFT, releve bancaire)",
                        "justification de remise", "factures d'achats anterieurs"],
}


def _poids(a):
    return a.gravite * POIDS_NIVEAU.get(a.niveau, 0.5)


def _ou_bruite(alertes):
    """Chaque alerte ajoute du doute sans que la somme depasse 100, et deux
    alertes moyennes pesent plus qu'une seule."""
    reste = 1.0
    for a in alertes:
        reste *= 1 - min(_poids(a), 100) / 100
    return 100 * (1 - reste)


def score_global(alertes):
    dossier = [a for a in alertes if a.type not in profileur.TYPES]
    profil = [a for a in alertes if a.type in profileur.TYPES]

    s_dossier = _ou_bruite(dossier)
    # Plancher : un doute emis sur le dossier appelle au minimum une demande de
    # justification. Liberer en affichant un motif de doute serait incoherent.
    # Il ne s'applique pas au profil seul : un profil oriente, il n'accuse pas.
    if dossier:
        s_dossier = max(s_dossier, SEUIL_DOCUMENTAIRE)

    s_profil = min(PLAFOND_PROFIL, _ou_bruite(profil))
    total = 100 * (1 - (1 - s_dossier / 100) * (1 - s_profil / 100))
    if s_dossier <= SEUIL_PHYSIQUE:
        total = min(total, SEUIL_PHYSIQUE)
    return round(max(s_dossier, total))


def recommandation(score):
    if score < SEUIL_DOCUMENTAIRE:
        return "LIBERATION"
    if score <= SEUIL_PHYSIQUE:
        return "CONTROLE_DOCUMENTAIRE"
    return "CONTROLE_PHYSIQUE"


def _est_reference_prix(n):
    return n.startswith("reference_")


def _prefixe_partiel(non_lus):
    """Seuls les champs de documents non lus ouvrent l'explication : une
    reference de prix approchee est signalee a part (badge), sinon ce message
    ouvrirait presque tous les dossiers et masquerait l'essentiel."""
    autres = [n for n in non_lus if not _est_reference_prix(n)]
    if not autres:
        return ""
    return "Analyse partielle : éléments non lus : " + ", ".join(autres) + ". "


def reference_prix(rapports):
    """Resume la qualite de la reference de prix pour le badge de l'interface."""
    for r in rapports:
        if r.agent != "Analyste prix":
            continue
        d = r.donnees
        if d.get("reference") == "PAS DE REFERENCE" or "type_reference" not in d:
            return {"type": "aucune", "fiabilite": "nulle", "nb_observations": 0,
                    "libelle": "Référence de prix : aucune — prix non contrôlé"}
        return {"type": d["type_reference"], "fiabilite": d["fiabilite_reference"],
                "nb_observations": d["nb_observations"],
                "libelle": (f"Référence de prix : {d['type_reference']} "
                            f"({d['nb_observations']} obs.) — fiabilité {d['fiabilite_reference']}")}
    return None


def _convergence(alertes):
    """Deux agents qui ne se consultent pas sur le fond (l'un lit les documents,
    l'autre les prix) aboutissent a la meme operation : c'est plus fort
    que deux alertes isolees, et l'inspecteur doit le voir d'emblee."""
    types = {a.type for a in alertes}
    if {"designation_vs_sh", "sous_evaluation_via_reclassement"} <= types:
        a = next(a for a in alertes if a.type == "sous_evaluation_via_reclassement")
        p = a.preuve
        return (f"Convergence : deux agents indépendants pointent la même opération — "
                f"l'inspecteur documentaire relève que la marchandise décrite relève du "
                f"code {p['code_suggere']} et non du {p['code_declare']} déclaré, et "
                f"l'analyste prix constate que, sous ce code, le prix déclaré est à "
                f"{p['ecart_pct']:+d} % de la référence. ")
    return ""


def synthetiser(rapports: list) -> dict:
    alertes = [a for r in rapports for a in r.alertes if a.gravite > 0]
    alertes.sort(key=_poids, reverse=True)
    non_lus = list(dict.fromkeys(n for r in rapports for n in r.non_lus))

    score = score_global(alertes)
    reco = recommandation(score)

    if alertes:
        n1 = sum(1 for a in alertes if a.niveau == NIVEAU_CONTRADICTION)
        phrase1 = (f"Score de doute {score}/100 ({reco.replace('_', ' ').lower()}) : "
                   f"{len(alertes)} alerte(s) dont {n1} contradiction(s) entre documents.")
        # On cite le message avant la mention OMC : les chiffres suffisent ici.
        cites = [a.message.split(" Motif de doute")[0] for a in alertes[:2]]
        phrase2 = "Points principaux : " + " ".join(cites)
        phrase3 = "La décision reste à l'inspecteur."
        explication = f"{phrase1} {_convergence(alertes)}{phrase2} {phrase3}"
    else:
        explication = (f"Score de doute {score}/100 : aucune incohérence relevée entre la "
                       "déclaration et les pièces jointes. La décision reste à l'inspecteur.")
    explication = _prefixe_partiel(non_lus) + explication

    documents = list(dict.fromkeys(p for a in alertes for p in PIECES.get(a.type, [])))

    return {
        "score": score,
        "recommandation": reco,
        "explication": explication,
        "alertes": [a.to_dict() for a in alertes],
        "documents_a_reclamer": documents,
        "champs_non_lus": non_lus,
        "reference_prix": reference_prix(rapports),
        "rapports": [{k: v for k, v in r.to_dict().items() if k != "donnees"} for r in rapports],
    }


def analyser_dossier(dossier, bareme_csv=analyste_prix.BAREME_DEFAUT,
                     historique_csv=profileur.HISTORIQUE_DEFAUT) -> dict:
    """Chaine complete : Agents 1 et 2 lisent le dossier, l'Agent 3 le profil
    de l'operateur, le coordinateur synthetise."""
    r1 = inspecteur_documentaire.analyser(dossier)
    # Premier lien entre agents : l'Agent 2 recoit ce que l'Agent 1 a etabli
    # (notamment un code SH suggere quand la designation contredit la DDM).
    r2 = analyste_prix.analyser(r1.donnees["ddm"], bareme_csv, r1.donnees)
    # Le profileur ne voit que l'historique anterieur a la date de la facture
    # (la DDM de test n'a pas de date propre).
    r3 = profileur.analyser(r1.donnees["ddm"], historique_csv, r1.donnees["facture"].get("date"))
    synthese = synthetiser([r1, r2, r3])
    synthese["numero_ddm"] = r1.donnees["ddm"].get("numero_ddm")
    return synthese


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(analyser_dossier(sys.argv[1] if len(sys.argv) > 1 else "dossier_18"),
                     indent=2, ensure_ascii=False))
