"""Interface inspecteur : py -m streamlit run app.py

L'ecran montre des doutes motives, jamais un verdict : chaque alerte porte
ses chiffres et l'endroit ou les verifier, et c'est l'inspecteur qui tranche.
"""
import os

# Avant tout import de numpy (via pandas ou scikit-learn) : sinon OpenBLAS a deja
# reserve de la memoire par coeur, et sur un poste charge l'allocation echoue.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import json
import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from agents import libelles, stockage
from agents.devises import fr
from agents.orchestrateur import analyser_dossier

RACINE = Path(__file__).resolve().parent
DOSSIERS = RACINE / "dossiers"

COULEUR_NIVEAU = {1: "#c62828", 2: "#ef6c00"}
LIBELLE_NIVEAU = {1: "Contradiction (niveau 1)", 2: "Écart à justifier (niveau 2)"}
COULEUR_RECO = {"LIBERATION": "#2e7d32", "CONTROLE_DOCUMENTAIRE": "#ef6c00",
                "CONTROLE_PHYSIQUE": "#c62828"}
LIBELLE_RECO = libelles.LIBELLES_RECO      # memes libelles que l'explication
PIECES = ["ddm.json", "facture.pdf", "colisage.pdf", "transport.pdf"]

st.set_page_config(page_title="SmartClearance TN", layout="wide")


def enregistrer_feedback(dossier, synthese, alerte, decision):
    """Boucle d'apprentissage : on garde chaque arbitrage de l'inspecteur pour
    recalibrer seuils et gravites plus tard, meme si rien n'est reentraine ici."""
    ligne = {
        "horodatage": datetime.now().isoformat(timespec="seconds"),
        "dossier": dossier,
        "numero_ddm": synthese.get("numero_ddm"),
        "type_alerte": alerte["type"],
        "niveau": alerte["niveau"],
        "gravite": alerte["gravite"],
        "preuve": alerte["preuve"],
        "score_global": synthese["score"],
        "recommandation": synthese["recommandation"],
        "decision_inspecteur": decision,
    }
    stockage.enregistrer_feedback(ligne)


def tableau_preuve(preuve):
    """Une seule ligne, une colonne par valeur : les chiffres compares se
    lisent cote a cote, sans avoir a remonter dans le message."""
    ligne = {k: (", ".join(map(str, v)) if isinstance(v, list)
                 else json.dumps(v, ensure_ascii=False) if isinstance(v, dict)
                 else "—" if v is None else v)
             for k, v in preuve.items()}
    return pd.DataFrame([ligne]).astype(str)


def analyser_depot(fichiers):
    """Les 4 pieces deposees sont recopiees sous leur nom attendu dans un
    dossier temporaire : la chaine d'analyse reste strictement la meme."""
    tmp = Path(tempfile.mkdtemp(prefix="smartclearance_"))
    for nom, f in fichiers.items():
        if f is not None:
            (tmp / nom).write_bytes(f.getvalue())
    return analyser_dossier(tmp)


# ---------------- Choix du dossier ----------------

# Corps de texte a 16 px minimum (lisibilite a l'ecran d'un poste d'inspection) ;
# notes et tableaux replies restent plus petits.
st.markdown("""<style>
[data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li { font-size: 16px; line-height: 1.55; }
[data-testid="stCaptionContainer"] p { font-size: 14px; }
</style>""", unsafe_allow_html=True)

st.title("SmartClearance TN")
st.caption("Aide au contrôle du couloir orange — recoupement DDM / pièces jointes. "
           "L'outil formule des doutes motivés ; la décision appartient à l'inspecteur.")

mode = st.radio("Source", ["Dossier de test", "Déposer les pièces du dossier"], horizontal=True)

if mode == "Dossier de test":
    noms = sorted(p.name for p in DOSSIERS.glob("dossier_*") if p.is_dir())
    # Affichage "Dossier 4" ; la valeur choisie reste le nom de repertoire.
    choix = st.selectbox("Dossier", noms, format_func=lambda n: f"Dossier {int(n.split('_')[1])}")
    if st.button("Analyser", type="primary"):
        st.session_state["synthese"] = analyser_dossier(DOSSIERS / choix)
        st.session_state["dossier"] = choix
else:
    depots = {nom: st.file_uploader(libelles.piece_depot(nom), type=[nom.split(".")[-1]],
                                    key=f"up_{nom}")
              for nom in PIECES}
    # Facultatif : une remise documentee que l'Agent 2 rapproche de l'ecart de prix.
    depots["justificatif.pdf"] = st.file_uploader(libelles.piece_depot("justificatif.pdf"),
                                                  type=["pdf"], key="up_justificatif.pdf")
    # Facultatif : exige seulement pour un regime preferentiel, son absence n'est pas une anomalie.
    depots["certificat_origine.pdf"] = st.file_uploader(libelles.piece_depot("certificat_origine.pdf"),
                                                        type=["pdf"], key="up_certificat_origine.pdf")
    manquants = [n for n in PIECES if depots[n] is None]
    if st.button("Analyser", type="primary", disabled=bool(manquants)):
        st.session_state["synthese"] = analyser_depot(depots)
        st.session_state["dossier"] = "depot_" + datetime.now().strftime("%H%M%S")
    if manquants:
        st.caption("Pièces manquantes : " + ", ".join(libelles.piece_depot(n) for n in manquants))

