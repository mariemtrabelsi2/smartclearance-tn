"""Coordinateur : rassemble les rapports des agents et produit une recommandation pour l'inspecteur.

Il ne tranche pas : il ordonne les doutes et dit quelles pieces reclamer.

Graphe de dependances reel (ce n'est pas "4 agents en parallele") :

                    [Agent 1 documentaire]
          lit la DDM et les PDF ; produit la date et la reference de
          facture, le code SH suggere, le texte du justificatif
                /                 |                    \\
               v                  v                     v
      [Agent 2 prix]      [Agent 3 profileur]    [registre des references]
      + foret d'isolation  (historique anterieur   (reference lue sur la
      (code SH suggere,     a la date de facture)   facture, sa date)
       justificatif)
               \\                  |                    /
                v                 v                   v
                          [Coordinateur]

Etage 1 : Agent 1, seul. C'est aussi l'essentiel du temps (lecture des PDF).
Etage 2 : Agent 2, Agent 3 et registre ne dependent que de l'Agent 1, pas les
          uns des autres : ils peuvent tourner en parallele (threads).
Etage 3 : le coordinateur, qui consomme tout.

Le lien Agent 1 -> Agent 2 (code SH suggere) est ce qui rend le systeme
agentique : le prix est controle sous le code de la marchandise decrite.

SMARTCLEARANCE_PARALLELE=1 execute l'etage 2 en threads (jamais en processus :
chaque processus dupliquerait l'interpreteur, sur un poste qui est deja tombe
a 653 Mo de memoire libre). Sequentiel par defaut : voir la mesure.
"""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from agents.base import RapportAgent, NIVEAU_CONTRADICTION
from agents import inspecteur_documentaire, analyste_prix, profileur, isolation
from agents import registre as agent_registre
from agents import redaction
from agents.devises import fmt_tnd, vers_tnd, MENTION_TAUX, SOURCE_TAUX

PARALLELE = os.environ.get("SMARTCLEARANCE_PARALLELE", "0").strip() == "1"
_EXECUTEUR = None


def _executeur():
    """Un seul pool, cree a la premiere analyse et reutilise : le recreer a
    chaque dossier couterait plus que ce que le parallelisme fait gagner."""
    global _EXECUTEUR
    if _EXECUTEUR is None:
        _EXECUTEUR = ThreadPoolExecutor(max_workers=3, thread_name_prefix="etage2")
    return _EXECUTEUR


# Ordre des agents pour le tri deterministe des alertes.
RANG_AGENT = {"Inspecteur documentaire": 0, "Analyste prix": 1, "Profileur": 2,
              "Registre des references": 3}

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
    "saisie_douteuse": ["piece originale (verification de la saisie)"],
    "reference_facture_dupliquee": ["facture commerciale originale",
                                    "declaration precedente couverte par la meme facture"],
    "ecart_origine_certificat": ["certificat d'origine original", "preuve d'origine du fabricant"],
    "autorite_emettrice_incoherente": ["certificat d'origine original",
                                       "verification aupres de l'autorite emettrice"],
    "ecart_exportateur": ["contrat commercial", "justification du circuit commercial (triangulation)"],
    "anciennete_importateur": ["extrait du registre de commerce"],
    "origine_juridiction_surveillee": ["certificat d'origine", "justificatif du circuit de paiement"],
    "fournisseur_inconnu": ["contrat commercial", "coordonnees et registre du fournisseur"],
    "changement_secteur": ["justification de la nouvelle activite (registre de commerce, agrement)"],
    "derive_prix": ["factures d'achats anterieurs", "justification de l'evolution des prix"],
    "fournisseur_partage": ["contrat commercial", "preuve de paiement (avis SWIFT, releve bancaire)"],
    "sous_evaluation_justifiee": ["preuve de paiement (avis SWIFT, releve bancaire)",
                                  "original signe du document de remise"],
    "sous_evaluation_justificatif_incoherent": ["preuve de paiement (avis SWIFT, releve bancaire)",
                                                "contrat commercial", "factures d'achats anterieurs"],
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


# Informations qui ne rendent pas l'analyse partielle : un certificat d'origine
# absent n'est pas une anomalie (il n'est exige que pour un regime preferentiel).
NON_LUS_INFORMATIFS = {"certificat_origine_absent"}


