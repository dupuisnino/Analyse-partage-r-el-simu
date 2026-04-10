import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
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
# BARRE LATÉRALE : UPLOADS & PARAMÈTRES
# ==========================================
st.sidebar.header("📁 1. Import des fichiers")
fichier_contacts = st.sidebar.file_uploader("1. Contacts Odoo (Excel/CSV)", type=['xlsx', 'csv'])

# L'interface change en fonction du bouton radio !
if mode_analyse == "📅 Mensuel (Contrôle de facture)":
    fichier_factures = st.sidebar.file_uploader("2. Fichier Sibelga (Excel)", type=['xlsx'], accept_multiple_files=False)
else:
    fichier_factures = st.sidebar.file_uploader("2. Fichiers Sibelga (Glissez les 12 mois)", type=['xlsx'], accept_multiple_files=True)

fichier_mapping = st.sidebar.file_uploader("3. Fichier de Mapping (Excel)", type=['xlsx'])
fichier_simu = st.sidebar.file_uploader("4. Simulation Streamlit (CSV)", type=['csv'])

# ==========================================
# VERIFICATION DES COLONNES SIBELGA
# ==========================================
col_ean_sel, col_vol_part_sel, col_vol_comp_sel, col_inj_part_sel, col_inj_comp_sel, col_date_sel = None, None, None, None, None, None

# On prend le premier fichier Sibelga pour détecter les colonnes
first_facture = None
if fichier_factures:
    first_facture = fichier_factures[0] if isinstance(fichier_factures, list) else fichier_factures

if first_facture:
    st.sidebar.header("🔧 2. Vérification des colonnes")
    
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

    col_date_sel = st.sidebar.selectbox("Colonne Date (Début)", options_colonnes, index=idx_date)
    col_ean_sel = st.sidebar.selectbox("Colonne EAN", options_colonnes, index=idx_ean)
    col_vol_part_sel = st.sidebar.selectbox("Consommation Partagée", options_colonnes, index=idx_vol_part)
    col_vol_comp_sel = st.sidebar.selectbox("Consommation Résiduelle/Réseau", options_colonnes, index=idx_vol_comp)
    col_inj_part_sel = st.sidebar.selectbox("Injection Partagée", options_colonnes, index=idx_inj_part)
    col_inj_comp_sel = st.sidebar.selectbox("Injection Résiduelle (Réseau)", options_colonnes, index=idx_inj_comp)


