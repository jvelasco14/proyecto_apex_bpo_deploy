import pandas as pd
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from datetime import datetime
from sqlalchemy import text
import warnings
import re

warnings.filterwarnings('ignore')

def ejecutar_modelos_predictivos_rrss(engine, fecha_simulada, hora_simulada, fecha_actual_completa):
    try:
        hora_actual = int(hora_simulada)
        if hora_actual >= 16: return 
            
        hora_proxima = hora_actual + 1
        hora_proxima_str = str(hora_proxima).zfill(2)
        hora_simulada_str = str(hora_simulada).zfill(2)
        
        # Búsqueda dinámica del día histórico anterior
        try:
            with engine.connect() as conn:
                q_ayer = f"SELECT MAX(SUBSTRING(CAST(fecha_inicio AS TEXT) FROM 1 FOR 10)) FROM hist_chats_monetizacion_rrss WHERE SUBSTRING(CAST(fecha_inicio AS TEXT) FROM 1 FOR 10) < '{fecha_simulada}'"
                res_ayer = conn.execute(text(q_ayer)).fetchone()
                fecha_ayer = str(res_ayer[0]) if res_ayer[0] else '2025-06-25'
        except:
            fecha_ayer = '2025-06-25'
        
        alertas_predictivas = []
        
        with engine.connect() as conn:
            # =======================================================
            # MODELO 1: FORECASTING DE TRÁFICO (CHATS)
            # =======================================================
            if hora_proxima < 16:
                # ARQUITECTURA LAMBDA: Hoy se lee de base (viva), ayer de hist_chats (histórica)
                q_acum_hoy = f"SELECT COUNT(*) as vol FROM chats_monetizacion_rrss WHERE SUBSTRING(CAST(fecha_inicio AS TEXT) FROM 1 FOR 10) = '{fecha_simulada}' AND SUBSTRING(CAST(fecha_inicio AS TEXT) FROM 12 FOR 2) <= '{hora_simulada_str}'"
                q_acum_ayer = f"SELECT COUNT(*) as vol FROM hist_chats_monetizacion_rrss WHERE SUBSTRING(CAST(fecha_inicio AS TEXT) FROM 1 FOR 10) = '{fecha_ayer}' AND SUBSTRING(CAST(fecha_inicio AS TEXT) FROM 12 FOR 2) <= '{hora_simulada_str}'"
                
                # BLINDAJE: Control de Dataframes vacíos
                df_acum_hoy = pd.read_sql_query(text(q_acum_hoy), conn)
                vol_acum_hoy = df_acum_hoy['vol'].iloc[0] if not df_acum_hoy.empty and pd.notna(df_acum_hoy['vol'].iloc[0]) else 0
                
                df_acum_ayer = pd.read_sql_query(text(q_acum_ayer), conn)
                vol_acum_ayer = df_acum_ayer['vol'].iloc[0] if not df_acum_ayer.empty and pd.notna(df_acum_ayer['vol'].iloc[0]) else 0
                
                tendencia_dia = 1.0
                if vol_acum_ayer > 0:
                    tendencia_dia = vol_acum_hoy / vol_acum_ayer
                    tendencia_dia = min(max(tendencia_dia, 0.5), 2.25)
                
                q_vol_ayer_prox = f"SELECT COUNT(*) as vol FROM hist_chats_monetizacion_rrss WHERE SUBSTRING(CAST(fecha_inicio AS TEXT) FROM 1 FOR 10) = '{fecha_ayer}' AND SUBSTRING(CAST(fecha_inicio AS TEXT) FROM 12 FOR 2) = '{hora_proxima_str}'"
                df_vol_ayer_prox = pd.read_sql_query(text(q_vol_ayer_prox), conn)
                vol_ayer_prox = df_vol_ayer_prox['vol'].iloc[0] if not df_vol_ayer_prox.empty and pd.notna(df_vol_ayer_prox['vol'].iloc[0]) else 0
                
                vol_predicho = int(vol_ayer_prox * tendencia_dia)
                if vol_predicho == 0: 
                    vol_predicho = int(vol_acum_hoy / max(1, hora_actual - 6))
                
                # ARQUITECTURA LAMBDA: Estadísticas en vivo
                q_stats = f"""
                    SELECT COUNT(DISTINCT agente) as agentes_activos,
                    AVG(EXTRACT(EPOCH FROM CAST(NULLIF(tiempo_conversacion, '') AS INTERVAL))) as tmo_promedio
                    FROM chats_monetizacion_rrss 
                    WHERE SUBSTRING(CAST(fecha_inicio AS TEXT) FROM 1 FOR 10) = '{fecha_simulada}' AND SUBSTRING(CAST(fecha_inicio AS TEXT) FROM 12 FOR 2) = '{hora_simulada_str}'
                """
                stats_hoy = pd.read_sql_query(text(q_stats), conn)
                
                if not stats_hoy.empty:
                    agentes_activos = stats_hoy['agentes_activos'].iloc[0] if pd.notna(stats_hoy['agentes_activos'].iloc[0]) else 1
                    tmo_promedio = stats_hoy['tmo_promedio'].iloc[0] if pd.notna(stats_hoy['tmo_promedio'].iloc[0]) else 300
                else:
                    agentes_activos, tmo_promedio = 1, 300
                
                tmo_promedio = min(max(tmo_promedio, 60), 1200)
                chats_por_agente = 3600 / tmo_promedio
                capacidad_instalada = int(agentes_activos * chats_por_agente * 3.0)
                if capacidad_instalada < 10: capacidad_instalada = 10
                
                severidad_traf = 'ALTA' if vol_predicho > capacidad_instalada else 'INFO'
                tipo_alerta_traf = '[PREDICTIVO] Riesgo de Desbordamiento de Chats' if severidad_traf == 'ALTA' else '[PREDICTIVO] Estado de Tráfico RRSS'
                
                alertas_predictivas.append({
                    'origen_datos': 'Redes Sociales',
                    'tipo_alerta': tipo_alerta_traf,
                    'severidad': severidad_traf,
                    'descripcion': f"Según tendencia, proyectamos {vol_predicho} chats entrantes entre las {hora_simulada_str}:00 y las {hora_proxima_str}:00 hrs. Capacidad operativa máxima estimada: {capacidad_instalada} chats.",
                    'identificador_registro': f"PRED-RRSS-VOL-{fecha_simulada}-{hora_simulada_str}",
                    'call_date': fecha_simulada,
                    'call_time': f"{hora_simulada_str}:00:00",
                    'fecha_deteccion': fecha_actual_completa
                })
                        
            # =======================================================
            # MODELO 2: DEGRADACIÓN DE TPR
            # =======================================================
            if hora_proxima < 16:
                q_tpr = f"""
                    SELECT AVG(EXTRACT(EPOCH FROM CAST(NULLIF(tiempo_primera_respuesta, '') AS INTERVAL))) as tpr_promedio
                    FROM chats_monetizacion_rrss 
                    WHERE SUBSTRING(CAST(fecha_inicio AS TEXT) FROM 1 FOR 10) = '{fecha_simulada}' AND SUBSTRING(CAST(fecha_inicio AS TEXT) FROM 12 FOR 2) = '{hora_simulada_str}'
                """
                df_tpr_hoy = pd.read_sql_query(text(q_tpr), conn)
                tpr_hoy = df_tpr_hoy['tpr_promedio'].iloc[0] if not df_tpr_hoy.empty and pd.notna(df_tpr_hoy['tpr_promedio'].iloc[0]) else 0
                
                if pd.notna(tpr_hoy) and tpr_hoy > 180:
                    alertas_predictivas.append({
                        'origen_datos': 'Redes Sociales',
                        'tipo_alerta': '[PREDICTIVO] Degradación SLA Primera Respuesta',
                        'severidad': 'MEDIA',
                        'descripcion': f"Inercia negativa. El Tiempo de Primera Respuesta (TPR) actual es de {round(tpr_hoy/60, 1)} min. Riesgo de incumplimiento del Nivel de Servicio para la próxima hora.",
                        'identificador_registro': f"PRED-RRSS-TPR-{fecha_simulada}-{hora_simulada_str}",
                        'call_date': fecha_simulada,
                        'call_time': f"{hora_simulada_str}:00:00",
                        'fecha_deteccion': fecha_actual_completa
                    })
            
            # =======================================================
            # MODELO 3: ANÁLISIS DE EFICIENCIA Y PROYECCIÓN (POR AGENTE)
            # =======================================================
            if hora_proxima < 16:
                # 1. Eficiencia de la hora actual (Hoy - Viva)
                q_eficiencia_hoy = f"""
                    SELECT COUNT(id_conversación) * 1.0 / NULLIF(COUNT(DISTINCT agente), 0) as chats_por_agente
                    FROM chats_monetizacion_rrss 
                    WHERE SUBSTRING(CAST(fecha_inicio AS TEXT) FROM 1 FOR 10) = '{fecha_simulada}' 
                    AND SUBSTRING(CAST(fecha_inicio AS TEXT) FROM 12 FOR 2) = '{hora_simulada_str}'
                    AND agente IS NOT NULL AND agente != '' AND agente != '[None]'
                """
                df_eficiencia_hoy = pd.read_sql_query(text(q_eficiencia_hoy), conn)
                eficiencia_hoy = df_eficiencia_hoy['chats_por_agente'].iloc[0] if not df_eficiencia_hoy.empty and pd.notna(df_eficiencia_hoy['chats_por_agente'].iloc[0]) else 0.0

                # 2. Eficiencia de la hora actual (Ayer - Histórico)
                q_eficiencia_ayer = f"""
                    SELECT COUNT(id_conversación) * 1.0 / NULLIF(COUNT(DISTINCT agente), 0) as chats_por_agente
                    FROM hist_chats_monetizacion_rrss 
                    WHERE SUBSTRING(CAST(fecha_inicio AS TEXT) FROM 1 FOR 10) = '{fecha_ayer}' 
                    AND SUBSTRING(CAST(fecha_inicio AS TEXT) FROM 12 FOR 2) = '{hora_simulada_str}'
                    AND agente IS NOT NULL AND agente != '' AND agente != '[None]'
                """
                df_eficiencia_ayer = pd.read_sql_query(text(q_eficiencia_ayer), conn)
                eficiencia_ayer = df_eficiencia_ayer['chats_por_agente'].iloc[0] if not df_eficiencia_ayer.empty and pd.notna(df_eficiencia_ayer['chats_por_agente'].iloc[0]) else 5.0 

                # 3. Eficiencia de la PRÓXIMA hora (Ayer - Histórico)
                q_eficiencia_prox_ayer = f"""
                    SELECT COUNT(id_conversación) * 1.0 / NULLIF(COUNT(DISTINCT agente), 0) as chats_por_agente
                    FROM hist_chats_monetizacion_rrss 
                    WHERE SUBSTRING(CAST(fecha_inicio AS TEXT) FROM 1 FOR 10) = '{fecha_ayer}' 
                    AND SUBSTRING(CAST(fecha_inicio AS TEXT) FROM 12 FOR 2) = '{hora_proxima_str}'
                    AND agente IS NOT NULL AND agente != '' AND agente != '[None]'
                """
                df_eficiencia_prox_ayer = pd.read_sql_query(text(q_eficiencia_prox_ayer), conn)
                eficiencia_prox_ayer = df_eficiencia_prox_ayer['chats_por_agente'].iloc[0] if not df_eficiencia_prox_ayer.empty and pd.notna(df_eficiencia_prox_ayer['chats_por_agente'].iloc[0]) else 5.0

                # --- A. ALERTA DEDUCTIVA (Lo que pasó en esta hora) ---
                if eficiencia_ayer > 0:
                    rendimiento = eficiencia_hoy / eficiencia_ayer
                    if rendimiento < 0.80 and eficiencia_hoy > 0:
                        alertas_predictivas.append({
                            'origen_datos': 'Redes Sociales',
                            'tipo_alerta': '[ANALÍTICA] Caída de Eficiencia por Agente',
                            'severidad': 'MEDIA',
                            'descripcion': f"Alerta de productividad. En la franja de las {hora_simulada_str}:00, cada asesor cerró {eficiencia_hoy:.1f} chats, un {(1-rendimiento)*100:.1f}% por debajo del histórico ({eficiencia_ayer:.1f} chats).",
                            'identificador_registro': f"ANALIT-RRSS-PROD-{fecha_simulada}-{hora_simulada_str}",
                            'call_date': fecha_simulada, 'call_time': f"{hora_simulada_str}:00:00", 'fecha_deteccion': fecha_actual_completa
                        })
                    elif eficiencia_hoy > 0:
                        alertas_predictivas.append({
                            'origen_datos': 'Redes Sociales',
                            'tipo_alerta': '[ANALÍTICA] Eficiencia Operativa Estable',
                            'severidad': 'INFO',
                            'descripcion': f"Productividad saludable. En la franja de las {hora_simulada_str}:00, cada asesor cerró {eficiencia_hoy:.1f} chats, alineado con el histórico ({eficiencia_ayer:.1f} chats).",
                            'identificador_registro': f"ANALIT-RRSS-PROD-{fecha_simulada}-{hora_simulada_str}",
                            'call_date': fecha_simulada, 'call_time': f"{hora_simulada_str}:00:00", 'fecha_deteccion': fecha_actual_completa
                        })

                # --- B. ALERTA PREDICTIVA (Lo que va a pasar en la próxima hora) ---
                tendencia_inercia = (eficiencia_hoy / eficiencia_ayer) if eficiencia_ayer > 0 else 1.0
                tendencia_inercia = min(max(tendencia_inercia, 0.5), 1.5) # Limitar la proyección
                
                proyeccion_prox_hora = eficiencia_prox_ayer * tendencia_inercia

                if proyeccion_prox_hora < (eficiencia_prox_ayer * 0.85):
                    alertas_predictivas.append({
                        'origen_datos': 'Redes Sociales',
                        'tipo_alerta': '[PREDICTIVO] Proyección Baja Eficiencia',
                        'severidad': 'MEDIA',
                        'descripcion': f"Según la inercia actual, proyectamos que cada agente cerrará solo {proyeccion_prox_hora:.1f} chats entre las {hora_proxima_str}:00 y {int(hora_proxima_str)+1}:00 hrs (el histórico es {eficiencia_prox_ayer:.1f}).",
                        'identificador_registro': f"PRED-RRSS-EFIC-{fecha_simulada}-{hora_proxima_str}",
                        'call_date': fecha_simulada, 'call_time': f"{hora_simulada_str}:00:00", 'fecha_deteccion': fecha_actual_completa
                    })
                else:
                    alertas_predictivas.append({
                        'origen_datos': 'Redes Sociales',
                        'tipo_alerta': '[PREDICTIVO] Proyección Eficiencia Óptima',
                        'severidad': 'INFO',
                        'descripcion': f"Según la inercia actual, proyectamos que cada agente cerrará {proyeccion_prox_hora:.1f} chats entre las {hora_proxima_str}:00 y {int(hora_proxima_str)+1}:00 hrs, cumpliendo la expectativa histórica ({eficiencia_prox_ayer:.1f} chats).",
                        'identificador_registro': f"PRED-RRSS-EFIC-{fecha_simulada}-{hora_proxima_str}",
                        'call_date': fecha_simulada, 'call_time': f"{hora_simulada_str}:00:00", 'fecha_deteccion': fecha_actual_completa
                    })    

        if alertas_predictivas:
            df_alertas_pred = pd.DataFrame(alertas_predictivas)
            df_alertas_pred['asesor_id'] = 'N/A (Campaña)'
            df_alertas_pred = df_alertas_pred[['origen_datos', 'tipo_alerta', 'severidad', 'descripcion', 'identificador_registro', 'asesor_id', 'call_date', 'call_time', 'fecha_deteccion']]
            
            try:
                with engine.connect() as conn:
                    df_exist = pd.read_sql_query(text("SELECT identificador_registro FROM ml_alertas_globales"), conn)
                alertas_nuevas = df_alertas_pred[~df_alertas_pred['identificador_registro'].isin(df_exist['identificador_registro'].tolist())]
            except:
                alertas_nuevas = df_alertas_pred

            if not alertas_nuevas.empty:
                try:
                    with engine.connect() as conn:
                        df_global_actual = pd.read_sql_query(text("SELECT * FROM ml_alertas_globales"), conn)
                    df_actualizado = pd.concat([df_global_actual, alertas_nuevas], ignore_index=True)
                    df_actualizado.sort_values(by=['call_date', 'call_time'], ascending=[False, False], inplace=True)
                    with engine.begin() as conn:
                        df_actualizado.to_sql('ml_alertas_globales', conn, if_exists='replace', index=False)
                    print(f"   🔮 [PREDICTIVO RRSS] {len(alertas_nuevas)} reporte(s) inyectado(s) y ordenado(s) a las {hora_simulada_str}:00.")
                except Exception:
                    with engine.begin() as conn:
                        alertas_nuevas.to_sql('ml_alertas_globales', conn, if_exists='append', index=False)

    except Exception as e:
        print(f"   ❌ Error predictivo RRSS: {e}")


