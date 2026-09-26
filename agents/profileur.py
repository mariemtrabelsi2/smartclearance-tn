"""Agent 3 : profil de l'operateur a partir de l'historique de ses declarations.

Un profil n'est pas une preuve. Toutes ses alertes sont de niveau 2 et
l'orchestrateur plafonne leur poids : elles orientent le regard de
l'inspecteur, elles ne justifient pas a elles seules un controle physique.
"""
import csv
import math
import statistics
from datetime import date
from pathlib import Path

from agents import nomenclature, stockage
from agents.base import RapportAgent, NIVEAU_ECART

RACINE = Path(__file__).resolve().parent.parent
HISTORIQUE_DEFAUT = RACINE / "donnees" / "historique.csv"
PAYS_RISQUE_DEFAUT = RACINE / "donnees" / "pays_risque.csv"

ANCIENNETE_MIN_MOIS = 6
DERIVE_MIN_DECLARATIONS = 6
DERIVE_PENTE_MAX_PCT = -2.0       # % par trimestre : en dessus, c'est du bruit de marche
DERIVE_T_MAX = -2.5               # statistique t de la pente : exige un signal net
PARTAGE_MIN_IMPORTATEURS = 3
PARTAGE_MIN_AVEC_ALERTES = 2
SEUIL_SOUS_EVAL_HISTO = 0.7       # prix <= 70 % de la mediane du code SH = sous-evaluation passee

TYPES = {"anciennete_importateur", "fournisseur_inconnu", "changement_secteur",
         "origine_juridiction_surveillee",
         "derive_prix", "fournisseur_partage"}


def _d(s):
    return date.fromisoformat(str(s)[:10])


def _mois_entre(a, b):
    return (b.year - a.year) * 12 + b.month - a.month + (b.day - a.day) / 30


def lire_historique(source=None):
    """Compatibilite : passe par la couche de stockage."""
    return stockage.lire_historique(source)


def lire_pays_risque(chemin):
    """Lignes '#' ignorees : elles portent l'avertissement sur l'origine de la liste."""
    if not Path(chemin).exists():
        return {}
    with open(chemin, newline="", encoding="utf-8") as f:
        lignes = [l for l in f if not l.lstrip().startswith("#")]
    return {l["code_pays"].strip().upper(): l for l in csv.DictReader(lignes)}


def _norm(s):
    return " ".join(str(s or "").upper().split())


def _regression(xs, ys):
    """Moindres carres a la main (pas de dependance) : pente et statistique t."""
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return 0.0, 0.0
    pente = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    residus = [y - (my + pente * (x - mx)) for x, y in zip(xs, ys)]
    se = math.sqrt(sum(r * r for r in residus) / (n - 2) / sxx) if n > 2 else 0.0
    t = pente / se if se > 0 else (-math.inf if pente < 0 else math.inf)
    return pente, t


