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
st.markdown("Choisissez votre précision, importez vos fichiers, puis explorez les résultats librement.")

# ==========================================
# FONCTIONS DE LECTURE (POUR LE MODE 15-MIN)
# ==========================================
@st.cache_data(show_spinner=False)
def parser_sibelga_15min(fichiers_bytes):
    df_list = []
    for f in fichiers_bytes:
        df_r = pd.read_excel(io.BytesIO(f))
        df_r['Datetime'] = pd.to_datetime(df_r['Date Début'])
        df_r['EAN'] = df_r['EAN'].astype(str).str.replace(' ', '').str.replace(r'\.0$', '', regex=True).str.strip()
        df_r['Volume (kWh)'] = pd.to_numeric(df_r['Volume (kWh)'], errors='coerce').fillna(0)

        df_piv = df_r.pivot_table(index=['Datetime', 'EAN'], columns='Type de volume', values='Volume (kWh)', aggfunc='sum').reset_index()

        for col in ['Consommation Partagée', 'Consommation Réseau', 'Injection Partagée', 'Injection Réseau']:
            if col not in df_piv.columns: df_piv[col] = 0.0

        df_list.append(df_piv)
    return pd.concat(df_list) if df_list else pd.DataFrame()

@st.cache_data(show_spinner=False)
def parser_simu_15min(fichier_bytes):
    df_s = pd.read_csv(io.BytesIO(fichier_bytes))
    
    # GESTION FUSEAUX HORAIRES : Convertit la simu UTC en heure locale Belge
    dt_simu = pd.to_datetime(df_s['Unnamed: 0'])
    if dt_simu.dt.tz is None:
        dt_simu = dt_simu.dt.tz_localize('UTC')
    df_s['Datetime'] = dt_simu.dt.tz_convert('Europe/Brussels').dt.tz_localize(None)

    p_bruts = set(c.split('_')[0] for c in df_s.columns if c not in ['Unnamed: 0', 'Datetime', 'Mois_Simu'])
    tech = {'external', 'grid', 'injection', 'internal', 'remaining', 'residual', 'shared', 'community', 'n', 'pv', 'total', 'self', 'tariff', 'period', 'battery', 'allocation', 'consumed', 'repartition'}
    p_simu = {p.strip() for p in p_bruts if p.strip().lower() not in tech}

    d_list = []
    for p in p_simu:
        temp = pd.DataFrame({'Datetime': df_s['Datetime'], 'Nom_Streamlit': p})
        temp['Sim_Conso_Partagee_MWh'] = df_s.get(f"{p}_shared_volume_from_community", 0) / 4000.0
        temp['Sim_Conso_Totale_MWh'] = df_s.get(f"{p}_residual_consumption_bc", 0) / 4000.0
        
        prod_part = df_s.get(f"{p}_shared_volume_to_community", 0)
        prod_tot = df_s.get(f"{p}_injection_bc", 0)
        temp['Sim_Prod_Partagee_MWh'] = np.abs(prod_part) / 4000.0
        temp['Sim_Prod_Totale_MWh'] = np.abs(prod_tot) / 4000.0
        d_list.append(temp)

    return pd.concat(d_list) if d_list else pd.DataFrame()


# ==========================================
# 1. BARRE LATÉRALE (DYNAMIQUE)
# ==========================================
st.sidebar.header("⚙️ 1. Paramétrage")
mode_precision = st.sidebar.radio("Mode d'analyse :", ["Analyse Mensuelle (Rapide)", "Analyse 15-min (Précise)"])

st.sidebar.header("📁 2. Import des fichiers")
fichier_contacts = st.sidebar.file_uploader("1. Contacts Odoo (Excel/CSV)", type=['xlsx', 'csv'])

# Uploaders conditionnels (Exclusivité)
if mode_precision == "Analyse Mensuelle (Rapide)":
    fichiers_sibelga = st.sidebar.file_uploader("2. Fichiers Sibelga MENSUELS", type=['xlsx'], accept_multiple_files=True)
else:
    fichiers_sibelga = st.sidebar.file_uploader("2. Fichiers Sibelga 15-MIN", type=['xlsx'], accept_multiple_files=True)

fichier_mapping = st.sidebar.file_uploader("3. Fichier de Mapping", type=['xlsx'])
fichier_simu = st.sidebar.file_uploader("4. Simulation Streamlit (CSV)", type=['csv'])


