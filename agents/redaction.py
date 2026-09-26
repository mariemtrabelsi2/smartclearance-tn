"""Redaction de l'explication destinee a l'inspecteur, par un LLM, sous controle.

PERIMETRE : le LLM ne redige QUE le texte de l'explication. Il ne calcule pas
le score, ne choisit pas la recommandation, ne cree, ne supprime et ne modifie
aucune alerte. Tout ce qui fonde une decision reste deterministe : un score
produit par un LLM ne serait ni verifiable ni opposable dans un contentieux.

Par defaut, AUCUN appel reseau : on lit le cache (donnees/explications.json),
sinon on garde l'explication deterministe. Seul outils/pregenerer_explications.py
autorise l'appel. Pendant la demonstration, une coupure reseau ne change rien.
"""
import hashlib
import json
import os
import re
import unicodedata
import urllib.request
from datetime import datetime
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
CACHE = RACINE / "donnees" / "explications.json"
JOURNAL_REJETS = RACINE / "donnees" / "redaction_rejets.jsonl"

try:
    from dotenv import load_dotenv
    load_dotenv(RACINE / ".env")
except ImportError:          # sans python-dotenv, seule une variable d'environnement compte
    pass

MODELE = os.environ.get("SMARTCLEARANCE_MODELE", "claude-opus-5")
URL_API = "https://api.anthropic.com/v1/messages"
DELAI_S = 5                  # une seule tentative, pas de nouvel essai

# Consigne transmise mot pour mot.
CONSIGNE = """Tu rediges une note de synthese pour un inspecteur des douanes, a
partir d'alertes deja etablies. Regles absolues :
- N'ecris QUE ce qui figure dans les donnees fournies. N'ajoute
  aucun fait, aucun chiffre, aucune hypothese.
- N'emploie jamais le mot 'fraude'. Ecris 'anomalie',
  'incoherence', ou 'doute motive'.
- Ne conclus pas. La decision appartient a l'inspecteur.
- Cite les chiffres exactement tels qu'ils sont donnes.
- 3 a 5 phrases, francais administratif sobre, pas de formule
  commerciale.
- Si des champs n'ont pas ete lus, commence par le dire."""


# ------------------------------------------------------------ entree du modele

def donnees_entree(synthese):
    """Uniquement ce que les agents ont deja etabli. Les comptes d'alertes sont
    fournis pour que le modele puisse les citer sans les calculer."""
    # La gravite est un reglage interne : ni utile au texte, ni a citer. L'omettre
    # evite aussi qu'un chiffre invente passe le controle parce qu'il coincide
    # avec une gravite (un 75 % invente passait grace a une gravite de 75).
    alertes = [{k: a[k] for k in ("type", "niveau", "message", "preuve", "source")}
               for a in synthese["alertes"]]
    return {
        "score": synthese["score"],
        "recommandation": synthese["recommandation"],
        "nb_alertes": len(alertes),
        "nb_contradictions": sum(1 for a in alertes if a["niveau"] == 1),
        "alertes": alertes,
        "champs_non_lus": synthese.get("champs_non_lus", []),
        "reference_prix": (synthese.get("reference_prix") or {}).get("libelle"),
        "valeur_declaree": (synthese.get("valeur_declaree") or {}).get("libelle"),
    }


