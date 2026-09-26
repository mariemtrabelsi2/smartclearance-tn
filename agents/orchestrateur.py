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
from agents.base import AGENTS, COUT_FAIBLE, COUT_ELEVE, NON_DEPLOYE, MOTIF_NON_DEPLOYE
from agents import inspecteur_documentaire, analyste_prix, profileur, isolation
from agents import registre as agent_registre
from agents import redaction
from agents import apprentissage
from agents import nomenclature
from agents import libelles
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


# Politique de routage : une table de regles ecrites, pas un modele, et rien
# ne l'apprend. Dans l'ordre :
#   1. un agent non deploye ne tourne jamais ;
#   2. un agent dont la precondition manque (donnee absente) ne tourne pas :
#      il n'a pas de quoi travailler, quel que soit son cout ;
#   3. un controle a cout faible tourne toujours, aucune regle de cout ne le saute ;
#   4. un agent a cout eleve ne tourne que si sa propre condition est vraie.
POLITIQUE = {
    COUT_FAIBLE: "toujours execute",
    COUT_ELEVE: "execute seulement si la condition est vraie",
}


def decider(cle, contexte):
    """Consigne {agent, cout, execute, motif} pour un agent du registre."""
    fiche = AGENTS[cle]
    if fiche.etat == NON_DEPLOYE:
        execute, motif = False, MOTIF_NON_DEPLOYE
    elif not fiche.precondition(contexte)[0]:
        execute, motif = False, fiche.precondition(contexte)[1]
    else:
        condition, motif = fiche.condition_execution(contexte)
        execute = True if POLITIQUE[fiche.cout] == "toujours execute" else bool(condition)
    return {"agent": fiche.nom, "cout": fiche.cout, "execute": execute, "motif": motif}


