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
    # Le certificat d'origine n'est exige que pour un regime preferentiel : absent,
    # il n'entre pas dans docs, donc ni alerte ni statut degrade.
    if (p / "certificat_origine.pdf").exists():
        try:
            docs["certificat"] = extraire_champs(pdf_vers_texte(p / "certificat_origine.pdf"), "certificat")
        except Exception:
            docs["certificat"] = {c: None for c in CHAMPS["certificat"]}
    return ddm, docs


def analyser(dossier: str) -> RapportAgent:
    r = RapportAgent(agent="Inspecteur documentaire")
    ddm, docs = charger(dossier)
    fac, col, tra = docs["facture"], docs["colisage"], docs["transport"]
    cer = docs.get("certificat")
    r.donnees = {"ddm": ddm, **docs}
    if cer is None:
        r.non_lus.append("certificat_origine_absent")
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
    if cer is not None:
        qtes["certificat"] = cer["quantite"]
    lues = {k: v for k, v in qtes.items() if v is not None}
    if len(set(lues.values())) > 1:
        r.ajouter(
            type="ecart_quantite", niveau=NIVEAU_CONTRADICTION, gravite=80,
            message="Les quantites ne concordent pas : "
                    + ", ".join(f"{k} {v}" for k, v in qtes.items()) + ".",
            preuve=qtes,
            source="facture : ligne article, colonne QTY / colisage : ligne 'Quantity' / DDM : champ quantite"
                   + (" / certificat : ligne 'Quantity'" if cer is not None else ""),
        )

    pn_col, pn_ddm = col["poids_net"], ddm.get("poids_net_kg")
    pn_cer = cer["poids_net"] if cer is not None else None

    def ecarte(pn):
        return pn is not None and pn_ddm is not None and _ecart_relatif(pn, pn_ddm) > 0.02

    if ecarte(pn_col) or ecarte(pn_cer):
        # Une seule alerte : le colisage fait reference, le certificat vient en
        # appui (ou seul s'il est le seul a diverger).
        pn = pn_col if ecarte(pn_col) else pn_cer
        doc = "du colisage" if ecarte(pn_col) else "du certificat d'origine"
        preuve = {"colisage_kg": pn_col, "DDM_kg": pn_ddm,
                  "ecart_pct": round(100 * (pn - pn_ddm) / pn_ddm, 1), "tolerance_pct": 2}
        if cer is not None:
            preuve["certificat_kg"] = pn_cer
        r.ajouter(
            type="ecart_poids", niveau=NIVEAU_CONTRADICTION, gravite=75,
            message=(f"Poids net {doc} ({pn:,.1f} kg) different du poids net "
                     f"declare ({pn_ddm:,.1f} kg), soit {pn - pn_ddm:+,.1f} kg."),
            preuve=preuve,
            source="colisage : ligne 'Net weight' / DDM : champ poids_net_kg"
                   + (" / certificat : ligne 'Net weight'" if cer is not None else ""),
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

    # Origine : trois sources si le certificat est la, deux sinon.
    def iso(x):
        return x.strip().upper() if x else None

    o_tra, o_ddm = iso(tra["pays_origine"]), iso(ddm.get("pays_origine"))
    o_cer = iso(cer["pays_origine"]) if cer is not None else None
    sources = {"certificat": o_cer, "transport": o_tra, "ddm": o_ddm}
    lus = [v for v in sources.values() if v]
    trois_divergent = len(lus) == 3 and len(set(lus)) == 3
    if o_tra and o_ddm and o_tra != o_ddm:
        preuve = {"connaissement": o_tra, "DDM": o_ddm}
        if cer is not None:
            preuve.update({"certificat": o_cer, "trois_sources_divergentes": trois_divergent})
        r.ajouter(
            type="ecart_origine", niveau=NIVEAU_CONTRADICTION, gravite=70,
            message=f"Le connaissement indique l'origine {o_tra}, la DDM declare {o_ddm}.",
            preuve=preuve,
            source="connaissement : ligne 'Country of origin' / DDM : champ pays_origine",
        )
    # Plus grave que l'ecart transport/DDM : le certificat est le document qui
    # FONDE l'origine, donc le droit au regime tarifaire preferentiel.
    if o_cer and o_ddm and o_cer != o_ddm:
        r.ajouter(
            type="ecart_origine_certificat", niveau=NIVEAU_CONTRADICTION, gravite=85,
            message=(f"Le certificat d'origine atteste l'origine {o_cer}, la DDM declare {o_ddm}"
                     + (f", le connaissement indique {o_tra} : les trois sources divergent."
                        if trois_divergent else ".")
                     + " Le certificat fonde l'origine et le regime tarifaire preferentiel."),
            preuve={**sources, "trois_sources_divergentes": trois_divergent},
            source="certificat : ligne 'Country of origin' / connaissement : ligne 'Country of origin' "
                   "/ DDM : champ pays_origine",
        )

    if cer is not None and cer["pays_autorite"] and o_cer and cer["pays_autorite"] != o_cer:
        r.ajouter(
            type="autorite_emettrice_incoherente", niveau=NIVEAU_CONTRADICTION, gravite=80,
            message=("L'autorite qui certifie l'origine n'est pas etablie dans le pays "
                     "d'origine annonce."),
            preuve={"origine_certifiee": o_cer, "pays_autorite": cer["pays_autorite"],
                    "autorite": cer["autorite_emettrice"]},
            source="certificat : lignes 'Issuing authority' et 'Country of origin'",
        )

    def norm(s):
        return " ".join(str(s).upper().split()) if s else None

    if cer is not None and cer["exportateur"] and fac["vendeur"] \
            and norm(cer["exportateur"]) != norm(fac["vendeur"]):
        r.ajouter(
            type="ecart_exportateur", niveau=NIVEAU_CONTRADICTION, gravite=65,
            message=(f"L'exportateur du certificat ({cer['exportateur']}) n'est pas le vendeur "
                     f"de la facture ({fac['vendeur']})."),
            preuve={"facture": fac["vendeur"], "certificat": cer["exportateur"]},
            source="facture : bloc SELLER / certificat : ligne 'Exporter'",
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

    code_sh = str(ddm.get("code_sh") or "")
    des_cer = cer["designation"] if cer is not None else None
    prod_cer = _produit(des_cer)
    if cer is not None and des_cer and prod_cer is None:
        r.non_lus.append(f"produit du certificat non reconnu par la table de reference : '{des_cer}'")
    # Chaque document est controle : si seul le certificat decrit une marchandise
    # incompatible avec le code declare, on le signale aussi.
    if prod_cer and code_sh and not code_sh.startswith(tuple(prod_cer["sh4"])) \
            and (prod is None or code_sh.startswith(tuple(prod["sh4"]))):
        r.ajouter(
            type="designation_vs_sh", niveau=NIVEAU_ECART, gravite=75,
            message=(f"Le certificat d'origine decrit '{des_cer}' ({prod_cer['libelle']}, position "
                     f"{' ou '.join(prod_cer['sh4'])}) mais la DDM declare le code SH {code_sh}."),
            preuve={"designation_certificat": des_cer, "designation_facture": designation,
                    "positions_admises": prod_cer["sh4"], "code_sh_declare": code_sh},
            source="certificat : ligne 'Goods' / DDM : champ code_sh",
        )
        r.donnees["code_sh_suggere"] = prod_cer["sh6"]

    if prod:
        if code_sh and not code_sh.startswith(tuple(prod["sh4"])):
            r.ajouter(
                type="designation_vs_sh", niveau=NIVEAU_ECART, gravite=75,
                message=(f"La facture decrit '{designation}' ({prod['libelle']}, position "
                         f"{' ou '.join(prod['sh4'])}) mais la DDM declare le code SH {code_sh} "
                         f"('{ddm.get('designation', '')}')."),
                preuve={"designation_facture": designation, "positions_admises": prod["sh4"],
                        "code_sh_declare": code_sh, "designation_DDM": ddm.get("designation"),
                        **({"designation_certificat": des_cer} if cer is not None else {})},
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
