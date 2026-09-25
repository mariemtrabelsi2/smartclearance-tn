"""Interface inspecteur : py -m streamlit run app.py

L'ecran montre des doutes motives, jamais un verdict : chaque alerte porte
ses chiffres et l'endroit ou les verifier, et c'est l'inspecteur qui tranche.
"""
import json
import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from agents.orchestrateur import analyser_dossier

RACINE = Path(__file__).resolve().parent
DOSSIERS = RACINE / "dossiers"
FEEDBACK = RACINE / "feedback.jsonl"

COULEUR_NIVEAU = {1: "#c62828", 2: "#ef6c00"}
LIBELLE_NIVEAU = {1: "Contradiction (niveau 1)", 2: "Écart à justifier (niveau 2)"}
COULEUR_RECO = {"LIBERATION": "#2e7d32", "CONTROLE_DOCUMENTAIRE": "#ef6c00",
                "CONTROLE_PHYSIQUE": "#c62828"}
LIBELLE_RECO = {"LIBERATION": "Libération", "CONTROLE_DOCUMENTAIRE": "Contrôle documentaire",
                "CONTROLE_PHYSIQUE": "Contrôle physique"}
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
    with open(FEEDBACK, "a", encoding="utf-8") as f:
        f.write(json.dumps(ligne, ensure_ascii=False) + "\n")


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

st.title("SmartClearance TN")
st.caption("Aide au contrôle du couloir orange — recoupement DDM / pièces jointes. "
           "L'outil formule des doutes motivés ; la décision appartient à l'inspecteur.")

mode = st.radio("Source", ["Dossier de test", "Déposer 4 fichiers"], horizontal=True)

if mode == "Dossier de test":
    noms = sorted(p.name for p in DOSSIERS.glob("dossier_*") if p.is_dir())
    choix = st.selectbox("Dossier", noms)
    if st.button("Analyser", type="primary"):
        st.session_state["synthese"] = analyser_dossier(DOSSIERS / choix)
        st.session_state["dossier"] = choix
else:
    depots = {nom: st.file_uploader(nom, type=[nom.split(".")[-1]], key=f"up_{nom}")
              for nom in PIECES}
    # Facultatif : une remise documentee que l'Agent 2 rapproche de l'ecart de prix.
    depots["justificatif.pdf"] = st.file_uploader("justificatif.pdf (facultatif)", type=["pdf"],
                                                  key="up_justificatif.pdf")
    # Facultatif : exige seulement pour un regime preferentiel, son absence n'est pas une anomalie.
    depots["certificat_origine.pdf"] = st.file_uploader("certificat_origine.pdf (facultatif)",
                                                        type=["pdf"], key="up_certificat_origine.pdf")
    manquants = [n for n in PIECES if depots[n] is None]
    if st.button("Analyser", type="primary", disabled=bool(manquants)):
        st.session_state["synthese"] = analyser_depot(depots)
        st.session_state["dossier"] = "depot_" + datetime.now().strftime("%H%M%S")
    if manquants:
        st.caption("Pièces manquantes : " + ", ".join(manquants))

s = st.session_state.get("synthese")
if not s:
    st.stop()
dossier = st.session_state["dossier"]

# ---------------- En-tete : score, recommandation, badge ----------------

st.divider()
c1, c2 = st.columns([1, 3])
with c1:
    st.markdown(f"<div style='font-size:4.5rem;font-weight:700;line-height:1'>{s['score']}"
                f"<span style='font-size:1.5rem;color:#888'>/100</span></div>",
                unsafe_allow_html=True)
    st.caption("Score de doute")
with c2:
    reco = s["recommandation"]
    st.markdown(f"<div style='display:inline-block;padding:.5rem 1.2rem;border-radius:.4rem;"
                f"background:{COULEUR_RECO[reco]};color:white;font-size:1.6rem;font-weight:600'>"
                f"{LIBELLE_RECO[reco]}</div>", unsafe_allow_html=True)
    ref = s.get("reference_prix")
    if ref:
        # Discret volontairement : c'est une information sur la qualite de la
        # reference, pas un constat sur le dossier.
        couleur = {"haute": "#2e7d32", "moyenne": "#ef6c00"}.get(ref["fiabilite"], "#757575")
        st.markdown(f"<span style='display:inline-block;margin-top:.6rem;padding:.15rem .6rem;"
                    f"border:1px solid {couleur};color:{couleur};border-radius:1rem;"
                    f"font-size:.8rem'>{ref['libelle']}</span>", unsafe_allow_html=True)
    st.write(s["explication"])
    vd = s.get("valeur_declaree")
    if vd and vd.get("usd"):
        st.markdown(f"**{vd['libelle']}**")
        # Le taux est dit fixe partout : un taux faux presente comme officiel
        # serait pire qu'un taux annonce comme illustration.
        st.caption(f"Montants en dinars : {vd['taux']} — {vd['source_taux']}.")

# ---------------- Alertes ----------------

st.subheader(f"Alertes ({len(s['alertes'])})")
if not s["alertes"]:
    st.success("Aucune incohérence relevée entre la déclaration et les pièces jointes.")

for i, a in enumerate(s["alertes"]):
    couleur = COULEUR_NIVEAU.get(a["niveau"], "#757575")
    st.markdown(
        f"<div style='border-left:6px solid {couleur};padding:.4rem .8rem;margin-top:1rem;"
        f"background:{couleur}14'><span style='color:{couleur};font-weight:700'>"
        f"{LIBELLE_NIVEAU.get(a['niveau'], '')} · {a['type']} · gravité {a['gravite']}</span>"
        f"<br>{a['message']}</div>", unsafe_allow_html=True)
    st.dataframe(tableau_preuve(a["preuve"]), hide_index=True, width="stretch")
    st.caption(f"Source : {a['source']}")

    cle = f"{dossier}_{i}_{a['type']}"
    b1, b2, _ = st.columns([1, 1, 3])
    if b1.button("Anomalie confirmée", key=f"conf_{cle}"):
        enregistrer_feedback(dossier, s, a, "anomalie_confirmee")
        st.toast("Enregistré : anomalie confirmée")
    if b2.button("Justification acceptée", key=f"just_{cle}"):
        enregistrer_feedback(dossier, s, a, "justification_acceptee")
        st.toast("Enregistré : justification acceptée")

# ---------------- Pieces a reclamer et champs non lus ----------------

if s["documents_a_reclamer"]:
    st.subheader("Pièces à réclamer à l'importateur")
    st.markdown("\n".join(f"- {d}" for d in s["documents_a_reclamer"]))

st.subheader("Champs non lus")
with st.container(border=True):
    if s["champs_non_lus"]:
        st.caption("Ces éléments n'ont pas pu être lus ou comparés : "
                   "aucun contrôle n'a été fait dessus, rien n'a été deviné.")
        st.markdown("\n".join(f"- `{n}`" for n in s["champs_non_lus"]))
    else:
        st.caption("Tous les champs attendus ont été lus.")

if s.get("normalisations"):
    # La declaration n'est jamais reecrite : on montre ce qui a ete lu et la
    # forme utilisee pour comparer, pour que l'inspecteur puisse contester.
    with st.expander(f"Normalisations appliquées pour comparer ({len(s['normalisations'])})"):
        st.caption("Valeurs brutes conservées telles quelles ; seule la forme normalisée sert aux comparaisons.")
        st.dataframe(pd.DataFrame(s["normalisations"]).astype(str), hide_index=True, width="stretch")