def analizar_rrss(engine, modo, tz_colombia):
    fecha_actual_completa = datetime.now(tz_colombia).strftime("%Y-%m-%d %H:%M:%S")

    if modo == 'horario':
        print("\n🔍 [RRSS - LIVE] Ejecutando análisis en tiempo real (Arquitectura Lambda)...")
        
        # Obtenemos dinámicamente la última hora de la tabla viva
        try:
            with engine.connect() as conn:
                res = conn.execute(text("SELECT MAX(SUBSTRING(CAST(fecha_inicio AS TEXT) FROM 1 FOR 10)), MAX(SUBSTRING(CAST(fecha_inicio AS TEXT) FROM 12 FOR 2)) FROM chats_monetizacion_rrss WHERE tiempo_conversacion IS NOT NULL")).fetchone()
                if res[0] is None:
                    print("   ⚠️ [RRSS] No hay datos en la tabla viva para analizar.")
                    return
                fecha_sim = str(res[0])
                hora_sim = str(res[1]).zfill(2)
        except Exception as e:
            print(f"   ❌ Error al obtener fecha/hora de la base viva (RRSS): {e}")
            return
            
        try:
            with engine.connect() as conn:
                resp_agentes = pd.read_sql_query(text("SELECT cedula, asesor FROM dim_agentes"), conn)
            mapa_cedulas = {}
            for _, ag in resp_agentes.iterrows():
                nom = str(ag.get("asesor", "")).strip().lower()
                ced = str(ag.get("cedula", "")).strip().replace('.0', '')
                if nom and ced: mapa_cedulas[nom] = ced
                
            with engine.connect() as conn:
                df_tip = pd.read_sql_query(text('SELECT "id_conversación" as id_conversacion, "ekia_código" as tipificacion FROM base_tipificaciones_rrss'), conn)
        except:
            mapa_cedulas = {}
            df_tip = pd.DataFrame()

        print(f"   ⌚ Analizando franja de las {hora_sim}:00 hrs del {fecha_sim}...")
            
        try:
            # ARQUITECTURA LAMBDA: Leemos de chats_monetizacion_rrss
            q_live = f"""
                SELECT "id_conversación" as id_conversacion, fecha_inicio, agente, tiempo_conversacion 
                FROM chats_monetizacion_rrss 
                WHERE SUBSTRING(CAST(fecha_inicio AS TEXT) FROM 1 FOR 10) = '{fecha_sim}'
                AND SUBSTRING(CAST(fecha_inicio AS TEXT) FROM 12 FOR 2) = '{hora_sim}'
                AND tiempo_conversacion IS NOT NULL
            """
            with engine.connect() as conn:
                df_chats = pd.read_sql_query(text(q_live), conn)
            
            # BLINDAJE: Validación estricta de datos antes de Isolation Forest
            if not df_chats.empty and len(df_chats) >= 5:
                df_chats['fecha_dt'] = pd.to_datetime(df_chats['fecha_inicio'], errors='coerce')
                df_chats['date'] = df_chats['fecha_dt'].dt.strftime('%Y-%m-%d')
                df_chats['time'] = df_chats['fecha_dt'].dt.strftime('%H:%M:%S')

                df_master = pd.merge(df_chats, df_tip, on='id_conversacion', how='left')
                df_master['segundos_hablados'] = pd.to_timedelta(df_master['tiempo_conversacion'], errors='coerce').dt.total_seconds()
                df_master = df_master.dropna(subset=['segundos_hablados', 'agente'])
                
                if len(df_master) > 1:
                    df_master['prediccion_ia'] = IsolationForest(n_estimators=100, contamination=0.03, random_state=42).fit_predict(df_master[['segundos_hablados']])
                    anomalias = df_master[df_master['prediccion_ia'] == -1].copy()

                    if not anomalias.empty:
                        alertas_df = pd.DataFrame()
                        alertas_df['origen_datos'] = ['Redes Sociales'] * len(anomalias)
                        alertas_df['tipo_alerta'] = ['Anomalía TMO en Chat'] * len(anomalias)
                        alertas_df['severidad'] = ['MEDIA'] * len(anomalias)
                        alertas_df['call_date'] = anomalias['date'].values
                        alertas_df['call_time'] = anomalias['time'].values
                        
                        descripciones, asesor_ids = [], []
                        for _, row in anomalias.iterrows():
                            segundos = row['segundos_hablados']
                            tip = row['tipificacion'] if pd.notna(row['tipificacion']) else 'Sin Ekia'
                            nombre_agente = str(row['agente']).strip()
                            cedula_agente = mapa_cedulas.get(nombre_agente.lower(), "N/A")
                            
                            dur_str = f"{round(segundos / 60, 1)} min" if segundos > 60 else f"{round(segundos, 1)} seg"
                            
                            descripciones.append(f"Agente {nombre_agente} (CC: {cedula_agente}) registró chat atípico de {dur_str}. Consultar código Ekia para auditoría: '{tip}'.")
                            asesor_ids.append(cedula_agente)
                        
                        alertas_df['descripcion'] = descripciones
                        alertas_df['identificador_registro'] = anomalias['id_conversacion'].astype(str).values
                        alertas_df['asesor_id'] = asesor_ids
                        alertas_df['fecha_deteccion'] = fecha_actual_completa

                        alertas_df = alertas_df[['origen_datos', 'tipo_alerta', 'severidad', 'descripcion', 'identificador_registro', 'asesor_id', 'call_date', 'call_time', 'fecha_deteccion']]

                        try:
                            with engine.connect() as conn:
                                df_exist = pd.read_sql_query(text("SELECT identificador_registro FROM ml_alertas_globales"), conn)
                            alertas_nuevas = alertas_df[~alertas_df['identificador_registro'].isin(df_exist['identificador_registro'].tolist())]
                        except: alertas_nuevas = alertas_df

                        if not alertas_nuevas.empty:
                            try:
                                with engine.connect() as conn:
                                    df_global_actual = pd.read_sql_query(text("SELECT * FROM ml_alertas_globales"), conn)
                                df_actualizado = pd.concat([df_global_actual, alertas_nuevas], ignore_index=True)
                                df_actualizado.sort_values(by=['call_date', 'call_time'], ascending=[False, False], inplace=True)
                                with engine.begin() as conn:
                                    df_actualizado.to_sql('ml_alertas_globales', conn, if_exists='replace', index=False)
                                print(f"   🔍 [MICRO RRSS] {len(alertas_nuevas)} chats anómalos ordenados a las {hora_sim}:00.")
                            except Exception:
                                with engine.begin() as conn:
                                    alertas_nuevas.to_sql('ml_alertas_globales', conn, if_exists='append', index=False)
                else:
                    print("   ⚠️ Datos limpios insuficientes para ejecutar Isolation Forest en RRSS.")
            else:
                print("   ⚠️ Volumen inferior a 5 chats. No se ejecutará Isolation Forest para RRSS.")
            
            ejecutar_modelos_predictivos_rrss(engine, fecha_sim, hora_sim, fecha_actual_completa)
            
        except Exception as e: print(f"   ❌ Error análisis live RRSS {fecha_sim} {hora_sim}:00: {e}")

    elif modo == 'cierre':
        print("\n🧠 [RRSS - DEEP INSIGHTS] Ejecutando análisis de cierre histórico...")
        
        # Obtenemos dinámicamente la última fecha registrada en el histórico de RRSS
        try:
            with engine.connect() as conn:
                res = conn.execute(text("SELECT MAX(SUBSTRING(CAST(fecha_inicio AS TEXT) FROM 1 FOR 10)) FROM hist_chats_monetizacion_rrss")).fetchone()
                fecha_cierre = str(res[0]) if res[0] else datetime.now(tz_colombia).strftime("%Y-%m-%d")
        except:
            fecha_cierre = datetime.now(tz_colombia).strftime("%Y-%m-%d")

        try:
            # ARQUITECTURA LAMBDA: Cierre consulta hist_chats_monetizacion_rrss
            q_chats = f"SELECT \"id_conversación\" as id_conversacion, agente, tiempo_conversacion, fecha_inicio FROM hist_chats_monetizacion_rrss WHERE agente IS NOT NULL AND agente != '[None]' AND SUBSTRING(fecha_inicio FROM 1 FOR 10) = '{fecha_cierre}'"
            with engine.connect() as conn:
                df_chats = pd.read_sql_query(text(q_chats), conn)
                df_nps = pd.read_sql_query(text('SELECT * FROM hist_base_nps_rrss'), conn)
                df_dim = pd.read_sql_query(text("SELECT asesor, wave FROM dim_agentes"), conn)

            # BLINDAJE: Verificación de DataFrame vacío
            if df_chats.empty or len(df_chats) < 5: 
                print(f"   ⚠️ No hay datos suficientes para perfilar agentes de RRSS el {fecha_cierre}.")
                return

            df_chats['tmo_segundos'] = pd.to_timedelta(df_chats['tiempo_conversacion'], errors='coerce').dt.total_seconds().fillna(0)
            id_nps_col = 'id_de_conversación' if 'id_de_conversación' in df_nps.columns else 'id_conversación'
            if id_nps_col in df_nps.columns: df_nps.rename(columns={id_nps_col: 'id_conversacion'}, inplace=True)
            columna_nota = 'recomendación' if 'recomendación' in df_nps.columns else None

            if columna_nota and 'id_conversacion' in df_nps.columns:
                df_nps['nota_numerica'] = pd.to_numeric(df_nps[columna_nota], errors='coerce')
                df_nps['es_promotor'] = df_nps['nota_numerica'].apply(lambda x: 1 if x >= 9 else 0)
                df_nps['es_encuesta'] = 1
                df_master = pd.merge(df_chats, df_nps[['id_conversacion', 'es_promotor', 'es_encuesta']], on='id_conversacion', how='left')
                df_master['es_promotor'], df_master['es_encuesta'] = df_master['es_promotor'].fillna(0), df_master['es_encuesta'].fillna(0)
            else:
                df_master = df_chats
                df_master['es_promotor'], df_master['es_encuesta'] = 0, 0

            df_master['agente_norm'] = df_master['agente'].astype(str).str.lower().str.strip()
            df_dim['asesor_norm'] = df_dim['asesor'].astype(str).str.lower().str.strip()

            agentes_kpi = df_master.groupby('agente_norm').agg(nombre_original=('agente', 'first'), total_chats=('id_conversacion', 'count'), tmo_promedio=('tmo_segundos', 'mean'), total_encuestas=('es_encuesta', 'sum'), total_promotores=('es_promotor', 'sum')).reset_index()
            agentes_filtrados = agentes_kpi[agentes_kpi['total_chats'] > 3].copy()
            
            if agentes_filtrados.empty: return

            agentes_filtrados['porcentaje_promotores'] = np.where(agentes_filtrados['total_encuestas'] > 0, (agentes_filtrados['total_promotores'] / agentes_filtrados['total_encuestas']) * 100, 0)
            agentes_filtrados = pd.merge(agentes_filtrados, df_dim[['asesor_norm', 'wave']], left_on='agente_norm', right_on='asesor_norm', how='left')
            agentes_filtrados['wave'] = agentes_filtrados['wave'].fillna('Desconocida')

            # BLINDAJE: K-Means(3) requiere 3 o más agentes
            if len(agentes_filtrados) >= 3:
                # 1. Escalamos las variables a una medida neutral
                scaler = StandardScaler()
                features_scaled = scaler.fit_transform(agentes_filtrados[['porcentaje_promotores', 'tmo_promedio']])
                
                # 2. PONDERACIÓN DE NEGOCIO: Multiplicar el NPS (índice 0) por 3.0 para darle mayor peso
                features_scaled[:, 0] = features_scaled[:, 0] * 3.0 
                
                # 3. Entrenar K-Means con los datos ponderados
                agentes_filtrados['cluster_id'] = KMeans(n_clusters=3, random_state=42, n_init=10).fit_predict(features_scaled)
                cluster_medias = agentes_filtrados.groupby('cluster_id')['porcentaje_promotores'].mean().sort_values()
                nombres_clusters = {cluster_medias.index[0]: 'Riesgo de Calidad (Bajo NPS)', cluster_medias.index[1]: 'Estándar (Calidad Media)', cluster_medias.index[2]: 'Resolutivos Estrella (Alto NPS)'}
                agentes_filtrados['cluster_nombre'] = agentes_filtrados['cluster_id'].map(nombres_clusters)

                insights_df = pd.DataFrame()
                insights_df['fecha_analisis'] = [fecha_cierre] * len(agentes_filtrados)
                insights_df['tipo_insight'] = ['Perfilamiento K-Means (Calidad vs TMO)'] * len(agentes_filtrados)
                insights_df['agente'] = agentes_filtrados['nombre_original'].values
                insights_df['wave'] = agentes_filtrados['wave'].values
                insights_df['cluster_nombre'] = agentes_filtrados['cluster_nombre'].values
                insights_df['metrica_principal'] = round(agentes_filtrados['porcentaje_promotores'], 2).values
                insights_df['metrica_secundaria'] = round(agentes_filtrados['tmo_promedio'], 2).values
                insights_df['fecha_ejecucion'] = fecha_actual_completa
                insights_df['descripcion_insight'] = [f"Agente de {r['wave']} agrupado en '{r['cluster_nombre']}' con {round(r['porcentaje_promotores'], 2)}% de Promotores y TMO de {round(r['tmo_promedio']/60, 1)} min." for _, r in agentes_filtrados.iterrows()]

                try:
                    with engine.begin() as conn: conn.execute(text(f"DELETE FROM ml_insights_rrss WHERE fecha_analisis = '{fecha_cierre}'"))
                except: pass
                
                with engine.begin() as conn:
                    insights_df.to_sql('ml_insights_rrss', conn, if_exists='append', index=False)
                print(f"   ✅ [{fecha_cierre}] Clasificados {len(insights_df)} agentes RRSS.")
            else:
                print(f"   ⚠️ Menos de 3 agentes activos para ejecutar K-Means en RRSS ({fecha_cierre}).")
        except Exception as e: print(f"   ❌ Error cierre RRSS {fecha_cierre}: {e}")