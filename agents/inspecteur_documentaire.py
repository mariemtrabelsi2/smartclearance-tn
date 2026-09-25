"""Agent 1 : recoupe les pieces jointes (facture, colisage, connaissement) avec la DDM.

Il ne conclut jamais a la fraude : il pose des faits compares cote a cote,
avec l'endroit ou l'inspecteur peut les verifier.
"""
import json
import re
import unicodedata
from pathlib import Path

from agents.base import RapportAgent, NIVEAU_CONTRADICTION, NIVEAU_ECART
from agents.extraction import pdf_vers_texte, extraire_champs, CHAMPS

RACINE = Path(__file__).resolve().parent.parent

# Table de repli pour les produits du jeu de test : mots-cles de la designation
# commerciale -> positions SH admises (4 chiffres ; l'huile d'olive vierge est en
# 1509, les autres huiles d'olive en 1510). sh6 = code a 6 chiffres propose en cas de
# faux classement : c'est la cle du bareme de prix, donc il reprend ses codes. et poids unitaire plausible (kg).
# Les bornes sont volontairement larges : on ne veut signaler que l'absurde
# (un bureau de 1,4 kg), pas un modele un peu plus leger que la moyenne.
PRODUITS = [
    {"mots": ["passenger car", "voiture"], "libelle": "voiture de tourisme",
     "sh4": ["8703"], "sh6": "870322", "poids_min": 600, "poids_max": 3500},
    {"mots": ["olive oil", "huile d'olive"], "libelle": "huile d'olive en bidon de 5 L",
     "sh4": ["1509", "1510"], "sh6": "151090", "poids_min": 3.5, "poids_max": 7},
    {"mots": ["office desk", "desk", "bureau"], "libelle": "bureau en bois",
     "sh4": ["9403"], "sh6": "940360", "poids_min": 8, "poids_max": 150},
    {"mots": ["smartphone", "mobile phone"], "libelle": "smartphone",
     "sh4": ["8517"], "sh6": "851713", "poids_min": 0.08, "poids_max": 0.6},
    {"mots": ["led tv", "television", "tv "], "libelle": "televiseur 43 pouces",
     "sh4": ["8528"], "sh6": "852872", "poids_min": 3, "poids_max": 25},
    {"mots": ["t-shirt", "tee-shirt", "tshirt"], "libelle": "t-shirt en coton",
     "sh4": ["6109"], "sh6": "610910", "poids_min": 0.08, "poids_max": 0.6},
]


def _chemin(dossier) -> Path:
    p = Path(dossier)
    if not p.is_absolute() and not p.exists():
        p = RACINE / "dossiers" / str(dossier)
    return p


def _produit(designation):
    if not designation:
        return None
    d = designation.lower() + " "
    for prod in PRODUITS:
        if any(m in d for m in prod["mots"]):
            return prod
    return None


TERMES_GENERIQUES = [r"marchandises? diverses?", r"divers(?:es)?", r"[ée]chantillons?",
                     r"samples?", r"general goods", r"assorted", r"miscellaneous", r"various"]


def _designation_vague(designation, prod):
    """Renvoie le motif ('terme generique' / 'trop courte') ou None.
    Une designation que la table sait classer n'est pas 'trop courte' : le
    critere est de pouvoir verifier le classement, pas de compter les mots."""
    if not designation:
        return None
    # Accents retires : 'Échantillons' et 'Echantillons' doivent se valoir.
    texte = "".join(c for c in unicodedata.normalize("NFKD", designation.lower())
                    if not unicodedata.combining(c))
    if any(re.search(rf"\b{t}\b", texte) for t in TERMES_GENERIQUES):
        return "terme generique"
    mots = designation.split()
    # Chiffre (1200cc, 128GB, 5L) = specification ; mot tout en majuscules
    # ou alphanumerique (SAMSUNG, XR-200) = marque ou reference produit.
    reference = any(re.search(r"\d", m) for m in mots)
    marque = any(len(m) >= 2 and m.isupper() for m in mots)
    if len(mots) < 4 and not reference and not marque and prod is None:
        return "trop courte"
    return None


def _ecart_relatif(a, b):
    return abs(a - b) / max(abs(a), abs(b), 1e-9)


def charger(dossier):
    """Lit les 4 pieces. Un PDF illisible ne fait pas planter l'agent :
    tous ses champs deviennent None et seront declares non lus."""
    p = _chemin(dossier)
    ddm = json.loads((p / "ddm.json").read_text(encoding="utf-8"))
    docs = {}
    for type_doc in ("facture", "colisage", "transport"):
        try:
            docs[type_doc] = extraire_champs(pdf_vers_texte(p / f"{type_doc}.pdf"), type_doc)
        except Exception:
            docs[type_doc] = {c: None for c in CHAMPS[type_doc]}
    return ddm, docs


