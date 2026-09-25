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
    "certificat": ["reference", "autorite_emettrice", "pays_autorite", "exportateur",
                   "destinataire", "pays_origine", "designation", "quantite", "poids_net",
                   "date_emission"],
}

# Nom de pays (tel qu'ecrit dans le libelle de l'autorite emettrice) -> ISO2.
# Un nom absent de cette table donne None : on ne devine pas un pays.
PAYS_ISO2 = {
    "china": "CN", "people's republic of china": "CN", "turkiye": "TR", "turkey": "TR",
    "türkiye": "TR", "italy": "IT", "italia": "IT", "egypt": "EG", "spain": "ES",
    "espana": "ES", "españa": "ES", "france": "FR", "germany": "DE", "india": "IN",
    "tunisia": "TN", "morocco": "MA", "algeria": "DZ", "united arab emirates": "AE",
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
    "certificat": {
        "autorite_emettrice": [r"issuing authority"],
        "exportateur": [r"exporter"],
        "destinataire": [r"consignee"],
        "pays_origine": [r"country of origin"],
        "designation": [r"goods", r"description of goods"],
        "quantite": [r"quantity"],
        "poids_net": [r"net weight"],
        "date_emission": [r"date of issue"],
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


# ---------------------------------------------------------------------------
# Normalisation. Principe : on ne corrige JAMAIS une valeur declaree. On garde
# le brut, on calcule a cote une valeur normalisee qui sert a comparer, et on
# dit quelle normalisation a ete appliquee.
# ---------------------------------------------------------------------------
ESPACES_SPECIAUX = {"\u00a0": " ", "\u202f": " ", "\u2009": " ", "\t": " "}
CHAMPS_CONTENEUR = {"conteneur"}
CHAMPS_PAYS = {"pays_origine", "pays_autorite"}
# Confusions de lecture classiques (OCR, saisie) : lettre a la place d'un chiffre.
CONFUSIONS = str.maketrans({"O": "0", "o": "0", "l": "1", "I": "1", "S": "5"})
# Normalisations qui ne changent rien au sens pour ces documents : pas la peine
# de les montrer a l'inspecteur a chaque dossier.
ANODINES = {"separateur de milliers (virgule)", "unite retiree"}


def _espaces(s):
    for a, b in ESPACES_SPECIAUX.items():
        s = s.replace(a, b)
    return s


def _jeton_numerique(s):
    """Nombre en tete de chaine, groupes separes par espaces compris ('1 250,50 kg')."""
    m = re.search(r"-?\d(?:[\d.,]|\s(?=\d{3}\b))*", s)
    if not m:
        return None
    # Le nombre doit etre un mot entier : '1O5O' ou 'l2S' ne donnent pas 1 ou 2.
    avant = s[:m.start()][-1:]
    apres = re.match(r"\S*", s[m.end():]).group(0)
    if (avant and avant.isalnum()) or re.search(r"\d", apres) or re.match(r"[OolIS]", apres):
        return None
    return m.group(0).rstrip(".,")


def normaliser_nombre(brut):
    """-> (valeur | None, [normalisations appliquees]).
    Regles explicites, sinon None : on ne devine pas un nombre ambigu."""
    if brut is None:
        return None, []
    s = str(brut)
    faites = []
    s2 = _espaces(s).strip()
    if s2 != s.strip():
        faites.append("espaces insecables")
    jeton = _jeton_numerique(s2)
    if jeton is None:
        return None, faites
    if s2 != jeton:
        faites.append("unite retiree")
    t = jeton
    if " " in t:
        if not re.fullmatch(r"-?\d{1,3}(?: \d{3})+(?:[.,]\d+)?", t):
            return None, faites
        t = t.replace(" ", "")
        faites.append("separateur de milliers (espace)")
    virgule, point = "," in t, "." in t
    if virgule and point:
        dec = "," if t.rfind(",") > t.rfind(".") else "."
        mil = "." if dec == "," else ","
        entier, _, frac = t.rpartition(dec)
        if not re.fullmatch(rf"-?\d{{1,3}}(?:\{mil}\d{{3}})+", entier) or not frac.isdigit():
            return None, faites
        t = entier.replace(mil, "") + "." + frac
        faites.append(f"separateur de milliers ({'virgule' if mil == ',' else 'point'})")
        if dec == ",":
            faites.append("virgule decimale")
    elif virgule:
        if re.fullmatch(r"-?\d{1,3}(?:,\d{3})+", t):
            # Convention de ces documents : virgule = milliers ('1,500' = 1500).
            t = t.replace(",", "")
            faites.append("separateur de milliers (virgule)")
        elif re.fullmatch(r"-?\d+,\d{1,2}", t):
            t = t.replace(",", ".")
            faites.append("virgule decimale")
        else:
            return None, faites
    elif point and re.fullmatch(r"-?\d{1,3}(?:\.\d{3}){2,}", t):
        t = t.replace(".", "")
        faites.append("separateur de milliers (point)")
    elif point and not re.fullmatch(r"-?\d+\.\d+", t):
        return None, faites
    try:
        return float(t), faites
    except ValueError:
        return None, faites


def nombre(brut):
    """Compatibilite : la valeur normalisee seule."""
    return normaliser_nombre(brut)[0]


def lecture_alternative(brut):
    """Si un champ numerique illisible contient O, l, I ou S au milieu de chiffres,
    propose la lecture avec les chiffres correspondants. Proposition seulement :
    l'appelant ne doit JAMAIS la substituer a la valeur lue."""
    if brut is None or not re.search(r"\d", str(brut)) or not re.search(r"[OolIS]", str(brut)):
        return None
    jeton = re.search(r"[\dOolIS][\dOolIS.,\s]*", str(brut))
    if not jeton or not re.search(r"\d", jeton.group(0)):
        return None
    alt = jeton.group(0).strip().translate(CONFUSIONS)
    return alt if normaliser_nombre(alt)[0] is not None else None


def cle_nom(s):
    """Comparaison de noms d'entreprise : casse et espaces ignores (l'affichage
    garde la forme d'origine)."""
    return " ".join(_espaces(str(s)).split()).casefold() if s else None


def cle_conteneur(s):
    return re.sub(r"[\s\-]", "", _espaces(str(s))).upper() if s else None


def normaliser_champ(champ, brut):
    """-> {"brut", "normalise", "normalisation_appliquee", "significative", ...}"""
    d = {"brut": brut, "normalise": None, "normalisation_appliquee": None, "significative": False}
    if brut is None or str(brut).strip() == "":
        return d
    faites = []
    if champ in ENTIERS or champ in DECIMAUX:
        v, faites = normaliser_nombre(brut)
        if v is not None and champ in ENTIERS:
            v = int(v) if v == int(v) else None
        d["normalise"] = v
        if v is None:
            alt = lecture_alternative(brut)
            if alt is not None:
                d["lecture_alternative"] = alt
    elif champ in CHAMPS_CONTENEUR:
        d["normalise"] = cle_conteneur(brut)
        if re.sub(r"\s", "", str(brut)).upper() != d["normalise"] or str(brut).strip() != str(brut).strip().upper():
            faites.append("conteneur : majuscules, espaces et tirets retires")
    elif champ in CHAMPS_PAYS:
        d["normalise"] = _espaces(str(brut)).strip().upper()
        if d["normalise"] != str(brut):
            faites.append("code pays en majuscules")
    else:
        d["normalise"] = " ".join(_espaces(str(brut)).split())
        if d["normalise"] != str(brut).strip():
            faites.append("espaces normalises")
    if faites:
        d["normalisation_appliquee"] = ", ".join(faites)
        d["significative"] = any(f not in ANODINES for f in faites)
    return d


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
    """Extracteur deterministe : marche sans reseau, toujours disponible.
    Renvoie les valeurs NORMALISEES (celles qui servent a comparer)."""
    return {c: d["normalise"] for c, d in extraire_champs_detail(texte, type_doc).items()}


def extraire_champs_detail(texte: str, type_doc: str) -> dict:
    """Pour chaque champ : brut, normalise et normalisation appliquee."""
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

    if type_doc == "certificat" and brut["autorite_emettrice"]:
        # 'Chamber of Commerce of Shanghai, China' -> 'China' -> CN
        morceaux = brut["autorite_emettrice"].rsplit(",", 1)
        if len(morceaux) == 2:
            brut["pays_autorite"] = PAYS_ISO2.get(" ".join(morceaux[1].split()).lower())

    return {c: normaliser_champ(c, v) for c, v in brut.items()}


def champs_manquants(champs: dict) -> list:
    return [c for c, v in champs.items() if v is None]
