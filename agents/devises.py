"""Conversions de devises. Deux usages distincts, a ne pas melanger :

1. devise d'un document -> USD (pivot) : pour COMPARER. Le bareme Comtrade est
   en USD/kg ; on ramene la valeur declaree dans cette unite, jamais l'inverse
   (convertir aussi le bareme ajouterait une erreur de change des deux cotes).
2. USD -> TND : pour AFFICHER et chiffrer l'impact. L'inspecteur raisonne en dinars.
"""

# Valeur d'UNE unite de la devise, exprimee en USD.
TAUX = {
    "USD": 1.0,     # pivot
    "EUR": 1.08,    # 1 EUR = 1,08 USD
    "TND": 0.32,    # 1 TND = 0,32 USD, soit 1 USD = 3,125 TND
}
DATE_TAUX = "2026-09-26"
SOURCE_TAUX = ("taux fixe d'illustration - en production, taux officiel BCT a la date "
               "d'enregistrement de la declaration")
MENTION_TAUX = f"taux d'illustration du {DATE_TAUX}, non officiel"


def _code(devise):
    return str(devise or "").strip().upper()


def taux(devise):
    """None pour une devise inconnue : jamais de conversion approximative."""
    return TAUX.get(_code(devise))


def vers_usd(montant, devise):
    t = taux(devise)
    if montant is None or t is None:
        return None
    return montant * t


def vers_tnd(montant_usd):
    if montant_usd is None:
        return None
    return montant_usd / TAUX["TND"]


def nombre_fr(x, decimales=2):
    return _nombre(x, decimales)


def _nombre(x, decimales):
    """Espace comme separateur de milliers, virgule decimale : lecture tunisienne."""
    s = f"{x:,.{decimales}f}".replace(",", " ").replace(".", ",")
    return s


def fmt_tnd(montant_usd, decimales=0):
    """'141 000 TND (45 000 USD)'"""
    if montant_usd is None:
        return "montant inconnu"
    return f"{_nombre(vers_tnd(montant_usd), decimales)} TND ({_nombre(montant_usd, decimales)} USD)"


def fmt_tnd_kg(prix_usd_kg):
    """'21,69 TND/kg (6,94 USD/kg)'"""
    if prix_usd_kg is None:
        return "prix inconnu"
    return f"{_nombre(vers_tnd(prix_usd_kg), 2)} TND/kg ({_nombre(prix_usd_kg, 2)} USD/kg)"


def conversion(montant, devise):
    """Bloc de preuve d'une conversion vers USD, ou None si la devise est inconnue."""
    t = taux(devise)
    if t is None or montant is None:
        return None
    return {"devise_facture": _code(devise), "taux_applique": t, "date_taux": DATE_TAUX,
            "valeur_usd": round(montant * t, 2), "source_taux": SOURCE_TAUX}
