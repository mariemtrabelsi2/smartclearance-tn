"""Agent 2 : compare le prix au kilo declare a une reference de marche.

Un prix bas n'est pas une preuve : c'est un motif de doute qui ouvre la
procedure de la Decision 6.1 (l'importateur justifie, la douane decide).
"""
import csv
import statistics
from pathlib import Path

from agents.base import RapportAgent, NIVEAU_ECART

RACINE = Path(__file__).resolve().parent.parent
BAREME_DEFAUT = RACINE / "bareme.csv"

SEUIL_SOUS_EVALUATION = -30.0   # en %, en dessous on ouvre un doute
GRAVITE_MAX = 90                # un prix bas reste une hypothese, jamais 100
SEUIL_SIMILAIRES = -50.0        # reference agregee sur d'autres origines : plus bruitee
FACTEUR_SIMILAIRES = 0.7

PREFIXE_SIMILAIRES = ("Aucune marchandise identique en base. Référence établie sur "
                      "marchandises similaires (même position SH, origines agrégées) — "
                      "hiérarchie des articles 2 et 3 de l'Accord OMC sur l'évaluation "
                      "en douane.")

MENTION_OMC = ("Motif de doute au sens de la Decision 6.1 de l'Accord OMC sur "
               "l'evaluation en douane. L'importateur est invite a justifier.")

# Amorcage : imports tunisiens 2023, UN Comtrade, USD/kg.
AMORCE = [
    ("852872", "CN", 23.86),
    ("851712", "CN", 142.50),
    ("870321", "ES", 9.50),
    ("151090", "IT", 4.20),
    ("940360", "TR", 3.80),
    ("610910", "TR", 18.50),
]


def creer_bareme_si_absent(chemin=BAREME_DEFAUT):
    chemin = Path(chemin)
    if chemin.exists():
        return
    with open(chemin, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["code_sh", "pays_origine", "prix_kg_usd", "source"])
        for sh, pays, prix in AMORCE:
            w.writerow([sh, pays, prix, "UN Comtrade 2023, imports Tunisie"])


def lire_bareme(chemin):
    """{(code_sh, pays): [prix...]} : plusieurs lignes par couple sont permises,
    d'ou la mediane, moins sensible qu'une moyenne a une ligne aberrante."""
    bareme = {}
    with open(chemin, newline="", encoding="utf-8") as f:
        for ligne in csv.DictReader(f):
            try:
                prix = float(ligne["prix_kg_usd"])
            except (TypeError, ValueError):
                continue
            cle = (ligne["code_sh"].strip(), ligne["pays_origine"].strip().upper())
            bareme.setdefault(cle, []).append(prix)
    return bareme


def analyser(donnees_ddm: dict, bareme_csv: str = BAREME_DEFAUT) -> RapportAgent:
    r = RapportAgent(agent="Analyste prix")
    creer_bareme_si_absent(bareme_csv)
    bareme = lire_bareme(bareme_csv)

    sh = str(donnees_ddm.get("code_sh") or "").strip()
    pays = str(donnees_ddm.get("pays_origine") or "").strip().upper()
    valeur, poids = donnees_ddm.get("valeur_cif_usd"), donnees_ddm.get("poids_net_kg")

    if not valeur or not poids:
        r.non_lus.append("DDM.valeur_cif_usd ou DDM.poids_net_kg : prix au kilo incalculable")
        r.statut = "INCOMPLET"
        return r

    prix_kg = valeur / poids
    r.donnees = {"prix_kg_declare": round(prix_kg, 2), "code_sh": sh, "pays_origine": pays}

    exacte = bareme.get((sh, pays))
    similaires = {o: v for (code, o), v in bareme.items() if code == sh and o != pays}

    if not exacte and not similaires:
        # Aucune reference du tout : l'agent passe la main plutot que d'inventer.
        # Le coordinateur decidera sur les autres criteres.
        r.non_lus.append(f"reference_{sh}")
        r.donnees["reference"] = "PAS DE REFERENCE"
        r.statut = "INCOMPLET"
        return r

    if exacte:
        # Marchandises identiques (art. 2) : reference fiable, seuil normal.
        prix_ref, seuil, facteur, fiabilite = exacte, SEUIL_SOUS_EVALUATION, 1.0, "haute"
        origines = [pays]
        prefixe = ""
    else:
        # Marchandises similaires (art. 3) : meme position, autres origines.
        # La reference est plus bruitee, donc on exige un ecart plus fort
        # et on abaisse la gravite, mais on n'efface pas le signal.
        prix_ref = [p for v in similaires.values() for p in v]
        seuil, facteur, fiabilite = SEUIL_SIMILAIRES, FACTEUR_SIMILAIRES, "moyenne"
        origines = sorted(similaires)
        prefixe = PREFIXE_SIMILAIRES + " "
        r.non_lus.append(f"reference_exacte_{sh}_{pays}")

    mediane = statistics.median(prix_ref)
    ecart = 100 * (prix_kg - mediane) / mediane
    r.donnees.update({"prix_kg_reference": mediane, "ecart_pct": round(ecart, 1),
                      "fiabilite_reference": fiabilite, "origines_reference": origines,
                      "type_reference": "identiques" if exacte else "similaires",
                      "nb_observations": len(prix_ref)})

    if ecart <= seuil:
        preuve = {"prix_kg_declare": round(prix_kg, 2), "prix_kg_reference": mediane,
                  "ecart_pct": round(ecart, 1), "seuil_pct": seuil,
                  "fiabilite_reference": fiabilite,
                  "type_reference": "identiques" if exacte else "similaires",
                  "origines_agregees": origines, "nb_observations": len(prix_ref)}
        r.ajouter(
            type="sous_evaluation", niveau=NIVEAU_ECART,
            gravite=round(min(GRAVITE_MAX, abs(ecart)) * facteur),
            message=(f"{prefixe}Prix declare {prix_kg:,.2f} USD/kg contre une reference de "
                     f"{mediane:,.2f} USD/kg ({ecart:+.0f} %). {MENTION_OMC}"),
            preuve=preuve,
            source=f"DDM : valeur_cif_usd / poids_net_kg ; bareme {Path(bareme_csv).name} "
                   f"lignes {sh}/{','.join(origines)}",
        )

    if not exacte:
        # Pose apres ajouter(), qui force 'ALERTE' : l'inspecteur doit savoir
        # que la reference n'est pas celle de marchandises identiques.
        r.statut = "REFERENCE_PARTIELLE"
    return r
