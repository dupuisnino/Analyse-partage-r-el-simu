import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from matplotlib.colors import LinearSegmentedColormap
import io

# Configuration de la page web
st.set_page_config(page_title="Audit Communauté d'Énergie", page_icon="⚡", layout="wide")
sns.set_theme(style="whitegrid")

st.title("⚡ Audit Automatique : Réalité vs Simulation")
st.markdown("Importez les 4 fichiers ci-dessous pour lancer l'analyse globale et détaillée.")

# ==========================================
# BARRE LATÉRALE : UPLOADS & PARAMÈTRES
# ==========================================
st.sidebar.markdown("### Choix de l'Analyse")
mode_analyse = st.sidebar.radio("Type de rapport :", ["📅 Mensuel (Contrôle)", "📆 Annuel (Bilan)"])
st.sidebar.divider()

st.sidebar.header("📁 1. Import des fichiers")
fichier_contacts = st.sidebar.file_uploader("1. Contacts Odoo (Excel/CSV)", type=['xlsx', 'csv'])

# L'upload Sibelga change selon le mode choisi !
if "Mensuel" in mode_analyse:
    fichier_factures = st.sidebar.file_uploader("2. Fichier Sibelga (Excel)", type=['xlsx'])
else:
    fichier_factures = st.sidebar.file_uploader("2. Fichiers Sibelga (Glissez les 12 mois)", type=['xlsx'], accept_multiple_files=True)

fichier_mapping = st.sidebar.file_uploader("3. Fichier de Mapping (Excel)", type=['xlsx'])
fichier_simu = st.sidebar.file_uploader("4. Simulation Streamlit (CSV)", type=['csv'])

# ==========================================
# VERIFICATION DES COLONNES SIBELGA & MOIS
# ==========================================
col_ean_sel, col_vol_part_sel, col_vol_comp_sel, col_inj_part_sel, col_inj_comp_sel, col_date_sel = None, None, None, None, None, None
mois_detecte = None

# On isole le premier fichier pour éviter le plantage
first_facture = None
if fichier_factures:
    first_facture = fichier_factures[0] if isinstance(fichier_factures, list) else fichier_factures

if first_facture:
    st.sidebar.header("🔧 2. Vérification des colonnes")
    st.sidebar.markdown("*L'outil a pré-sélectionné les colonnes Sibelga. Corrigez-les si nécessaire.*")
    
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

    idx_ean = trouver_colonne_index([['ean']], [])
    idx_vol_part = trouver_colonne_index([['partage', 'kwh'], ['partage', 'volume'], ['partage', 'consomm']], ['injection', 'production', 'taux', 'statut', 'type', 'cle'])
    idx_vol_comp = trouver_colonne_index([['complementaire', 'kwh'], ['residuel', 'consomm'], ['complementaire', 'volume'], ['residuel', 'volume'], ['reseau', 'consomm'], ['reseau', 'kwh']], ['injection', 'production', 'taux', 'statut', 'partage'])
    idx_inj_part = trouver_colonne_index([['partage', 'injection'], ['partage', 'production']], ['taux', 'statut'])
    idx_inj_comp = trouver_colonne_index([['residuel', 'injection'], ['complementaire', 'injection'], ['reseau', 'injection'], ['reseau', 'kwh']], ['taux', 'statut', 'partage', 'consommation', 'consomm'])
    
    idx_date = trouver_colonne_index([['fromdate'], ['date', 'debut'], ['from', 'date'], ['periode', 'debut']], ['fin', 'to', 'todate'])

    col_date_sel = st.sidebar.selectbox("Colonne Date (Début)", options_colonnes, index=idx_date)
    col_ean_sel = st.sidebar.selectbox("Colonne EAN", options_colonnes, index=idx_ean)
    col_vol_part_sel = st.sidebar.selectbox("Consommation Partagée", options_colonnes, index=idx_vol_part)
    col_vol_comp_sel = st.sidebar.selectbox("Consommation Résiduelle/Réseau", options_colonnes, index=idx_vol_comp)
    col_inj_part_sel = st.sidebar.selectbox("Injection Partagée", options_colonnes, index=idx_inj_part)
    col_inj_comp_sel = st.sidebar.selectbox("Injection Résiduelle (Réseau)", options_colonnes, index=idx_inj_comp)

    # Extraction automatique du mois d'après la première ligne de la facture (Utile pour le mode mensuel)
    if col_date_sel != "--- À sélectionner ---":
        try:
            first_facture.seek(0)
            df_dates = pd.read_excel(first_facture, nrows=5)
            first_facture.seek(0) 
            
            premiere_date = df_dates[col_date_sel].dropna().iloc[0]
            mois_detecte = pd.to_datetime(premiere_date).month
        except Exception:
            pass

