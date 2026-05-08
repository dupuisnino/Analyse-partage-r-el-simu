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
st.markdown("Choisissez votre niveau de précision, importez vos fichiers, et explorez les résultats.")

# ==========================================
# FONCTIONS DE TRAITEMENT (CACHÉES & VECTORISÉES)
# ==========================================

@st.cache_data(show_spinner=False)
def traiter_sibelga_mensuel(fichiers_bytes):
    df_list = []
    for f in fichiers_bytes:
        df_r = pd.read_excel(io.BytesIO(f), dtype=str)
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
            df_r[c] = pd.to_numeric(df_r[c].astype(str).str.replace(',', '.'), errors='coerce').fillna(0)
            
        df_agg = df_r.groupby(c_ean)[[c_vol_part, c_vol_comp, c_inj_part, c_inj_comp]].sum().reset_index()
        df_agg.columns = ['EAN', 'Volume Partagé (kWh)', 'Volume Complémentaire (kWh)', 'Injection Partagée (kWh)', 'Injection Résiduelle (kWh)']
        df_agg['Mois'], df_agg['Annee'] = m_encours, y_encours
        df_list.append(df_agg)
    return pd.concat(df_list) if df_list else pd.DataFrame()

@st.cache_data(show_spinner=False)
def traiter_sibelga_15min(fichiers_bytes):
    df_list = []
    for f in fichiers_bytes:
        df_r = pd.read_excel(io.BytesIO(f))
        
        # Le fichier 1/4h Sibelga est déjà à l'heure locale
        df_r['Datetime'] = pd.to_datetime(df_r['Date Début'])
        df_r['EAN'] = df_r['EAN'].astype(str).str.replace(' ', '').str.replace(r'\.0$', '', regex=True).str.strip()
        df_r['Volume (kWh)'] = pd.to_numeric(df_r['Volume (kWh)'], errors='coerce').fillna(0)
        
        # Pivot vectorisé
        df_piv = df_r.pivot_table(index=['Datetime', 'EAN'], columns='Type de volume', values='Volume (kWh)', aggfunc='sum').reset_index()
        
        for col in ['Consommation Partagée', 'Consommation Réseau', 'Injection Partagée', 'Injection Réseau']:
            if col not in df_piv.columns: df_piv[col] = 0.0
            
        df_piv.rename(columns={
            'Consommation Partagée': 'Volume Partagé (kWh)',
            'Consommation Réseau': 'Volume Complémentaire (kWh)',
            'Injection Partagée': 'Injection Partagée (kWh)',
            'Injection Réseau': 'Injection Résiduelle (kWh)'
        }, inplace=True)
        
        df_list.append(df_piv)
    return pd.concat(df_list) if df_list else pd.DataFrame()

@st.cache_data(show_spinner=False)
def traiter_simu_universelle(fichier_bytes, mapping_sim):
    """ Gère la simulation 15-min (UTC vers Europe/Brussels) """
    df_s = pd.read_csv(io.BytesIO(fichier_bytes))
    
    # 1. GESTION DU CHANGEMENT D'HEURE BELGE
    dt_simu = pd.to_datetime(df_s['Unnamed: 0'])
    if dt_simu.dt.tz is None:
        dt_simu = dt_simu.dt.tz_localize('UTC') # On considère la simu brute comme universelle
    
    # Conversion en heure belge exacte
    df_s['Datetime'] = dt_simu.dt.tz_convert('Europe/Brussels').dt.tz_localize(None)
    
    # 2. EXTRACTION DES MEMBRES
    p_bruts = set(c.split('_')[0] for c in df_s.columns if c not in ['Unnamed: 0', 'Datetime'])
    tech = {'external', 'grid', 'injection', 'internal', 'remaining', 'residual', 'shared', 'community', 'n', 'pv', 'total', 'self', 'tariff', 'period', 'battery', 'allocation', 'consumed', 'repartition'}
    p_simu = {p.strip() for p in p_bruts if p.strip().lower() not in tech}
    
    d_list = []
    for p in p_simu:
        temp = pd.DataFrame({'Datetime': df_s['Datetime'], 'Nom_Streamlit': p})
        temp['Sim_Conso_Partagee_MWh'] = df_s.get(f"{p}_shared_volume_from_community", 0) / 4000.0
        temp['Sim_Conso_Totale_MWh'] = df_s.get(f"{p}_residual_consumption_bc", 0) / 4000.0
        
        prod_part = df_s.get(f"{p}_shared_volume_to_community", 0)
        prod_tot = df_s.get(f"{p}_injection_bc", 0)
        if isinstance(prod_part, pd.Series): prod_part = prod_part.abs()
        if isinstance(prod_tot, pd.Series): prod_tot = prod_tot.abs()
            
        temp['Sim_Prod_Partagee_MWh'] = prod_part / 4000.0
        temp['Sim_Prod_Totale_MWh'] = prod_tot / 4000.0
        d_list.append(temp)
        
    df_sim = pd.concat(d_list)
    df_sim['Proprietaire'] = df_sim['Nom_Streamlit'].map(mapping_sim).fillna(df_sim['Nom_Streamlit'])
    # Agrégation par Propriétaire et Datetime au cas où le mapping fusionne 2 noms
    df_sim_final = df_sim.groupby(['Proprietaire', 'Datetime']).sum(numeric_only=True).reset_index()
    
    return df_sim_final, p_simu


