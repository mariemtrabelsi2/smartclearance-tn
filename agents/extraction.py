"""Lecture des pieces jointes PDF et extraction des champs utiles.

Regle d'or : un champ qu'on ne lit pas avec certitude vaut None.
L'inspecteur prefere un trou signale a une valeur inventee.
"""
import re

import pdfplumber

# Champs attendus par type de document : sert aussi a mesurer ce qui n'a pas ete lu.
CHAMPS = {
    "facture": ["reference", "vendeur", "acheteur", "date", "incoterm", "devise",
                "designation", "quantite", "prix_unitaire", "montant_total"],
    "colisage": ["reference", "conteneur", "designation", "nb_colis", "quantite",
                 "poids_net", "poids_brut"],
    "transport": ["reference", "navire", "port_chargement", "pays_origine",
                  "conteneur", "nb_colis", "poids_brut", "expediteur"],
}

# Libelles anglais des documents commerciaux -> nos champs.
# Plusieurs variantes par champ parce que chaque fournisseur a sa maquette.
LIBELLES = {
    "facture": {
        "date": [r"date", r"invoice date"],
        "incoterm": [r"incoterms?"],
        "devise": [r"currency"],
        "montant_total": [r"total(?: cif| fob| cfr)?(?: [a-z]{3})?", r"grand total"],
    },
    "colisage": {
        "conteneur": [r"container(?: no\.?)?"],
        "designation": [r"goods", r"description"],
        "nb_colis": [r"number of packages", r"packages"],
        "quantite": [r"quantity", r"qty"],
        "poids_net": [r"net weight"],
        "poids_brut": [r"gross weight"],
    },
    "transport": {
        "navire": [r"vessel"],
        "port_chargement": [r"port of loading"],
        "pays_origine": [r"country of origin", r"origin"],
        "conteneur": [r"container(?: no\.?)?"],
        "nb_colis": [r"packages", r"number of packages"],
        "poids_brut": [r"gross weight"],
        "expediteur": [r"shipper"],
    },
}

# Champs numeriques : on les convertit, et un echec de conversion donne None.
ENTIERS = {"quantite", "nb_colis"}
DECIMAUX = {"prix_unitaire", "montant_total", "poids_net", "poids_brut"}


def pdf_vers_texte(chemin) -> str:
    """layout=True garde l'alignement en colonnes : sans lui, vendeur et
    acheteur sont colles sur une seule ligne et impossibles a separer."""
    with pdfplumber.open(chemin) as pdf:
        pages = [p.extract_text(layout=True) or "" for p in pdf.pages]
    return "\n".join(l.rstrip() for l in "\n".join(pages).splitlines())


def nombre(brut):
    """'1,650,000.0 kg' -> 1650000.0. La virgule est un separateur de milliers
    dans ces documents ; on refuse tout ce qui n'a pas cette forme plutot que
    de risquer de lire 1,5 comme 15."""
    if brut is None:
        return None
    m = re.search(r"-?[\d][\d,.]*", str(brut))
    if not m:
        return None
    jeton = m.group(0).rstrip(".,")
    # Le jeton ENTIER doit etre bien forme : '1,5' ne doit pas devenir 1.
    if not re.fullmatch(r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?", jeton):
        return None
    return float(jeton.replace(",", ""))


def _typer(champ, valeur):
    if valeur is None or valeur == "":
        return None
    if champ in ENTIERS:
        n = nombre(valeur)
        return int(n) if n is not None and n == int(n) else None
    if champ in DECIMAUX:
        return nombre(valeur)
    return valeur.strip()


def _lignes(texte):
    return [l for l in texte.splitlines() if l.strip()]


def _valeur_apres_libelle(lignes, motifs):
    """Premiere ligne qui COMMENCE par le libelle : ancrer au debut evite de
    prendre 'Port of discharge' pour 'Port of loading' ou l'inverse."""
    for motif in motifs:
        rx = re.compile(rf"^\s*{motif}\s*[:.]?\s+(.+?)\s*$", re.IGNORECASE)
        for l in lignes:
            m = rx.match(l)
            if m:
                return m.group(1)
    return None


def _reference(lignes):
    for l in lignes:
        m = re.match(r"^\s*(?:ref(?:erence)?|invoice no\.?|b/l no\.?)\s*[:.]?\s*(\S+)", l, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def _colonnes_parties(lignes):
    """Bloc SELLER / BUYER cote a cote : on coupe la ligne suivante a la
    position ou commence 'BUYER' dans l'en-tete."""
    for i, l in enumerate(lignes):
        m = re.search(r"\bSELLER\b.*?\bBUYER\b", l, re.IGNORECASE)
        if m and i + 1 < len(lignes):
            coupe = l.upper().index("BUYER")
            suivante = lignes[i + 1]
            vendeur = suivante[:coupe].strip() or None
            acheteur = suivante[coupe:].strip() or None
            return vendeur, acheteur
    return None, None


def _ligne_article(lignes):
    """Premiere ligne apres l'en-tete DESCRIPTION/QTY : designation, qte, PU, montant.
    Les colonnes sont separees par au moins 2 espaces en mode layout."""
    for i, l in enumerate(lignes):
        if re.search(r"\bDESCRIPTION\b", l, re.IGNORECASE) and re.search(r"\bQTY\b|QUANTITY", l, re.IGNORECASE):
            for suivante in lignes[i + 1:i + 3]:
                m = re.match(r"^\s*(.+?)\s{2,}([\d,]+)\s+([\d,]+(?:\.\d+)?)\s+([\d,]+(?:\.\d+)?)\s*$", suivante)
                if m:
                    return m.groups()
            return None
    return None


def extraire_champs(texte: str, type_doc: str) -> dict:
    """Extracteur deterministe : marche sans reseau, toujours disponible."""
    if type_doc not in CHAMPS:
        raise ValueError(f"type_doc inconnu : {type_doc}")
    lignes = _lignes(texte)
    brut = {c: None for c in CHAMPS[type_doc]}
    brut["reference"] = _reference(lignes)

    for champ, motifs in LIBELLES[type_doc].items():
        brut[champ] = _valeur_apres_libelle(lignes, motifs)

    if type_doc == "facture":
        brut["vendeur"], brut["acheteur"] = _colonnes_parties(lignes)
        article = _ligne_article(lignes)
        if article:
            brut["designation"], brut["quantite"], brut["prix_unitaire"], montant_ligne = article
            # Le total explicite fait foi ; a defaut on garde le montant de la ligne.
            if brut["montant_total"] is None:
                brut["montant_total"] = montant_ligne
        if brut["incoterm"]:
            # 'CIF Rades' -> 'CIF' : le lieu n'est pas compare a la DDM.
            brut["incoterm"] = brut["incoterm"].split()[0].upper()

    return {c: _typer(c, v) for c, v in brut.items()}


def champs_manquants(champs: dict) -> list:
    return [c for c, v in champs.items() if v is None]