def analyser(ddm: dict, historique_csv=None, date_ddm=None,
             pays_risque_csv=PAYS_RISQUE_DEFAUT) -> RapportAgent:
    """date_ddm : date de l'operation. On ne regarde que l'historique ANTERIEUR,
    sinon l'operation se justifierait elle-meme (un changement de secteur
    deviendrait 'habituel' des qu'il est enregistre)."""
    r = RapportAgent(agent="Profileur")
    histo = stockage.lire_historique(historique_csv)
    if histo is None:
        r.non_lus.append("historique des declarations indisponible")
        r.statut = "INCOMPLET"
        return r

    ref = _d(date_ddm) if date_ddm else max(l["date"] for l in histo)
    histo = [l for l in histo if l["date"] < ref]

    imp, four = _norm(ddm.get("importateur")), _norm(ddm.get("fournisseur"))
    sh = str(ddm.get("code_sh") or "")
    siennes = [l for l in histo if _norm(l["importateur"]) == imp]
    r.donnees = {"importateur": ddm.get("importateur"), "date_reference": ref.isoformat(),
                 "nb_declarations_historique": len(siennes)}

    if not siennes:
        # Un operateur inconnu n'est pas suspect : on le dit, on ne conclut rien.
        r.non_lus.append(f"historique_importateur : '{ddm.get('importateur')}' absent de l'historique")
        r.statut = "INCOMPLET"
        return r

    # Juridiction sous surveillance : critere objectif et cite (liste GAFI), pas
    # un jugement sur l'operateur. La DDM ne donne pas le pays du fournisseur :
    # on le controle seulement s'il est fourni.
    liste = lire_pays_risque(pays_risque_csv)
    for role, code in (("pays d'origine", ddm.get("pays_origine")),
                       ("pays du fournisseur", ddm.get("pays_fournisseur"))):
        entree = liste.get(str(code or "").strip().upper())
        if entree:
            r.ajouter(
                type="origine_juridiction_surveillee", niveau=NIVEAU_ECART, gravite=35,
                message=(f"Le {role} ({entree['code_pays']}) figure sur la liste des juridictions "
                         f"sous surveillance renforcee : {entree['motif']}."),
                preuve={"pays": entree["code_pays"], "motif": entree["motif"],
                        "source": entree["source"]},
                source=f"{Path(pays_risque_csv).name}",
            )
            break

    # a) Anciennete
    premiere = min(l["date"] for l in siennes)
    anciennete = _mois_entre(premiere, ref)
    if anciennete < ANCIENNETE_MIN_MOIS:
        r.ajouter(
            type="anciennete_importateur", niveau=NIVEAU_ECART, gravite=30,
            message=(f"Operateur recent : premiere declaration le {premiere.isoformat()}, "
                     f"soit {anciennete:.1f} mois avant cette operation."),
            preuve={"premiere_declaration": premiere.isoformat(),
                    "anciennete_mois": round(anciennete, 1), "seuil_mois": ANCIENNETE_MIN_MOIS,
                    "nb_declarations": len(siennes)},
            source="historique des declarations de l'importateur",
        )

    # b) Fournisseur jamais vu, tous importateurs confondus
    if four and not any(_norm(l["fournisseur"]) == four for l in histo):
        r.ajouter(
            type="fournisseur_inconnu", niveau=NIVEAU_ECART, gravite=25,
            message=f"Fournisseur '{ddm.get('fournisseur')}' jamais rencontre dans l'historique.",
            preuve={"fournisseur": ddm.get("fournisseur"), "nb_declarations_historique": len(histo)},
            source="historique des declarations, tous importateurs",
        )

    # c) Changement de secteur (chapitre SH)
    chapitres = sorted({l["code_sh"][:2] for l in siennes})
    if sh and sh[:2] not in chapitres:
        r.ajouter(
            type="changement_secteur", niveau=NIVEAU_ECART, gravite=50,
            # Meme controle, message lisible : les libelles des chapitres, pas leurs numeros.
            message=(f"L'importateur n'a jamais importe de marchandises de ce chapitre. Chapitres "
                     f"habituels : {', '.join(nomenclature.chapitre_lisible(c) for c in chapitres)} ; "
                     f"chapitre declare : {nomenclature.chapitre_lisible(sh[:2])}."),
            preuve={"chapitres_habituels": chapitres, "chapitre_declare": sh[:2],
                    "libelles_habituels": [nomenclature.libelle_chapitre(c) for c in chapitres],
                    "libelle_declare": nomenclature.libelle_chapitre(sh[:2]),
                    "nb_declarations": len(siennes)},
            source="historique des declarations de l'importateur",
        )

    # d) Derive du prix au kilo pour ce code SH
    serie = sorted((l for l in siennes if l["code_sh"] == sh), key=lambda l: l["date"])
    if len(serie) >= DERIVE_MIN_DECLARATIONS:
        t0 = serie[0]["date"]
        xs = [_mois_entre(t0, l["date"]) / 3 for l in serie]      # en trimestres
        ys = [l["prix_kg"] for l in serie]
        pente, t = _regression(xs, ys)
        pente_pct = 100 * pente / statistics.mean(ys)
        r.donnees.update({"derive_pente_pct_par_trimestre": round(pente_pct, 1),
                          "derive_t": round(t, 2) if math.isfinite(t) else None})
        if pente_pct <= DERIVE_PENTE_MAX_PCT and t <= DERIVE_T_MAX:
            r.ajouter(
                type="derive_prix", niveau=NIVEAU_ECART, gravite=60,
                message=(f"Le prix au kilo declare par cet importateur pour le code {sh} baisse "
                         f"regulierement : {pente_pct:+.1f} % par trimestre sur "
                         f"{len(serie)} declarations."),
                preuve={"pente_pct_par_trimestre": round(pente_pct, 1),
                        "nb_declarations": len(serie),
                        "periode": f"{serie[0]['date']:%Y-%m} a {serie[-1]['date']:%Y-%m}",
                        "premier_prix_kg": round(ys[0], 2), "dernier_prix_kg": round(ys[-1], 2)},
                source="historique des declarations de l'importateur, meme code SH",
            )

    # e) Fournisseur partage par des importateurs deja en sous-evaluation
    if four:
        medianes = {}
        for l in histo:
            medianes.setdefault(l["code_sh"], []).append(l["prix_kg"])
        medianes = {k: statistics.median(v) for k, v in medianes.items()}
        clients = {}
        for l in histo:
            if _norm(l["fournisseur"]) == four:
                sous = l["prix_kg"] <= SEUIL_SOUS_EVAL_HISTO * medianes[l["code_sh"]]
                clients[_norm(l["importateur"])] = clients.get(_norm(l["importateur"]), False) or sous
        avec_alertes = sum(clients.values())
        if len(clients) >= PARTAGE_MIN_IMPORTATEURS and avec_alertes >= PARTAGE_MIN_AVEC_ALERTES:
            r.ajouter(
                type="fournisseur_partage", niveau=NIVEAU_ECART, gravite=55,
                message=(f"Le fournisseur '{ddm.get('fournisseur')}' livre {len(clients)} "
                         f"importateurs, dont {avec_alertes} ont deja declare des prix inferieurs "
                         f"de plus de 30 % a la mediane du marche."),
                preuve={"fournisseur": ddm.get("fournisseur"), "nb_importateurs": len(clients),
                        "dont_avec_alertes": avec_alertes},
                source="historique des declarations, tous importateurs de ce fournisseur",
            )
    return r
