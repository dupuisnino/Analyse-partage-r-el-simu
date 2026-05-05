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

st.title("⚡ Audit Automatique : Réalité vs Simulation (Quart-Horaire)")
st.markdown("Importez vos fichiers Sibelga 15-min, lancez l'analyse, puis explorez les profils de charge exacts.")

# ==========================================
# 1. BARRE LATÉRALE : UPLOADS UNIQUEMENT
# ==========================================
st.sidebar.header("📁 1. Import des fichiers")
fichier_contacts = st.sidebar.file_uploader("1. Contacts Odoo (Excel/CSV)", type=['xlsx', 'csv'])
fichier_factures = st.sidebar.file_uploader("2. Fichiers Sibelga 15-min (Excel)", type=['xlsx'], accept_multiple_files=True)
fichier_mapping = st.sidebar.file_uploader("3. Fichier de Mapping", type=['xlsx'])
fichier_simu = st.sidebar.file_uploader("4. Simulation Streamlit 15-min (CSV)", type=['csv'])


# ==========================================
# 2. MOTEUR DE CALCUL CENTRAL
# ==========================================
if fichier_contacts and fichier_factures and fichier_mapping and fichier_simu:
    
    btn_lancer = st.sidebar.button("🚀 Lancer l'Analyse 15-min", type="primary", use_container_width=True)
    
    if btn_lancer or st.session_state.get('trigger_recalc', False):
        
        if st.session_state.get('trigger_recalc', False):
            st.session_state['trigger_recalc'] = False
            
        with st.spinner("Analyse quart-horaire et alignement des profils de charge en cours (Cela peut prendre quelques secondes)..."):
            try:
                # --- A. MAPPING & CONTACTS ---
                if 'custom_mapping' not in st.session_state or btn_lancer:
                    df_mapping_raw = pd.read_excel(fichier_mapping)
                    if 'Critère de liaison' not in df_mapping_raw.columns:
                        df_mapping_raw['Critère de liaison'] = "Contrat d'énergie"
                    else:
                        df_mapping_raw['Critère de liaison'] = df_mapping_raw['Critère de liaison'].fillna("Contrat d'énergie")
                        df_mapping_raw['Critère de liaison'] = df_mapping_raw['Critère de liaison'].replace({"Contrat d'energie": "Contrat d'énergie"})
                    st.session_state['custom_mapping'] = df_mapping_raw
                else:
                    df_mapping_raw = st.session_state['custom_mapping']

                df_mapping = df_mapping_raw.copy()
                df_mapping['Nom_Streamlit'] = df_mapping['Nom_Streamlit'].astype(str).str.split(',')
                df_mapping = df_mapping.explode('Nom_Streamlit')
                df_mapping['Nom_Reel'] = df_mapping['Nom_Reel'].astype(str).str.split(',')
                df_mapping = df_mapping.explode('Nom_Reel')
                df_mapping['Nom_Streamlit'] = df_mapping['Nom_Streamlit'].str.strip()
                df_mapping['Nom_Reel'] = df_mapping['Nom_Reel'].str.strip()
                
                count_sim = df_mapping.groupby('Nom_Streamlit')['Nom_Reel'].transform('nunique')
                df_mapping['Super_Groupe'] = np.where(count_sim > 1, df_mapping['Nom_Streamlit'], df_mapping['Nom_Reel'])
                
                mapping_sim = dict(zip(df_mapping['Nom_Streamlit'], df_mapping['Super_Groupe']))
                mapping_ean = dict(zip(df_mapping[df_mapping['Critère de liaison'] == 'EAN']['Nom_Reel'], df_mapping[df_mapping['Critère de liaison'] == 'EAN']['Super_Groupe']))
                mapping_epo = dict(zip(df_mapping[df_mapping['Critère de liaison'] == 'Entry Point Owner']['Nom_Reel'], df_mapping[df_mapping['Critère de liaison'] == 'Entry Point Owner']['Super_Groupe']))
                mask_groupe = ~df_mapping['Critère de liaison'].isin(['EAN', 'Entry Point Owner'])
                mapping_groupe = dict(zip(df_mapping[mask_groupe]['Nom_Reel'], df_mapping[mask_groupe]['Super_Groupe']))

                df_contacts = pd.read_excel(fichier_contacts, dtype=str)
                est_un_titre = df_contacts['Ean'].isna() & df_contacts['Nom'].astype(str).str.contains(r'\(\d+\)$')
                df_contacts['Groupe_Odoo'] = np.where(est_un_titre, df_contacts['Nom'].astype(str).str.replace(r' \(\d+\)$', '', regex=True).str.strip(), np.nan)
                df_contacts['Groupe_Odoo'] = df_contacts['Groupe_Odoo'].ffill()
                df_contacts = df_contacts.dropna(subset=['Ean']).copy() 
                df_contacts['Ean'] = df_contacts['Ean'].astype(str).str.replace(' ', '').str.replace(r'\.0$', '', regex=True).str.strip()
                df_contacts = df_contacts.drop_duplicates(subset=['Ean'], keep='first')
                if 'Entry Point Owner' in df_contacts.columns:
                    df_contacts['Entry Point Owner'] = df_contacts['Entry Point Owner'].astype(str).replace(['nan', 'NaN'], np.nan).str.strip()

                # --- B. LECTURE DES FICHIERS SIBELGA 15-MIN ---
                df_reels_list = []
                for fact in fichier_factures:
                    fact.seek(0)
                    df_r = pd.read_excel(fact)
                    
                    # Nettoyage et formatage du fichier 15-min Sibelga
                    df_r['Datetime'] = pd.to_datetime(df_r['Date Début'])
                    df_r['EAN'] = df_r['EAN'].astype(str).str.replace(' ', '').str.replace(r'\.0$', '', regex=True).str.strip()
                    df_r['Volume (kWh)'] = pd.to_numeric(df_r['Volume (kWh)'], errors='coerce').fillna(0)
                    
                    # Pivot pour avoir les types de volume en colonnes
                    df_piv = df_r.pivot_table(index=['Datetime', 'EAN'], columns='Type de volume', values='Volume (kWh)', aggfunc='sum').reset_index()
                    
                    # Sécurité : créer les colonnes si elles n'existent pas dans le mois en cours
                    for col in ['Consommation Partagée', 'Consommation Réseau', 'Injection Partagée', 'Injection Réseau']:
                        if col not in df_piv.columns:
                            df_piv[col] = 0.0
                            
                    cols_to_merge = ['Ean', 'Groupe_Odoo', 'Nom']
                    if 'Entry Point Owner' in df_contacts.columns:
                        cols_to_merge.append('Entry Point Owner')
                        
                    df_c = pd.merge(df_piv, df_contacts[cols_to_merge], left_on='EAN', right_on='Ean', how='left')
                    df_c['Prop_Odoo'] = df_c['Groupe_Odoo'].fillna(df_c['Nom']).fillna("Inconnu")
                    
                    df_c['Mapped_EAN'] = df_c['EAN'].map(mapping_ean)
                    df_c['Mapped_EPO'] = df_c['Entry Point Owner'].map(mapping_epo) if 'Entry Point Owner' in df_c.columns else np.nan
                    df_c['Mapped_Groupe'] = df_c['Prop_Odoo'].map(mapping_groupe)
                    
                    df_c['Proprietaire'] = df_c['Mapped_EAN'].fillna(df_c['Mapped_EPO']).fillna(df_c['Mapped_Groupe']).fillna(df_c['Prop_Odoo'])
                    
                    # Conversion en MWh
                    df_c['Reel_Conso_Partagee_MWh'] = df_c['Consommation Partagée'] / 1000.0
                    df_c['Reel_Conso_Totale_MWh'] = (df_c['Consommation Partagée'] + df_c['Consommation Réseau']) / 1000.0
                    df_c['Reel_Prod_Partagee_MWh'] = df_c['Injection Partagée'] / 1000.0
                    df_c['Reel_Prod_Totale_MWh'] = (df_c['Injection Partagée'] + df_c['Injection Réseau']) / 1000.0
                    
                    df_reels_list.append(df_c[['Datetime', 'Proprietaire', 'Reel_Conso_Partagee_MWh', 'Reel_Conso_Totale_MWh', 'Reel_Prod_Partagee_MWh', 'Reel_Prod_Totale_MWh']])

                if not df_reels_list:
                    st.error("❌ Aucun fichier Sibelga n'a pu être lu.")
                    st.stop()

                df_reels_all = pd.concat(df_reels_list)
                # Agrégation 15-min finale pour la réalité
                df_reels_final = df_reels_all.groupby(['Proprietaire', 'Datetime']).sum().reset_index()

                # --- C. TRAITEMENT VECTORISÉ DE LA SIMULATION 15-MIN ---
                df_s = pd.read_csv(fichier_simu)
                # On aligne les dates (suppression du fuseau horaire si présent pour correspondre à Sibelga)
                df_s['Datetime'] = pd.to_datetime(df_s['Unnamed: 0'], utc=True).dt.tz_localize(None)

                # Extraction dynamique des membres
                p_bruts = set(c.split('_')[0] for c in df_s.columns if c not in ['Unnamed: 0', 'Datetime'])
                tech_words = {'external', 'grid', 'injection', 'internal', 'remaining', 'residual', 'shared', 'community', 'n', 'pv', 'total', 'self', 'tariff', 'period', 'battery'}
                p_simu = {p.strip() for p in p_bruts if p.strip().lower() not in tech_words}

                # Construction rapide du dataframe de simulation
                d_simu_list = []
                for p in p_simu:
                    temp = pd.DataFrame({'Datetime': df_s['Datetime'], 'Nom_Streamlit': p})
                    temp['Sim_Conso_Partagee_MWh'] = df_s.get(f"{p}_shared_volume_from_community", 0) / 4000.0
                    temp['Sim_Conso_Totale_MWh'] = df_s.get(f"{p}_residual_consumption_bc", 0) / 4000.0
                    
                    # Sécurisation des valeurs de production (valeur absolue)
                    prod_part = df_s.get(f"{p}_shared_volume_to_community", 0)
                    prod_tot = df_s.get(f"{p}_injection_bc", 0)
                    if isinstance(prod_part, pd.Series): prod_part = prod_part.abs()
                    if isinstance(prod_tot, pd.Series): prod_tot = prod_tot.abs()
                        
                    temp['Sim_Prod_Partagee_MWh'] = prod_part / 4000.0
                    temp['Sim_Prod_Totale_MWh'] = prod_tot / 4000.0
                    d_simu_list.append(temp)

                df_sim_agg = pd.concat(d_simu_list)
                df_sim_agg['Proprietaire'] = df_sim_agg['Nom_Streamlit'].map(mapping_sim).fillna(df_sim_agg['Nom_Streamlit'])
                df_sim_final = df_sim_agg.groupby(['Proprietaire', 'Datetime'])[['Sim_Conso_Partagee_MWh', 'Sim_Conso_Totale_MWh', 'Sim_Prod_Partagee_MWh', 'Sim_Prod_Totale_MWh']].sum().reset_index()

                # --- D. FUSION GLOBALE EXACTE (15-MIN) ---
                # On fusionne sur Proprietaire ET Datetime
                df_comparatif = pd.merge(df_reels_final, df_sim_final, on=['Proprietaire', 'Datetime'], how='outer')
                
                # On détermine la présence d'une facture si Sibelga a une ligne pour ce moment
                df_comparatif['Has_Facture'] = df_comparatif['Reel_Conso_Totale_MWh'].notna()
                df_comparatif = df_comparatif[~df_comparatif['Proprietaire'].astype(str).isin(['', '0', 'nan', 'NaN', 'Inconnu', 'Indéfini'])]
                df_comparatif = df_comparatif.fillna(0)

                # Recréation des repères temporels pour les vues globales
                df_comparatif['Mois'] = df_comparatif['Datetime'].dt.month
                df_comparatif['Annee'] = df_comparatif['Datetime'].dt.year
                df_comparatif['Sort_Key'] = df_comparatif['Annee'] * 100 + df_comparatif['Mois']

                # ALERTES
                alertes = []
                simu_sans_map = p_simu - set(mapping_sim.keys())
                if len(simu_sans_map) > 0: alertes.append(("warning", f"**ALERTE MAPPING (Membres Streamlit non traduits) :** {', '.join(simu_sans_map)}"))
                m_simules = set(df_sim_final['Proprietaire'])
                m_factures = set(df_reels_final['Proprietaire'])
                simu_jamais_fact = list(m_simules - m_factures)
                fact_jamais_sim = list(m_factures - m_simules)
                if fact_jamais_sim: alertes.append(("warning", f"**Présents chez Sibelga mais JAMAIS simulés :** {', '.join(fact_jamais_sim)}"))
                if simu_jamais_fact: alertes.append(("warning", f"**Simulés mais INCONNUS chez Sibelga :** {', '.join(simu_jamais_fact)}"))
                if not alertes: alertes.append(("success", "✅ Bases de données parfaitement alignées !"))

                # Erreurs Quart-Horaires
                df_comparatif['Erreur_Conso_MWh'] = df_comparatif['Sim_Conso_Totale_MWh'] - df_comparatif['Reel_Conso_Totale_MWh']
                df_comparatif['Erreur_Prod_MWh'] = df_comparatif['Sim_Prod_Totale_MWh'] - df_comparatif['Reel_Prod_Totale_MWh']
                df_comparatif['Erreur_Partage_MWh'] = df_comparatif['Sim_Conso_Partagee_MWh'] - df_comparatif['Reel_Conso_Partagee_MWh']

                noms_mois = {1:'Jan', 2:'Fév', 3:'Mar', 4:'Avr', 5:'Mai', 6:'Juin', 7:'Juil', 8:'Août', 9:'Sep', 10:'Oct', 11:'Nov', 12:'Déc'}
                df_comparatif['Periode_Str'] = df_comparatif['Mois'].map(noms_mois) + " " + df_comparatif['Annee'].astype(int).astype(str)

                df_analyse = df_comparatif[~df_comparatif['Proprietaire'].isin(simu_jamais_fact)].copy()
                df_analyse = df_analyse.sort_values(['Proprietaire', 'Datetime'])

                # SAUVEGARDE EN MEMOIRE
                st.session_state['df_comparatif'] = df_comparatif
                st.session_state['df_analyse'] = df_analyse
                st.session_state['alertes'] = alertes
                st.session_state['simu_sans_map'] = list(simu_sans_map)
                st.session_state['fact_jamais_sim'] = list(fact_jamais_sim)
                
                cols_ref = ['Groupe_Odoo', 'Entry Point Owner', 'Ean'] if 'Entry Point Owner' in df_contacts.columns else ['Groupe_Odoo', 'Nom', 'Ean']
                st.session_state['df_contacts_ref'] = df_contacts[cols_ref].copy()
                
                st.session_state['calcul_termine'] = True

            except Exception as e:
                st.error(f"❌ Une erreur s'est produite lors de l'analyse : {e}")