def empreinte(entree):
    brut = json.dumps(entree, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(brut.encode("utf-8")).hexdigest()[:16]


def cle_cache(synthese, entree):
    return f"{synthese.get('numero_ddm')}|{empreinte(entree)}"


# ------------------------------------------------------------ controles de sortie

_NOMBRE = re.compile(r"\d{1,3}(?:[   ,.]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?")


def _valeurs(jeton):
    """Toutes les lectures plausibles d'un nombre ecrit : '1,600' peut valoir
    1600 ou 1.6 selon la convention. On compare des valeurs, pas des graphies."""
    t = re.sub(r"[   ]", "", jeton)
    lectures = set()
    for mil, dec in ((",", "."), (".", ",")):
        s = t.replace(mil, "").replace(dec, ".")
        try:
            lectures.add(round(float(s), 6))
        except ValueError:
            pass
    try:
        lectures.add(round(float(t.replace(",", ".")), 6))
    except ValueError:
        pass
    return lectures


def nombres_du_texte(texte):
    return [(m.group(0), _valeurs(m.group(0))) for m in _NOMBRE.finditer(texte)]


def nombres_autorises(entree):
    """Toute valeur numerique presente dans les donnees d'entree, y compris
    celles ecrites dans les messages des agents."""
    autorises = set()

    def parcourir(x):
        if isinstance(x, bool):
            return
        if isinstance(x, (int, float)):
            autorises.add(round(float(abs(x)), 6))
        elif isinstance(x, str):
            for _, v in nombres_du_texte(x):
                autorises.update(v)
        elif isinstance(x, dict):
            for k, v in x.items():
                parcourir(k)
                parcourir(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                parcourir(v)
    parcourir(entree)
    return autorises


def _sans_accents(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def controler(texte, entree):
    """-> None si le texte est acceptable, sinon le motif du rejet."""
    if not texte or not texte.strip():
        return "reponse vide"
    if "fraud" in _sans_accents(texte.lower()):
        return "emploi du mot 'fraude'"
    autorises = nombres_autorises(entree)
    inventes = [j for j, v in nombres_du_texte(texte) if not (v & autorises)]
    if inventes:
        return f"nombre(s) absent(s) des donnees : {', '.join(inventes[:5])}"
    return None


def journaliser_rejet(synthese, motif, texte):
    JOURNAL_REJETS.parent.mkdir(parents=True, exist_ok=True)
    with open(JOURNAL_REJETS, "a", encoding="utf-8") as f:
        f.write(json.dumps({"horodatage": datetime.now().isoformat(timespec="seconds"),
                            "numero_ddm": synthese.get("numero_ddm"), "modele": MODELE,
                            "motif": motif, "texte_rejete": (texte or "")[:1000]},
                           ensure_ascii=False) + "\n")


# ------------------------------------------------------------ appel au modele

def cle_api():
    return os.environ.get("ANTHROPIC_API_KEY") or None


def appeler_modele(entree):
    """-> (texte | None, motif d'echec | None). Une seule tentative, 5 s."""
    cle = cle_api()
    if not cle:
        return None, "pas de cle API"
    corps = {
        "model": MODELE,
        "max_tokens": 1024,
        # Tache courte : effort bas pour tenir dans le delai de 5 s.
        "output_config": {"effort": "low"},
        # Si le modele decline, le serveur relance sur un modele de repli.
        "fallbacks": "default",
        "system": CONSIGNE,
        "messages": [{"role": "user", "content":
                      "Donnees du dossier (JSON) :\n" + json.dumps(entree, ensure_ascii=False)}],
    }
    requete = urllib.request.Request(
        URL_API, data=json.dumps(corps).encode("utf-8"), method="POST",
        headers={"x-api-key": cle, "anthropic-version": "2023-06-01",
                 "anthropic-beta": "server-side-fallback-2026-07-01",
                 "content-type": "application/json"})
    try:
        with urllib.request.urlopen(requete, timeout=DELAI_S) as rep:
            reponse = json.loads(rep.read().decode("utf-8"))
    except Exception as e:          # reseau absent, delai depasse, erreur HTTP
        return None, f"appel impossible ({type(e).__name__})"
    if reponse.get("stop_reason") == "refusal":
        return None, "refus du modele"
    texte = "".join(b.get("text", "") for b in reponse.get("content", []) if b.get("type") == "text")
    return texte.strip(), None


# ------------------------------------------------------------ cache

def lire_cache():
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def ecrire_cache(cache):
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, CACHE)


# ------------------------------------------------------------ point d'entree

def rediger_explication(synthese, autoriser_reseau=False, cache=None):
    """-> (texte, source, detail). source vaut "llm" ou "deterministe".
    Le repli est l'explication deterministe deja calculee par le coordinateur.
    Aucune erreur n'est visible : tout echec retombe sur le repli."""
    repli = synthese["explication"]
    entree = donnees_entree(synthese)
    cle = cle_cache(synthese, entree)
    cache = lire_cache() if cache is None else cache

    if cle in cache:
        return cache[cle]["texte"], "llm", {"modele": cache[cle]["modele"], "cache": True}
    if not autoriser_reseau:
        return repli, "deterministe", {"motif": "hors cache, aucun appel reseau"}

    texte, echec = appeler_modele(entree)
    if echec:
        return repli, "deterministe", {"motif": echec}
    motif = controler(texte, entree)
    if motif:
        journaliser_rejet(synthese, motif, texte)
        return repli, "deterministe", {"motif": f"rejet : {motif}"}
    cache[cle] = {"texte": texte, "modele": MODELE,
                  "genere_le": datetime.now().isoformat(timespec="seconds")}
    return texte, "llm", {"modele": MODELE, "cache": False}
