import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from matplotlib.colors import LinearSegmentedColormap
import io

# Configuration de la page web
st.set_page_config(page_title="Dashboard Communauté d'Énergie", page_icon="⚡", layout="wide")
sns.set_theme(style="whitegrid")

st.title("⚡ Audit & Stratégie : Réalité vs Simulation")

# ==========================================
# 1. SWITCH MENSUEL / ANNUEL
# ==========================================
st.markdown("### Choix de l'Analyse")
mode_analyse = st.radio(
    "Quel type de rapport souhaitez-vous générer ?", 
    ["📅 Mensuel (Contrôle de facture)", "📆 Annuel (Saisonnalité & Bilan)"], 
    horizontal=True
)
st.divider()

# ==========================================
# 2. BARRE LATÉRALE : UPLOADS & PARAMÈTRES
# ==========================================
st.sidebar.header("📁 1. Import des fichiers")
fichier_contacts = st.sidebar.file_uploader("1. Contacts Odoo (Excel/CSV)", type=['xlsx', 'csv'])

if "Mensuel" in mode_analyse:
    fichier_factures = st.sidebar.file_uploader("2. Fichier Sibelga (Excel)", type=['xlsx'], accept_multiple_files=False)
else:
    fichier_factures = st.sidebar.file_uploader("2. Fichiers Sibelga (Glissez les 12 mois)", type=['xlsx'], accept_multiple_files=True)

fichier_mapping = st.sidebar.file_uploader("3. Fichier de Mapping (Excel)", type=['xlsx'])
fichier_simu = st.sidebar.file_uploader("4. Simulation Streamlit (CSV)", type=['csv'])

# ==========================================
# 3. VERIFICATION DES COLONNES (Aperçu)
# ==========================================
col_ean_sel, col_vol_part_sel, col_vol_comp_sel, col_inj_part_sel, col_inj_comp_sel, col_date_sel = None, None, None, None, None, None
mois_detecte = None

# On isole le premier fichier pour éviter le plantage
first_facture = None
if fichier_factures:
    first_facture = fichier_factures[0] if isinstance(fichier_factures, list) else fichier_factures

if first_facture:
    st.sidebar.header("🔧 2. Vérification des colonnes")
    st.sidebar.markdown("*Aperçu de la détection sur le 1er fichier.*")
    
    first_facture.seek(0)
    df_cols = pd.read_excel(first_facture, nrows=0)
    first_facture.seek(0)
    colonnes_sibelga = df_cols.columns.tolist()
    options_colonnes = ["--- À sélectionner ---"] + colonnes_sibelga
    
    def trouver_colonne_index(options_mots_cles, mots_exclus):
        for mots_cles in options_mots_cles:
            for c in colonnes_sibelga:
                c_norm = str(c).lower().replace('é', 'e').replace('è', 'e')
                if all(m in c_norm for m in mots_cles) and not any(ex in c_norm for ex in mots_exclus):
                    return options_colonnes.index(c)
        return 0

    idx_date = trouver_colonne_index([['fromdate'], ['date', 'debut'], ['from', 'date'], ['periode', 'debut']], ['fin', 'to', 'todate'])
    idx_ean = trouver_colonne_index([['ean']], [])
    idx_vol_part = trouver_colonne_index([['partage', 'kwh'], ['partage', 'volume'], ['partage', 'consomm']], ['injection', 'production', 'taux', 'statut', 'type', 'cle'])
    idx_vol_comp = trouver_colonne_index([['complementaire', 'kwh'], ['residuel', 'consomm'], ['complementaire', 'volume'], ['residuel', 'volume'], ['reseau', 'consomm'], ['reseau', 'kwh']], ['injection', 'production', 'taux', 'statut', 'partage'])
    idx_inj_part = trouver_colonne_index([['partage', 'injection'], ['partage', 'production']], ['taux', 'statut'])
    idx_inj_comp = trouver_colonne_index([['residuel', 'injection'], ['complementaire', 'injection'], ['reseau', 'injection'], ['reseau', 'kwh']], ['taux', 'statut', 'partage', 'consommation', 'consomm'])

    col_date_sel = st.sidebar.selectbox("Colonne Date", options_colonnes, index=idx_date)
    col_ean_sel = st.sidebar.selectbox("Colonne EAN", options_colonnes, index=idx_ean)
    col_vol_part_sel = st.sidebar.selectbox("Consommation Partagée", options_colonnes, index=idx_vol_part)
    col_vol_comp_sel = st.sidebar.selectbox("Conso Résiduelle/Réseau", options_colonnes, index=idx_vol_comp)
    col_inj_part_sel = st.sidebar.selectbox("Injection Partagée", options_colonnes, index=idx_inj_part)
    col_inj_comp_sel = st.sidebar.selectbox("Injection Résiduelle", options_colonnes, index=idx_inj_comp)

    if "Mensuel" in mode_analyse and col_date_sel != "--- À sélectionner ---":
        try:
            first_facture.seek(0)
            df_dates = pd.read_excel(first_facture, nrows=5)
            first_facture.seek(0)
            premiere_date = df_dates[col_date_sel].dropna().iloc[0]
            mois_detecte = pd.to_datetime(premiere_date).month
        except:
            pass

if "Mensuel" in mode_analyse:
    st.sidebar.header("📅 3. Paramètres")
    index_defaut_mois = (mois_detecte - 1) if mois_detecte else 1
    mois_cible = st.sidebar.selectbox("Mois à analyser", range(1, 13), index=index_defaut_mois, format_func=lambda x: ['Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin', 'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre'][x-1])