# ==========================================
# 3. INTERFACE POST-CALCUL
# ==========================================
if st.session_state.get('calcul_termine', False):
    
    df_analyse = st.session_state['df_analyse']
    df_comparatif = st.session_state['df_comparatif']
    
    # Agrégation mensuelle pour conserver les vues macro
    df_mensuel_agg = df_analyse.groupby(['Proprietaire', 'Mois', 'Annee', 'Sort_Key', 'Periode_Str']).sum(numeric_only=True).reset_index()
    # On recalcule les pourcentages macro
    df_mensuel_agg['Erreur_Conso_%'] = np.where(df_mensuel_agg['Reel_Conso_Totale_MWh'] > 0, (df_mensuel_agg['Erreur_Conso_MWh'] / df_mensuel_agg['Reel_Conso_Totale_MWh']) * 100, 0.0)
    df_mensuel_agg['Erreur_Prod_%'] = np.where(df_mensuel_agg['Reel_Prod_Totale_MWh'] > 0, (df_mensuel_agg['Erreur_Prod_MWh'] / df_mensuel_agg['Reel_Prod_Totale_MWh']) * 100, 0.0)
    df_mensuel_agg['Erreur_Partage_%'] = np.where(df_mensuel_agg['Reel_Conso_Partagee_MWh'] > 0, (df_mensuel_agg['Erreur_Partage_MWh'] / df_mensuel_agg['Reel_Conso_Partagee_MWh']) * 100, 0.0)
    df_mensuel_agg['Abs_Erreur_Conso'] = df_mensuel_agg['Erreur_Conso_MWh'].abs()
    df_mensuel_agg['Abs_Erreur_Prod'] = df_mensuel_agg['Erreur_Prod_MWh'].abs()
    df_mensuel_agg['Abs_Erreur_Conso_%'] = df_mensuel_agg['Erreur_Conso_%'].abs()
    df_mensuel_agg['Abs_Erreur_Prod_%'] = df_mensuel_agg['Erreur_Prod_%'].abs()

    # Affichage des alertes
    st.subheader("🚨 Alertes d'Audit")
    for type_alerte, msg in st.session_state['alertes']:
        if type_alerte == "error": st.error(msg)
        elif type_alerte == "warning": st.warning(msg)
        else: st.success(msg)
    
    st.divider()
    
    col_choix1, col_choix2 = st.columns([1, 2])
    vue_choisie = col_choix1.radio("Sélectionnez le mode d'exploration :", ["📆 Vue Globale / Annuelle", "📅 Vue Mensuelle (Détail)", "🔗 Éditeur de Mapping"], index=0)

    # =========================================================
    # 📅 VUE MENSUELLE (Filtrage sur 1 mois)
    # =========================================================
    if vue_choisie == "📅 Vue Mensuelle (Détail)":
        periodes_dispos = df_mensuel_agg[['Sort_Key', 'Periode_Str']].drop_duplicates().sort_values('Sort_Key')
        mois_cible_str = col_choix2.selectbox("Sélectionnez le mois à analyser en détail :", periodes_dispos['Periode_Str'].tolist())
        
        df_m = df_mensuel_agg[(df_mensuel_agg['Periode_Str'] == mois_cible_str) & (df_mensuel_agg['Has_Facture'] > 0)].copy()
        
        st.divider()
        st.subheader(f"🌍 Analyse Globale ({mois_cible_str})")
        col_m1, col_m2, col_m3 = st.columns(3)
        
        tot_r_conso = df_m['Reel_Conso_Totale_MWh'].sum()
        tot_s_conso = df_m['Sim_Conso_Totale_MWh'].sum()
        pct_conso = ((tot_s_conso - tot_r_conso) / tot_r_conso * 100) if tot_r_conso > 0 else 0
        
        tot_r_prod = df_m['Reel_Prod_Totale_MWh'].sum()
        tot_s_prod = df_m['Sim_Prod_Totale_MWh'].sum()
        pct_prod = ((tot_s_prod - tot_r_prod) / tot_r_prod * 100) if tot_r_prod > 0 else 0
        
        tot_r_ech = df_m['Reel_Conso_Partagee_MWh'].sum()
        tot_s_ech = df_m['Sim_Conso_Partagee_MWh'].sum()
        pct_ech = ((tot_s_ech - tot_r_ech) / tot_r_ech * 100) if tot_r_ech > 0 else 0
        
        col_m1.metric("⚡ Total Consommé", f"{tot_r_conso:.2f} MWh", f"{pct_conso:+.1f}% (Simu: {tot_s_conso:.2f})", delta_color="off")
        col_m2.metric("☀️ Total Produit", f"{tot_r_prod:.2f} MWh", f"{pct_prod:+.1f}% (Simu: {tot_s_prod:.2f})", delta_color="off")
        col_m3.metric("🤝 Total Échangé", f"{tot_r_ech:.2f} MWh", f"{pct_ech:+.1f}% (Simu: {tot_s_ech:.2f})", delta_color="off")
        
        st.divider()
        st.subheader("📊 Vue globale : Réalité vs Simulation")
        fig_nuage, axes = plt.subplots(2, 2, figsize=(16, 14))
        for idx, (col_r, col_s, title, color) in enumerate([('Reel_Conso_Totale_MWh', 'Sim_Conso_Totale_MWh', '1. Conso Totale', '#3498db'), ('Reel_Prod_Totale_MWh', 'Sim_Prod_Totale_MWh', '2. Prod Totale', '#2ecc71'), ('Reel_Conso_Partagee_MWh', 'Sim_Conso_Partagee_MWh', '3. Conso Échangée', '#9b59b6'), ('Reel_Prod_Partagee_MWh', 'Sim_Prod_Partagee_MWh', '4. Prod Échangée', '#f1c40f')]):
            row, col = idx // 2, idx % 2
            df_f = df_m[(df_m[col_r] > 0) | (df_m[col_s] > 0)].copy()
            axes[row, col].scatter(df_f[col_r], df_f[col_s], color=color, alpha=0.8, edgecolor='black', s=60)
            m = max(df_f[col_r].max(), df_f[col_s].max())
            if pd.notna(m) and m > 0: axes[row, col].plot([0, m], [0, m], 'r--', label='Idéal')
            axes[row, col].set_title(title, fontweight='bold'); axes[row, col].set_xlabel('Sibelga'); axes[row, col].set_ylabel('Streamlit')
            
            df_f['Err_Abs_Locale'] = (df_f[col_s] - df_f[col_r]).abs()
            top5 = df_f.sort_values(by='Err_Abs_Locale', ascending=False).head(5)
            for _, r_data in top5.iterrows():
                axes[row, col].annotate(r_data['Proprietaire'][:15], (r_data[col_r], r_data[col_s]), fontsize=9, xytext=(5,5), textcoords='offset points')
                
        plt.tight_layout(); st.pyplot(fig_nuage)


    # =========================================================
    # 📆 VUE GLOBALE ANNUELLE
    # =========================================================
    elif vue_choisie == "📆 Vue Globale / Annuelle":
        st.divider()
        st.subheader("🌍 Bilan Cumulé sur la période (Apples to Apples)")
        
        df_apples = df_mensuel_agg[df_mensuel_agg['Has_Facture'] > 0]
        
        col_a1, col_a2, col_a3 = st.columns(3)
        t_rc = df_apples['Reel_Conso_Totale_MWh'].sum()
        t_sc = df_apples['Sim_Conso_Totale_MWh'].sum()
        pc_c = ((t_sc - t_rc) / t_rc * 100) if t_rc > 0 else 0
        t_rp = df_apples['Reel_Prod_Totale_MWh'].sum()
        t_sp = df_apples['Sim_Prod_Totale_MWh'].sum()
        pc_p = ((t_sp - t_rp) / t_rp * 100) if t_rp > 0 else 0
        t_re = df_apples['Reel_Conso_Partagee_MWh'].sum()
        t_se = df_apples['Sim_Conso_Partagee_MWh'].sum()
        pc_e = ((t_se - t_re) / t_re * 100) if t_re > 0 else 0
        
        col_a1.metric("⚡ Total Consommé (Cumulé)", f"{t_rc:.2f} MWh", f"{pc_c:+.1f}% (Simu: {t_sc:.2f})", delta_color="off")
        col_a2.metric("☀️ Total Produit (Cumulé)", f"{t_rp:.2f} MWh", f"{pc_p:+.1f}% (Simu: {t_sp:.2f})", delta_color="off")
        col_a3.metric("🤝 Total Échangé (Cumulé)", f"{t_re:.2f} MWh", f"{pc_e:+.1f}% (Simu: {t_se:.2f})", delta_color="off")
        st.divider()

        st.subheader("📈 Visualisation Détaillée Globale")
        choix_kpi_global = st.radio("Sélectionnez l'indicateur global à analyser :", ["⚡ Consommation", "☀️ Production", "🤝 Échange (Partagé)"], horizontal=True)
        
        if choix_kpi_global == "⚡ Consommation":
            col_r, col_s, col_err_mwh, col_err_pct = 'Reel_Conso_Totale_MWh', 'Sim_Conso_Totale_MWh', 'Erreur_Conso_MWh', 'Erreur_Conso_%'
        elif choix_kpi_global == "☀️ Production":
            col_r, col_s, col_err_mwh, col_err_pct = 'Reel_Prod_Totale_MWh', 'Sim_Prod_Totale_MWh', 'Erreur_Prod_MWh', 'Erreur_Prod_%'
        else:
            col_r, col_s, col_err_mwh, col_err_pct = 'Reel_Conso_Partagee_MWh', 'Sim_Conso_Partagee_MWh', 'Erreur_Partage_MWh', 'Erreur_Partage_%'

        df_trend = df_apples.groupby(['Sort_Key', 'Periode_Str'], sort=False)[[col_r, col_s]].sum().reset_index()
        fig_trend, ax_trend = plt.subplots(figsize=(14, 4))
        ax_trend.plot(df_trend['Periode_Str'], df_trend[col_r], marker='o', color='#3498db', linewidth=2.5, label='Réalité (Sibelga)')
        ax_trend.plot(df_trend['Periode_Str'], df_trend[col_s], marker='x', color='#e74c3c', linestyle='--', linewidth=2.5, label='Simulation (Streamlit)')
        ax_trend.set_ylabel('MWh')
        ax_trend.legend()
        st.pyplot(fig_trend, use_container_width=False)
        
        st.markdown("---")
        st.subheader("👤 Analyse Individuelle (Profil de Charge Quart-Horaire)")
        membre_choisi = st.selectbox("Sélectionnez un membre :", sorted(df_analyse['Proprietaire'].unique()))
        
        # Isolation des données 15-min pour le membre
        df_indiv = df_analyse[(df_analyse['Proprietaire'] == membre_choisi) & (df_analyse['Has_Facture'] == True)].copy()
        
        if not df_indiv.empty:
            choix_kpi_indiv = st.radio(f"Indicateur pour {membre_choisi} :", ["⚡ Consommation", "☀️ Production", "🤝 Échange (Partagé)"], horizontal=True)
            if choix_kpi_indiv == "⚡ Consommation":
                c_r, c_s = 'Reel_Conso_Totale_MWh', 'Sim_Conso_Totale_MWh'
            elif choix_kpi_indiv == "☀️ Production":
                c_r, c_s = 'Reel_Prod_Totale_MWh', 'Sim_Prod_Totale_MWh'
            else:
                c_r, c_s = 'Reel_Conso_Partagee_MWh', 'Sim_Conso_Partagee_MWh'
            
            # --- Graphique de Courbe de Charge Interactif ---
            df_indiv_chart = df_indiv[['Datetime', c_r, c_s]].set_index('Datetime')
            df_indiv_chart.rename(columns={c_r: 'Réalité (Sibelga)', c_s: 'Simulation'}, inplace=True)
            st.line_chart(df_indiv_chart, use_container_width=True)
            # ------------------------------------------------
            
        else:
            st.info("Ce membre n'a aucune donnée quart-horaire sur la période sélectionnée.")

    # =========================================================
    # 🔗 ÉDITEUR DE MAPPING INTERACTIF
    # =========================================================
    elif vue_choisie == "🔗 Éditeur de Mapping":
        st.divider()
        st.subheader("🛠️ Éditeur de Correspondance (Mapping)")
        
        col_hint1, col_hint2 = st.columns(2)
        with col_hint1:
            liste_simu = st.session_state.get('simu_sans_map', [])
            if liste_simu: st.warning("**Noms Streamlit orphelins :**\n\n" + ", ".join(liste_simu))
            else: st.success("✅ Tous les membres de la simulation sont mappés.")
                
        with col_hint2:
            liste_fact = st.session_state.get('fact_jamais_sim', [])
            if liste_fact: st.info("**Noms Odoo facturés mais non simulés :**\n\n" + ", ".join(liste_fact))
            else: st.success("✅ Tous les compteurs facturés ont une simulation.")

        with st.expander("Voir le référentiel des contacts Odoo"):
            st.dataframe(st.session_state['df_contacts_ref'], use_container_width=True)

        col_config = {
            "Critère de liaison": st.column_config.SelectboxColumn(
                "Critère de liaison", options=["Contrat d'énergie", "Entry Point Owner", "EAN"], required=True
            )
        }

        edited_mapping = st.data_editor(st.session_state['custom_mapping'], num_rows="dynamic", use_container_width=True, column_config=col_config)
        
        if st.button("💾 Enregistrer le Mapping et Recalculer", type="primary"):
            st.session_state['custom_mapping'] = edited_mapping
            st.session_state['trigger_recalc'] = True
            st.rerun()