s = st.session_state.get("synthese")
if not s:
    st.stop()
dossier = st.session_state["dossier"]

# ---------------- En-tete : score, recommandation, badge ----------------

st.divider()

# Bandeau de decision : la seule chose qu'il faut voir sans defiler.
BANDEAU = {"LIBERATION": ("LIBÉRATION", "#1e7b34"),
           "CONTROLE_DOCUMENTAIRE": ("CONTRÔLE DOCUMENTAIRE RECOMMANDÉ", "#b35400"),
           "CONTROLE_PHYSIQUE": ("CONTRÔLE PHYSIQUE RECOMMANDÉ", "#8e1b1b")}
texte_bandeau, fond_bandeau = BANDEAU.get(s["recommandation"], (s["recommandation"], "#555"))
nb = len(s["alertes"])
signaux = "aucun signal relevé" if nb == 0 else ("1 signal relevé" if nb == 1 else f"{nb} signaux relevés")
st.markdown(
    f"<div style='background:{fond_bandeau};color:#fff;padding:1.1rem 1.4rem;border-radius:.5rem;"
    f"font-size:36px;font-weight:800;letter-spacing:.02em;line-height:1.15'>{texte_bandeau}</div>"
    f"<div style='margin:.6rem 0 1.2rem;font-size:18px'>Score de doute {s['score']}/100 — {signaux}</div>",
    unsafe_allow_html=True)

def chiffre(col, valeur, libelle, complement=""):
    """Gros chiffre, petit libelle en dessous."""
    col.markdown(
        f"<div style='font-size:40px;font-weight:800;line-height:1.1'>{valeur}"
        f"<span style='font-size:18px;font-weight:600;opacity:.7'>{complement}</span></div>"
        f"<div style='font-size:14px;opacity:.75;margin-top:.2rem'>{libelle}</div>",
        unsafe_allow_html=True)


vd = s.get("valeur_declaree") or {}
k1, k2, k3 = st.columns(3)
chiffre(k1, s["score"], "Score de doute", "/100")
chiffre(k2, nb, "Nombre de signaux")
chiffre(k3, f"{fr(vd['tnd'])} TND" if vd.get("tnd") else "—", "Valeur déclarée",
        f" ({fr(vd['usd'])} USD)" if vd.get("usd") else "")
st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)

# ---------------- Alertes ----------------

st.subheader(f"Signaux relevés ({len(s['alertes'])})")
if not s["alertes"]:
    st.success("Aucune incohérence relevée entre la déclaration et les pièces jointes.")

# Affichage seulement : niveau 1 d'abord, puis niveau 2, chacun par gravite
# decroissante. La synthese et le score ne sont pas touches.
alertes_affichees = sorted(s["alertes"], key=lambda a: (a["niveau"], -a["gravite"]))
for i, a in enumerate(alertes_affichees):
    couleur = COULEUR_NIVEAU.get(a["niveau"], "#757575")
    st.markdown(
        f"<div style='border-left:8px solid {couleur};background:{couleur}1f;border-radius:.4rem;"
        f"padding:.8rem 1rem;margin-top:1.1rem'>"
        f"<div style='font-size:18px;font-weight:700'>{libelles.alerte(a['type'])}</div>"
        f"<div style='font-size:13px;color:{couleur};font-weight:600;margin:.15rem 0 .5rem'>"
        f"{LIBELLE_NIVEAU.get(a['niveau'], '')} · gravité {a['gravite']}</div>"
        f"<div style='font-size:16px;line-height:1.5'>{a['message']}</div></div>",
        unsafe_allow_html=True)
    # Un systeme qui se modifie sans le dire serait refuse : l'ajustement appris
    # reste visible, hors du depliant, avec ce qui le fonde.
    if "ajustement_apprentissage" in a["preuve"]:
        p = a["preuve"]
        st.info(f"Gravité ajustée par les retours des inspecteurs : x{fr(p['ajustement_apprentissage'])} "
                f"({p['gravite_avant_ajustement']} → {a['gravite']}), fondé sur {p['fonde_sur']}, "
                f"calculé le {p['calcule_le']}.")
    with st.expander("Détail du calcul", expanded=False):
        st.dataframe(tableau_preuve(a["preuve"]), hide_index=True, width="stretch")
        st.caption(f"Source : {a['source']}")
        if "retours_inspecteurs" in a["preuve"]:
            st.caption(f"Retours des inspecteurs sur ce motif : {a['preuve']['retours_inspecteurs']}.")

    cle = f"{dossier}_{i}_{a['type']}"
    b1, b2, _ = st.columns([1, 1, 3])
    if b1.button("Anomalie confirmée", key=f"conf_{cle}"):
        enregistrer_feedback(dossier, s, a, "anomalie_confirmee")
        st.toast("Enregistré : anomalie confirmée")
    if b2.button("Justification acceptée", key=f"just_{cle}"):
        enregistrer_feedback(dossier, s, a, "justification_acceptee")
        st.toast("Enregistré : justification acceptée")

