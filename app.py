import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import io

# Configuration de la page web
st.set_page_config(page_title="Audit Communauté d'Énergie", page_icon="⚡", layout="wide")
sns.set_theme(style="whitegrid")

st.title("⚡ Audit Automatique : Réalité vs Simulation")
st.markdown("Importez les 4 fichiers ci-dessous. **Aucun nom de fichier spécifique n'est requis !**")

# ==========================================
# BARRE LATÉRALE : UPLOADS & PARAMÈTRES
# ==========================================
st.sidebar.header("📁 1. Import des fichiers")
fichier_contacts = st.sidebar.file_uploader("1. Contacts Odoo (Excel)", type=['xlsx', 'csv'])
fichier_factures = st.sidebar.file_uploader("2. Factures Réelles (Excel)", type=['xlsx'])
fichier_mapping = st.sidebar.file_uploader("3. Fichier de Mapping (Excel)", type=['xlsx'])
fichier_simu = st.sidebar.file_uploader("4. Simulation Streamlit (CSV)", type=['csv'])

st.sidebar.header("📅 2. Paramètres")
mois_cible = st.sidebar.selectbox("Mois à analyser", range(1, 13), index=1, format_func=lambda x: ['Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin', 'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre'][x-1])

# ==========================================
# MOTEUR D'ANALYSE (Se lance au clic)
# ==========================================
if fichier_contacts and fichier_factures and fichier_mapping and fichier_simu:
    if st.sidebar.button("🚀 Lancer l'Analyse", type="primary"):
        with st.spinner("Calculs en cours..."):
            try:
                # ---------------------------------------------------------
                # ETAPE 1 & 2 : LECTURE ET TRAITEMENT (Ton code exact)
                # ---------------------------------------------------------
                # Contacts
                df_contacts = pd.read_excel(fichier_contacts)
                est_un_titre = df_contacts['Ean'].isna() & df_contacts['Nom'].astype(str).str.contains(r'\(\d+\)$')
                df_contacts['Groupe_Odoo'] = np.where(est_un_titre, df_contacts['Nom'].astype(str).str.replace(r' \(\d+\)$', '', regex=True).str.strip(), np.nan)
                df_contacts['Groupe_Odoo'] = df_contacts['Groupe_Odoo'].ffill()
                df_contacts = df_contacts.dropna(subset=['Ean']).copy() 
                df_contacts['Ean'] = df_contacts['Ean'].astype(str).str.replace(' ', '').str.strip()
                df_contacts = df_contacts.drop_duplicates(subset=['Ean'], keep='first')
                
                # Factures
                df_reels = pd.read_excel(fichier_factures)
                df_reels['EAN'] = df_reels['EAN'].astype(str).str.strip()
                colonnes_vol = ['Volume Partagé (kWh)', 'Volume Complémentaire (kWh)', 'Injection Partagée (kWh)', 'Injection Résiduelle (kWh)']
                for col in colonnes_vol:
                    df_reels[col] = pd.to_numeric(df_reels[col], errors='coerce').fillna(0)
                df_reels_agg = df_reels.groupby('EAN')[colonnes_vol].sum().reset_index()
                
                df_reels_complet = pd.merge(df_reels_agg, df_contacts[['Ean', 'Groupe_Odoo', 'Nom']], left_on='EAN', right_on='Ean', how='left')
                df_reels_complet['Proprietaire'] = df_reels_complet['Groupe_Odoo'].fillna(df_reels_complet['Nom']).fillna("Inconnu")
                
                df_reels_complet['Reel_Conso_Partagee_MWh'] = df_reels_complet['Volume Partagé (kWh)'] / 1000.0
                df_reels_complet['Reel_Conso_Totale_MWh'] = (df_reels_complet['Volume Partagé (kWh)'] + df_reels_complet['Volume Complémentaire (kWh)']) / 1000.0
                df_reels_complet['Reel_Prod_Partagee_MWh'] = df_reels_complet['Injection Partagée (kWh)'] / 1000.0
                df_reels_complet['Reel_Prod_Totale_MWh'] = (df_reels_complet['Injection Partagée (kWh)'] + df_reels_complet['Injection Résiduelle (kWh)']) / 1000.0
                df_reels_final = df_reels_complet.groupby('Proprietaire')[['Reel_Conso_Partagee_MWh', 'Reel_Conso_Totale_MWh', 'Reel_Prod_Partagee_MWh', 'Reel_Prod_Totale_MWh']].sum().reset_index()

                # Simulation
                df_mapping = pd.read_excel(fichier_mapping)
                mapping_dict = dict(zip(df_mapping['Nom_Streamlit'].astype(str).str.strip(), df_mapping['Nom_Reel'].astype(str).str.strip()))

                df_sim_p = pd.read_csv(fichier_simu)
                dates = pd.to_datetime(df_sim_p['Unnamed: 0'])
                df_sim_p_filtre = df_sim_p[dates.dt.month == mois_cible]
                sommes_simu = df_sim_p_filtre.sum(numeric_only=True)
                
                participants_simu = set(col.split('_')[0] for col in df_sim_p.columns if col != 'Unnamed: 0')
                
                donnees_simu = []
                for p in participants_simu:
                    donnees_simu.append({
                        'Nom_Streamlit': p.strip(),
                        'Sim_Conso_Partagee_MWh': sommes_simu.get(f"{p}_shared_volume_from_community", 0) / 4000.0,
                        'Sim_Conso_Totale_MWh': sommes_simu.get(f"{p}_residual_consumption_bc", 0) / 4000.0,
                        'Sim_Prod_Partagee_MWh': abs(sommes_simu.get(f"{p}_shared_volume_to_community", 0)) / 4000.0,
                        'Sim_Prod_Totale_MWh': abs(sommes_simu.get(f"{p}_injection_bc", 0)) / 4000.0
                    })
                df_sim_agg = pd.DataFrame(donnees_simu)
                df_sim_agg['Proprietaire'] = df_sim_agg['Nom_Streamlit'].map(mapping_dict)
                df_sim_final = df_sim_agg.dropna(subset=['Proprietaire']).groupby('Proprietaire')[['Sim_Conso_Partagee_MWh', 'Sim_Conso_Totale_MWh', 'Sim_Prod_Partagee_MWh', 'Sim_Prod_Totale_MWh']].sum().reset_index()

                # Fusion
                df_comparatif = pd.merge(df_reels_final, df_sim_final, on='Proprietaire', how='outer', indicator=True)
                df_comparatif = df_comparatif[~df_comparatif['Proprietaire'].astype(str).isin(['', '0', 'nan', 'NaN', 'Inconnu', 'Indéfini'])]

                # ---------------------------------------------------------
                # ALERTES ET AUDITS SUR L'INTERFACE WEB
                # ---------------------------------------------------------
                st.subheader("🚨 Alertes d'Audit")
                eans_inconnus = df_reels_complet[df_reels_complet['Proprietaire'] == 'Inconnu']['EAN'].unique()
                if len(eans_inconnus) > 0:
                    st.error(f"**ALERTE ODOO (EAN facturés mais inconnus):** {', '.join(eans_inconnus)}")
                
                participants_propres = set(p.strip() for p in participants_simu)
                mots_techniques = {'external', 'grid', 'injection', 'internal', 'remaining', 'residual', 'shared', 'community', 'n'}
                simu_sans_mapping = (participants_propres - set(mapping_dict.keys())) - mots_techniques
                if len(simu_sans_mapping) > 0:
                    st.warning(f"**ALERTE MAPPING (Membres Streamlit non traduits):** {', '.join(simu_sans_mapping)}")

                reel_sans_simu = df_comparatif[df_comparatif['_merge'] == 'left_only']['Proprietaire'].tolist()
                simu_sans_reel = df_comparatif[df_comparatif['_merge'] == 'right_only']['Proprietaire'].tolist()
                if reel_sans_simu: st.warning(f"**Facturés mais NON simulés:** {', '.join(reel_sans_simu)}")
                if simu_sans_reel: st.warning(f"**Simulés mais SANS facture ce mois-ci:** {', '.join(simu_sans_reel)}")
                
                if len(eans_inconnus) == 0 and len(simu_sans_mapping) == 0 and not reel_sans_simu and not simu_sans_reel:
                    st.success("✅ Aucun problème détecté. Les bases de données sont parfaitement alignées !")

                # Nettoyage final pour calculs
                df_comparatif = df_comparatif.drop(columns=['_merge']).fillna(0)
                df_comparatif = df_comparatif[(df_comparatif['Reel_Conso_Totale_MWh'] > 0) | (df_comparatif['Sim_Conso_Totale_MWh'] > 0) | (df_comparatif['Reel_Prod_Totale_MWh'] > 0) | (df_comparatif['Sim_Prod_Totale_MWh'] > 0)]
                df_comparatif['Erreur_Conso_MWh'] = df_comparatif['Sim_Conso_Totale_MWh'] - df_comparatif['Reel_Conso_Totale_MWh']
                df_comparatif['Erreur_Prod_MWh'] = df_comparatif['Sim_Prod_Totale_MWh'] - df_comparatif['Reel_Prod_Totale_MWh']
                df_comparatif['Abs_Erreur_Conso'] = df_comparatif['Erreur_Conso_MWh'].abs()
                df_comparatif['Abs_Erreur_Prod'] = df_comparatif['Erreur_Prod_MWh'].abs()
                df_comparatif = df_comparatif.round(3)

                st.divider()
                # ---------------------------------------------------------
                # GRAPHIQUE 1 : TOP 10 DES PIRES ERREURS EN BARRES
                # ---------------------------------------------------------
                st.subheader("📉 Top 10 des pires dimensionnements")
                col1, col2 = st.columns(2)
                
                # Barres Conso
                df_pire_conso = df_comparatif.sort_values(by='Abs_Erreur_Conso', ascending=False)
                top10_conso = df_pire_conso.head(10).copy()
                fig_bar_conso, ax1 = plt.subplots(figsize=(8, 5))
                couleurs_conso = ['#e74c3c' if val > 0 else '#3498db' for val in top10_conso['Erreur_Conso_MWh']]
                sns.barplot(data=top10_conso, x='Erreur_Conso_MWh', y='Proprietaire', palette=couleurs_conso, ax=ax1)
                ax1.set_title('CONSOMMATION', fontweight='bold')
                ax1.axvline(0, color='black', linewidth=1)
                col1.pyplot(fig_bar_conso)

                # Barres Prod
                df_pire_prod = df_comparatif.sort_values(by='Abs_Erreur_Prod', ascending=False)
                top10_prod = df_pire_prod.head(10).copy()
                top10_prod = top10_prod[top10_prod['Abs_Erreur_Prod'] > 0]
                if not top10_prod.empty:
                    fig_bar_prod, ax2 = plt.subplots(figsize=(8, 5))
                    couleurs_prod = ['#e74c3c' if val > 0 else '#3498db' for val in top10_prod['Erreur_Prod_MWh']]
                    sns.barplot(data=top10_prod, x='Erreur_Prod_MWh', y='Proprietaire', palette=couleurs_prod, ax=ax2)
                    ax2.set_title('PRODUCTION', fontweight='bold')
                    ax2.axvline(0, color='black', linewidth=1)
                    col2.pyplot(fig_bar_prod)

                st.divider()
                # ---------------------------------------------------------
                # GRAPHIQUE 2 : LES 4 NUAGES DE POINTS (avec Annotations Top 5)
                # ---------------------------------------------------------
                st.subheader("📊 Vue globale : Réalité vs Simulation")
                fig_nuage, axes = plt.subplots(2, 2, figsize=(16, 14))
                
                # 1. Conso Totale
                df_c_tot = df_comparatif[(df_comparatif['Reel_Conso_Totale_MWh'] > 0) | (df_comparatif['Sim_Conso_Totale_MWh'] > 0)]
                axes[0, 0].scatter(df_c_tot['Reel_Conso_Totale_MWh'], df_c_tot['Sim_Conso_Totale_MWh'], color='#3498db', alpha=0.8, edgecolor='black', s=60)
                max_c_tot = max(df_c_tot['Reel_Conso_Totale_MWh'].max(), df_c_tot['Sim_Conso_Totale_MWh'].max())
                if pd.notna(max_c_tot) and max_c_tot > 0: axes[0, 0].plot([0, max_c_tot], [0, max_c_tot], 'r--', label='Idéal (Simu = Réalité)')
                axes[0, 0].set_title('1. Consommation Totale (MWh)', fontsize=14, fontweight='bold')
                axes[0, 0].set_xlabel('Réalité (Factures)'); axes[0, 0].set_ylabel('Simulation')
                for _, row in df_c_tot.sort_values(by='Abs_Erreur_Conso', ascending=False).head(5).iterrows():
                    axes[0, 0].annotate(row['Proprietaire'][:20], (row['Reel_Conso_Totale_MWh'], row['Sim_Conso_Totale_MWh']), fontsize=9, xytext=(5,5), textcoords='offset points')

                # 2. Prod Totale
                df_p_tot = df_comparatif[(df_comparatif['Reel_Prod_Totale_MWh'] > 0) | (df_comparatif['Sim_Prod_Totale_MWh'] > 0)]
                axes[0, 1].scatter(df_p_tot['Reel_Prod_Totale_MWh'], df_p_tot['Sim_Prod_Totale_MWh'], color='#2ecc71', alpha=0.8, edgecolor='black', s=60)
                max_p_tot = max(df_p_tot['Reel_Prod_Totale_MWh'].max(), df_p_tot['Sim_Prod_Totale_MWh'].max())
                if pd.notna(max_p_tot) and max_p_tot > 0: axes[0, 1].plot([0, max_p_tot], [0, max_p_tot], 'r--', label='Idéal')
                axes[0, 1].set_title('2. Production Totale (MWh)', fontsize=14, fontweight='bold')
                axes[0, 1].set_xlabel('Réalité (Factures)'); axes[0, 1].set_ylabel('Simulation')
                for _, row in df_p_tot.sort_values(by='Abs_Erreur_Prod', ascending=False).head(5).iterrows():
                    axes[0, 1].annotate(row['Proprietaire'][:20], (row['Reel_Prod_Totale_MWh'], row['Sim_Prod_Totale_MWh']), fontsize=9, xytext=(5,5), textcoords='offset points')

                # 3. Conso Échangée
                df_c_part = df_comparatif[(df_comparatif['Reel_Conso_Partagee_MWh'] > 0) | (df_comparatif['Sim_Conso_Partagee_MWh'] > 0)]
                axes[1, 0].scatter(df_c_part['Reel_Conso_Partagee_MWh'], df_c_part['Sim_Conso_Partagee_MWh'], color='#9b59b6', alpha=0.8, edgecolor='black', s=60)
                max_c_part = max(df_c_part['Reel_Conso_Partagee_MWh'].max(), df_c_part['Sim_Conso_Partagee_MWh'].max())
                if pd.notna(max_c_part) and max_c_part > 0: axes[1, 0].plot([0, max_c_part], [0, max_c_part], 'r--', label='Idéal')
                axes[1, 0].set_title('3. Consommation Échangée (MWh)', fontsize=14, fontweight='bold')
                axes[1, 0].set_xlabel('Réalité (Factures)'); axes[1, 0].set_ylabel('Simulation')
                df_c_part['Err_part'] = (df_c_part['Sim_Conso_Partagee_MWh'] - df_c_part['Reel_Conso_Partagee_MWh']).abs()
                for _, row in df_c_part.sort_values(by='Err_part', ascending=False).head(5).iterrows():
                    axes[1, 0].annotate(row['Proprietaire'][:20], (row['Reel_Conso_Partagee_MWh'], row['Sim_Conso_Partagee_MWh']), fontsize=9, xytext=(5,5), textcoords='offset points')

                # 4. Prod Échangée
                df_p_part = df_comparatif[(df_comparatif['Reel_Prod_Partagee_MWh'] > 0) | (df_comparatif['Sim_Prod_Partagee_MWh'] > 0)]
                axes[1, 1].scatter(df_p_part['Reel_Prod_Partagee_MWh'], df_p_part['Sim_Prod_Partagee_MWh'], color='#f1c40f', alpha=0.8, edgecolor='black', s=60)
                max_p_part = max(df_p_part['Reel_Prod_Partagee_MWh'].max(), df_p_part['Sim_Prod_Partagee_MWh'].max())
                if pd.notna(max_p_part) and max_p_part > 0: axes[1, 1].plot([0, max_p_part], [0, max_p_part], 'r--', label='Idéal')
                axes[1, 1].set_title('4. Production Échangée (MWh)', fontsize=14, fontweight='bold')
                axes[1, 1].set_xlabel('Réalité (Factures)'); axes[1, 1].set_ylabel('Simulation')
                df_p_part['Err_part'] = (df_p_part['Sim_Prod_Partagee_MWh'] - df_p_part['Reel_Prod_Partagee_MWh']).abs()
                for _, row in df_p_part.sort_values(by='Err_part', ascending=False).head(5).iterrows():
                    axes[1, 1].annotate(row['Proprietaire'][:20], (row['Reel_Prod_Partagee_MWh'], row['Sim_Prod_Partagee_MWh']), fontsize=9, xytext=(5,5), textcoords='offset points')

                plt.tight_layout()
                st.pyplot(fig_nuage)

                st.divider()
                # ---------------------------------------------------------
                # TABLEAU DE DONNÉES ET TÉLÉCHARGEMENT
                # ---------------------------------------------------------
                st.subheader("📋 Tableau récapitulatif")
                st.dataframe(df_comparatif.drop(columns=['Abs_Erreur_Conso', 'Abs_Erreur_Prod']))
                
                # Bouton de téléchargement
                csv = df_comparatif.drop(columns=['Abs_Erreur_Conso', 'Abs_Erreur_Prod']).to_csv(index=False, sep=';', decimal=',').encode('utf-8')
                st.download_button(
                    label="📥 Télécharger le rapport complet pour Excel",
                    data=csv,
                    file_name=f"Audit_Comparaison_Mois_{mois_cible}.csv",
                    mime="text/csv",
                    type="primary"
                )

            except Exception as e:
                st.error(f"❌ Une erreur s'est produite lors de l'analyse : {e}")

else:
    st.info("👈 Veuillez importer les 4 fichiers Excel/CSV dans le menu de gauche pour démarrer.")
