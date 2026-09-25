"""Agent 2 : compare le prix au kilo declare a une reference de marche.

Un prix bas n'est pas une preuve : c'est un motif de doute qui ouvre la
procedure de la Decision 6.1 (l'importateur justifie, la douane decide).
"""
import csv
import re
import statistics
from pathlib import Path

from agents.base import RapportAgent, NIVEAU_ECART

RACINE = Path(__file__).resolve().parent.parent
BAREME_DEFAUT = RACINE / "bareme.csv"

SEUIL_SOUS_EVALUATION = -30.0   # en %, en dessous on ouvre un doute
GRAVITE_MAX = 90                # un prix bas reste une hypothese, jamais 100
SEUIL_SIMILAIRES = -50.0        # reference agregee sur d'autres origines : plus bruitee
FACTEUR_SIMILAIRES = 0.7
FACTEUR_JUSTIFIE = 0.4          # remise documentee qui couvre l'ecart
FACTEUR_INCOHERENT = 1.2        # remise documentee qui NE couvre PAS l'ecart : pretexte possible
TERMES_REMISE = [r"discount", r"promotion(?:al)?", r"credit note", r"clearance", r"rabais",
                 r"soldes?", r"end of series", r"remise"]
BONUS_RECLASSEMENT = 20         # faux classement + prix bas : deux signaux convergents

PREFIXE_SIMILAIRES = ("Aucune marchandise identique en base. Référence établie sur "
                      "marchandises similaires (même position SH, origines agrégées) — "
                      "hiérarchie des articles 2 et 3 de l'Accord OMC sur l'évaluation "
                      "en douane.")

MENTION_OMC = ("Motif de doute au sens de la Decision 6.1 de l'Accord OMC sur "
               "l'evaluation en douane. L'importateur est invite a justifier.")

