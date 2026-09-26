"""Libelles d'AFFICHAGE. Aucun identifiant n'est renomme dans le code : les types
d'alerte, champs et marqueurs gardent leur nom interne partout (agents,
evaluer.py, verites terrain, resultats). Ce module ne sert qu'a l'ecran.
Libelle absent : on affiche l'identifiant tel quel plutot que de planter.
"""
import re

LIBELLES_ALERTE = {
    "anciennete_importateur": "Importateur récemment enregistré",
    "autorite_emettrice_incoherente": "Autorité émettrice inhabituelle",
    "changement_secteur": "Changement de secteur d'activité",
    "code_sh_inexistant": "Code SH inexistant",
    "derive_prix": "Baisse de prix progressive",
    "designation_vague": "Désignation trop vague",
    "designation_vs_sh": "La désignation ne correspond pas au code déclaré",
    "ecart_conteneur": "Numéro de conteneur différent selon les pièces",
    "ecart_exportateur": "Exportateur différent selon les pièces",
    "ecart_origine": "Origine différente selon les pièces",
    "ecart_origine_certificat": "Origine du certificat différente de la déclaration",
    "ecart_poids": "Poids différent selon les pièces",
    "ecart_quantite": "Quantité différente selon les pièces",
    "ecart_reference": "Référence de facture différente selon les pièces",
    "ecart_valeur": "Valeur différente selon les pièces",
    "erreur_arithmetique": "Erreur de calcul sur la facture",
    "fournisseur_inconnu": "Fournisseur jamais vu",
    "fournisseur_partage": "Fournisseur commun à plusieurs importateurs signalés",
    "origine_juridiction_surveillee": "Origine sous surveillance renforcée",
    "poids_invraisemblable": "Poids incompatible avec la marchandise",
    "reference_facture_dupliquee": "Facture déjà utilisée sur une autre déclaration",
    "saisie_douteuse": "Valeur saisie douteuse",
    "sous_evaluation": "Prix très inférieur à la référence",
    "sous_evaluation_via_reclassement": "Prix très inférieur à la référence du code réellement décrit",
    "sous_evaluation_justifiee": "Prix bas, justificatif cohérent",
    "sous_evaluation_justificatif_incoherent": "Prix bas, justificatif qui n'explique pas l'écart",
}

LIBELLES_RECO = {"LIBERATION": "Libération", "CONTROLE_DOCUMENTAIRE": "Contrôle documentaire",
                 "CONTROLE_PHYSIQUE": "Contrôle physique"}

LIBELLES_PIECES_DEPOT = {
    "ddm.json": "Déclaration en détail (DDM), fichier JSON",
    "facture.pdf": "Facture commerciale (PDF)",
    "colisage.pdf": "Liste de colisage (PDF)",
    "transport.pdf": "Titre de transport (PDF)",
    "justificatif.pdf": "Justificatif commercial (PDF), facultatif",
    "certificat_origine.pdf": "Certificat d'origine (PDF), facultatif",
}

# Pieces et champs des marqueurs "<piece>.<champ>" des champs non lus.
PIECES = {"facture": "la facture", "colisage": "la liste de colisage",
          "transport": "le titre de transport", "certificat": "le certificat d'origine"}
CHAMPS = {
    "reference": "Référence", "vendeur": "Vendeur", "acheteur": "Acheteur", "date": "Date",
    "incoterm": "Incoterm", "devise": "Devise", "designation": "Désignation",
    "quantite": "Quantité", "prix_unitaire": "Prix unitaire", "montant_total": "Montant total",
    "conteneur": "Numéro de conteneur", "nb_colis": "Nombre de colis", "poids_net": "Poids net",
    "poids_brut": "Poids brut", "navire": "Navire", "port_chargement": "Port de chargement",
    "pays_origine": "Pays d'origine", "expediteur": "Expéditeur",
    "autorite_emettrice": "Autorité émettrice", "pays_autorite": "Pays de l'autorité émettrice",
    "exportateur": "Exportateur", "destinataire": "Destinataire",
    "date_emission": "Date d'émission",
}
# Pays avec leur article, pour "depuis l'Espagne", "depuis la Chine".
PAYS = {"CN": "la Chine", "ES": "l'Espagne", "IT": "l'Italie", "TR": "la Turquie",
        "EG": "l'Égypte", "FR": "la France", "DE": "l'Allemagne", "IN": "l'Inde",
        "AE": "les Émirats arabes unis", "TN": "la Tunisie", "MA": "le Maroc", "DZ": "l'Algérie"}


def alerte(type_alerte):
    return LIBELLES_ALERTE.get(type_alerte, type_alerte)


def recommandation(code):
    return LIBELLES_RECO.get(code, code)


def piece_depot(nom_fichier):
    return LIBELLES_PIECES_DEPOT.get(nom_fichier, nom_fichier)


def non_lu(marqueur):
    """Marqueur interne -> texte lisible ; inconnu : tel quel."""
    if marqueur == "certificat_origine_absent":
        return "Certificat d'origine non fourni"
    m = re.fullmatch(r"reference_exacte_(\d+)_([A-Z]{2})", marqueur)
    if m:
        pays = PAYS.get(m.group(2), f"l'origine {m.group(2)}")
        return f"Aucun prix de référence pour le code {m.group(1)} depuis {pays}"
    m = re.fullmatch(r"reference_(\d+)", marqueur)
    if m:
        return f"Aucun prix de référence pour le code {m.group(1)}"
    m = re.fullmatch(r"(facture|colisage|transport|certificat)\.(\w+)", marqueur)
    if m:
        return f"{CHAMPS.get(m.group(2), m.group(2))}, sur {PIECES[m.group(1)]}"
    return marqueur