if "Mensuel" in mode_analyse:
    st.sidebar.header("📅 3. Paramètres")
    index_defaut_mois = (mois_detecte - 1) if mois_detecte else 1
    mois_cible = st.sidebar.selectbox("Mois à analyser", range(1, 13), index=index_defaut_mois, format_func=lambda x: ['Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin', 'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre'][x-1])

    if mois_detecte:
        st.sidebar.success("✅ Mois détecté automatiquement d'après la facture Sibelga !")


# ==========================================
# MOTEUR D'ANALYSE
# ==========================================
if fichier_contacts and fichier_factures and fichier_mapping and fichier_simu:
    if st.button("🚀 Lancer le calcul", type="primary", use_container_width=True):
        st.session_state['calcul_lance'] = True
        
    if st.session_state.get('calcul_lance', False):
        
        if "--- À sélectionner ---" in [col_ean_sel, col_vol_part_sel, col_vol_comp_sel, col_inj_part_sel, col_inj_comp_sel]:
            st.error("❌ Oups ! Certaines colonnes Sibelga n'ont pas pu être trouvées. Veuillez les sélectionner manuellement dans le menu de gauche avant de lancer l'analyse.")
            st.stop()
            
        with st.spinner("Calculs en cours..."):
            try:
                # ---------------------------------------------------------
                # BASE COMMUNE : MAPPING ET CONTACTS
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

                df_contacts = pd.read_excel(fichier_contacts, dtype=str)
                est_un_titre = df_contacts['Ean'].isna() & df_contacts['Nom'].astype(str).str.contains(r'\(\d+\)$')
                df_contacts['Groupe_Odoo'] = np.where(est_un_titre, df_contacts['Nom'].astype(str).str.replace(r' \(\d+\)$', '', regex=True).str.strip(), np.nan)
                df_contacts['Groupe_Odoo'] = df_contacts['Groupe_Odoo'].ffill()
                df_contacts = df_contacts.dropna(subset=['Ean']).copy() 
                df_contacts['Ean'] = df_contacts['Ean'].astype(str).str.replace(' ', '').str.replace(r'\.0$', '', regex=True).str.strip()
                df_contacts = df_contacts.drop_duplicates(subset=['Ean'], keep='first')
                
                noms_mois = {1:'Jan', 2:'Fév', 3:'Mar', 4:'Avr', 5:'Mai', 6:'Juin', 7:'Juil', 8:'Août', 9:'Sep', 10:'Oct', 11:'Nov', 12:'Déc'}

                # =========================================================
                # 🟢 MODE MENSUEL 
                # =========================================================
                if "Mensuel" in mode_analyse:
                    df_reels = pd.read_excel(first_facture, dtype=str)
                    df_reels[col_ean_sel] = df_reels[col_ean_sel].astype(str).str.replace(' ', '').str.replace(r'\.0$', '', regex=True).str.strip()
                    colonnes_vol = [col_vol_part_sel, col_vol_comp_sel, col_inj_part_sel, col_inj_comp_sel]
                    
                    for col in colonnes_vol:
                        if df_reels[col].dtype == object:
                            df_reels[col] = df_reels[col].astype(str).str.replace(',', '.')
                        df_reels[col] = pd.to_numeric(df_reels[col], errors='coerce').fillna(0)
                        
                    df_reels_agg = df_reels.groupby(col_ean_sel)[colonnes_vol].sum().reset_index()
                    df_reels_agg = df_reels_agg.rename(columns={
                        col_ean_sel: 'EAN', col_vol_part_sel: 'Volume Partagé (kWh)', col_vol_comp_sel: 'Volume Complémentaire (kWh)',
                        col_inj_part_sel: 'Injection Partagée (kWh)', col_inj_comp_sel: 'Injection Résiduelle (kWh)'
                    })
                    
                    df_reels_complet = pd.merge(df_reels_agg, df_contacts[['Ean', 'Groupe_Odoo', 'Nom']], left_on='EAN', right_on='Ean', how='left')
                    df_reels_complet['Proprietaire_Odoo'] = df_reels_complet['Groupe_Odoo'].fillna(df_reels_complet['Nom']).fillna("Inconnu")
                    df_reels_complet['Proprietaire'] = df_reels_complet['Proprietaire_Odoo'].map(mapping_reel).fillna(df_reels_complet['Proprietaire_Odoo'])
                    
                    df_reels_complet['Reel_Conso_Partagee_MWh'] = df_reels_complet['Volume Partagé (kWh)'] / 1000.0
                    df_reels_complet['Reel_Conso_Totale_MWh'] = (df_reels_complet['Volume Partagé (kWh)'] + df_reels_complet['Volume Complémentaire (kWh)']) / 1000.0
                    df_reels_complet['Reel_Prod_Partagee_MWh'] = df_reels_complet['Injection Partagée (kWh)'] / 1000.0
                    df_reels_complet['Reel_Prod_Totale_MWh'] = (df_reels_complet['Injection Partagée (kWh)'] + df_reels_complet['Injection Résiduelle (kWh)']) / 1000.0
                    df_reels_final = df_reels_complet.groupby('Proprietaire')[['Reel_Conso_Partagee_MWh', 'Reel_Conso_Totale_MWh', 'Reel_Prod_Partagee_MWh', 'Reel_Prod_Totale_MWh']].sum().reset_index()
    
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
                    eans_inconnus = df_reels_complet[df_reels_complet['Proprietaire_Odoo'] == 'Inconnu']['EAN'].unique()
                    if len(eans_inconnus) > 0: st.error(f"**ALERTE ODOO (EAN facturés mais inconnus dans contacts) :** {', '.join(eans_inconnus)}")
                    
                    simu_sans_mapping = participants_simu - set(mapping_sim.keys())
                    if len(simu_sans_mapping) > 0: st.warning(f"**ALERTE MAPPING (Membres Streamlit non traduits) :** {', '.join(simu_sans_mapping)}")
    
                    reel_sans_simu = df_comparatif[df_comparatif['_merge'] == 'left_only']['Proprietaire'].tolist()
                    simu_sans_reel = df_comparatif[df_comparatif['_merge'] == 'right_only']['Proprietaire'].tolist()
                    if reel_sans_simu: st.warning(f"**Facturés mais NON simulés :** {', '.join(reel_sans_simu)}")
                    if simu_sans_reel: st.warning(f"**Simulés mais SANS facture ce mois-ci :** {', '.join(simu_sans_reel)} *(Exclus des graphiques/totaux, gardés dans le tableau)*")
                    
                    if len(eans_inconnus) == 0 and len(simu_sans_mapping) == 0 and not reel_sans_simu and not simu_sans_reel:
                        st.success("✅ Aucun problème détecté. Les bases de données sont parfaitement alignées !")
    
                    df_comparatif = df_comparatif.drop(columns=['_merge']).fillna(0)
                    df_comparatif = df_comparatif[(df_comparatif['Reel_Conso_Totale_MWh'] > 0) | (df_comparatif['Sim_Conso_Totale_MWh'] > 0) | (df_comparatif['Reel_Prod_Totale_MWh'] > 0) | (df_comparatif['Sim_Prod_Totale_MWh'] > 0)]
                    
                    df_comparatif['Erreur_Conso_MWh'] = df_comparatif['Sim_Conso_Totale_MWh'] - df_comparatif['Reel_Conso_Totale_MWh']
                    df_comparatif['Erreur_Prod_MWh'] = df_comparatif['Sim_Prod_Totale_MWh'] - df_comparatif['Reel_Prod_Totale_MWh']
                    df_comparatif['Abs_Erreur_Conso'] = df_comparatif['Erreur_Conso_MWh'].abs()
                    df_comparatif['Abs_Erreur_Prod'] = df_comparatif['Erreur_Prod_MWh'].abs()
    
                    df_comparatif['Erreur_Conso_%'] = np.where(df_comparatif['Reel_Conso_Totale_MWh'] > 0, (df_comparatif['Erreur_Conso_MWh'] / df_comparatif['Reel_Conso_Totale_MWh']) * 100, np.where(df_comparatif['Sim_Conso_Totale_MWh'] > 0, 100.0, 0.0))
                    df_comparatif['Erreur_Prod_%'] = np.where(df_comparatif['Reel_Prod_Totale_MWh'] > 0, (df_comparatif['Erreur_Prod_MWh'] / df_comparatif['Reel_Prod_Totale_MWh']) * 100, np.where(df_comparatif['Sim_Prod_Totale_MWh'] > 0, 100.0, 0.0))
                    df_comparatif['Abs_Erreur_Conso_%'] = df_comparatif['Erreur_Conso_%'].abs()
                    df_comparatif['Abs_Erreur_Prod_%'] = df_comparatif['Erreur_Prod_%'].abs()
    
                    df_comparatif = df_comparatif.round(3)
                    df_analyse = df_comparatif[~df_comparatif['Proprietaire'].isin(simu_sans_reel)].copy()
    
                    st.divider()
                    st.subheader("🌍 Analyse Globale de la Communauté")
                    col_met1, col_met2, col_met3 = st.columns(3)
                    
                    tot_reel_conso = df_analyse['Reel_Conso_Totale_MWh'].sum()
                    tot_sim_conso = df_analyse['Sim_Conso_Totale_MWh'].sum()
                    pct_conso = ((tot_sim_conso - tot_reel_conso) / tot_reel_conso * 100) if tot_reel_conso > 0 else 0
                    
                    tot_reel_prod = df_analyse['Reel_Prod_Totale_MWh'].sum()
                    tot_sim_prod = df_analyse['Sim_Prod_Totale_MWh'].sum()
                    pct_prod = ((tot_sim_prod - tot_reel_prod) / tot_reel_prod * 100) if tot_reel_prod > 0 else 0
                    
                    tot_reel_ech = df_analyse['Reel_Conso_Partagee_MWh'].sum()
                    tot_sim_ech = df_analyse['Sim_Conso_Partagee_MWh'].sum()
                    pct_ech = ((tot_sim_ech - tot_reel_ech) / tot_reel_ech * 100) if tot_reel_ech > 0 else 0
                    
                    col_met1.metric("⚡ Total Consommé (MWh)", f"{tot_reel_conso:.2f}", f"{pct_conso:+.1f}% (Simu: {tot_sim_conso:.2f})", delta_color="off")
                    col_met2.metric("☀️ Total Produit (MWh)", f"{tot_reel_prod:.2f}", f"{pct_prod:+.1f}% (Simu: {tot_sim_prod:.2f})", delta_color="off")
                    col_met3.metric("🤝 Total Échangé (MWh)", f"{tot_reel_ech:.2f}", f"{pct_ech:+.1f}% (Simu: {tot_sim_ech:.2f})", delta_color="off")
    
                    st.divider()
                    st.subheader("📉 Pire dimensionnement (MWh)")
                    col1, col2 = st.columns(2)
                    
                    df_pire_conso = df_analyse.sort_values(by='Abs_Erreur_Conso', ascending=False)
                    top10_conso = df_pire_conso.head(10).copy()
                    fig_bar_conso, ax1 = plt.subplots(figsize=(8, 5))
                    couleurs_conso = ['#e74c3c' if val > 0 else '#3498db' for val in top10_conso['Erreur_Conso_MWh']]
                    sns.barplot(data=top10_conso, x='Erreur_Conso_MWh', y='Proprietaire', palette=couleurs_conso, ax=ax1)
                    ax1.set_title('CONSOMMATION', fontweight='bold')
                    ax1.set_xlabel('Écart (MWh)')
                    ax1.set_ylabel('')
                    ax1.axvline(0, color='black', linewidth=1)
                    col1.pyplot(fig_bar_conso)
    
                    df_pire_prod = df_analyse.sort_values(by='Abs_Erreur_Prod', ascending=False)
                    top10_prod = df_pire_prod.head(10).copy()
                    top10_prod = top10_prod[top10_prod['Abs_Erreur_Prod'] > 0]
                    if not top10_prod.empty:
                        fig_bar_prod, ax2 = plt.subplots(figsize=(8, 5))
                        couleurs_prod = ['#e74c3c' if val > 0 else '#3498db' for val in top10_prod['Erreur_Prod_MWh']]
                        sns.barplot(data=top10_prod, x='Erreur_Prod_MWh', y='Proprietaire', palette=couleurs_prod, ax=ax2)
                        ax2.set_title('PRODUCTION', fontweight='bold')
                        ax2.set_xlabel('Écart (MWh)')
                        ax2.set_ylabel('')
                        ax2.axvline(0, color='black', linewidth=1)
                        col2.pyplot(fig_bar_prod)
    
                    st.divider()
                    st.subheader("📉 Pire dimensionnement (%)")
                    col3, col4 = st.columns(2)
                    
                    df_pire_conso_pct = df_analyse.sort_values(by='Abs_Erreur_Conso_%', ascending=False)
                    top10_conso_pct = df_pire_conso_pct.head(10).copy()
                    top10_conso_pct = top10_conso_pct[top10_conso_pct['Abs_Erreur_Conso_%'] > 0]
                    if not top10_conso_pct.empty:
                        fig_bar_conso_pct, ax3 = plt.subplots(figsize=(8, 5))
                        couleurs_conso_pct = ['#e74c3c' if val > 0 else '#3498db' for val in top10_conso_pct['Erreur_Conso_%']]
                        sns.barplot(data=top10_conso_pct, x='Erreur_Conso_%', y='Proprietaire', palette=couleurs_conso_pct, ax=ax3)
                        ax3.set_title('CONSOMMATION (%)', fontweight='bold')
                        ax3.set_xlabel('Écart (%)')
                        ax3.set_ylabel('')
                        ax3.axvline(0, color='black', linewidth=1)
                        col3.pyplot(fig_bar_conso_pct)
    
                    df_pire_prod_pct = df_analyse.sort_values(by='Abs_Erreur_Prod_%', ascending=False)
                    top10_prod_pct = df_pire_prod_pct.head(10).copy()
                    top10_prod_pct = top10_prod_pct[top10_prod_pct['Abs_Erreur_Prod_%'] > 0]
                    if not top10_prod_pct.empty:
                        fig_bar_prod_pct, ax4 = plt.subplots(figsize=(8, 5))
                        couleurs_prod_pct = ['#e74c3c' if val > 0 else '#3498db' for val in top10_prod_pct['Erreur_Prod_%']]
                        sns.barplot(data=top10_prod_pct, x='Erreur_Prod_%', y='Proprietaire', palette=couleurs_prod_pct, ax=ax4)
                        ax4.set_title('PRODUCTION (%)', fontweight='bold')
                        ax4.set_xlabel('Écart (%)')
                        ax4.set_ylabel('')
                        ax4.axvline(0, color='black', linewidth=1)
                        col4.pyplot(fig_bar_prod_pct)
    
                    st.divider()
                    st.subheader("📊 Vue globale : Réalité vs Simulation")
                    fig_nuage, axes = plt.subplots(2, 2, figsize=(16, 14))
                    
                    df_c_tot = df_analyse[(df_analyse['Reel_Conso_Totale_MWh'] > 0) | (df_analyse['Sim_Conso_Totale_MWh'] > 0)]
                    axes[0, 0].scatter(df_c_tot['Reel_Conso_Totale_MWh'], df_c_tot['Sim_Conso_Totale_MWh'], color='#3498db', alpha=0.8, edgecolor='black', s=60)
                    max_c_tot = max(df_c_tot['Reel_Conso_Totale_MWh'].max(), df_c_tot['Sim_Conso_Totale_MWh'].max())
                    if pd.notna(max_c_tot) and max_c_tot > 0: axes[0, 0].plot([0, max_c_tot], [0, max_c_tot], 'r--', label='Idéal (Simu = Réalité)')
                    axes[0, 0].set_title('1. Consommation Totale (MWh)', fontsize=14, fontweight='bold')
                    axes[0, 0].set_xlabel('Réalité (Sibelga)'); axes[0, 0].set_ylabel('Simulation (Streamlit)')
                    for _, row in df_c_tot.sort_values(by='Abs_Erreur_Conso', ascending=False).head(5).iterrows():
                        axes[0, 0].annotate(row['Proprietaire'][:20], (row['Reel_Conso_Totale_MWh'], row['Sim_Conso_Totale_MWh']), fontsize=9, xytext=(5,5), textcoords='offset points')
    
                    df_p_tot = df_analyse[(df_analyse['Reel_Prod_Totale_MWh'] > 0) | (df_analyse['Sim_Prod_Totale_MWh'] > 0)]
                    axes[0, 1].scatter(df_p_tot['Reel_Prod_Totale_MWh'], df_p_tot['Sim_Prod_Totale_MWh'], color='#2ecc71', alpha=0.8, edgecolor='black', s=60)
                    max_p_tot = max(df_p_tot['Reel_Prod_Totale_MWh'].max(), df_p_tot['Sim_Prod_Totale_MWh'].max())
                    if pd.notna(max_p_tot) and max_p_tot > 0: axes[0, 1].plot([0, max_p_tot], [0, max_p_tot], 'r--', label='Idéal')
                    axes[0, 1].set_title('2. Production Totale (MWh)', fontsize=14, fontweight='bold')
                    axes[0, 1].set_xlabel('Réalité (Sibelga)'); axes[0, 1].set_ylabel('Simulation (Streamlit)')
                    for _, row in df_p_tot.sort_values(by='Abs_Erreur_Prod', ascending=False).head(5).iterrows():
                        axes[0, 1].annotate(row['Proprietaire'][:20], (row['Reel_Prod_Totale_MWh'], row['Sim_Prod_Totale_MWh']), fontsize=9, xytext=(5,5), textcoords='offset points')
    
                    df_c_part = df_analyse[(df_analyse['Reel_Conso_Partagee_MWh'] > 0) | (df_analyse['Sim_Conso_Partagee_MWh'] > 0)]
                    axes[1, 0].scatter(df_c_part['Reel_Conso_Partagee_MWh'], df_c_part['Sim_Conso_Partagee_MWh'], color='#9b59b6', alpha=0.8, edgecolor='black', s=60)
                    max_c_part = max(df_c_part['Reel_Conso_Partagee_MWh'].max(), df_c_part['Sim_Conso_Partagee_MWh'].max())
                    if pd.notna(max_c_part) and max_c_part > 0: axes[1, 0].plot([0, max_c_part], [0, max_c_part], 'r--', label='Idéal')
                    axes[1, 0].set_title('3. Consommation Échangée (MWh)', fontsize=14, fontweight='bold')
                    axes[1, 0].set_xlabel('Réalité (Sibelga)'); axes[1, 0].set_ylabel('Simulation (Streamlit)')
                    df_c_part['Err_part'] = (df_c_part['Sim_Conso_Partagee_MWh'] - df_c_part['Reel_Conso_Partagee_MWh']).abs()
                    for _, row in df_c_part.sort_values(by='Err_part', ascending=False).head(5).iterrows():
                        axes[1, 0].annotate(row['Proprietaire'][:20], (row['Reel_Conso_Partagee_MWh'], row['Sim_Conso_Partagee_MWh']), fontsize=9, xytext=(5,5), textcoords='offset points')
    
                    df_p_part = df_analyse[(df_analyse['Reel_Prod_Partagee_MWh'] > 0) | (df_analyse['Sim_Prod_Partagee_MWh'] > 0)]
                    axes[1, 1].scatter(df_p_part['Reel_Prod_Partagee_MWh'], df_p_part['Sim_Prod_Partagee_MWh'], color='#f1c40f', alpha=0.8, edgecolor='black', s=60)
                    max_p_part = max(df_p_part['Reel_Prod_Partagee_MWh'].max(), df_p_part['Sim_Prod_Partagee_MWh'].max())
                    if pd.notna(max_p_part) and max_p_part > 0: axes[1, 1].plot([0, max_p_part], [0, max_p_part], 'r--', label='Idéal')
                    axes[1, 1].set_title('4. Production Échangée (MWh)', fontsize=14, fontweight='bold')
                    axes[1, 1].set_xlabel('Réalité (Sibelga)'); axes[1, 1].set_ylabel('Simulation (Streamlit)')
                    df_p_part['Err_part'] = (df_p_part['Sim_Prod_Partagee_MWh'] - df_p_part['Reel_Prod_Partagee_MWh']).abs()
                    for _, row in df_p_part.sort_values(by='Err_part', ascending=False).head(5).iterrows():
                        axes[1, 1].annotate(row['Proprietaire'][:20], (row['Reel_Prod_Partagee_MWh'], row['Sim_Prod_Partagee_MWh']), fontsize=9, xytext=(5,5), textcoords='offset points')
    
                    plt.tight_layout()
                    st.pyplot(fig_nuage)


                # =================================================================================================
                # 🔵 MODE ANNUEL (Bilan & Tendance Globale)
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

                        # 1. TRI CHRONOLOGIQUE INTELLIGENT (Année + Mois)
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
                        df_c['Sort_Key'] = y_encours * 100 + m_encours # Clé pour trier "2025-08" avant "2026-02"
                        df_reels_list.append(df_c)

                    if not df_reels_list:
                        st.error("❌ Aucun fichier Sibelga n'a pu être traité correctement.")
                        st.stop()

                    df_reels_all = pd.concat(df_reels_list)
                    df_reels_final = df_reels_all.groupby(['Proprietaire', 'Mois', 'Annee', 'Sort_Key'])[['Reel_Conso_Partagee_MWh', 'Reel_Conso_Totale_MWh', 'Reel_Prod_Partagee_MWh', 'Reel_Prod_Totale_MWh']].sum().reset_index()

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
                    df_analyse['Periode_Str'] = df_analyse['Mois'].map(noms_mois) + " '" + df_analyse['Annee'].astype(int).astype(str).str[-2:]
                    df_analyse = df_analyse.sort_values('Sort_Key')

                    st.divider()
                    st.subheader("🌍 Bilan Annuel Global")
                    col_a1, col_a2, col_a3 = st.columns(3)
                    
                    t_rc = df_analyse['Reel_Conso_Totale_MWh'].sum()
                    t_sc = df_analyse['Sim_Conso_Totale_MWh'].sum()
                    pc_c = ((t_sc - t_rc) / t_rc * 100) if t_rc > 0 else 0
                    
                    t_rp = df_analyse['Reel_Prod_Totale_MWh'].sum()
                    t_sp = df_analyse['Sim_Prod_Totale_MWh'].sum()
                    pc_p = ((t_sp - t_rp) / t_rp * 100) if t_rp > 0 else 0
                    
                    t_re = df_analyse['Reel_Conso_Partagee_MWh'].sum()
                    t_se = df_analyse['Sim_Conso_Partagee_MWh'].sum()
                    pc_e = ((t_se - t_re) / t_re * 100) if t_re > 0 else 0
                    
                    # 5. Valeurs simulées ajoutées à côté des pourcentages annuels
                    col_a1.metric("⚡ Total Consommé (Cumulé)", f"{t_rc:.2f} MWh", f"{pc_c:+.1f}% (Simu: {t_sc:.2f})", delta_color="off")
                    col_a2.metric("☀️ Total Produit (Cumulé)", f"{t_rp:.2f} MWh", f"{pc_p:+.1f}% (Simu: {t_sp:.2f})", delta_color="off")
                    col_a3.metric("🤝 Total Échangé (Cumulé)", f"{t_re:.2f} MWh", f"{pc_e:+.1f}% (Simu: {t_se:.2f})", delta_color="off")
                    
                    st.divider()

                    # 2. MENU INTERACTIF GLOBAL
                    st.subheader("📈 Visualisation Détaillée Globale")
                    choix_kpi_global = st.radio("Sélectionnez l'indicateur global à analyser :", ["⚡ Consommation", "☀️ Production", "🤝 Échange (Partagé)"], horizontal=True)
                    
                    if choix_kpi_global == "⚡ Consommation":
                        col_r, col_s, col_err = 'Reel_Conso_Totale_MWh', 'Sim_Conso_Totale_MWh', 'Erreur_Conso_MWh'
                    elif choix_kpi_global == "☀️ Production":
                        col_r, col_s, col_err = 'Reel_Prod_Totale_MWh', 'Sim_Prod_Totale_MWh', 'Erreur_Prod_MWh'
                    else:
                        col_r, col_s, col_err = 'Reel_Conso_Partagee_MWh', 'Sim_Conso_Partagee_MWh', 'Erreur_Partage_MWh'

                    st.markdown(f"**Saisonnalité : {choix_kpi_global.split(' ')[1]}**")
                    df_trend_data = df_analyse[df_analyse['Has_Facture'] == True]
                    df_trend = df_trend_data.groupby(['Sort_Key', 'Periode_Str'])[[col_r, col_s]].sum().reset_index()
                    
                    fig_trend, ax_trend = plt.subplots(figsize=(12, 4))
                    ax_trend.plot(df_trend['Periode_Str'], df_trend[col_r], marker='o', color='#3498db', linewidth=2.5, label='Réalité (Sibelga)')
                    ax_trend.plot(df_trend['Periode_Str'], df_trend[col_s], marker='x', color='#e74c3c', linestyle='--', linewidth=2.5, label='Simulation (Streamlit)')
                    ax_trend.set_ylabel('MWh')
                    ax_trend.legend()
                    st.pyplot(fig_trend)
                    
                    # 4. HEATMAP ARC-EN-CIEL
                    st.markdown(f"**Écarts (MWh) par Membre : {choix_kpi_global.split(' ')[1]}**")
                    st.markdown("*Gris = Pas de facture Sibelga ce mois-là pour ce membre.*")
                    
                    df_analyse['Erreur_Heatmap'] = np.where(df_analyse['Has_Facture'], df_analyse[col_err], np.nan)
                    pivot_heat = df_analyse.pivot(index='Proprietaire', columns='Periode_Str', values='Erreur_Heatmap')
                    
                    colonnes_ordonnees = df_analyse[['Sort_Key', 'Periode_Str']].drop_duplicates().sort_values('Sort_Key')['Periode_Str'].tolist()
                    pivot_heat = pivot_heat.reindex(columns=colonnes_ordonnees)
                    
                    # Palette personnalisée (Violet -> Bleu -> Vert(0) -> Jaune -> Orange -> Rouge)
                    colors_custom = ['#8e44ad', '#2c3e50', '#2980b9', '#27ae60', '#f1c40f', '#e67e22', '#c0392b']
                    cmap_custom = LinearSegmentedColormap.from_list("custom_error", colors_custom)

                    fig_heat, ax_heat = plt.subplots(figsize=(14, max(4, len(pivot_heat)*0.4)))
                    ax_heat.set_facecolor('#ecf0f1') 
                    sns.heatmap(pivot_heat, cmap=cmap_custom, center=0, annot=True, fmt=".2f", ax=ax_heat, cbar_kws={'label': "Erreur (MWh)"}, linewidths=0.5)
                    ax_heat.set_ylabel('')
                    ax_heat.set_xlabel('')
                    st.pyplot(fig_heat)
                    
                    st.divider()

                    # 3. PROFIL INDIVIDUEL ZOOMÉ (Et Boutons Intelligents)
                    st.subheader("👤 Analyse Individuelle")
                    membre_choisi = st.selectbox("Sélectionnez un membre :", sorted(df_analyse['Proprietaire'].unique()))
                    
                    # On filtre et on retire d'office les mois où le membre n'a pas de facture (Zoom)
                    df_indiv = df_analyse[(df_analyse['Proprietaire'] == membre_choisi) & (df_analyse['Has_Facture'] == True)].sort_values('Sort_Key')
                    
                    if not df_indiv.empty:
                        # Logique des boutons intelligents (on cache la prod si réelle ET simulée sont à 0)
                        has_conso = (df_indiv['Reel_Conso_Totale_MWh'].sum() > 0) or (df_indiv['Sim_Conso_Totale_MWh'].sum() > 0)
                        has_prod = (df_indiv['Reel_Prod_Totale_MWh'].sum() > 0) or (df_indiv['Sim_Prod_Totale_MWh'].sum() > 0)
                        
                        options_indiv = []
                        if has_conso:
                            options_indiv.extend(["⚡ Conso Totale", "🤝 Conso Partagée"])
                        if has_prod:
                            options_indiv.extend(["☀️ Prod Totale", "🤝 Prod Partagée"])
                            
                        # Sécurité au cas où tout serait à 0
                        if not options_indiv:
                            options_indiv = ["⚡ Conso Totale"]
                            
                        choix_kpi_indiv = st.radio(f"Indicateur pour {membre_choisi} :", options_indiv, horizontal=True)
                        
                        if choix_kpi_indiv == "⚡ Conso Totale":
                            c_r, c_s = 'Reel_Conso_Totale_MWh', 'Sim_Conso_Totale_MWh'
                        elif choix_kpi_indiv == "☀️ Prod Totale":
                            c_r, c_s = 'Reel_Prod_Totale_MWh', 'Sim_Prod_Totale_MWh'
                        elif choix_kpi_indiv == "🤝 Conso Partagée":
                            c_r, c_s = 'Reel_Conso_Partagee_MWh', 'Sim_Conso_Partagee_MWh'
                        else:
                            c_r, c_s = 'Reel_Prod_Partagee_MWh', 'Sim_Prod_Partagee_MWh'
                        
                        col_i1, col_i2 = st.columns([1, 2])
                        tot_i_r = df_indiv[c_r].sum()
                        err_i_p = ((df_indiv[c_s].sum() - tot_i_r) / tot_i_r * 100) if tot_i_r > 0 else 0
                        
                        col_i1.metric(f"Bilan Annuel", f"{tot_i_r:.2f} MWh", f"{err_i_p:+.1f}% simulé", delta_color="off")
                        
                        fig_indiv, ax_indiv = plt.subplots(figsize=(8, 4))
                        ax_indiv.plot(df_indiv['Periode_Str'], df_indiv[c_r], marker='o', color='#9b59b6', linewidth=2, label='Réalité')
                        ax_indiv.plot(df_indiv['Periode_Str'], df_indiv[c_s], marker='x', color='#f1c40f', linestyle='--', linewidth=2, label='Simulation')
                        ax_indiv.set_ylabel('MWh')
                        ax_indiv.legend()
                        col_i2.pyplot(fig_indiv)
                    else:
                        st.info("Ce membre n'a aucune facture enregistrée sur la période sélectionnée.")

                # =================================================================================================
                # 📥 TÉLÉCHARGEMENT COMMUN
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