# Amorcage : imports tunisiens 2023, UN Comtrade, USD/kg.
AMORCE = [
    ("852872", "CN", 23.86),
    ("851713", "CN", 142.50),
    ("870322", "ES", 9.50),
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


def _chercher_reference(bareme, sh, pays):
    """Hierarchie OMC : marchandises identiques (meme SH, meme origine), sinon
    similaires (meme SH, autres origines), sinon rien. None = pas de reference."""
    exacte = bareme.get((sh, pays))
    if exacte:
        # Marchandises identiques (art. 2) : reference fiable, seuil normal.
        return {"prix_ref": exacte, "seuil": SEUIL_SOUS_EVALUATION, "facteur": 1.0,
                "fiabilite": "haute", "type": "identiques", "origines": [pays], "prefixe": ""}
    similaires = {o: v for (code, o), v in bareme.items() if code == sh and o != pays}
    if similaires:
        # Marchandises similaires (art. 3) : meme position, autres origines.
        # La reference est plus bruitee, donc on exige un ecart plus fort
        # et on abaisse la gravite, mais on n'efface pas le signal.
        return {"prix_ref": [p for v in similaires.values() for p in v],
                "seuil": SEUIL_SIMILAIRES, "facteur": FACTEUR_SIMILAIRES,
                "fiabilite": "moyenne", "type": "similaires", "origines": sorted(similaires),
                "prefixe": PREFIXE_SIMILAIRES + " "}
    return None


def _rapprocher_justificatif(r, texte, prix_kg):
    """Rapproche la remise annoncee de l'ecart constate. L'alerte n'est jamais
    effacee : on dit seulement si la remise suffit a expliquer le prix.
    Critere : le prix AVANT remise doit revenir dans la bande normale (au-dessus
    du seuil de la reference utilisee). Sinon la remise est un pretexte possible."""
    bas = texte.lower()
    if not any(re.search(rf"\b{t}\b", bas) for t in TERMES_REMISE):
        r.non_lus.append("justificatif.pdf : aucun terme de remise reconnu")
        return
    lignes = [" ".join(l.split()) for l in texte.splitlines() if l.strip()]
    type_doc = lignes[0] if lignes else "document joint"
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", texte)
    remise = float(m.group(1)) if m and 0 < float(m.group(1)) < 100 else None

    for a in r.alertes:
        if a.type not in ("sous_evaluation", "sous_evaluation_via_reclassement"):
            continue
        ref = a.preuve.get("prix_kg_reference") or a.preuve.get("reference_code_suggere")
        ecart, seuil = a.preuve["ecart_pct"], a.preuve["seuil_pct"]
        a.preuve.update({"justificatif": type_doc,
                         "remise_annoncee": f"{remise:g}%" if remise is not None else None,
                         "ecart_constate": f"{ecart}%"})
        entete = (f"Ecart de prix de {ecart:.0f} %. Un document justificatif est joint "
                  f"({type_doc}). L'inspecteur doit verifier la concordance entre la remise "
                  f"annoncee et le reglement effectif.")
        if remise is None:
            # Remise non chiffree : impossible de verifier qu'elle couvre l'ecart,
            # donc aucune attenuation.
            a.preuve["coherent"] = None
            a.type = "sous_evaluation_justifiee"
            a.message = f"{entete} La remise n'est pas chiffree : concordance invérifiable. {MENTION_OMC}"
            continue
        avant_remise = prix_kg / (1 - remise / 100)
        residuel = 100 * (avant_remise - ref) / ref
        coherent = residuel > seuil
        a.preuve.update({"coherent": coherent, "ecart_apres_remise_pct": round(residuel, 1)})
        if coherent:
            a.type = "sous_evaluation_justifiee"
            a.gravite = round(a.gravite * FACTEUR_JUSTIFIE)
            a.message = f"{entete} {MENTION_OMC}"
        else:
            a.type = "sous_evaluation_justificatif_incoherent"
            a.gravite = min(GRAVITE_MAX, round(a.gravite * FACTEUR_INCOHERENT))
            a.message = (f"La remise annoncee ({remise:g}%) n'explique pas l'ecart constate "
                         f"({ecart:.0f}%) : meme avant remise, le prix resterait a "
                         f"{residuel:+.0f} % de la reference. {entete} {MENTION_OMC}")


def analyser(donnees_ddm: dict, bareme_csv: str = BAREME_DEFAUT,
             donnees_agent1: dict = None) -> RapportAgent:
    """donnees_agent1 : ce que l'inspecteur documentaire a etabli. S'il a vu que
    la designation ne colle pas au code declare, on verifie aussi le prix avec
    le code de la marchandise reellement decrite."""
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

    # ---------- 1. Code declare ----------
    ref = _chercher_reference(bareme, sh, pays)
    if ref is None:
        # Aucune reference : l'agent ne conclut rien sur le code declare,
        # mais on ne sort plus tout de suite, le code suggere peut encore parler.
        r.non_lus.append(f"reference_{sh}")
        r.donnees["reference"] = "PAS DE REFERENCE"
        statut_declare = "INCOMPLET"
    else:
        if ref["type"] == "similaires":
            r.non_lus.append(f"reference_exacte_{sh}_{pays}")
        mediane = statistics.median(ref["prix_ref"])
        ecart = 100 * (prix_kg - mediane) / mediane
        r.donnees.update({"prix_kg_reference": mediane, "ecart_pct": round(ecart, 1),
                          "fiabilite_reference": ref["fiabilite"],
                          "origines_reference": ref["origines"],
                          "type_reference": ref["type"],
                          "nb_observations": len(ref["prix_ref"])})
        if ecart <= ref["seuil"]:
            r.ajouter(
                type="sous_evaluation", niveau=NIVEAU_ECART,
                gravite=round(min(GRAVITE_MAX, abs(ecart)) * ref["facteur"]),
                message=(f"{ref['prefixe']}Prix declare {prix_kg:,.2f} USD/kg contre une reference de "
                         f"{mediane:,.2f} USD/kg ({ecart:+.0f} %). {MENTION_OMC}"),
                preuve={"prix_kg_declare": round(prix_kg, 2), "prix_kg_reference": mediane,
                        "ecart_pct": round(ecart, 1), "seuil_pct": ref["seuil"],
                        "fiabilite_reference": ref["fiabilite"], "type_reference": ref["type"],
                        "origines_agregees": ref["origines"],
                        "nb_observations": len(ref["prix_ref"])},
                source=f"DDM : valeur_cif_usd / poids_net_kg ; bareme {Path(bareme_csv).name} "
                       f"lignes {sh}/{','.join(ref['origines'])}",
            )
        statut_declare = "REFERENCE_PARTIELLE" if ref["type"] == "similaires" else None

    # ---------- 2. Code suggere par l'Agent 1 ----------
    # Un faux classement peut servir a echapper au controle de prix : sous le
    # code declare, la marchandise n'a pas de reference ou une reference basse.
    suggere = str((donnees_agent1 or {}).get("code_sh_suggere") or "").strip()
    alerte_reclassement = False
    if suggere and suggere != sh:
        ref2 = _chercher_reference(bareme, suggere, pays)
        r.donnees["code_sh_suggere"] = suggere
        if ref2 is None:
            r.non_lus.append(f"reference_{suggere}")
        else:
            med2 = statistics.median(ref2["prix_ref"])
            ecart2 = 100 * (prix_kg - med2) / med2
            r.donnees.update({"reference_code_suggere": med2, "ecart_pct_code_suggere": round(ecart2, 1)})
            if ecart2 <= ref2["seuil"]:
                alerte_reclassement = True
                r.ajouter(
                    type="sous_evaluation_via_reclassement", niveau=NIVEAU_ECART,
                    # Deux anomalies independantes qui se renforcent : on part de
                    # l'ecart et on le majore, sans depasser le plafond d'une hypothese.
                    gravite=min(GRAVITE_MAX, round(abs(ecart2)) + BONUS_RECLASSEMENT),
                    message=("Le code declare ne correspond pas a la designation. Verifie avec "
                             "le code correspondant a la marchandise reellement decrite, le prix "
                             f"presente un ecart de {ecart2:.0f} %. Le classement errone peut "
                             f"masquer une sous-evaluation. {MENTION_OMC}"),
                    preuve={"code_declare": sh, "code_suggere": suggere,
                            "prix_declare": round(prix_kg, 2), "reference_code_suggere": med2,
                            "ecart_pct": round(ecart2),
                            "seuil_pct": ref2["seuil"], "fiabilite_reference": ref2["fiabilite"],
                            "type_reference": ref2["type"], "origines_agregees": ref2["origines"],
                            "nb_observations": len(ref2["prix_ref"])},
                    source=(f"inspecteur documentaire : designation facture -> SH {suggere} ; "
                            f"bareme {Path(bareme_csv).name} lignes {suggere}/{','.join(ref2['origines'])}"),
                )

    # ---------- 3. Justificatif de remise joint au dossier ----------
    texte = (donnees_agent1 or {}).get("justificatif")
    if texte:
        _rapprocher_justificatif(r, texte, prix_kg)

    # Pose apres ajouter(), qui force 'ALERTE' : l'inspecteur doit savoir que la
    # reference du code declare est absente ou approchee. Une alerte de
    # reclassement l'emporte sur 'INCOMPLET' : l'agent a bien trouve quelque chose.
    if statut_declare == "INCOMPLET" and not alerte_reclassement:
        r.statut = "INCOMPLET"
    elif statut_declare == "REFERENCE_PARTIELLE":
        r.statut = "REFERENCE_PARTIELLE"
    return r