# ==========================================
# 1. BARRE LATÉRALE DYNAMIQUE
# ==========================================
st.sidebar.header("⚙️ 1. Paramétrage")
mode_precision = st.sidebar.radio("Précision de l'audit :", ["Analyse Mensuelle (Rapide)", "Analyse 15-min (Précise)"])

st.sidebar.header("📁 2. Import des fichiers")
fichier_contacts = st.sidebar.file_uploader("A. Contacts Odoo (Excel/CSV)", type=['xlsx', 'csv'])

# Uploaders conditionnels (Exclusivité)
if mode_precision == "Analyse Mensuelle (Rapide)":
    fichiers_sibelga = st.sidebar.file_uploader("B. Fichiers Sibelga MENSUELS", type=['xlsx'], accept_multiple_files=True)
else:
    fichiers_sibelga = st.sidebar.file_uploader("B. Fichiers Sibelga 15-MIN", type=['xlsx'], accept_multiple_files=True)

fichier_mapping = st.sidebar.file_uploader("C. Fichier de Mapping", type=['xlsx'])
fichier_simu = st.sidebar.file_uploader("D. Simulation Streamlit (Toujours 15-min)", type=['csv'])


# ==========================================
# 2. MOTEUR DE CALCUL CENTRAL
# ==========================================
if fichier_contacts and fichiers_sibelga and fichier_mapping and fichier_simu:
    
    btn_lancer = st.sidebar.button("🚀 Lancer l'Analyse", type="primary", use_container_width=True)
    
    if btn_lancer or st.session_state.get('trigger_recalc', False):
        if st.session_state.get('trigger_recalc', False): st.session_state['trigger_recalc'] = False
            
        with st.spinner("Alignement des fuseaux horaires et fusion des données en cours..."):
            try:
                # --- A. MAPPING ---
                if 'custom_mapping' not in st.session_state or btn_lancer:
                    df_mapping_raw = pd.read_excel(fichier_mapping)
                    df_mapping_raw['Critère de liaison'] = df_mapping_raw.get('Critère de liaison', "Contrat d'énergie").fillna("Contrat d'énergie")
                    st.session_state['custom_mapping'] = df_mapping_raw
                else:
                    df_mapping_raw = st.session_state['custom_mapping']

                df_map = df_mapping_raw.copy()
                df_map['Nom_Streamlit'] = df_map['Nom_Streamlit'].astype(str).str.split(',').explode().str.strip()
                df_map['Nom_Reel'] = df_map['Nom_Reel'].astype(str).str.split(',').explode().str.strip()
                
                mapping_sim = dict(zip(df_map['Nom_Streamlit'], df_map['Nom_Reel']))
                mapping_ean = dict(zip(df_map[df_map['Critère de liaison'] == 'EAN']['Nom_Reel'], df_map[df_map['Critère de liaison'] == 'EAN']['Nom_Reel']))
                mapping_epo = dict(zip(df_map[df_map['Critère de liaison'] == 'Entry Point Owner']['Nom_Reel'], df_map[df_map['Critère de liaison'] == 'Entry Point Owner']['Nom_Reel']))
                mask_g = ~df_map['Critère de liaison'].isin(['EAN', 'Entry Point Owner'])
                mapping_groupe = dict(zip(df_map[mask_g]['Nom_Reel'], df_map[mask_g]['Nom_Reel']))

                # --- B. CONTACTS ---
                df_contacts = pd.read_excel(fichier_contacts, dtype=str)
                df_contacts['Ean'] = df_contacts['Ean'].astype(str).str.replace(' ', '').str.replace(r'\.0$', '', regex=True).str.strip()
                if 'Entry Point Owner' in df_contacts.columns:
                    df_contacts['Entry Point Owner'] = df_contacts['Entry Point Owner'].astype(str).replace(['nan', 'NaN'], np.nan).str.strip()

                # --- C. LECTURE SIBELGA SELON LE MODE ---
                f_bytes = [f.getvalue() for f in fichiers_sibelga]
                if mode_precision == "Analyse Mensuelle (Rapide)":
                    df_sibelga_base = traiter_sibelga_mensuel(f_bytes)
                else:
                    df_sibelga_base = traiter_sibelga_15min(f_bytes)

                if df_sibelga_base.empty:
                    st.error("❌ Impossible de lire les fichiers Sibelga avec ce format.")
                    st.stop()

                # --- D. APPLICATION DU MAPPING SUR SIBELGA ---
                cols_to_merge = ['Ean', 'Groupe_Odoo', 'Nom'] if 'Entry Point Owner' not in df_contacts.columns else ['Ean', 'Groupe_Odoo', 'Nom', 'Entry Point Owner']
                df_c = pd.merge(df_sibelga_base, df_contacts[cols_to_merge], left_on='EAN', right_on='Ean', how='left')
                df_c['Prop_Odoo'] = df_c['Groupe_Odoo'].fillna(df_c['Nom']).fillna("Indéfini")
                
                df_c['Mapped_EAN'] = df_c['EAN'].map(mapping_ean)
                df_c['Mapped_EPO'] = df_c['Entry Point Owner'].map(mapping_epo) if 'Entry Point Owner' in df_c.columns else np.nan
                df_c['Mapped_Groupe'] = df_c['Prop_Odoo'].map(mapping_groupe)
                df_c['Proprietaire'] = df_c['Mapped_EAN'].fillna(df_c['Mapped_EPO']).fillna(df_c['Mapped_Groupe']).fillna(df_c['Prop_Odoo'])
                
                df_c['Reel_Conso_Partagee_MWh'] = df_c['Volume Partagé (kWh)'] / 1000.0
                df_c['Reel_Conso_Totale_MWh'] = (df_c['Volume Partagé (kWh)'] + df_c['Volume Complémentaire (kWh)']) / 1000.0
                df_c['Reel_Prod_Partagee_MWh'] = df_c['Injection Partagée (kWh)'] / 1000.0
                df_c['Reel_Prod_Totale_MWh'] = (df_c['Injection Partagée (kWh)'] + df_c['Injection Résiduelle (kWh)']) / 1000.0

                # --- E. LECTURE DE LA SIMULATION ---
                df_sim_base, p_simu = traiter_simu_universelle(fichier_simu.getvalue(), mapping_sim)

                # --- F. FUSION SELON LE MODE ---
                if mode_precision == "Analyse Mensuelle (Rapide)":
                    df_c_final = df_c.groupby(['Proprietaire', 'Mois', 'Annee']).sum(numeric_only=True).reset_index()
                    
                    # On agrège la simulation au mois
                    df_sim_base['Mois'] = df_sim_base['Datetime'].dt.month
                    df_sim_base['Annee'] = df_sim_base['Datetime'].dt.year
                    df_sim_final = df_sim_base.groupby(['Proprietaire', 'Mois', 'Annee']).sum(numeric_only=True).reset_index()
                    
                    df_comparatif = pd.merge(df_c_final, df_sim_final, on=['Proprietaire', 'Mois', 'Annee'], how='outer')
                    df_comparatif['Date_Courbe'] = pd.to_datetime(df_comparatif['Annee'].astype(str) + '-' + df_comparatif['Mois'].astype(str) + '-01')
                    
                else: # Mode 15-min
                    df_c_final = df_c.groupby(['Proprietaire', 'Datetime']).sum(numeric_only=True).reset_index()
                    
                    # Ligne par ligne (1/4h)
                    df_comparatif = pd.merge(df_c_final, df_sim_base, on=['Proprietaire', 'Datetime'], how='outer')
                    
                    df_comparatif['Mois'] = df_comparatif['Datetime'].dt.month
                    df_comparatif['Annee'] = df_comparatif['Datetime'].dt.year
                    
                    # Pour alléger les graphiques d'évolution, on crée un marqueur "Jour"
                    df_comparatif['Date_Courbe'] = df_comparatif['Datetime'].dt.normalize()

                # --- G. GESTION DES ERREURS & NETTOYAGE ---
                df_comparatif['Has_Facture'] = df_comparatif['Reel_Conso_Totale_MWh'].notna()
                df_comparatif = df_comparatif[~df_comparatif['Proprietaire'].astype(str).isin(['', '0', 'nan', 'NaN'])]
                df_comparatif = df_comparatif.fillna(0)
                
                df_comparatif['Sort_Key'] = df_comparatif['Annee'] * 100 + df_comparatif['Mois']
                
                df_comparatif['Erreur_Conso_MWh'] = df_comparatif['Sim_Conso_Totale_MWh'] - df_comparatif['Reel_Conso_Totale_MWh']
                df_comparatif['Erreur_Prod_MWh'] = df_comparatif['Sim_Prod_Totale_MWh'] - df_comparatif['Reel_Prod_Totale_MWh']
                df_comparatif['Erreur_Partage_MWh'] = df_comparatif['Sim_Conso_Partagee_MWh'] - df_comparatif['Reel_Conso_Partagee_MWh']
                
                df_comparatif['Erreur_Conso_%'] = np.where(df_comparatif['Reel_Conso_Totale_MWh'] > 0, (df_comparatif['Erreur_Conso_MWh'] / df_comparatif['Reel_Conso_Totale_MWh']) * 100, np.where(df_comparatif['Sim_Conso_Totale_MWh'] > 0, 100.0, 0.0))
                df_comparatif['Erreur_Prod_%'] = np.where(df_comparatif['Reel_Prod_Totale_MWh'] > 0, (df_comparatif['Erreur_Prod_MWh'] / df_comparatif['Reel_Prod_Totale_MWh']) * 100, np.where(df_comparatif['Sim_Prod_Totale_MWh'] > 0, 100.0, 0.0))
                df_comparatif['Erreur_Partage_%'] = np.where(df_comparatif['Reel_Conso_Partagee_MWh'] > 0, (df_comparatif['Erreur_Partage_MWh'] / df_comparatif['Reel_Conso_Partagee_MWh']) * 100, np.where(df_comparatif['Sim_Conso_Partagee_MWh'] > 0, 100.0, 0.0))
                
                df_comparatif['Abs_Erreur_Conso'] = df_comparatif['Erreur_Conso_MWh'].abs()
                df_comparatif['Abs_Erreur_Prod'] = df_comparatif['Erreur_Prod_MWh'].abs()
                df_comparatif['Abs_Erreur_Conso_%'] = df_comparatif['Erreur_Conso_%'].abs()
                df_comparatif['Abs_Erreur_Prod_%'] = df_comparatif['Erreur_Prod_%'].abs()

                noms_mois = {1:'Jan', 2:'Fév', 3:'Mar', 4:'Avr', 5:'Mai', 6:'Juin', 7:'Juil', 8:'Août', 9:'Sep', 10:'Oct', 11:'Nov', 12:'Déc'}
                df_comparatif['Periode_Str'] = df_comparatif['Mois'].map(noms_mois) + " " + df_comparatif['Annee'].astype(int).astype(str)

                # ALERTES
                alertes = []
                m_simules = set(df_sim_base['Proprietaire'])
                m_factures = set(df_c_final['Proprietaire'])
                simu_jamais_fact = list(m_simules - m_factures)
                fact_jamais_sim = list(m_factures - m_simules)
                
                if fact_jamais_sim: alertes.append(("warning", f"**Facturés mais JAMAIS simulés (Mis à 0) :** {', '.join(fact_jamais_sim)}"))
                if simu_jamais_fact: alertes.append(("warning", f"**Simulés mais SANS AUCUNE facture (Ignorés) :** {', '.join(simu_jamais_fact)}"))
                if not alertes: alertes.append(("success", "✅ Bases de données parfaitement alignées !"))

                # On ignore les membres qui ne sont QUE dans la simu et jamais facturés
                df_analyse = df_comparatif[~df_comparatif['Proprietaire'].isin(simu_jamais_fact)].copy()
                
                st.session_state['df_analyse'] = df_analyse
                st.session_state['alertes'] = alertes
                st.session_state['calcul_termine'] = True
                st.session_state['mode_audit'] = mode_precision

            except Exception as e:
                st.error(f"❌ Erreur lors de l'analyse : {e}")