def analyser(dossier: str) -> RapportAgent:
    r = RapportAgent(agent="Inspecteur documentaire")
    ddm, docs = charger(dossier)
    fac, col, tra = docs["facture"], docs["colisage"], docs["transport"]
    r.donnees = {"ddm": ddm, **docs}
    # Piece facultative : l'Agent 2 la rapproche de l'ecart de prix. On ne la
    # juge pas ici, on transmet seulement son texte.
    justif = _chemin(dossier) / "justificatif.pdf"
    if justif.exists():
        try:
            r.donnees["justificatif"] = pdf_vers_texte(justif)
        except Exception:
            r.non_lus.append("justificatif.pdf : illisible")

    for type_doc, champs in docs.items():
        r.non_lus += [f"{type_doc}.{c}" for c, v in champs.items() if v is None]

    # ---------- NIVEAU 1 : contradictions ----------

    # Quantite : une seule alerte qui montre les trois chiffres, pour que
    # l'inspecteur voie d'un coup d'oeil quel document diverge.
    qtes = {"facture": fac["quantite"], "colisage": col["quantite"], "DDM": ddm.get("quantite")}
    lues = {k: v for k, v in qtes.items() if v is not None}
    if len(set(lues.values())) > 1:
        r.ajouter(
            type="ecart_quantite", niveau=NIVEAU_CONTRADICTION, gravite=80,
            message=(f"Les quantites ne concordent pas : facture {qtes['facture']}, "
                     f"colisage {qtes['colisage']}, DDM {qtes['DDM']}."),
            preuve=qtes,
            source="facture : ligne article, colonne QTY / colisage : ligne 'Quantity' / DDM : champ quantite",
        )

    pn_col, pn_ddm = col["poids_net"], ddm.get("poids_net_kg")
    if pn_col is not None and pn_ddm is not None and _ecart_relatif(pn_col, pn_ddm) > 0.02:
        r.ajouter(
            type="ecart_poids", niveau=NIVEAU_CONTRADICTION, gravite=75,
            message=(f"Poids net du colisage ({pn_col:,.1f} kg) different du poids net "
                     f"declare ({pn_ddm:,.1f} kg), soit {pn_col - pn_ddm:+,.1f} kg."),
            preuve={"colisage_kg": pn_col, "DDM_kg": pn_ddm,
                    "ecart_pct": round(100 * (pn_col - pn_ddm) / pn_ddm, 1), "tolerance_pct": 2},
            source="colisage : ligne 'Net weight' / DDM : champ poids_net_kg",
        )

    mt, v_ddm = fac["montant_total"], ddm.get("valeur_cif_usd")
    if mt is not None and v_ddm is not None and _ecart_relatif(mt, v_ddm) > 0.01:
        r.ajouter(
            type="ecart_valeur", niveau=NIVEAU_CONTRADICTION, gravite=85,
            message=(f"La facture totalise {mt:,.2f} {fac['devise'] or ''} alors que la DDM "
                     f"declare une valeur CIF de {v_ddm:,.2f} USD."),
            preuve={"facture_total": mt, "DDM_valeur_cif_usd": v_ddm,
                    "ecart_pct": round(100 * (v_ddm - mt) / mt, 1), "tolerance_pct": 1},
            source="facture : ligne 'TOTAL CIF' / DDM : champ valeur_cif_usd",
        )

    o_tra, o_ddm = tra["pays_origine"], ddm.get("pays_origine")
    if o_tra and o_ddm and o_tra.strip().upper() != o_ddm.strip().upper():
        r.ajouter(
            type="ecart_origine", niveau=NIVEAU_CONTRADICTION, gravite=70,
            message=f"Le connaissement indique l'origine {o_tra}, la DDM declare {o_ddm}.",
            preuve={"connaissement": o_tra, "DDM": o_ddm},
            source="connaissement : ligne 'Country of origin' / DDM : champ pays_origine",
        )

    q, pu = fac["quantite"], fac["prix_unitaire"]
    if q is not None and pu is not None and mt is not None and _ecart_relatif(q * pu, mt) > 0.01:
        r.ajouter(
            type="erreur_arithmetique", niveau=NIVEAU_CONTRADICTION, gravite=60,
            message=(f"Sur la facture, {q} x {pu:,.2f} = {q * pu:,.2f}, "
                     f"mais le total affiche est {mt:,.2f}."),
            preuve={"quantite": q, "prix_unitaire": pu, "produit_calcule": round(q * pu, 2),
                    "total_affiche": mt},
            source="facture : ligne article (QTY, UNIT PRICE) et ligne 'TOTAL'",
        )

    c_col, c_tra = col["conteneur"], tra["conteneur"]
    if c_col and c_tra and c_col.replace(" ", "").upper() != c_tra.replace(" ", "").upper():
        r.ajouter(
            type="ecart_conteneur", niveau=NIVEAU_CONTRADICTION, gravite=65,
            message=f"Conteneur {c_col} sur le colisage, {c_tra} sur le connaissement.",
            preuve={"colisage": c_col, "connaissement": c_tra, "DDM": ddm.get("conteneur")},
            source="colisage : ligne 'Container' / connaissement : ligne 'Container'",
        )

    ref = fac["reference"]
    if ref:
        absente = []
        if col["reference"] and col["reference"] != ref:
            absente.append("colisage")
        if ddm.get("reference_facture") and ddm["reference_facture"] != ref:
            absente.append("DDM")
        if absente:
            r.ajouter(
                type="ecart_reference", niveau=NIVEAU_CONTRADICTION, gravite=40,
                message=f"La reference facture {ref} ne se retrouve pas sur : {', '.join(absente)}.",
                preuve={"facture": ref, "colisage": col["reference"],
                        "DDM": ddm.get("reference_facture")},
                source="facture : ligne 'Ref' / colisage : ligne 'Ref' / DDM : champ reference_facture",
            )

    # ---------- NIVEAU 2 : ecarts qui peuvent avoir une explication ----------

    designation = fac["designation"] or col["designation"]
    prod = _produit(designation)
    if designation and prod is None:
        r.non_lus.append(f"produit non reconnu par la table de reference : '{designation}'")

    vague = _designation_vague(fac["designation"], prod)
    if vague:
        r.ajouter(
            type="designation_vague", niveau=NIVEAU_ECART, gravite=45,
            message=("Designation insuffisamment precise pour verifier le classement "
                     "tarifaire. Complement d'information a demander."),
            preuve={"designation_facture": fac["designation"],
                    "longueur": len(fac["designation"].split()), "motif": vague},
            source="facture : ligne article, colonne DESCRIPTION",
        )

    if prod:
        code_sh = str(ddm.get("code_sh") or "")
        if code_sh and not code_sh.startswith(tuple(prod["sh4"])):
            r.ajouter(
                type="designation_vs_sh", niveau=NIVEAU_ECART, gravite=75,
                message=(f"La facture decrit '{designation}' ({prod['libelle']}, position "
                         f"{' ou '.join(prod['sh4'])}) mais la DDM declare le code SH {code_sh} "
                         f"('{ddm.get('designation', '')}')."),
                preuve={"designation_facture": designation, "positions_admises": prod["sh4"],
                        "code_sh_declare": code_sh, "designation_DDM": ddm.get("designation")},
                source="facture : ligne article, colonne DESCRIPTION / DDM : champ code_sh",
            )
            # Transmis a l'Agent 2 : le prix sera aussi controle sous ce code.
            r.donnees["code_sh_suggere"] = prod["sh6"]

        # Le poids unitaire depend de la quantite retenue. Si les documents se
        # contredisent sur la quantite, on n'alerte que si AUCUNE des quantites
        # ne donne un poids plausible : sinon on accuserait le poids a tort.
        pn = col["poids_net"] if col["poids_net"] is not None else ddm.get("poids_net_kg")
        candidates = sorted({v for v in lues.values() if v})
        if pn and candidates:
            unitaires = {qq: pn / qq for qq in candidates}
            if all(not (prod["poids_min"] <= u <= prod["poids_max"]) for u in unitaires.values()):
                u = unitaires[candidates[0]] if len(candidates) == 1 else None
                r.ajouter(
                    type="poids_invraisemblable", niveau=NIVEAU_ECART, gravite=70,
                    message=(f"{pn:,.1f} kg pour {', '.join(str(c) for c in candidates)} unites "
                             f"de '{designation}' : "
                             + (f"{u:.3f} kg par unite" if u is not None else "poids unitaire")
                             + f", hors de la plage plausible {prod['poids_min']}-{prod['poids_max']} kg."),
                    preuve={"poids_net_kg": pn,
                            "poids_unitaire_kg": {str(k): round(v, 3) for k, v in unitaires.items()},
                            "plage_plausible_kg": [prod["poids_min"], prod["poids_max"]],
                            "reference": "table de repli interne"},
                    source="colisage : ligne 'Net weight' / facture : colonne QTY",
                )

    # Plus de la moitie des champs illisibles : les controles ci-dessus ne
    # prouvent plus rien, il faut le dire plutot que d'afficher 'OK'.
    total = sum(len(v) for v in docs.values())
    manquants = sum(1 for v in docs.values() for x in v.values() if x is None)
    if manquants > total / 2:
        r.statut = "INCOMPLET"
    return r