# Nom de rapport de chaque agent (celui que l'agent ecrit lui-meme).
RAPPORT_DE = {"prix": "Analyste prix", "profil": "Profileur", "registre": "Registre des references"}

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
    "ddm_champ_obligatoire_absent": ["Déclaration rectifiée (champ obligatoire renseigné)"],
    "ecart_quantite": ["Contrat commercial", "Liste de colisage rectifiée"],
    "ecart_poids": ["Ticket de pesée", "Liste de colisage rectifiée"],
    "ecart_valeur": ["Preuve de paiement (avis SWIFT, relevé bancaire)", "Contrat commercial"],
    "ecart_origine": ["Certificat d'origine"],
    "erreur_arithmetique": ["Facture commerciale rectifiée"],
    "ecart_conteneur": ["Connaissement original"],
    "ecart_reference": ["Facture commerciale originale"],
    "poids_invraisemblable": ["Fiche technique du produit", "Ticket de pesée"],
    "designation_vs_sh": ["Fiche technique du produit", "Catalogue fournisseur"],
    "designation_vague": ["Fiche technique du produit", "Désignation détaillée (marque, modèle, référence)"],
    "sous_evaluation_via_reclassement": ["Fiche technique du produit", "Contrat commercial",
                                         "Preuve de paiement (avis SWIFT, relevé bancaire)"],
    "saisie_douteuse": ["Pièce originale (vérification de la saisie)"],
    "code_sh_inexistant": ["Déclaration rectifiée (code SH valide)", "Fiche technique du produit"],
    "reference_facture_dupliquee": ["Facture commerciale originale",
                                    "Déclaration précédente couverte par la même facture"],
    "ecart_origine_certificat": ["Certificat d'origine original", "Preuve d'origine du fabricant"],
    "autorite_emettrice_incoherente": ["Certificat d'origine original",
                                       "Vérification auprès de l'autorité émettrice"],
    "ecart_exportateur": ["Contrat commercial", "Justification du circuit commercial (triangulation)"],
    "anciennete_importateur": ["Extrait du registre de commerce"],
    "origine_juridiction_surveillee": ["Certificat d'origine", "Justificatif du circuit de paiement"],
    "fournisseur_inconnu": ["Contrat commercial", "Coordonnées et registre du fournisseur"],
    "changement_secteur": ["Justification de la nouvelle activité (registre de commerce, agrément)"],
    "derive_prix": ["Factures d'achats antérieurs", "Justification de l'évolution des prix"],
    "fournisseur_partage": ["Contrat commercial", "Preuve de paiement (avis SWIFT, relevé bancaire)"],
    "sous_evaluation_justifiee": ["Preuve de paiement (avis SWIFT, relevé bancaire)",
                                  "Original signé du document de remise"],
    "sous_evaluation_justificatif_incoherent": ["Preuve de paiement (avis SWIFT, relevé bancaire)",
                                                "Contrat commercial", "Factures d'achats antérieurs"],
    "sous_evaluation": ["Contrat commercial", "Preuve de paiement (avis SWIFT, relevé bancaire)",
                        "Justification de remise", "Factures d'achats antérieurs"],
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
    return "Analyse partielle : éléments non lus : " + ", ".join(libelles.non_lu(n) for n in autres) + ". "


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
                f"code {nomenclature.code_lisible(p['code_suggere'])} et non du "
                f"{nomenclature.code_lisible(p['code_declare'])} déclaré, et "
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
        phrase1 = (f"Score de doute {score}/100 ({libelles.recommandation(reco)}) : "
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
                     rediger=True, ajustements=apprentissage.AJUSTEMENTS_DEFAUT) -> dict:
    """Chaine complete : Agents 1 et 2 lisent le dossier, l'Agent 3 le profil
    de l'operateur, le registre les doublons de facture, le coordinateur
    synthetise. Sources : None = source par defaut du stockage actif.
    registre : True = registre par defaut, un chemin = ce registre (mesures),
    False/None = registre desactive (rien n'est ecrit)."""
    # Etage 1 : l'Agent 1 seul. Il lit la DDM et les PDF (l'essentiel du temps).
    # Cout faible : toujours execute (la politique ne peut pas le sauter).
    controles = [decider("documentaire", {"dossier": dossier})]
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

    # Decisions consignees AVANT l'execution de l'etage 2. Seuls une donnee
    # absente (precondition) ou l'appelant (registre desactive pour une mesure
    # sans ecriture) empechent un agent a cout faible de tourner, et c'est dit.
    contexte = {"dossier": dossier, "ddm": ddm, "facture": facture, "agent1": r1.donnees}
    sautes = {}
    for cle in ("prix", "profil", "registre", "imagerie"):
        c = decider(cle, contexte)
        if cle == "registre" and not registre:
            c.update(execute=False, motif="désactivé à l'appel (analyse sans écriture au registre)")
        elif cle in taches and not c["execute"]:
            # Precondition manquante : l'agent ne tourne pas, mais le controle
            # non fait reste visible dans les champs non lus, comme avant.
            del taches[cle]
            sautes[cle] = RapportAgent(agent=RAPPORT_DE[cle], statut="NON EXECUTE",
                                       non_lus=[f"{c['agent']} non exécuté : {c['motif']}"])
        controles.append(c)
    # L'imagerie n'a aucune tache : meme decidee, elle ne produirait rien.

    if PARALLELE:
        futurs = {nom: _executeur().submit(f) for nom, f in taches.items()}
        resultats = {nom: futur.result() for nom, futur in futurs.items()}
    else:
        resultats = {nom: f() for nom, f in taches.items()}

    # Ordre FIXE des rapports, quel que soit l'ordre d'arrivee des branches.
    resultats.update(sautes)
    rapports = [r1] + [resultats[nom] for nom in ("prix", "profil", "registre") if nom in resultats]
    # Boucle d'apprentissage : seulement la gravite des alertes de niveau 2, et
    # seulement si donnees/ajustements.json existe (absent dans la version livree).
    apprentissage.appliquer(rapports, ajustements)
    synthese = synthetiser(rapports)
    # Apres synthetiser : le journal des controles n'entre ni dans le score ni
    # dans la recommandation, ni dans l'empreinte de l'explication.
    synthese["controles"] = controles
    synthese["numero_ddm"] = r1.donnees["ddm"].get("numero_ddm")
    synthese["normalisations"] = r1.donnees.get("normalisations", [])
    # Contexte pour juger le prix de CETTE marchandise ; aucun effet sur le score.
    synthese["marchandise"] = {"designation": r1.donnees["facture"].get("designation"),
                               **r1.donnees.get("qualite", {})}
    code = r1.donnees["ddm"].get("code_sh")
    synthese["code_sh"] = {"code_sh": code, "designation_officielle": nomenclature.designation(code),
                           "designation_DDM": r1.donnees["ddm"].get("designation")}
    v = r1.donnees["ddm"].get("valeur_cif_usd")
    synthese["valeur_declaree"] = {"usd": v, "tnd": round(vers_tnd(v)) if v else None,
                                   "libelle": f"Valeur déclarée : {fmt_tnd(v)}",
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