# ==========================================
# 2. MOTEUR DE CALCUL CENTRAL
# ==========================================
if fichier_contacts and fichiers_sibelga and fichier_mapping and fichier_simu:
    
    btn_lancer = st.sidebar.button("🚀 Lancer l'Analyse", type="primary", use_container_width=True)
    
    if btn_lancer or st.session_state.get('trigger_recalc', False):
        if st.session_state.get('trigger_recalc', False):
            st.session_state['trigger_recalc'] = False
            
        with st.spinner("Analyse, fusion et magie temporelle en cours..."):
            try:
                # --- A. MAPPING & CONTACTS (COMMUN) ---
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

                cols_to_merge = ['Ean', 'Groupe_Odoo', 'Nom']
                if 'Entry Point Owner' in df_contacts.columns: cols_to_merge.append('Entry Point Owner')

                # ==========================================
                # SÉPARATION DES MODES DE CALCUL
                # ==========================================
                if mode_precision == "Analyse Mensuelle (Rapide)":
                    
                    # --- B. SIBELGA MENSUEL (BASE CODE) ---
                    df_reels_list = []
                    for fact in fichiers_sibelga:
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

                        if not all([c_date, c_ean, c_vol_part, c_vol_comp, c_inj_part, c_inj_comp]): continue

                        premiere_date = pd.to_datetime(df_r[c_date].dropna().iloc[0])
                        m_encours, y_encours = premiere_date.month, premiere_date.year
                        
                        df_r[c_ean] = df_r[c_ean].astype(str).str.replace(' ','').str.replace(r'\.0$','',regex=True).str.strip()
                        for c in [c_vol_part, c_vol_comp, c_inj_part, c_inj_comp]:
                            if df_r[c].dtype == object: df_r[c] = df_r[c].astype(str).str.replace(',', '.')
                            df_r[c] = pd.to_numeric(df_r[c], errors='coerce').fillna(0)
                            
                        df_agg = df_r.groupby(c_ean)[[c_vol_part, c_vol_comp, c_inj_part, c_inj_comp]].sum().reset_index()
                        df_agg.columns = ['EAN', 'Volume Partagé (kWh)', 'Volume Complémentaire (kWh)', 'Injection Partagée (kWh)', 'Injection Résiduelle (kWh)']
                        
                        df_c = pd.merge(df_agg, df_contacts[cols_to_merge], left_on='EAN', right_on='Ean', how='left')
                        df_c['Prop_Odoo'] = df_c['Groupe_Odoo'].fillna(df_c['Nom']).fillna("Indéfini")
                        
                        df_c['Mapped_EAN'] = df_c['EAN'].map(mapping_ean)
                        df_c['Mapped_EPO'] = df_c['Entry Point Owner'].map(mapping_epo) if 'Entry Point Owner' in df_c.columns else np.nan
                        df_c['Mapped_Groupe'] = df_c['Prop_Odoo'].map(mapping_groupe)
                        df_c['Proprietaire'] = df_c['Mapped_EAN'].fillna(df_c['Mapped_EPO']).fillna(df_c['Mapped_Groupe']).fillna(df_c['Prop_Odoo'])
                        
                        df_c['Reel_Conso_Partagee_MWh'] = df_c['Volume Partagé (kWh)'] / 1000.0
                        df_c['Reel_Conso_Totale_MWh'] = (df_c['Volume Partagé (kWh)'] + df_c['Volume Complémentaire (kWh)']) / 1000.0
                        df_c['Reel_Prod_Partagee_MWh'] = df_c['Injection Partagée (kWh)'] / 1000.0
                        df_c['Reel_Prod_Totale_MWh'] = (df_c['Injection Partagée (kWh)'] + df_c['Injection Résiduelle (kWh)']) / 1000.0
                        
                        df_c['Mois'], df_c['Annee'] = m_encours, y_encours
                        df_c['Sort_Key'] = y_encours * 100 + m_encours
                        df_reels_list.append(df_c)

                    if not df_reels_list:
                        st.error("❌ Aucun fichier Sibelga mensuel n'a pu être lu.")
                        st.stop()

                    df_reels_all = pd.concat(df_reels_list)
                    df_reels_final = df_reels_all.groupby(['Proprietaire', 'Mois', 'Annee', 'Sort_Key'])[['Reel_Conso_Partagee_MWh', 'Reel_Conso_Totale_MWh', 'Reel_Prod_Partagee_MWh', 'Reel_Prod_Totale_MWh']].sum().reset_index()

                    # --- C. SIMULATION MENSUELLE (BASE CODE) ---
                    master_calendar = df_reels_all[['Mois', 'Annee', 'Sort_Key']].drop_duplicates()

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

                    # --- D. FUSION GLOBALE MENSUELLE ---
                    all_props = list(set(df_reels_final['Proprietaire']).union(set(df_sim_final['Proprietaire'])))
                    df_props = pd.DataFrame({'Proprietaire': all_props})
                    df_base = df_props.assign(key=1).merge(master_calendar.assign(key=1), on='key').drop('key', axis=1)

                    df_comparatif = pd.merge(df_base, df_reels_final, on=['Proprietaire', 'Mois', 'Annee', 'Sort_Key'], how='left')
                    df_comparatif['Has_Facture'] = df_comparatif['Reel_Conso_Totale_MWh'].notna()
                    df_comparatif = pd.merge(df_comparatif, df_sim_final, on=['Proprietaire', 'Mois'], how='left')
                    
                    df_comparatif['Date_Courbe'] = pd.to_datetime(df_comparatif['Annee'].astype(str) + '-' + df_comparatif['Mois'].astype(str) + '-01')


                # ==========================================
                # MODE 15-MINUTES (NOUVEAU)
                # ==========================================
                else: 
                    # --- Sibelga 15-min ---
                    f_bytes_sib = [f.getvalue() for f in fichiers_sibelga]
                    df_piv = parser_sibelga_15min(f_bytes_sib)
                    if df_piv.empty:
                        st.error("Format 15-min Sibelga invalide.")
                        st.stop()

                    df_c = pd.merge(df_piv, df_contacts[cols_to_merge], left_on='EAN', right_on='Ean', how='left')
                    df_c['Prop_Odoo'] = df_c['Groupe_Odoo'].fillna(df_c['Nom']).fillna("Indéfini")
                    
                    df_c['Mapped_EAN'] = df_c['EAN'].map(mapping_ean)
                    df_c['Mapped_EPO'] = df_c['Entry Point Owner'].map(mapping_epo) if 'Entry Point Owner' in df_c.columns else np.nan
                    df_c['Mapped_Groupe'] = df_c['Prop_Odoo'].map(mapping_groupe)
                    df_c['Proprietaire'] = df_c['Mapped_EAN'].fillna(df_c['Mapped_EPO']).fillna(df_c['Mapped_Groupe']).fillna(df_c['Prop_Odoo'])

                    df_reels_all = df_c # Pour les alertes "inconnus"
                    df_reels_final = df_c.groupby(['Proprietaire', 'Datetime'])[['Reel_Conso_Partagee_MWh', 'Reel_Conso_Totale_MWh', 'Reel_Prod_Partagee_MWh', 'Reel_Prod_Totale_MWh']].sum().reset_index()

                    # --- Simu 15-min (Ajustement Fuseau Horaire) ---
                    df_sim_raw = parser_simu_15min(fichier_simu.getvalue())
                    p_simu = df_sim_raw['Nom_Streamlit'].unique() if not df_sim_raw.empty else []
                    
                    df_sim_raw['Proprietaire'] = df_sim_raw['Nom_Streamlit'].map(mapping_sim).fillna(df_sim_raw['Nom_Streamlit'])
                    df_sim_final = df_sim_raw.groupby(['Proprietaire', 'Datetime'])[['Sim_Conso_Partagee_MWh', 'Sim_Conso_Totale_MWh', 'Sim_Prod_Partagee_MWh', 'Sim_Prod_Totale_MWh']].sum().reset_index()

                    # --- FUSION EXACTE SUR LE QUART D'HEURE ---
                    df_comparatif = pd.merge(df_reels_final, df_sim_final, on=['Proprietaire', 'Datetime'], how='outer')

                    df_comparatif['Has_Facture'] = df_comparatif['Reel_Conso_Totale_MWh'].notna()
                    df_comparatif['Mois'] = df_comparatif['Datetime'].dt.month
                    df_comparatif['Annee'] = df_comparatif['Datetime'].dt.year
                    df_comparatif['Sort_Key'] = df_comparatif['Annee'] * 100 + df_comparatif['Mois']
                    df_comparatif['Date_Courbe'] = df_comparatif['Datetime'].dt.normalize() # Date sans l'heure pour agrégation journalière


                # --- NETTOYAGE ET ERREURS (COMMUN AUX DEUX MODES) ---
                df_comparatif = df_comparatif[~df_comparatif['Proprietaire'].astype(str).isin(['', '0', 'nan', 'NaN'])]
                df_comparatif = df_comparatif.fillna(0)

                # ALERTES
                alertes = []
                inconnus = df_reels_all[df_reels_all['Prop_Odoo'] == 'Indéfini']['EAN'].unique()
                if len(inconnus) > 0: alertes.append(("error", f"**ALERTE ODOO (EAN facturés mais inconnus) :** {', '.join(inconnus)}"))
                simu_sans_map = set(p_simu) - set(mapping_sim.keys()) if mode_precision == "Analyse 15-min (Précise)" else set(p_simu) - set(mapping_sim.keys())
                if len(simu_sans_map) > 0: alertes.append(("warning", f"**ALERTE MAPPING (Membres Streamlit non traduits) :** {', '.join(simu_sans_map)}"))
                
                m_simules = set(df_sim_final['Proprietaire'])
                m_factures = set(df_reels_final['Proprietaire'])
                simu_jamais_fact = list(m_simules - m_factures)
                fact_jamais_sim = list(m_factures - m_simules)
                
                if fact_jamais_sim: alertes.append(("warning", f"**Facturés mais JAMAIS simulés (Ajoutés avec simu=0) :** {', '.join(fact_jamais_sim)}"))
                if simu_jamais_fact: alertes.append(("warning", f"**Simulés mais SANS AUCUNE facture (Ignorés) :** {', '.join(simu_jamais_fact)}"))
                if not alertes: alertes.append(("success", "✅ Bases de données parfaitement alignées sur la période !"))

                # Erreurs détaillées
                df_comparatif['Erreur_Conso_MWh'] = df_comparatif['Sim_Conso_Totale_MWh'] - df_comparatif['Reel_Conso_Totale_MWh']
                df_comparatif['Erreur_Prod_MWh'] = df_comparatif['Sim_Prod_Totale_MWh'] - df_comparatif['Reel_Prod_Totale_MWh']
                df_comparatif['Erreur_Partage_MWh'] = df_comparatif['Sim_Conso_Partagee_MWh'] - df_comparatif['Reel_Conso_Partagee_MWh']
                
                noms_mois = {1:'Jan', 2:'Fév', 3:'Mar', 4:'Avr', 5:'Mai', 6:'Juin', 7:'Juil', 8:'Août', 9:'Sep', 10:'Oct', 11:'Nov', 12:'Déc'}
                df_comparatif['Periode_Str'] = df_comparatif['Mois'].map(noms_mois) + " " + df_comparatif['Annee'].astype(int).astype(str)

                df_analyse = df_comparatif[~df_comparatif['Proprietaire'].isin(simu_jamais_fact)].copy()

                # SAUVEGARDE EN MEMOIRE
                st.session_state['df_comparatif'] = df_comparatif
                st.session_state['df_analyse'] = df_analyse.sort_values('Sort_Key')
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
    
    df_analyse_brut = st.session_state['df_analyse']
    
    # -----------------------------------------------------
    # AGRÉGATION MENSUELLE SÉCURISÉE POUR LES KPI & VUES GLOBALES
    # -----------------------------------------------------
    df_mensuel_agg = df_analyse_brut.groupby(['Proprietaire', 'Mois', 'Annee', 'Sort_Key', 'Periode_Str']).agg({
        'Reel_Conso_Partagee_MWh': 'sum',
        'Reel_Conso_Totale_MWh': 'sum',
        'Sim_Conso_Partagee_MWh': 'sum',
        'Sim_Conso_Totale_MWh': 'sum',
        'Reel_Prod_Partagee_MWh': 'sum',
        'Reel_Prod_Totale_MWh': 'sum',
        'Sim_Prod_Partagee_MWh': 'sum',
        'Sim_Prod_Totale_MWh': 'sum',
        'Has_Facture': 'max' # True si au moins un 1/4h facturé
    }).reset_index()

    df_mensuel_agg['Erreur_Conso_MWh'] = df_mensuel_agg['Sim_Conso_Totale_MWh'] - df_mensuel_agg['Reel_Conso_Totale_MWh']
    df_mensuel_agg['Erreur_Prod_MWh'] = df_mensuel_agg['Sim_Prod_Totale_MWh'] - df_mensuel_agg['Reel_Prod_Totale_MWh']
    df_mensuel_agg['Erreur_Partage_MWh'] = df_mensuel_agg['Sim_Conso_Partagee_MWh'] - df_mensuel_agg['Reel_Conso_Partagee_MWh']
    
    df_mensuel_agg['Erreur_Conso_%'] = np.where(df_mensuel_agg['Reel_Conso_Totale_MWh'] > 0, (df_mensuel_agg['Erreur_Conso_MWh'] / df_mensuel_agg['Reel_Conso_Totale_MWh']) * 100, np.where(df_mensuel_agg['Sim_Conso_Totale_MWh'] > 0, 100.0, 0.0))
    df_mensuel_agg['Erreur_Prod_%'] = np.where(df_mensuel_agg['Reel_Prod_Totale_MWh'] > 0, (df_mensuel_agg['Erreur_Prod_MWh'] / df_mensuel_agg['Reel_Prod_Totale_MWh']) * 100, np.where(df_mensuel_agg['Sim_Prod_Totale_MWh'] > 0, 100.0, 0.0))
    df_mensuel_agg['Erreur_Partage_%'] = np.where(df_mensuel_agg['Reel_Conso_Partagee_MWh'] > 0, (df_mensuel_agg['Erreur_Partage_MWh'] / df_mensuel_agg['Reel_Conso_Partagee_MWh']) * 100, np.where(df_mensuel_agg['Sim_Conso_Partagee_MWh'] > 0, 100.0, 0.0))
    
    df_mensuel_agg['Abs_Erreur_Conso'] = df_mensuel_agg['Erreur_Conso_MWh'].abs()
    df_mensuel_agg['Abs_Erreur_Prod'] = df_mensuel_agg['Erreur_Prod_MWh'].abs()
    df_mensuel_agg['Abs_Erreur_Conso_%'] = df_mensuel_agg['Erreur_Conso_%'].abs()
    df_mensuel_agg['Abs_Erreur_Prod_%'] = df_mensuel_agg['Erreur_Prod_%'].abs()
    # -----------------------------------------------------

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
        
        df_mensuel = df_mensuel_agg[(df_mensuel_agg['Periode_Str'] == mois_cible_str) & (df_mensuel_agg['Has_Facture'] > 0)].copy()
        
        st.divider()
        st.subheader(f"🌍 Analyse Globale ({mois_cible_str})")
        col_m1, col_m2, col_m3 = st.columns(3)
        
        tot_r_conso = df_mensuel['Reel_Conso_Totale_MWh'].sum()
        tot_s_conso = df_mensuel['Sim_Conso_Totale_MWh'].sum()
        pct_conso = ((tot_s_conso - tot_r_conso) / tot_r_conso * 100) if tot_r_conso > 0 else 0
        
        tot_r_prod = df_mensuel['Reel_Prod_Totale_MWh'].sum()
        tot_s_prod = df_mensuel['Sim_Prod_Totale_MWh'].sum()
        pct_prod = ((tot_s_prod - tot_r_prod) / tot_r_prod * 100) if tot_r_prod > 0 else 0
        
        tot_r_ech = df_mensuel['Reel_Conso_Partagee_MWh'].sum()
        tot_s_ech = df_mensuel['Sim_Conso_Partagee_MWh'].sum()
        pct_ech = ((tot_s_ech - tot_r_ech) / tot_r_ech * 100) if tot_r_ech > 0 else 0
        
        col_m1.metric("⚡ Total Consommé", f"{tot_r_conso:.2f} MWh", f"{pct_conso:+.1f}% (Simu: {tot_s_conso:.2f})", delta_color="off")
        col_m2.metric("☀️ Total Produit", f"{tot_r_prod:.2f} MWh", f"{pct_prod:+.1f}% (Simu: {tot_s_prod:.2f})", delta_color="off")
        col_m3.metric("🤝 Total Échangé", f"{tot_r_ech:.2f} MWh", f"{pct_ech:+.1f}% (Simu: {tot_s_ech:.2f})", delta_color="off")
        
        st.divider()
        st.subheader("📉 Pire dimensionnement (MWh)")
        st.markdown("*Rouge = Surestimé par la simulation*")
        col1, col2 = st.columns(2)
        top10_c = df_mensuel.sort_values(by='Abs_Erreur_Conso', ascending=False).head(10)
        if not top10_c.empty:
            fig1, ax1 = plt.subplots(figsize=(8, 5))
            sns.barplot(data=top10_c, x='Erreur_Conso_MWh', y='Proprietaire', palette=['#e74c3c' if v>0 else '#3498db' for v in top10_c['Erreur_Conso_MWh']], ax=ax1)
            ax1.set_title('CONSOMMATION'); ax1.axvline(0, color='black'); ax1.set_ylabel(''); col1.pyplot(fig1)

        top10_p = df_mensuel.sort_values(by='Abs_Erreur_Prod', ascending=False).head(10)
        top10_p = top10_p[top10_p['Abs_Erreur_Prod'] > 0]
        if not top10_p.empty:
            fig2, ax2 = plt.subplots(figsize=(8, 5))
            sns.barplot(data=top10_p, x='Erreur_Prod_MWh', y='Proprietaire', palette=['#e74c3c' if v>0 else '#3498db' for v in top10_p['Erreur_Prod_MWh']], ax=ax2)
            ax2.set_title('PRODUCTION'); ax2.axvline(0, color='black'); ax2.set_ylabel(''); col2.pyplot(fig2)
            
        st.divider()
        st.subheader("📉 Pire dimensionnement (%)")
        col3, col4 = st.columns(2)
        top10_cp = df_mensuel.sort_values(by='Abs_Erreur_Conso_%', ascending=False).head(10)
        if not top10_cp.empty:
            fig3, ax3 = plt.subplots(figsize=(8, 5))
            sns.barplot(data=top10_cp, x='Erreur_Conso_%', y='Proprietaire', palette=['#e74c3c' if v>0 else '#3498db' for v in top10_cp['Erreur_Conso_%']], ax=ax3)
            ax3.set_title('CONSOMMATION (%)'); ax3.axvline(0, color='black'); ax3.set_ylabel(''); col3.pyplot(fig3)

        top10_pp = df_mensuel.sort_values(by='Abs_Erreur_Prod_%', ascending=False).head(10)
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
            
            df_f = df_mensuel[(df_mensuel[col_r] > 0) | (df_mensuel[col_s] > 0)].copy()
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
        st.subheader("🌍 Bilan Cumulé sur la période")
        
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
        choix_kpi_global = st.radio("Sélectionnez l'indicateur global :", ["⚡ Consommation", "☀️ Production", "🤝 Échange (Partagé)"], horizontal=True)
        
        if choix_kpi_global == "⚡ Consommation":
            col_r, col_s, col_err_mwh, col_err_pct = 'Reel_Conso_Totale_MWh', 'Sim_Conso_Totale_MWh', 'Erreur_Conso_MWh', 'Erreur_Conso_%'
        elif choix_kpi_global == "☀️ Production":
            col_r, col_s, col_err_mwh, col_err_pct = 'Reel_Prod_Totale_MWh', 'Sim_Prod_Totale_MWh', 'Erreur_Prod_MWh', 'Erreur_Prod_%'
        else:
            col_r, col_s, col_err_mwh, col_err_pct = 'Reel_Conso_Partagee_MWh', 'Sim_Conso_Partagee_MWh', 'Erreur_Partage_MWh', 'Erreur_Partage_%'

        n_mois = len(df_mensuel_agg['Sort_Key'].unique())
        fig_width = max(14, n_mois * 0.9)

        df_trend = df_apples.groupby(['Sort_Key', 'Periode_Str'], sort=False)[[col_r, col_s]].sum().reset_index()
        
        fig_trend, ax_trend = plt.subplots(figsize=(fig_width, 4))
        ax_trend.plot(df_trend['Periode_Str'], df_trend[col_r], marker='o', color='#3498db', linewidth=2.5, label='Réalité (Sibelga)')
        ax_trend.plot(df_trend['Periode_Str'], df_trend[col_s], marker='x', color='#e74c3c', linestyle='--', linewidth=2.5, label='Simulation (Streamlit)')
        ax_trend.set_ylabel('MWh')
        ax_trend.legend()
        st.pyplot(fig_trend, use_container_width=False)
        
        st.markdown("---")
        col_h1, col_h2 = st.columns([1, 1])
        with col_h1:
            st.markdown(f"**Écarts par Membre : {choix_kpi_global.split(' ')[1]}**")
        with col_h2:
            choix_unite_heatmap = st.radio("Unité de la Heatmap :", ["MWh", "Pourcentage (%)"], horizontal=True, label_visibility="collapsed")

        col_err_active = col_err_mwh if choix_unite_heatmap == "MWh" else col_err_pct
        format_heat = ".2f" if choix_unite_heatmap == "MWh" else ".0f"
        label_bar = "Erreur (MWh)" if choix_unite_heatmap == "MWh" else "Erreur (%)"

        membres_kpi = df_mensuel_agg.groupby('Proprietaire')[[col_r, col_s]].sum()
        membres_utiles = membres_kpi[(membres_kpi[col_r] > 0) | (membres_kpi[col_s] > 0)].index
        df_heat = df_mensuel_agg[df_mensuel_agg['Proprietaire'].isin(membres_utiles)].copy()
        
        df_heat['Erreur_Heatmap'] = np.where(df_heat['Has_Facture'] > 0, df_heat[col_err_active], np.nan)
        pivot_heat = df_heat.pivot(index='Proprietaire', columns='Periode_Str', values='Erreur_Heatmap')
        colonnes_ordonnees = df_heat[['Sort_Key', 'Periode_Str']].drop_duplicates().sort_values('Sort_Key')['Periode_Str'].tolist()
        pivot_heat = pivot_heat.reindex(columns=colonnes_ordonnees)
        
        colors_custom = ['#8e44ad', '#2c3e50', '#2980b9', '#27ae60', '#f1c40f', '#e67e22', '#c0392b']
        cmap_custom = LinearSegmentedColormap.from_list("custom_error", colors_custom)

        if not pivot_heat.empty:
            fig_heat, ax_heat = plt.subplots(figsize=(fig_width, max(4, len(pivot_heat)*0.4)))
            ax_heat.set_facecolor('#ecf0f1') 
            sns.heatmap(pivot_heat, cmap=cmap_custom, center=0, annot=True, fmt=format_heat, ax=ax_heat, cbar_kws={'label': label_bar}, linewidths=0.5)
            ax_heat.set_ylabel('')
            ax_heat.set_xlabel('')
            st.pyplot(fig_heat, use_container_width=False)
            
        st.divider()

        # ===============================================
        # ANALYSE INDIVIDUELLE (AGRÉGATION JOURNALIÈRE)
        # ===============================================
        st.subheader("👤 Analyse Individuelle")
        membre_choisi = st.selectbox("Sélectionnez un membre :", sorted(df_analyse_brut['Proprietaire'].unique()))
        
        # On repart de df_analyse_brut (qui contient les vraies Date_Courbe) pour filtrer
        df_indiv = df_analyse_brut[(df_analyse_brut['Proprietaire'] == membre_choisi) & (df_analyse_brut['Has_Facture'] == True)].copy()
        
        if not df_indiv.empty:
            # Regroupement par jour !
            df_indiv_jour = df_indiv.groupby('Date_Courbe')[[
                'Reel_Conso_Totale_MWh', 'Sim_Conso_Totale_MWh', 
                'Reel_Prod_Totale_MWh', 'Sim_Prod_Totale_MWh', 
                'Reel_Conso_Partagee_MWh', 'Sim_Conso_Partagee_MWh'
            ]].sum().reset_index()

            has_conso = (df_indiv_jour['Reel_Conso_Totale_MWh'].sum() > 0) or (df_indiv_jour['Sim_Conso_Totale_MWh'].sum() > 0)
            has_prod = (df_indiv_jour['Reel_Prod_Totale_MWh'].sum() > 0) or (df_indiv_jour['Sim_Prod_Totale_MWh'].sum() > 0)
            
            options_indiv = []
            if has_conso: options_indiv.extend(["⚡ Conso Totale", "🤝 Conso Partagée"])
            if has_prod: options_indiv.extend(["☀️ Prod Totale", "🤝 Prod Partagée"])
            if not options_indiv: options_indiv = ["⚡ Conso Totale"]
                
            choix_kpi_indiv = st.radio(f"Indicateur pour {membre_choisi} :", options_indiv, horizontal=True)
            
            if choix_kpi_indiv == "⚡ Conso Totale": c_r, c_s = 'Reel_Conso_Totale_MWh', 'Sim_Conso_Totale_MWh'
            elif choix_kpi_indiv == "☀️ Prod Totale": c_r, c_s = 'Reel_Prod_Totale_MWh', 'Sim_Prod_Totale_MWh'
            elif choix_kpi_indiv == "🤝 Conso Partagée": c_r, c_s = 'Reel_Conso_Partagee_MWh', 'Sim_Conso_Partagee_MWh'
            else: c_r, c_s = 'Reel_Prod_Partagee_MWh', 'Sim_Prod_Partagee_MWh'
            
            col_i1, col_i2 = st.columns([1, 2])
            tot_i_r = df_indiv_jour[c_r].sum()
            err_i_p = ((df_indiv_jour[c_s].sum() - tot_i_r) / tot_i_r * 100) if tot_i_r > 0 else 0
            
            col_i1.metric(f"Bilan de la Période", f"{tot_i_r:.2f} MWh", f"{err_i_p:+.1f}% simulé", delta_color="off")
            
            fig_indiv, ax_indiv = plt.subplots(figsize=(fig_width, 4))
            # On retire les gros points ronds (marker) s'il y a trop de jours pour garder une belle ligne
            use_marker = 'o' if len(df_indiv_jour) < 35 else None
            
            ax_indiv.plot(df_indiv_jour['Date_Courbe'], df_indiv_jour[c_r], marker=use_marker, color='#9b59b6', linewidth=2, label='Réalité')
            ax_indiv.plot(df_indiv_jour['Date_Courbe'], df_indiv_jour[c_s], marker='x' if use_marker else None, color='#f1c40f', linestyle='--', linewidth=2, label='Simulation')
            ax_indiv.set_ylabel('MWh / Jour')
            ax_indiv.legend()
            col_i2.pyplot(fig_indiv, use_container_width=False)
        else:
            st.info("Ce membre n'a aucune facture enregistrée sur la période sélectionnée.")

    # =========================================================
    # 🔗 ÉDITEUR DE MAPPING INTERACTIF
    # =========================================================
    elif vue_choisie == "🔗 Éditeur de Mapping":
        st.divider()
        st.subheader("🛠️ Éditeur de Correspondance (Mapping)")
        
        col_hint1, col_hint2 = st.columns(2)
        with col_hint1:
            liste_simu = st.session_state.get('simu_sans_map', [])
            if liste_simu: st.warning("**Noms Streamlit orphelins (À lier) :**\n\n" + ", ".join(liste_simu))
            else: st.success("✅ Tous les membres de la simulation sont mappés.")
                
        with col_hint2:
            liste_fact = st.session_state.get('fact_jamais_sim', [])
            if liste_fact: st.info("**Noms Odoo facturés mais non simulés :**\n\n" + ", ".join(liste_fact))
            else: st.success("✅ Tous les compteurs facturés ont une simulation.")

        with st.expander("Voir le référentiel des contacts Odoo (Pour copier-coller)"):
            st.dataframe(st.session_state['df_contacts_ref'], use_container_width=True)

        col_config = {"Critère de liaison": st.column_config.SelectboxColumn("Critère de liaison", options=["Contrat d'énergie", "Entry Point Owner", "EAN"], required=True)}
        edited_mapping = st.data_editor(st.session_state['custom_mapping'], num_rows="dynamic", use_container_width=True, column_config=col_config)
        
        if st.button("💾 Enregistrer le Mapping et Recalculer", type="primary"):
            st.session_state['custom_mapping'] = edited_mapping
            st.session_state['trigger_recalc'] = True
            st.rerun()

    # ==========================================
    # BASE DE DONNÉES
    # ==========================================
    st.divider()
    st.subheader("📋 Base de Données Complète")
    df_affichage = st.session_state['df_comparatif'].drop(columns=['Abs_Erreur_Conso', 'Abs_Erreur_Prod', 'Abs_Erreur_Conso_%', 'Abs_Erreur_Prod_%', 'Sort_Key', 'Periode_Str', 'Has_Facture', 'Erreur_Heatmap'], errors='ignore')
    st.dataframe(df_affichage, use_container_width=True)
    
    csv = df_affichage.to_csv(index=False, sep=';', decimal=',').encode('utf-8')
    st.download_button(label="📥 Télécharger le rapport complet pour Excel", data=csv, file_name="Audit_Complet_Donnees.csv", mime="text/csv", type="primary")