# ==========================================
# 3. INTERFACE DE RESTITUTION
# ==========================================
if st.session_state.get('calcul_termine', False):
    df_analyse = st.session_state['df_analyse']
    
    # Agrégation mensuelle forcée pour les KPI (Pour garder des tableaux lisibles)
    df_mensuel = df_analyse.groupby(['Proprietaire', 'Mois', 'Annee', 'Sort_Key', 'Periode_Str']).sum(numeric_only=True).reset_index()
    # Recalculer les pourcentages proprement pour l'aggrégat mensuel
    df_mensuel['Erreur_Conso_%'] = np.where(df_mensuel['Reel_Conso_Totale_MWh'] > 0, (df_mensuel['Erreur_Conso_MWh'] / df_mensuel['Reel_Conso_Totale_MWh']) * 100, 0.0)
    df_mensuel['Erreur_Prod_%'] = np.where(df_mensuel['Reel_Prod_Totale_MWh'] > 0, (df_mensuel['Erreur_Prod_MWh'] / df_mensuel['Reel_Prod_Totale_MWh']) * 100, 0.0)
    df_mensuel['Abs_Erreur_Conso'] = df_mensuel['Erreur_Conso_MWh'].abs()
    df_mensuel['Abs_Erreur_Prod'] = df_mensuel['Erreur_Prod_MWh'].abs()
    df_mensuel['Abs_Erreur_Conso_%'] = df_mensuel['Erreur_Conso_%'].abs()
    df_mensuel['Abs_Erreur_Prod_%'] = df_mensuel['Erreur_Prod_%'].abs()
    
    st.subheader("🚨 Alertes d'Audit")
    for type_alerte, msg in st.session_state['alertes']:
        if type_alerte == "error": st.error(msg)
        elif type_alerte == "warning": st.warning(msg)
        else: st.success(msg)
    st.divider()
    
    col_c1, col_c2 = st.columns([1, 2])
    vue = col_c1.radio("Mode d'exploration :", ["📆 Vue Globale / Annuelle", "📅 Vue Mensuelle (Détail)"], index=0)

    # ----------------------------------------
    # VUE GLOBALE
    # ----------------------------------------
    if vue == "📆 Vue Globale / Annuelle":
        st.subheader(f"🌍 Bilan Cumulé ({st.session_state['mode_audit']})")
        df_apples = df_mensuel[df_mensuel['Has_Facture'] > 0]
        
        ca1, ca2, ca3 = st.columns(3)
        t_rc = df_apples['Reel_Conso_Totale_MWh'].sum()
        t_sc = df_apples['Sim_Conso_Totale_MWh'].sum()
        t_rp = df_apples['Reel_Prod_Totale_MWh'].sum()
        t_sp = df_apples['Sim_Prod_Totale_MWh'].sum()
        t_re = df_apples['Reel_Conso_Partagee_MWh'].sum()
        t_se = df_apples['Sim_Conso_Partagee_MWh'].sum()
        
        ca1.metric("⚡ Total Consommé", f"{t_rc:.2f} MWh", f"{((t_sc - t_rc)/t_rc*100) if t_rc>0 else 0:+.1f}% (Simu: {t_sc:.2f})", delta_color="off")
        ca2.metric("☀️ Total Produit", f"{t_rp:.2f} MWh", f"{((t_sp - t_rp)/t_rp*100) if t_rp>0 else 0:+.1f}% (Simu: {t_sp:.2f})", delta_color="off")
        ca3.metric("🤝 Total Échangé", f"{t_re:.2f} MWh", f"{((t_se - t_re)/t_re*100) if t_re>0 else 0:+.1f}% (Simu: {t_se:.2f})", delta_color="off")
        st.divider()

        st.subheader("👤 Profil de charge : Analyse Individuelle")
        membre_choisi = st.selectbox("Sélectionnez un membre :", sorted(df_analyse['Proprietaire'].unique()))
        
        # Agrégation JOURNALIÈRE pour l'affichage de la courbe (Performance + Lisibilité)
        df_indiv = df_analyse[(df_analyse['Proprietaire'] == membre_choisi) & (df_analyse['Has_Facture'] > 0)]
        df_indiv_jour = df_indiv.groupby('Date_Courbe')[['Reel_Conso_Totale_MWh', 'Sim_Conso_Totale_MWh', 'Reel_Prod_Totale_MWh', 'Sim_Prod_Totale_MWh', 'Reel_Conso_Partagee_MWh', 'Sim_Conso_Partagee_MWh']].sum().reset_index()
        
        if not df_indiv_jour.empty:
            choix_kpi = st.radio(f"Indicateur pour {membre_choisi} :", ["⚡ Consommation", "☀️ Production", "🤝 Échange (Partagé)"], horizontal=True)
            if choix_kpi == "⚡ Consommation": c_r, c_s = 'Reel_Conso_Totale_MWh', 'Sim_Conso_Totale_MWh'
            elif choix_kpi == "☀️ Production": c_r, c_s = 'Reel_Prod_Totale_MWh', 'Sim_Prod_Totale_MWh'
            else: c_r, c_s = 'Reel_Conso_Partagee_MWh', 'Sim_Conso_Partagee_MWh'
            
            fig_ind, ax_ind = plt.subplots(figsize=(14, 4))
            ax_ind.plot(df_indiv_jour['Date_Courbe'], df_indiv_jour[c_r], color='#3498db', label='Réalité Sibelga')
            ax_ind.plot(df_indiv_jour['Date_Courbe'], df_indiv_jour[c_s], color='#e74c3c', linestyle='--', alpha=0.8, label='Simulation')
            ax_ind.set_ylabel('MWh / Jour')
            ax_ind.legend()
            st.pyplot(fig_ind, use_container_width=False)
        else:
            st.info("Aucune donnée facturée pour ce membre.")

    # ----------------------------------------
    # VUE MENSUELLE (Filtrée)
    # ----------------------------------------
    elif vue == "📅 Vue Mensuelle (Détail)":
        periodes_dispos = df_mensuel[['Sort_Key', 'Periode_Str']].drop_duplicates().sort_values('Sort_Key')
        mois_cible = col_c2.selectbox("Sélectionnez le mois :", periodes_dispos['Periode_Str'].tolist())
        
        df_m = df_mensuel[(df_mensuel['Periode_Str'] == mois_cible) & (df_mensuel['Has_Facture'] > 0)].copy()
        
        st.subheader("📉 Pires écarts (MWh)")
        c1, c2 = st.columns(2)
        top_c = df_m.sort_values(by='Abs_Erreur_Conso', ascending=False).head(10)
        if not top_c.empty:
            fig1, ax1 = plt.subplots(figsize=(8, 4))
            sns.barplot(data=top_c, x='Erreur_Conso_MWh', y='Proprietaire', palette=['#e74c3c' if v>0 else '#3498db' for v in top_c['Erreur_Conso_MWh']], ax=ax1)
            ax1.set_title('CONSOMMATION'); ax1.axvline(0, color='black'); ax1.set_ylabel(''); c1.pyplot(fig1)

        top_p = df_m.sort_values(by='Abs_Erreur_Prod', ascending=False).head(10)
        if not top_p.empty:
            fig2, ax2 = plt.subplots(figsize=(8, 4))
            sns.barplot(data=top_p, x='Erreur_Prod_MWh', y='Proprietaire', palette=['#e74c3c' if v>0 else '#3498db' for v in top_p['Erreur_Prod_MWh']], ax=ax2)
            ax2.set_title('PRODUCTION'); ax2.axvline(0, color='black'); ax2.set_ylabel(''); c2.pyplot(fig2)