# ==========================================
# MOTEUR D'ANALYSE PRINCIPAL
# ==========================================
if fichier_contacts and fichier_factures and fichier_mapping and fichier_simu:
    if st.button("🚀 Lancer le calcul", type="primary", use_container_width=True):
        
        if "--- À sélectionner ---" in [col_ean_sel, col_vol_part_sel, col_vol_comp_sel, col_inj_part_sel, col_inj_comp_sel, col_date_sel]:
            st.error("❌ Oups ! Certaines colonnes Sibelga n'ont pas pu être trouvées. Veuillez les sélectionner dans le menu de gauche.")
            st.stop()
            
        with st.spinner("Analyse et fusion des bases de données en cours..."):
            try:
                # ---------------------------------------------------------
                # 0. MAPPING BIDIRECTIONNEL
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

                # ---------------------------------------------------------
                # 1. CONTACTS ODOO
                # ---------------------------------------------------------
                df_contacts = pd.read_excel(fichier_contacts, dtype=str)
                est_un_titre = df_contacts['Ean'].isna() & df_contacts['Nom'].astype(str).str.contains(r'\(\d+\)$')
                df_contacts['Groupe_Odoo'] = np.where(est_un_titre, df_contacts['Nom'].astype(str).str.replace(r' \(\d+\)$', '', regex=True).str.strip(), np.nan)
                df_contacts['Groupe_Odoo'] = df_contacts['Groupe_Odoo'].ffill()
                df_contacts = df_contacts.dropna(subset=['Ean']).copy() 
                df_contacts['Ean'] = df_contacts['Ean'].astype(str).str.replace(' ', '').str.replace(r'\.0$', '', regex=True).str.strip()
                df_contacts = df_contacts.drop_duplicates(subset=['Ean'], keep='first')
                
                # ---------------------------------------------------------
                # 2. FACTURES SIBELGA (Gère 1 ou plusieurs fichiers)
                # ---------------------------------------------------------
                factures_list = fichier_factures if isinstance(fichier_factures, list) else [fichier_factures]
                df_reels_complet_list = []
                
                for fact in factures_list:
                    fact.seek(0)
                    df_reels = pd.read_excel(fact, dtype=str)
                    
                    # Extraction du mois pour ce fichier précis
                    fact.seek(0)
                    df_dates = pd.read_excel(fact, nrows=5)
                    premiere_date = df_dates[col_date_sel].dropna().iloc[0]
                    mois_en_cours = pd.to_datetime(premiere_date).month

                    df_reels[col_ean_sel] = df_reels[col_ean_sel].astype(str).str.replace(' ', '').str.replace(r'\.0$', '', regex=True).str.strip()
                    colonnes_vol = [col_vol_part_sel, col_vol_comp_sel, col_inj_part_sel, col_inj_comp_sel]
                    
                    for col in colonnes_vol:
                        if df_reels[col].dtype == object:
                            df_reels[col] = df_reels[col].astype(str).str.replace(',', '.')
                        df_reels[col] = pd.to_numeric(df_reels[col], errors='coerce').fillna(0)
                        
                    df_reels_agg = df_reels.groupby(col_ean_sel)[colonnes_vol].sum().reset_index()
                    df_reels_agg = df_reels_agg.rename(columns={
                        col_ean_sel: 'EAN', col_vol_part_sel: 'Volume Partagé (kWh)',
                        col_vol_comp_sel: 'Volume Complémentaire (kWh)', col_inj_part_sel: 'Injection Partagée (kWh)',
                        col_inj_comp_sel: 'Injection Résiduelle (kWh)'
                    })
                    
                    df_reels_c = pd.merge(df_reels_agg, df_contacts[['Ean', 'Groupe_Odoo', 'Nom']], left_on='EAN', right_on='Ean', how='left')
                    df_reels_c['Proprietaire_Odoo'] = df_reels_c['Groupe_Odoo'].fillna(df_reels_c['Nom']).fillna("Inconnu")
                    df_reels_c['Proprietaire'] = df_reels_c['Proprietaire_Odoo'].map(mapping_reel).fillna(df_reels_c['Proprietaire_Odoo'])
                    
                    df_reels_c['Reel_Conso_Partagee_MWh'] = df_reels_c['Volume Partagé (kWh)'] / 1000.0
                    df_reels_c['Reel_Conso_Totale_MWh'] = (df_reels_c['Volume Partagé (kWh)'] + df_reels_c['Volume Complémentaire (kWh)']) / 1000.0
                    df_reels_c['Reel_Prod_Partagee_MWh'] = df_reels_c['Injection Partagée (kWh)'] / 1000.0
                    df_reels_c['Reel_Prod_Totale_MWh'] = (df_reels_c['Injection Partagée (kWh)'] + df_reels_c['Injection Résiduelle (kWh)']) / 1000.0
                    df_reels_c['Mois'] = mois_en_cours
                    
                    df_reels_complet_list.append(df_reels_c)

                df_reels_all = pd.concat(df_reels_complet_list)
                df_reels_final = df_reels_all.groupby(['Proprietaire', 'Mois'])[['Reel_Conso_Partagee_MWh', 'Reel_Conso_Totale_MWh', 'Reel_Prod_Partagee_MWh', 'Reel_Prod_Totale_MWh']].sum().reset_index()

                # ---------------------------------------------------------
                # 3. SIMULATION STREAMLIT
                # ---------------------------------------------------------
                df_sim_p = pd.read_csv(fichier_simu)
                dates = pd.to_datetime(df_sim_p['Unnamed: 0'])
                df_sim_p['Mois_Simu'] = dates.dt.month
                
                # On ne garde que les mois qui ont été trouvés dans les factures Sibelga
                mois_presents_sibelga = df_reels_all['Mois'].unique().tolist()
                df_sim_p = df_sim_p[df_sim_p['Mois_Simu'].isin(mois_presents_sibelga)]

                participants_bruts = set(col.split('_')[0] for col in df_sim_p.columns if col not in ['Unnamed: 0', 'Mois_Simu'])
                mots_techniques = {'external', 'grid', 'injection', 'internal', 'remaining', 'residual', 'shared', 'community', 'n'}
                participants_simu = {p.strip() for p in participants_bruts if p.strip().lower() not in mots_techniques}
                
                donnees_simu = []
                for mois_en_cours, group in df_sim_p.groupby('Mois_Simu'):
                    sommes_simu = group.sum(numeric_only=True)
                    for p in participants_simu:
                        donnees_simu.append({
                            'Mois': mois_en_cours,
                            'Nom_Streamlit': p,
                            'Sim_Conso_Partagee_MWh': sommes_simu.get(f"{p}_shared_volume_from_community", 0) / 4000.0,
                            'Sim_Conso_Totale_MWh': sommes_simu.get(f"{p}_residual_consumption_bc", 0) / 4000.0,
                            'Sim_Prod_Partagee_MWh': abs(sommes_simu.get(f"{p}_shared_volume_to_community", 0)) / 4000.0,
                            'Sim_Prod_Totale_MWh': abs(sommes_simu.get(f"{p}_injection_bc", 0)) / 4000.0
                        })
                df_sim_agg = pd.DataFrame(donnees_simu)
                df_sim_agg['Proprietaire'] = df_sim_agg['Nom_Streamlit'].map(mapping_sim).fillna(df_sim_agg['Nom_Streamlit'])
                df_sim_final = df_sim_agg.groupby(['Proprietaire', 'Mois'])[['Sim_Conso_Partagee_MWh', 'Sim_Conso_Totale_MWh', 'Sim_Prod_Partagee_MWh', 'Sim_Prod_Totale_MWh']].sum().reset_index()

                # ---------------------------------------------------------
                # 4. FUSION GLOBALE & AUDIT
                # ---------------------------------------------------------
                df_comparatif = pd.merge(df_reels_final, df_sim_final, on=['Proprietaire', 'Mois'], how='outer', indicator=True)
                df_comparatif = df_comparatif[~df_comparatif['Proprietaire'].astype(str).isin(['', '0', 'nan', 'NaN', 'Inconnu', 'Indéfini'])]
                df_comparatif['Has_Facture'] = df_comparatif['_merge'].isin(['both', 'left_only'])

                st.subheader("🚨 Alertes d'Audit")
                eans_inconnus = df_reels_all[df_reels_all['Proprietaire_Odoo'] == 'Inconnu']['EAN'].unique()
                if len(eans_inconnus) > 0: st.error(f"**ALERTE ODOO (EAN facturés mais inconnus dans contacts) :** {', '.join(eans_inconnus)}")
                
                simu_sans_mapping = participants_simu - set(mapping_sim.keys())
                if len(simu_sans_mapping) > 0: st.warning(f"**ALERTE MAPPING (Membres Streamlit non traduits) :** {', '.join(simu_sans_mapping)}")

                membres_simules = set(df_sim_final['Proprietaire'])
                membres_factures = set(df_reels_final['Proprietaire'])
                simu_sans_reel = list(membres_simules - membres_factures)
                reel_sans_simu = list(membres_factures - membres_simules)

                if reel_sans_simu: st.warning(f"**Facturés mais JAMAIS simulés :** {', '.join(reel_sans_simu)}")
                if simu_sans_reel: st.warning(f"**Simulés mais SANS AUCUNE facture Sibelga sur la période :** {', '.join(simu_sans_reel)} *(Ils seront exclus des graphiques)*")
                
                if len(eans_inconnus) == 0 and len(simu_sans_mapping) == 0 and not reel_sans_simu and not simu_sans_reel:
                    st.success("✅ Aucun problème détecté. Les bases de données sont parfaitement alignées !")

                df_comparatif = df_comparatif.drop(columns=['_merge']).fillna(0)
                
                df_comparatif['Erreur_Conso_MWh'] = df_comparatif['Sim_Conso_Totale_MWh'] - df_comparatif['Reel_Conso_Totale_MWh']
                df_comparatif['Erreur_Prod_MWh'] = df_comparatif['Sim_Prod_Totale_MWh'] - df_comparatif['Reel_Prod_Totale_MWh']
                df_comparatif['Abs_Erreur_Conso'] = df_comparatif['Erreur_Conso_MWh'].abs()
                df_comparatif['Abs_Erreur_Prod'] = df_comparatif['Erreur_Prod_MWh'].abs()

                df_comparatif['Erreur_Conso_%'] = np.where(df_comparatif['Reel_Conso_Totale_MWh'] > 0, (df_comparatif['Erreur_Conso_MWh'] / df_comparatif['Reel_Conso_Totale_MWh']) * 100, np.where(df_comparatif['Sim_Conso_Totale_MWh'] > 0, 100.0, 0.0))
                df_comparatif['Erreur_Prod_%'] = np.where(df_comparatif['Reel_Prod_Totale_MWh'] > 0, (df_comparatif['Erreur_Prod_MWh'] / df_comparatif['Reel_Prod_Totale_MWh']) * 100, np.where(df_comparatif['Sim_Prod_Totale_MWh'] > 0, 100.0, 0.0))
                df_comparatif['Abs_Erreur_Conso_%'] = df_comparatif['Erreur_Conso_%'].abs()
                df_comparatif['Abs_Erreur_Prod_%'] = df_comparatif['Erreur_Prod_%'].abs()
                df_comparatif = df_comparatif.round(3)

                # Base saine : on exclut ceux qui n'ont jamais eu de facture de l'année
                df_analyse = df_comparatif[~df_comparatif['Proprietaire'].isin(simu_sans_reel)].copy()
                noms_mois = {1:'Jan', 2:'Fév', 3:'Mar', 4:'Avr', 5:'Mai', 6:'Juin', 7:'Juil', 8:'Août', 9:'Sep', 10:'Oct', 11:'Nov', 12:'Déc'}


                # ==============================================================================
                # 🎨 AFFICHAGE CONDITIONNEL : MENSUEL OU ANNUEL
                # ==============================================================================
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

                if mode_analyse == "📆 Annuel (Saisonnalité & Bilan)":
                    # --- VUE ANNUELLE ---
                    
                    # 1. Courbe de tendance globale
                    st.subheader("📈 Saisonnalité et Tendance Globale")
                    df_trend = df_analyse.groupby('Mois')[['Reel_Conso_Totale_MWh', 'Sim_Conso_Totale_MWh']].sum().reset_index().sort_values('Mois')
                    df_trend['Mois_Nom'] = df_trend['Mois'].map(noms_mois)
                    
                    fig_trend, ax_trend = plt.subplots(figsize=(12, 4))
                    ax_trend.plot(df_trend['Mois_Nom'], df_trend['Reel_Conso_Totale_MWh'], marker='o', color='#3498db', linewidth=2.5, label='Réalité (Sibelga)')
                    ax_trend.plot(df_trend['Mois_Nom'], df_trend['Sim_Conso_Totale_MWh'], marker='x', color='#e74c3c', linestyle='--', linewidth=2.5, label='Simulation (Streamlit)')
                    ax_trend.set_ylabel('Énergie Totale (MWh)', fontweight='bold')
                    ax_trend.legend()
                    st.pyplot(fig_trend)
                    st.divider()

                    # 2. Carte de Chaleur (Heatmap)
                    st.subheader("🗺️ Carte de Chaleur des Erreurs (%)")
                    st.markdown("*Une case **Grise** indique que le membre n'avait pas de facture Sibelga sur ce mois.*")
                    
                    # Remplacement magique par NaN pour les mois sans facture pour déclencher le gris
                    df_analyse['Erreur_Heatmap'] = np.where(df_analyse['Has_Facture'], df_analyse['Erreur_Conso_%'], np.nan)
                    pivot_heat = df_analyse.pivot(index='Proprietaire', columns='Mois', values='Erreur_Heatmap')
                    pivot_heat.rename(columns=noms_mois, inplace=True)
                    
                    fig_heat, ax_heat = plt.subplots(figsize=(14, max(4, len(pivot_heat)*0.4)))
                    ax_heat.set_facecolor('#ecf0f1') # Couleur grise pour les cases vides
                    sns.heatmap(pivot_heat, cmap='coolwarm', center=0, annot=True, fmt=".0f", ax=ax_heat, cbar_kws={'label': "Erreur % (Sim vs Reel)"}, linewidths=0.5)
                    ax_heat.set_ylabel('')
                    ax_heat.set_xlabel('')
                    st.pyplot(fig_heat)
                    st.divider()

                    # 3. Profil Individuel
                    st.subheader("👤 Profil Individuel du Membre")
                    membres_liste = sorted(df_analyse['Proprietaire'].unique())
                    membre_choisi = st.selectbox("Sélectionnez un membre pour analyser son année :", membres_liste)
                    
                    df_indiv = df_analyse[df_analyse['Proprietaire'] == membre_choisi].sort_values('Mois')
                    df_indiv['Mois_Nom'] = df_indiv['Mois'].map(noms_mois)
                    
                    col_i1, col_i2 = st.columns([1, 2])
                    
                    tot_i_reel = df_indiv['Reel_Conso_Totale_MWh'].sum()
                    tot_i_sim = df_indiv['Sim_Conso_Totale_MWh'].sum()
                    err_i_pct = ((tot_i_sim - tot_i_reel) / tot_i_reel * 100) if tot_i_reel > 0 else 0
                    
                    col_i1.metric(f"Bilan Annuel Consommation", f"{tot_i_reel:.2f} MWh", f"{err_i_pct:+.1f}% d'erreur simulée", delta_color="off")
                    
                    fig_indiv, ax_indiv = plt.subplots(figsize=(8, 4))
                    ax_indiv.plot(df_indiv['Mois_Nom'], df_indiv['Reel_Conso_Totale_MWh'], marker='o', color='#9b59b6', label='Consommation Réelle')
                    ax_indiv.plot(df_indiv['Mois_Nom'], df_indiv['Sim_Conso_Totale_MWh'], marker='x', color='#f1c40f', linestyle='--', label='Consommation Simulée')
                    ax_indiv.set_ylabel('MWh')
                    ax_indiv.legend()
                    col_i2.pyplot(fig_indiv)

                else:
                    # --- VUE MENSUELLE CLASSIQUE (L'ancien Dashboard) ---
                    # Comme c'est Mensuel, on fusionne sur le seul mois disponible pour les barres
                    df_mensuel = df_analyse.groupby('Proprietaire')[['Reel_Conso_Totale_MWh', 'Sim_Conso_Totale_MWh', 'Reel_Prod_Totale_MWh', 'Sim_Prod_Totale_MWh', 'Erreur_Conso_MWh', 'Erreur_Prod_MWh', 'Erreur_Conso_%', 'Erreur_Prod_%', 'Abs_Erreur_Conso', 'Abs_Erreur_Prod', 'Abs_Erreur_Conso_%', 'Abs_Erreur_Prod_%']].sum().reset_index()

                    st.subheader("📉 Pire dimensionnement (%)")
                    col3, col4 = st.columns(2)
                    df_pire_conso_pct = df_mensuel.sort_values(by='Abs_Erreur_Conso_%', ascending=False).head(10).copy()
                    if not df_pire_conso_pct.empty:
                        fig_bar_conso_pct, ax3 = plt.subplots(figsize=(8, 5))
                        sns.barplot(data=df_pire_conso_pct, x='Erreur_Conso_%', y='Proprietaire', palette=['#e74c3c' if val > 0 else '#3498db' for val in df_pire_conso_pct['Erreur_Conso_%']], ax=ax3)
                        ax3.set_title('CONSOMMATION (%)', fontweight='bold')
                        ax3.axvline(0, color='black', linewidth=1); ax3.set_ylabel('')
                        col3.pyplot(fig_bar_conso_pct)

                    df_pire_prod_pct = df_mensuel.sort_values(by='Abs_Erreur_Prod_%', ascending=False).head(10).copy()
                    df_pire_prod_pct = df_pire_prod_pct[df_pire_prod_pct['Abs_Erreur_Prod_%'] > 0]
                    if not df_pire_prod_pct.empty:
                        fig_bar_prod_pct, ax4 = plt.subplots(figsize=(8, 5))
                        sns.barplot(data=df_pire_prod_pct, x='Erreur_Prod_%', y='Proprietaire', palette=['#e74c3c' if val > 0 else '#3498db' for val in df_pire_prod_pct['Erreur_Prod_%']], ax=ax4)
                        ax4.set_title('PRODUCTION (%)', fontweight='bold')
                        ax4.axvline(0, color='black', linewidth=1); ax4.set_ylabel('')
                        col4.pyplot(fig_bar_prod_pct)

                    st.divider()
                    st.subheader("📊 Vue globale : Réalité vs Simulation")
                    fig_nuage, axes = plt.subplots(2, 2, figsize=(16, 14))
                    
                    df_c_tot = df_mensuel[(df_mensuel['Reel_Conso_Totale_MWh'] > 0) | (df_mensuel['Sim_Conso_Totale_MWh'] > 0)]
                    axes[0, 0].scatter(df_c_tot['Reel_Conso_Totale_MWh'], df_c_tot['Sim_Conso_Totale_MWh'], color='#3498db', alpha=0.8, edgecolor='black', s=60)
                    m = max(df_c_tot['Reel_Conso_Totale_MWh'].max(), df_c_tot['Sim_Conso_Totale_MWh'].max())
                    if pd.notna(m) and m > 0: axes[0, 0].plot([0, m], [0, m], 'r--')
                    axes[0, 0].set_title('1. Consommation Totale (MWh)'); axes[0, 0].set_xlabel('Réalité (Sibelga)'); axes[0, 0].set_ylabel('Simulation (Streamlit)')
                    
                    df_p_tot = df_mensuel[(df_mensuel['Reel_Prod_Totale_MWh'] > 0) | (df_mensuel['Sim_Prod_Totale_MWh'] > 0)]
                    axes[0, 1].scatter(df_p_tot['Reel_Prod_Totale_MWh'], df_p_tot['Sim_Prod_Totale_MWh'], color='#2ecc71', alpha=0.8, edgecolor='black', s=60)
                    m = max(df_p_tot['Reel_Prod_Totale_MWh'].max(), df_p_tot['Sim_Prod_Totale_MWh'].max())
                    if pd.notna(m) and m > 0: axes[0, 1].plot([0, m], [0, m], 'r--')
                    axes[0, 1].set_title('2. Production Totale (MWh)'); axes[0, 1].set_xlabel('Réalité (Sibelga)'); axes[0, 1].set_ylabel('Simulation (Streamlit)')

                    plt.tight_layout()
                    st.pyplot(fig_nuage)


                # ---------------------------------------------------------
                # FIN : TELECHARGEMENT GLOBAL (Vaut pour Mensuel & Annuel)
                # ---------------------------------------------------------
                st.divider()
                st.subheader("📋 Base de Données Complète")
                colonnes_a_retirer = ['Abs_Erreur_Conso', 'Abs_Erreur_Prod', 'Abs_Erreur_Conso_%', 'Abs_Erreur_Prod_%', 'Has_Facture']
                df_affichage = df_comparatif.drop(columns=colonnes_a_retirer)
                st.dataframe(df_affichage, use_container_width=True)
                
                csv = df_affichage.to_csv(index=False, sep=';', decimal=',').encode('utf-8')
                st.download_button(
                    label="📥 Télécharger le rapport complet pour Excel",
                    data=csv,
                    file_name="Audit_Dashboard_Data.csv",
                    mime="text/csv",
                    type="primary"
                )

            except Exception as e:
                st.error(f"❌ Une erreur s'est produite lors de l'analyse : {e}")

else:
    st.info("👈 Veuillez choisir un mode d'analyse et importer les fichiers dans le menu de gauche pour démarrer.")