# ---------------- Explication et pieces a reclamer (visibles) ----------------

st.subheader("Explication")
st.write(s["explication"])
# Discret : l'inspecteur doit savoir si le texte vient d'un modele de langage.
# Dans les deux cas, score, recommandation et alertes sont calcules sans LLM.
if s.get("source_explication") == "llm":
    # Nom technique du modele en repli discret (infobulle), pas dans la phrase.
    st.caption("Explication générée par un modèle de langage externe à partir des alertes ; "
               "score et recommandation calculés sans modèle de langage.",
               help=f"Modèle : {s['detail_explication'].get('modele')}")
else:
    st.caption("Explication rédigée automatiquement.")

if s["documents_a_reclamer"]:
    st.subheader("Pièces à réclamer à l'importateur")
    st.markdown("\n".join(f"- {d}" for d in s["documents_a_reclamer"]))

# ---------------- Tout le reste : depliants fermes ----------------

st.markdown("<div style='height:.8rem'></div>", unsafe_allow_html=True)
with st.expander("Contexte du dossier", expanded=False):
    m = s.get("marchandise") or {}
    if m.get("designation"):
        specs = ", ".join(f"{k} {v}" for k, v in (m.get("specifications") or {}).items())
        mentions = m.get("qualite_degradante", []) + m.get("qualite_valorisante", [])
        st.markdown(f"**Marchandise : {m['designation']}**"
                    + (f" — spécifications : {specs}" if specs else "")
                    + (f" — qualité annoncée : {', '.join(mentions)}" if mentions else ""))
    sh = s.get("code_sh") or {}
    if sh.get("code_sh"):
        st.markdown(f"**Code SH déclaré : {sh['code_sh']}** — {sh.get('designation_DDM') or ''}")
        st.caption("Nomenclature SH 2022 (libellé officiel, en anglais) : "
                   + (sh.get("designation_officielle") or "code absent de la nomenclature"))
    ref = s.get("reference_prix")
    if ref:
        couleur = {"haute": "#2e7d32", "moyenne": "#ef6c00"}.get(ref["fiabilite"], "#757575")
        st.markdown(f"<span style='display:inline-block;padding:.15rem .6rem;"
                    f"border:1px solid {couleur};color:{couleur};border-radius:1rem;"
                    f"font-size:.85rem'>{ref['libelle']}</span>", unsafe_allow_html=True)
    if vd.get("usd"):
        st.markdown(f"**{vd['libelle']}**")
        # Le taux est dit fixe partout : un taux faux presente comme officiel
        # serait pire qu'un taux annonce comme illustration.
        st.caption(f"Montants en dinars : {vd['taux']} — {vd['source_taux']}.")

with st.expander(f"Champs non lus ({len(s['champs_non_lus'])})", expanded=False):
    if s["champs_non_lus"]:
        st.caption("Ces éléments n'ont pas pu être lus ou comparés : "
                   "aucun contrôle n'a été fait dessus, rien n'a été deviné.")
        # Du texte, pas du code : marqueurs internes traduits en francais.
        st.markdown("\n".join(f"- {libelles.non_lu(n)}" for n in s["champs_non_lus"]))
    else:
        st.caption("Tous les champs attendus ont été lus.")

if s.get("normalisations"):
    # La declaration n'est jamais reecrite : on montre ce qui a ete lu et la
    # forme utilisee pour comparer, pour que l'inspecteur puisse contester.
    with st.expander(f"Normalisations appliquées pour comparer ({len(s['normalisations'])})",
                     expanded=False):
        st.caption("Valeurs brutes conservées telles quelles ; seule la forme normalisée sert aux comparaisons.")
        st.dataframe(pd.DataFrame(s["normalisations"]).astype(str), hide_index=True, width="stretch")

if s.get("controles"):
    # Qui a tourne, et pourquoi : la politique de routage est une table de
    # regles (orchestrateur.POLITIQUE), jamais un modele.
    with st.expander("Contrôles exécutés", expanded=False):
        st.caption("Un contrôle à coût faible est toujours exécuté ; un contrôle à coût élevé "
                   "ne l'est que si sa condition est remplie.")
        st.dataframe(pd.DataFrame([{"Agent": c["agent"],
                                    "Coût": {"faible": "faible", "eleve": "élevé"}.get(c["cout"], c["cout"]),
                                    "Exécuté": "oui" if c["execute"] else "non",
                                    "Motif": c["motif"]} for c in s["controles"]]),
                     hide_index=True, width="stretch")