# ==========================================
# 4. MOTEUR D'ANALYSE PRINCIPAL
# ==========================================
if fichier_contacts and fichier_factures and fichier_mapping and fichier_simu:
    
    # Fix du syndrome du bouton
    if st.button("🚀 Lancer le calcul", type="primary", use_container_width=True):
        st.session_state['calcul_lance'] = True
        
    if st.session_state.get('calcul_lance', False):
        
        if "--- À sélectionner ---" in [col_ean_sel, col_vol_part_sel, col_vol_comp_sel, col_inj_part_sel, col_inj_comp_sel, col_date_sel]:
            st.error("❌ Oups ! Certaines colonnes Sibelga n'ont pas pu être trouvées. Veuillez les sélectionner manuellement dans la barre latérale.")
            st.stop()
            
        with st.spinner("Analyse et fusion des bases de données en cours..."):
            try:
                # ---------------------------------------------------------
                # MAPPING BIDIRECTIONNEL (Commun)
                # ---------------------------------------------------------
                df_mapping = pd.read_excel(fichier_mapping)
                df_mapping['Nom_Streamlit'] = df_mapping['Nom_Streamlit'].astype(str).str.split(',')
                df_mapping = df_mapping.explode('Nom_Streamlit')
                df_mapping['Nom_Reel'] = df_mapping['Nom_Reel'].astype(str).str.split(',')
                df_mapping = df_mapping.explode('Nom_Reel')
                df_mapping['Nom_Streamlit'] = df_mapping['Nom_Streamlit'].str.strip()
                df_mapping['Nom_Reel'] = df_mapping['Nom_Reel'].str.strip()
                count_sim = df_mapping.groupby('Nom_Streamlit')['Nom_Reel'].transform('nunique')
                df_mapping['Super_Groupe'] = np.where(count_sim > 1, df_mapping['Nom_Streamlit'], df_mapping['Nom_Reel'])
                mapping_sim = dict(zip(df_mapping['Nom_Streamlit'], df_mapping['Super_Groupe']))
                mapping_reel = dict(zip(df_mapping['Nom_Reel'], df_mapping['Super_Groupe']))

                # CONTACTS ODOO (Commun)
                df_contacts = pd.read_excel(fichier_contacts, dtype=str)
                est_un_titre = df_contacts['Ean'].isna() & df_contacts['Nom'].astype(str).str.contains(r'\(\d+\)$')
                df_contacts['Groupe_Odoo'] = np.where(est_un_titre, df_contacts['Nom'].astype(str).str.replace(r' \(\d+\)$', '', regex=True).str.strip(), np.nan)
                df_contacts['Groupe_Odoo'] = df_contacts['Groupe_Odoo'].ffill()
                df_contacts = df_contacts.dropna(subset=['Ean']).copy() 
                df_contacts['Ean'] = df_contacts['Ean'].astype(str).str.replace(' ', '').str.replace(r'\.0$', '', regex=True).str.strip()
                df_contacts = df_contacts.drop_duplicates(subset=['Ean'], keep='first')
                
                noms_mois = {1:'Jan', 2:'Fév', 3:'Mar', 4:'Avr', 5:'Mai', 6:'Juin', 7:'Juil', 8:'Août', 9:'Sep', 10:'Oct', 11:'Nov', 12:'Déc'}

                
                # =================================================================================================
                # 🟢🟢🟢 MODE MENSUEL 
                # =================================================================================================
                if "Mensuel" in mode_analyse:
                    
                    first_facture.seek(0)
                    df_reels = pd.read_excel(first_facture, dtype=str)
                    colonnes_locales = df_reels.columns.tolist()
                    def trouver_col_locale(options_mots_cles, mots_exclus):
                        for mots_cles in options_mots_cles:
                            for c in colonnes_locales:
                                c_norm = str(c).lower().replace('é', 'e').replace('è', 'e')
                                if all(m in c_norm for m in mots_cles) and not any(ex in c_norm for ex in mots_exclus):
                                    return c
                        return None

                    c_ean = trouver_col_locale([['ean']], [])
                    c_vol_part = trouver_col_locale([['partage', 'kwh'], ['partage', 'volume'], ['partage', 'consomm']], ['injection', 'production', 'taux', 'statut', 'type', 'cle'])
                    c_vol_comp = trouver_col_locale([['complementaire', 'kwh'], ['residuel', 'consomm'], ['complementaire', 'volume'], ['residuel', 'volume'], ['reseau', 'consomm'], ['reseau', 'kwh']], ['injection', 'production', 'taux', 'statut', 'partage'])
                    c_inj_part = trouver_col_locale([['partage', 'injection'], ['partage', 'production']], ['taux', 'statut'])
                    c_inj_comp = trouver_col_locale([['residuel', 'injection'], ['complementaire', 'injection'], ['reseau', 'injection'], ['reseau', 'kwh']], ['taux', 'statut', 'partage', 'consommation', 'consomm'])

                    df_reels[c_ean] = df_reels[c_ean].astype(str).str.replace(' ', '').str.replace(r'\.0$', '', regex=True).str.strip()
                    colonnes_vol = [c_vol_part, c_vol_comp, c_inj_part, c_inj_comp]
                    for col in colonnes_vol:
                        if df_reels[col].dtype == object:
                            df_reels[col] = df_reels[col].astype(str).str.replace(',', '.')
                        df_reels[col] = pd.to_numeric(df_reels[col], errors='coerce').fillna(0)
                        
                    df_reels_agg = df_reels.groupby(c_ean)[colonnes_vol].sum().reset_index()
                    df_reels_agg = df_reels_agg.rename(columns={c_ean: 'EAN', c_vol_part: 'Volume Partagé (kWh)', c_vol_comp: 'Volume Complémentaire (kWh)', c_inj_part: 'Injection Partagée (kWh)', c_inj_comp: 'Injection Résiduelle (kWh)'})
                    
                    df_reels_c = pd.merge(df_reels_agg, df_contacts[['Ean', 'Groupe_Odoo', 'Nom']], left_on='EAN', right_on='Ean', how='left')
                    df_reels_c['Proprietaire_Odoo'] = df_reels_c['Groupe_Odoo'].fillna(df_reels_c['Nom']).fillna("Inconnu")
                    df_reels_c['Proprietaire'] = df_reels_c['Proprietaire_Odoo'].map(mapping_reel).fillna(df_reels_c['Proprietaire_Odoo'])
                    
                    df_reels_c['Reel_Conso_Partagee_MWh'] = df_reels_c['Volume Partagé (kWh)'] / 1000.0
                    df_reels_c['Reel_Conso_Totale_MWh'] = (df_reels_c['Volume Partagé (kWh)'] + df_reels_c['Volume Complémentaire (kWh)']) / 1000.0
                    df_reels_c['Reel_Prod_Partagee_MWh'] = df_reels_c['Injection Partagée (kWh)'] / 1000.0
                    df_reels_c['Reel_Prod_Totale_MWh'] = (df_reels_c['Injection Partagée (kWh)'] + df_reels_c['Injection Résiduelle (kWh)']) / 1000.0
                    df_reels_final = df_reels_c.groupby('Proprietaire')[['Reel_Conso_Partagee_MWh', 'Reel_Conso_Totale_MWh', 'Reel_Prod_Partagee_MWh', 'Reel_Prod_Totale_MWh']].sum().reset_index()

                    df_sim_p = pd.read_csv(fichier_simu)
                    dates = pd.to_datetime(df_sim_p['Unnamed: 0'])
                    df_sim_p_filtre = df_sim_p[dates.dt.month == mois_cible]
                    sommes_simu = df_sim_p_filtre.sum(numeric_only=True)
                    
                    participants_bruts = set(col.split('_')[0] for col in df_sim_p.columns if col != 'Unnamed: 0')
                    mots_techniques = {'external', 'grid', 'injection', 'internal', 'remaining', 'residual', 'shared', 'community', 'n'}
                    participants_simu = {p.strip() for p in participants_bruts if p.strip().lower() not in mots_techniques}
                    
                    donnees_simu = []
                    for p in participants_simu:
                        donnees_simu.append({
                            'Nom_Streamlit': p,
                            'Sim_Conso_Partagee_MWh': sommes_simu.get(f"{p}_shared_volume_from_community", 0) / 4000.0,
                            'Sim_Conso_Totale_MWh': sommes_simu.get(f"{p}_residual_consumption_bc", 0) / 4000.0,
                            'Sim_Prod_Partagee_MWh': abs(sommes_simu.get(f"{p}_shared_volume_to_community", 0)) / 4000.0,
                            'Sim_Prod_Totale_MWh': abs(sommes_simu.get(f"{p}_injection_bc", 0)) / 4000.0
                        })
                    df_sim_agg = pd.DataFrame(donnees_simu)
                    df_sim_agg['Proprietaire'] = df_sim_agg['Nom_Streamlit'].map(mapping_sim).fillna(df_sim_agg['Nom_Streamlit'])
                    df_sim_final = df_sim_agg.groupby('Proprietaire')[['Sim_Conso_Partagee_MWh', 'Sim_Conso_Totale_MWh', 'Sim_Prod_Partagee_MWh', 'Sim_Prod_Totale_MWh']].sum().reset_index()

                    df_comparatif = pd.merge(df_reels_final, df_sim_final, on='Proprietaire', how='outer', indicator=True)
                    df_comparatif = df_comparatif[~df_comparatif['Proprietaire'].astype(str).isin(['', '0', 'nan', 'NaN', 'Inconnu', 'Indéfini'])]

                    st.subheader("🚨 Alertes d'Audit")
                    eans_inconnus = df_reels_c[df_reels_c['Proprietaire_Odoo'] == 'Inconnu']['EAN'].unique()
                    if len(eans_inconnus) > 0: st.error(f"**ALERTE ODOO (EAN facturés mais inconnus dans contacts) :** {', '.join(eans_inconnus)}")
                    simu_sans_mapping = participants_simu - set(mapping_sim.keys())
                    if len(simu_sans_mapping) > 0: st.warning(f"**ALERTE MAPPING (Membres Streamlit non traduits) :** {', '.join(simu_sans_mapping)}")
                    reel_sans_simu = df_comparatif[df_comparatif['_merge'] == 'left_only']['Proprietaire'].tolist()
                    simu_sans_reel = df_comparatif[df_comparatif['_merge'] == 'right_only']['Proprietaire'].tolist()
                    if reel_sans_simu: st.warning(f"**Facturés mais NON simulés :** {', '.join(reel_sans_simu)}")
                    if simu_sans_reel: st.warning(f"**Simulés mais SANS facture ce mois-ci :** {', '.join(simu_sans_reel)} *(Exclus des graphiques)*")
                    if len(eans_inconnus) == 0 and len(simu_sans_mapping) == 0 and not reel_sans_simu and not simu_sans_reel:
                        st.success("✅ Aucun problème détecté. Les bases de données sont parfaitement alignées !")

                    df_comparatif = df_comparatif.drop(columns=['_merge']).fillna(0)
                    df_comparatif = df_comparatif[(df_comparatif['Reel_Conso_Totale_MWh'] > 0) | (df_comparatif['Sim_Conso_Totale_MWh'] > 0) | (df_comparatif['Reel_Prod_Totale_MWh'] > 0) | (df_comparatif['Sim_Prod_Totale_MWh'] > 0)]
                    
                    df_comparatif['Erreur_Conso_MWh'] = df_comparatif['Sim_Conso_Totale_MWh'] - df_comparatif['Reel_Conso_Totale_MWh']
                    df_comparatif['Erreur_Prod_MWh'] = df_comparatif['Sim_Prod_Totale_MWh'] - df_comparatif['Reel_Prod_Totale_MWh']
                    df_comparatif['Erreur_Partage_MWh'] = df_comparatif['Sim_Conso_Partagee_MWh'] - df_comparatif['Reel_Conso_Partagee_MWh']
                    df_comparatif['Abs_Erreur_Conso'] = df_comparatif['Erreur_Conso_MWh'].abs()
                    df_comparatif['Abs_Erreur_Prod'] = df_comparatif['Erreur_Prod_MWh'].abs()
                    df_comparatif['Erreur_Conso_%'] = np.where(df_comparatif['Reel_Conso_Totale_MWh'] > 0, (df_comparatif['Erreur_Conso_MWh'] / df_comparatif['Reel_Conso_Totale_MWh']) * 100, np.where(df_comparatif['Sim_Conso_Totale_MWh'] > 0, 100.0, 0.0))
                    df_comparatif['Erreur_Prod_%'] = np.where(df_comparatif['Reel_Prod_Totale_MWh'] > 0, (df_comparatif['Erreur_Prod_MWh'] / df_comparatif['Reel_Prod_Totale_MWh']) * 100, np.where(df_comparatif['Sim_Prod_Totale_MWh'] > 0, 100.0, 0.0))
                    df_comparatif['Abs_Erreur_Conso_%'] = df_comparatif['Erreur_Conso_%'].abs()
                    df_comparatif['Abs_Erreur_Prod_%'] = df_comparatif['Erreur_Prod_%'].abs()
                    df_comparatif = df_comparatif.round(3)

                    df_analyse = df_comparatif[~df_comparatif['Proprietaire'].isin(simu_sans_reel)].copy()

                    # --- GRAPHIQUES MENSUELS ---
                    st.divider()
                    st.subheader("🌍 Analyse Mensuelle Globale")
                    col_m1, col_m2, col_m3 = st.columns(3)
                    tot_r_conso = df_analyse['Reel_Conso_Totale_MWh'].sum()
                    pct_conso = ((df_analyse['Sim_Conso_Totale_MWh'].sum() - tot_r_conso) / tot_r_conso * 100) if tot_r_conso > 0 else 0
                    tot_r_prod = df_analyse['Reel_Prod_Totale_MWh'].sum()
                    pct_prod = ((df_analyse['Sim_Prod_Totale_MWh'].sum() - tot_r_prod) / tot_r_prod * 100) if tot_r_prod > 0 else 0
                    tot_r_ech = df_analyse['Reel_Conso_Partagee_MWh'].sum()
                    pct_ech = ((df_analyse['Sim_Conso_Partagee_MWh'].sum() - tot_r_ech) / tot_r_ech * 100) if tot_r_ech > 0 else 0
                    col_m1.metric("⚡ Total Consommé", f"{tot_r_conso:.2f}", f"{pct_conso:+.1f}% d'erreur", delta_color="off")
                    col_m2.metric("☀️ Total Produit", f"{tot_r_prod:.2f}", f"{pct_prod:+.1f}% d'erreur", delta_color="off")
                    col_m3.metric("🤝 Total Échangé", f"{tot_r_ech:.2f}", f"{pct_ech:+.1f}% d'erreur", delta_color="off")
                    st.divider()

                    st.subheader("📉 Pire dimensionnement (MWh)")
                    col1, col2 = st.columns(2)
                    top10_c = df_analyse.sort_values(by='Abs_Erreur_Conso', ascending=False).head(10)
                    fig1, ax1 = plt.subplots(figsize=(8, 5))
                    sns.barplot(data=top10_c, x='Erreur_Conso_MWh', y='Proprietaire', palette=['#e74c3c' if v>0 else '#3498db' for v in top10_c['Erreur_Conso_MWh']], ax=ax1)
                    ax1.set_title('CONSOMMATION'); ax1.axvline(0, color='black'); ax1.set_ylabel(''); col1.pyplot(fig1)

                    top10_p = df_analyse.sort_values(by='Abs_Erreur_Prod', ascending=False).head(10)
                    top10_p = top10_p[top10_p['Abs_Erreur_Prod'] > 0]
                    if not top10_p.empty:
                        fig2, ax2 = plt.subplots(figsize=(8, 5))
                        sns.barplot(data=top10_p, x='Erreur_Prod_MWh', y='Proprietaire', palette=['#e74c3c' if v>0 else '#3498db' for v in top10_p['Erreur_Prod_MWh']], ax=ax2)
                        ax2.set_title('PRODUCTION'); ax2.axvline(0, color='black'); ax2.set_ylabel(''); col2.pyplot(fig2)
                    st.divider()

                    st.subheader("📉 Pire dimensionnement (%)")
                    col3, col4 = st.columns(2)
                    top10_cp = df_analyse.sort_values(by='Abs_Erreur_Conso_%', ascending=False).head(10)
                    if not top10_cp.empty:
                        fig3, ax3 = plt.subplots(figsize=(8, 5))
                        sns.barplot(data=top10_cp, x='Erreur_Conso_%', y='Proprietaire', palette=['#e74c3c' if v>0 else '#3498db' for v in top10_cp['Erreur_Conso_%']], ax=ax3)
                        ax3.set_title('CONSOMMATION (%)'); ax3.axvline(0, color='black'); ax3.set_ylabel(''); col3.pyplot(fig3)

                    top10_pp = df_analyse.sort_values(by='Abs_Erreur_Prod_%', ascending=False).head(10)
                    top10_pp = top10_pp[top10_pp['Abs_Erreur_Prod_%'] > 0]
                    if not top10_pp.empty:
                        fig4, ax4 = plt.subplots(figsize=(8, 5))
                        sns.barplot(data=top10_pp, x='Erreur_Prod_%', y='Proprietaire', palette=['#e74c3c' if v>0 else '#3498db' for v in top10_pp['Erreur_Prod_%']], ax=ax4)
                        ax4.set_title('PRODUCTION (%)'); ax4.axvline(0, color='black'); ax4.set_ylabel(''); col4.pyplot(fig4)
                    st.divider()

                    st.subheader("📊 Vue globale : Réalité vs Simulation")
                    fig_nuage, axes = plt.subplots(2, 2, figsize=(16, 14))
                    for idx, (col_r, col_s, title, color) in enumerate([('Reel_Conso_Totale_MWh', 'Sim_Conso_Totale_MWh', '1. Conso Totale', '#3498db'), ('Reel_Prod_Totale_MWh', 'Sim_Prod_Totale_MWh', '2. Prod Totale', '#2ecc71'), ('Reel_Conso_Partagee_MWh', 'Sim_Conso_Partagee_MWh', '3. Conso Échangée', '#9b59b6'), ('Reel_Prod_Partagee_MWh', 'Sim_Prod_Partagee_MWh', '4. Prod Échangée', '#f1c40f')]):
                        row, col = idx // 2, idx % 2
                        df_f = df_analyse[(df_analyse[col_r] > 0) | (df_analyse[col_s] > 0)]
                        axes[row, col].scatter(df_f[col_r], df_f[col_s], color=color, alpha=0.8, edgecolor='black', s=60)
                        m = max(df_f[col_r].max(), df_f[col_s].max())
                        if pd.notna(m) and m > 0: axes[row, col].plot([0, m], [0, m], 'r--', label='Idéal')
                        axes[row, col].set_title(title, fontweight='bold'); axes[row, col].set_xlabel('Sibelga'); axes[row, col].set_ylabel('Streamlit')
                    plt.tight_layout(); st.pyplot(fig_nuage)


                # =================================================================================================
                # 🔵🔵🔵 MODE ANNUEL
                # =================================================================================================
                else:
                    df_reels_list = []
                    for fact in fichier_factures:
                        fact.seek(0)
                        df_r = pd.read_excel(fact, dtype=str)
                        c_locales = df_r.columns.tolist()
                        
                        def trv(opt, exc):
                            for m in opt:
                                for c in c_locales:
                                    if all(x in str(c).lower().replace('é','e') for x in m) and not any(x in str(c).lower() for x in exc): return c
                            return None

                        c_date = trv([['fromdate'], ['date', 'debut'], ['from', 'date'], ['periode', 'debut']], ['fin', 'to', 'todate'])
                        c_ean = trv([['ean']], [])
                        c_vol_part = trv([['partage', 'kwh'], ['partage', 'volume'], ['partage', 'consomm']], ['injection', 'production', 'taux', 'statut'])
                        c_vol_comp = trv([['complementaire', 'kwh'], ['residuel', 'consomm'], ['complementaire', 'volume'], ['residuel', 'volume'], ['reseau', 'consomm']], ['injection', 'production', 'taux', 'statut'])
                        c_inj_part = trv([['partage', 'injection'], ['partage', 'production']], ['taux', 'statut'])
                        c_inj_comp = trv([['residuel', 'injection'], ['complementaire', 'injection'], ['reseau', 'injection'], ['reseau', 'kwh']], ['taux', 'statut', 'consomm'])

                        if not all([c_date, c_ean, c_vol_part, c_vol_comp, c_inj_part, c_inj_comp]):
                            continue 

                        # GESTION TEMPORELLE (Année + Mois)
                        premiere_date = pd.to_datetime(df_r[c_date].dropna().iloc[0])
                        m_encours = premiere_date.month
                        y_encours = premiere_date.year
                        
                        df_r[c_ean] = df_r[c_ean].astype(str).str.replace(' ','').str.replace(r'\.0$','',regex=True).str.strip()
                        for c in [c_vol_part, c_vol_comp, c_inj_part, c_inj_comp]:
                            if df_r[c].dtype == object: df_r[c] = df_r[c].astype(str).str.replace(',', '.')
                            df_r[c] = pd.to_numeric(df_r[c], errors='coerce').fillna(0)
                            
                        df_agg = df_r.groupby(c_ean)[[c_vol_part, c_vol_comp, c_inj_part, c_inj_comp]].sum().reset_index()
                        df_agg.columns = ['EAN', 'Volume Partagé (kWh)', 'Volume Complémentaire (kWh)', 'Injection Partagée (kWh)', 'Injection Résiduelle (kWh)']
                        
                        df_c = pd.merge(df_agg, df_contacts[['Ean', 'Groupe_Odoo', 'Nom']], left_on='EAN', right_on='Ean', how='left')
                        df_c['Prop_Odoo'] = df_c['Groupe_Odoo'].fillna(df_c['Nom']).fillna("Inconnu")
                        df_c['Proprietaire'] = df_c['Prop_Odoo'].map(mapping_reel).fillna(df_c['Prop_Odoo'])
                        
                        df_c['Reel_Conso_Partagee_MWh'] = df_c['Volume Partagé (kWh)'] / 1000.0
                        df_c['Reel_Conso_Totale_MWh'] = (df_c['Volume Partagé (kWh)'] + df_c['Volume Complémentaire (kWh)']) / 1000.0
                        df_c['Reel_Prod_Partagee_MWh'] = df_c['Injection Partagée (kWh)'] / 1000.0
                        df_c['Reel_Prod_Totale_MWh'] = (df_c['Injection Partagée (kWh)'] + df_c['Injection Résiduelle (kWh)']) / 1000.0
                        
                        df_c['Mois'] = m_encours
                        df_c['Annee'] = y_encours
                        df_c['Sort_Key'] = y_encours * 100 + m_encours
                        df_reels_list.append(df_c)

                    if not df_reels_list:
                        st.error("❌ Aucun fichier Sibelga n'a pu être traité correctement.")
                        st.stop()

                    df_reels_all = pd.concat(df_reels_list)
                    df_reels_final = df_reels_all.groupby(['Proprietaire', 'Mois', 'Annee', 'Sort_Key'])[['Reel_Conso_Partagee_MWh', 'Reel_Conso_Totale_MWh', 'Reel_Prod_Partagee_MWh', 'Reel_Prod_Totale_MWh']].sum().reset_index()

                    # On mémorise la clé de tri de chaque mois pour la fusion
                    mois_annee_map = df_reels_all[['Mois', 'Annee', 'Sort_Key']].drop_duplicates().set_index('Mois')

                    df_s = pd.read_csv(fichier_simu)
                    df_s['Mois_Simu'] = pd.to_datetime(df_s['Unnamed: 0']).dt.month
                    mois_presents = df_reels_all['Mois'].unique().tolist()
                    df_s = df_s[df_s['Mois_Simu'].isin(mois_presents)]

                    p_bruts = set(c.split('_')[0] for c in df_s.columns if c not in ['Unnamed: 0', 'Mois_Simu'])
                    tech = {'external', 'grid', 'injection', 'internal', 'remaining', 'residual', 'shared', 'community', 'n'}
                    p_simu = {p.strip() for p in p_bruts if p.strip().lower() not in tech}

                    d_simu = []
                    for m_encours, group in df_s.groupby('Mois_Simu'):
                        s_simu = group.sum(numeric_only=True)
                        for p in p_simu:
                            d_simu.append({
                                'Mois': m_encours, 'Nom_Streamlit': p,
                                'Sim_Conso_Partagee_MWh': s_simu.get(f"{p}_shared_volume_from_community", 0) / 4000.0,
                                'Sim_Conso_Totale_MWh': s_simu.get(f"{p}_residual_consumption_bc", 0) / 4000.0,
                                'Sim_Prod_Partagee_MWh': abs(s_simu.get(f"{p}_shared_volume_to_community", 0)) / 4000.0,
                                'Sim_Prod_Totale_MWh': abs(s_simu.get(f"{p}_injection_bc", 0)) / 4000.0
                            })
                    df_sim_agg = pd.DataFrame(d_simu)
                    df_sim_agg['Proprietaire'] = df_sim_agg['Nom_Streamlit'].map(mapping_sim).fillna(df_sim_agg['Nom_Streamlit'])
                    df_sim_final = df_sim_agg.groupby(['Proprietaire', 'Mois'])[['Sim_Conso_Partagee_MWh', 'Sim_Conso_Totale_MWh', 'Sim_Prod_Partagee_MWh', 'Sim_Prod_Totale_MWh']].sum().reset_index()

                    df_comparatif = pd.merge(df_reels_final, df_sim_final, on=['Proprietaire', 'Mois'], how='outer', indicator=True)
                    df_comparatif = df_comparatif[~df_comparatif['Proprietaire'].astype(str).isin(['', '0', 'nan', 'NaN', 'Inconnu', 'Indéfini'])]
                    df_comparatif['Has_Facture'] = df_comparatif['_merge'].isin(['both', 'left_only'])
                    
                    # On injecte la bonne année pour le tri chronologique
                    df_comparatif['Annee'] = df_comparatif['Mois'].map(mois_annee_map['Annee'])
                    df_comparatif['Sort_Key'] = df_comparatif['Mois'].map(mois_annee_map['Sort_Key'])

                    st.subheader("🚨 Alertes d'Audit Annuel")
                    inconnus = df_reels_all[df_reels_all['Prop_Odoo'] == 'Inconnu']['EAN'].unique()
                    if len(inconnus) > 0: st.error(f"**ALERTE ODOO (EAN facturés mais inconnus) :** {', '.join(inconnus)}")
                    simu_sans_map = p_simu - set(mapping_sim.keys())
                    if len(simu_sans_map) > 0: st.warning(f"**ALERTE MAPPING (Membres Streamlit non traduits) :** {', '.join(simu_sans_map)}")
                    
                    m_simules = set(df_sim_final['Proprietaire'])
                    m_factures = set(df_reels_final['Proprietaire'])
                    simu_jamais_fact = list(m_simules - m_factures)
                    fact_jamais_sim = list(m_factures - m_simules)
                    
                    if fact_jamais_sim: st.warning(f"**Facturés sur l'année mais JAMAIS simulés :** {', '.join(fact_jamais_sim)}")
                    if simu_jamais_fact: st.warning(f"**Simulés sur l'année mais SANS AUCUNE facture :** {', '.join(simu_jamais_fact)}")
                    if len(inconnus)==0 and not simu_sans_map and not fact_jamais_sim and not simu_jamais_fact:
                        st.success("✅ Bases de données alignées sur toute l'année !")

                    df_comparatif = df_comparatif.drop(columns=['_merge']).fillna(0)
                    df_comparatif['Erreur_Conso_MWh'] = df_comparatif['Sim_Conso_Totale_MWh'] - df_comparatif['Reel_Conso_Totale_MWh']
                    df_comparatif['Erreur_Prod_MWh'] = df_comparatif['Sim_Prod_Totale_MWh'] - df_comparatif['Reel_Prod_Totale_MWh']
                    df_comparatif['Erreur_Partage_MWh'] = df_comparatif['Sim_Conso_Partagee_MWh'] - df_comparatif['Reel_Conso_Partagee_MWh']

                    df_analyse = df_comparatif[~df_comparatif['Proprietaire'].isin(simu_jamais_fact)].copy()
                    
                    # Chaîne de caractères chronologique (ex: "Jan 26")
                    df_analyse['Periode_Str'] = df_analyse['Mois'].map(noms_mois) + " '" + df_analyse['Annee'].astype(int).astype(str).str[-2:]
                    df_analyse = df_analyse.sort_values('Sort_Key')

                    # --- GRAPHIQUES ANNUELS ---
                    st.divider()
                    st.subheader("🌍 Bilan Annuel Global")
                    col_a1, col_a2, col_a3 = st.columns(3)
                    t_rc = df_analyse['Reel_Conso_Totale_MWh'].sum()
                    pc_c = ((df_analyse['Sim_Conso_Totale_MWh'].sum() - t_rc) / t_rc * 100) if t_rc > 0 else 0
                    t_rp = df_analyse['Reel_Prod_Totale_MWh'].sum()
                    pc_p = ((df_analyse['Sim_Prod_Totale_MWh'].sum() - t_rp) / t_rp * 100) if t_rp > 0 else 0
                    t_re = df_analyse['Reel_Conso_Partagee_MWh'].sum()
                    pc_e = ((df_analyse['Sim_Conso_Partagee_MWh'].sum() - t_re) / t_re * 100) if t_re > 0 else 0
                    
                    col_a1.metric("⚡ Total Consommé (Cumulé)", f"{t_rc:.2f} MWh", f"{pc_c:+.1f}% (Simu: {df_analyse['Sim_Conso_Totale_MWh'].sum():.2f})", delta_color="off")
                    col_a2.metric("☀️ Total Produit (Cumulé)", f"{t_rp:.2f} MWh", f"{pc_p:+.1f}% (Simu: {df_analyse['Sim_Prod_Totale_MWh'].sum():.2f})", delta_color="off")
                    col_a3.metric("🤝 Total Échangé (Cumulé)", f"{t_re:.2f} MWh", f"{pc_e:+.1f}% (Simu: {df_analyse['Sim_Conso_Partagee_MWh'].sum():.2f})", delta_color="off")
                    st.divider()

                    # SÉLECTEUR DE VUE POUR LES GRAPHIQUES ANNUELS
                    st.subheader("📈 Visualisation Détaillée")
                    choix_kpi = st.radio("Sélectionnez l'indicateur à analyser :", ["⚡ Consommation", "☀️ Production", "🤝 Échange (Partagé)"], horizontal=True)
                    
                    if choix_kpi == "⚡ Consommation":
                        col_reel, col_sim, col_err = 'Reel_Conso_Totale_MWh', 'Sim_Conso_Totale_MWh', 'Erreur_Conso_MWh'
                    elif choix_kpi == "☀️ Production":
                        col_reel, col_sim, col_err = 'Reel_Prod_Totale_MWh', 'Sim_Prod_Totale_MWh', 'Erreur_Prod_MWh'
                    else:
                        col_reel, col_sim, col_err = 'Reel_Conso_Partagee_MWh', 'Sim_Conso_Partagee_MWh', 'Erreur_Partage_MWh'

                    # TENDANCE CHRONOLOGIQUE
                    st.markdown(f"**Saisonnalité Globale : {choix_kpi.split(' ')[1]}**")
                    df_trend_data = df_analyse[df_analyse['Has_Facture'] == True]
                    df_trend = df_trend_data.groupby(['Sort_Key', 'Periode_Str'])[[col_reel, col_sim]].sum().reset_index()
                    
                    fig_trend, ax_trend = plt.subplots(figsize=(12, 4))
                    ax_trend.plot(df_trend['Periode_Str'], df_trend[col_reel], marker='o', color='#3498db', linewidth=2.5, label='Réalité (Sibelga)')
                    ax_trend.plot(df_trend['Periode_Str'], df_trend[col_sim], marker='x', color='#e74c3c', linestyle='--', linewidth=2.5, label='Simulation (Streamlit)')
                    ax_trend.set_ylabel('MWh'); ax_trend.legend(); st.pyplot(fig_trend)
                    
                    # HEATMAP ARC-EN-CIEL (MWh)
                    st.markdown(f"**Écarts (MWh) par Membre : {choix_kpi.split(' ')[1]}**")
                    st.markdown("*Une case grise signifie que le membre n'avait pas de facture Sibelga ce mois-là.*")
                    
                    df_analyse['Erreur_Heatmap'] = np.where(df_analyse['Has_Facture'], df_analyse[col_err], np.nan)
                    pivot_heat = df_analyse.pivot(index='Proprietaire', columns='Periode_Str', values='Erreur_Heatmap')
                    
                    # On force l'ordre chronologique des colonnes
                    colonnes_ordonnees = df_analyse['Periode_Str'].unique().tolist()
                    pivot_heat = pivot_heat.reindex(columns=colonnes_ordonnees)
                    
                    # Création de la palette Violet -> Bleu -> Vert -> Jaune -> Orange -> Rouge
                    colors_custom = ['#8e44ad', '#2c3e50', '#2980b9', '#27ae60', '#f1c40f', '#e67e22', '#c0392b']
                    cmap_custom = LinearSegmentedColormap.from_list("custom_error", colors_custom)

                    fig_heat, ax_heat = plt.subplots(figsize=(14, max(4, len(pivot_heat)*0.4)))
                    ax_heat.set_facecolor('#ecf0f1') 
                    sns.heatmap(pivot_heat, cmap=cmap_custom, center=0, annot=True, fmt=".2f", ax=ax_heat, cbar_kws={'label': "Erreur (MWh)"}, linewidths=0.5)
                    ax_heat.set_ylabel(''); ax_heat.set_xlabel(''); st.pyplot(fig_heat)
                    st.divider()

                    # PROFIL INDIVIDUEL ZOOMÉ
                    st.subheader("👤 Profil Individuel")
                    membre_choisi = st.selectbox("Sélectionnez un membre :", sorted(df_analyse['Proprietaire'].unique()))
                    
                    # Le filtre 'Has_Facture == True' efface automatiquement les mois vides !
                    df_indiv = df_analyse[(df_analyse['Proprietaire'] == membre_choisi) & (df_analyse['Has_Facture'] == True)].sort_values('Sort_Key')
                    
                    if not df_indiv.empty:
                        col_i1, col_i2 = st.columns([1, 2])
                        tot_i_r = df_indiv[col_reel].sum()
                        err_i_p = ((df_indiv[col_sim].sum() - tot_i_r) / tot_i_r * 100) if tot_i_r > 0 else 0
                        col_i1.metric(f"Bilan {choix_kpi.split(' ')[1]}", f"{tot_i_r:.2f} MWh", f"{err_i_p:+.1f}% simulé", delta_color="off")
                        
                        fig_indiv, ax_indiv = plt.subplots(figsize=(8, 4))
                        ax_indiv.plot(df_indiv['Periode_Str'], df_indiv[col_reel], marker='o', color='#9b59b6', label='Réalité')
                        ax_indiv.plot(df_indiv['Periode_Str'], df_indiv[col_sim], marker='x', color='#f1c40f', linestyle='--', label='Simulation')
                        ax_indiv.set_ylabel('MWh'); ax_indiv.legend(); col_i2.pyplot(fig_indiv)
                    else:
                        st.info("Ce membre n'a aucune donnée de facture pour cet indicateur.")


                # =================================================================================================
                # 📥 TÉLÉCHARGEMENT COMMUN (VALABLE POUR LES DEUX MODES)
                # =================================================================================================
                st.divider()
                st.subheader("📋 Base de Données Complète")
                cols_to_drop = ['Abs_Erreur_Conso', 'Abs_Erreur_Prod', 'Abs_Erreur_Conso_%', 'Abs_Erreur_Prod_%', 'Sort_Key', 'Periode_Str', 'Has_Facture', 'Erreur_Heatmap']
                
                df_affichage = df_comparatif.drop(columns=[c for c in cols_to_drop if c in df_comparatif.columns], errors='ignore')
                st.dataframe(df_affichage, use_container_width=True)
                
                csv = df_affichage.to_csv(index=False, sep=';', decimal=',').encode('utf-8')
                nom_fichier = f"Audit_Mois_{mois_cible}.csv" if "Mensuel" in mode_analyse else "Audit_Annuel_Global.csv"
                
                st.download_button(
                    label="📥 Télécharger le rapport complet pour Excel",
                    data=csv,
                    file_name=nom_fichier,
                    mime="text/csv",
                    type="primary"
                )

            except Exception as e:
                st.error(f"❌ Une erreur s'est produite lors de l'analyse : {e}")

else:
    st.info("👈 Veuillez choisir un mode d'analyse et importer les fichiers dans le menu de gauche pour démarrer.")