def _prefixe_partiel(non_lus):
    """Seuls les champs de documents non lus ouvrent l'explication : une
    reference de prix approchee est signalee a part (badge), sinon ce message
    ouvrirait presque tous les dossiers et masquerait l'essentiel."""
    autres = [n for n in non_lus if not _est_reference_prix(n) and n not in NON_LUS_INFORMATIFS]
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
    # Reperee par sa preuve et non par son type : un justificatif joint peut
    # renommer l'alerte de reclassement sans effacer la convergence.
    reclass = [a for a in alertes if "code_suggere" in a.preuve]
    if reclass and any(a.type == "designation_vs_sh" for a in alertes):
        a = reclass[0]
        p = a.preuve
        return (f"Convergence : deux agents indépendants pointent la même opération — "
                f"l'inspecteur documentaire relève que la marchandise décrite relève du "
                f"code {p['code_suggere']} et non du {p['code_declare']} déclaré, et "
                f"l'analyste prix constate que, sous ce code, le prix déclaré est à "
                f"{p['ecart_pct']:+d} % de la référence. ")
    return ""


def _agent_de(alerte, rapports):
    return next(r.agent for r in rapports if any(a is alerte for a in r.alertes))


def synthetiser(rapports: list) -> dict:
    # Tri deterministe par agent avant le tri par poids : l'ordre ne depend
    # jamais de l'ordre d'arrivee des branches paralleles. A l'interieur d'un
    # agent, l'ordre est celui de son code (sequentiel, donc deja deterministe) ;
    # un tri par niveau puis type le changerait pour des alertes a poids egal,
    # et avec lui les alertes citees dans l'explication. Les deux tris sont stables.
    alertes = sorted((a for r in rapports for a in r.alertes if a.gravite > 0),
                     key=lambda a: RANG_AGENT.get(_agent_de(a, rapports), 99))
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


def analyser_dossier(dossier, bareme_csv=None, historique_csv=None, registre=True,
                     rediger=True) -> dict:
    """Chaine complete : Agents 1 et 2 lisent le dossier, l'Agent 3 le profil
    de l'operateur, le registre les doublons de facture, le coordinateur
    synthetise. Sources : None = source par defaut du stockage actif.
    registre : True = registre par defaut, un chemin = ce registre (mesures),
    False/None = registre desactive (rien n'est ecrit)."""
    # Etage 1 : l'Agent 1 seul. Il lit la DDM et les PDF (l'essentiel du temps).
    r1 = inspecteur_documentaire.analyser(dossier)
    ddm, facture = r1.donnees["ddm"], r1.donnees["facture"]

    def branche_prix():
        # Premier lien entre agents : l'Agent 2 recoit ce que l'Agent 1 a etabli
        # (notamment un code SH suggere quand la designation contredit la DDM).
        r2 = analyste_prix.analyser(ddm, bareme_csv, r1.donnees)
        # Signal secondaire : ne cree aucune alerte, majore au plus x1.15 une
        # alerte de prix deja motivee par l'ecart a la reference.
        isolation.confirmer(r2.alertes, ddm, historique_csv)
        return r2

    # Etage 2 : trois branches independantes entre elles, toutes nourries par
    # l'Agent 1. Le profileur ne voit que l'historique anterieur a la date de
    # la facture (la DDM de test n'a pas de date propre).
    taches = {"prix": branche_prix,
              "profil": lambda: profileur.analyser(ddm, historique_csv, facture.get("date"))}
    if registre:
        source = None if registre is True else registre
        taches["registre"] = lambda: agent_registre.analyser(ddm, facture, source)

    if PARALLELE:
        futurs = {nom: _executeur().submit(f) for nom, f in taches.items()}
        resultats = {nom: futur.result() for nom, futur in futurs.items()}
    else:
        resultats = {nom: f() for nom, f in taches.items()}

    # Ordre FIXE des rapports, quel que soit l'ordre d'arrivee des branches.
    rapports = [r1] + [resultats[nom] for nom in ("prix", "profil", "registre") if nom in resultats]
    synthese = synthetiser(rapports)
    synthese["numero_ddm"] = r1.donnees["ddm"].get("numero_ddm")
    synthese["normalisations"] = r1.donnees.get("normalisations", [])
    v = r1.donnees["ddm"].get("valeur_cif_usd")
    synthese["valeur_declaree"] = {"usd": v, "tnd": round(vers_tnd(v)) if v else None,
                                   "libelle": f"Valeur declaree : {fmt_tnd(v)}",
                                   "taux": MENTION_TAUX, "source_taux": SOURCE_TAUX}

    # Redaction : APRES que score, recommandation et alertes sont figes. Le LLM
    # ne touche qu'au texte ; hors cache, aucun appel reseau (repli deterministe).
    if rediger:
        texte, source, detail = redaction.rediger_explication(synthese)
        synthese["explication_deterministe"] = synthese["explication"]
        synthese["explication"] = texte
        synthese["source_explication"] = source
        synthese["detail_explication"] = detail
    return synthese


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(analyser_dossier(sys.argv[1] if len(sys.argv) > 1 else "dossier_18"),
                     indent=2, ensure_ascii=False))
