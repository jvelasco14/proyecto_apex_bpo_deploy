import pandas as pd
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from datetime import datetime
from sqlalchemy import text
import warnings

warnings.filterwarnings('ignore')

def analizar_tendencia_horaria(engine, fecha_simulada, hora_simulada, fecha_actual_completa):
    try:
        # ARQUITECTURA LAMBDA: Consultamos la tabla VIVA
        query_macro = f"""
            SELECT 
                SUBSTRING(CAST(time AS TEXT), 1, 2) AS hora,
                COUNT(call_id) as volumen_llamadas,
                AVG(CASE WHEN talk_time IS NOT NULL THEN EXTRACT(EPOCH FROM CAST(talk_time AS INTERVAL)) ELSE 0 END) as tmo_promedio
            FROM base_llamadas_migraciones
            WHERE date = '{fecha_simulada}' AND SUBSTRING(CAST(time AS TEXT), 1, 2) <= '{hora_simulada}'
            GROUP BY hora
            ORDER BY hora;
        """
        with engine.connect() as conn:
            df_macro = pd.read_sql_query(text(query_macro), conn)

        # BLINDAJE: Solo analiza si hay al menos 3 horas de datos para comparar
        if not df_macro.empty and len(df_macro) >= 3:
            X_macro = df_macro[['volumen_llamadas', 'tmo_promedio']]
            df_macro['anomalia_hora'] = IsolationForest(n_estimators=100, contamination=0.25, random_state=42).fit_predict(X_macro)
            horas_anomalas = df_macro[df_macro['anomalia_hora'] == -1]
            
            horas_anomalas = horas_anomalas[horas_anomalas['hora'] == hora_simulada]
            
            if not horas_anomalas.empty:
                alertas_macro_df = pd.DataFrame()
                alertas_macro_df['origen_datos'] = ['Migraciones - Macro Tráfico'] * len(horas_anomalas)
                alertas_macro_df['tipo_alerta'] = ['Saturación / Anomalía Sistémica'] * len(horas_anomalas)
                alertas_macro_df['severidad'] = ['ALTA'] * len(horas_anomalas)
                
                descripciones = []
                for _, r in horas_anomalas.iterrows():
                    tmo = r['tmo_promedio']
                    dur_str = f"{round(tmo / 60, 1)} min" if tmo > 60 else f"{round(tmo, 1)} seg"
                    descripciones.append(f"Franja horaria {r['hora']}:00 hrs presentó un flujo atípico con {r['volumen_llamadas']} llamadas y TMO de {dur_str}.")
                
                alertas_macro_df['descripcion'] = descripciones
                alertas_macro_df['identificador_registro'] = [f"MACRO-{fecha_simulada}-{r['hora']}" for _, r in horas_anomalas.iterrows()]
                alertas_macro_df['call_date'] = [fecha_simulada] * len(horas_anomalas)
                alertas_macro_df['call_time'] = [f"{r['hora']}:00:00" for _, r in horas_anomalas.iterrows()]
                alertas_macro_df['fecha_deteccion'] = fecha_actual_completa

                try:
                    with engine.connect() as conn:
                        df_exist = pd.read_sql_query(text("SELECT identificador_registro FROM ml_alertas_macro"), conn)
                    alertas_nuevas = alertas_macro_df[~alertas_macro_df['identificador_registro'].isin(df_exist['identificador_registro'].tolist())]
                except: alertas_nuevas = alertas_macro_df

                if not alertas_nuevas.empty:
                    with engine.begin() as conn:
                        alertas_nuevas.to_sql('ml_alertas_macro', conn, if_exists='append', index=False)
                    print(f"   💾 [MACRO] 1 alerta sistémica detectada a las {hora_simulada}:00.")
    except Exception as e: print(f"   ❌ Error macro: {e}")


def ejecutar_modelos_predictivos(engine, fecha_simulada, hora_simulada, fecha_actual_completa):
    try:
        hora_actual = int(hora_simulada)
        if hora_actual >= 19: return
            
        hora_proxima = hora_actual + 1
        hora_proxima_str = str(hora_proxima).zfill(2)
        hora_simulada_str = str(hora_simulada).zfill(2)
        
        # Búsqueda dinámica del día histórico anterior
        try:
            with engine.connect() as conn:
                q_ayer = f"SELECT MAX(date) FROM hist_base_llamadas_migraciones WHERE date < '{fecha_simulada}'"
                res_ayer = conn.execute(text(q_ayer)).fetchone()
                fecha_ayer = str(res_ayer[0]) if res_ayer[0] else '2025-06-25'
        except:
            fecha_ayer = '2025-06-25'
        
        alertas_predictivas = []
        
        with engine.connect() as conn:
            # =======================================================
            # MODELO 1: FORECASTING (ACUMULADO HOY VS AYER)
            # =======================================================
            if hora_proxima < 19:
                q_acum_hoy = f"SELECT COUNT(call_id) as vol FROM base_llamadas_migraciones WHERE date = '{fecha_simulada}' AND SUBSTRING(CAST(time AS TEXT), 1, 2) <= '{hora_simulada_str}'"
                q_acum_ayer = f"SELECT COUNT(call_id) as vol FROM hist_base_llamadas_migraciones WHERE date = '{fecha_ayer}' AND SUBSTRING(CAST(time AS TEXT), 1, 2) <= '{hora_simulada_str}'"
                
                # BLINDAJE: Extracción segura de dataframes vacíos
                df_acum_hoy = pd.read_sql_query(text(q_acum_hoy), conn)
                vol_acum_hoy = df_acum_hoy['vol'].iloc[0] if not df_acum_hoy.empty and pd.notna(df_acum_hoy['vol'].iloc[0]) else 0
                
                df_acum_ayer = pd.read_sql_query(text(q_acum_ayer), conn)
                vol_acum_ayer = df_acum_ayer['vol'].iloc[0] if not df_acum_ayer.empty and pd.notna(df_acum_ayer['vol'].iloc[0]) else 0
                
                tendencia_dia = 1.0
                if vol_acum_ayer > 0:
                    tendencia_dia = vol_acum_hoy / vol_acum_ayer
                    tendencia_dia = min(max(tendencia_dia, 0.5), 2.25) 
                
                q_vol_ayer_prox = f"SELECT COUNT(call_id) as vol FROM hist_base_llamadas_migraciones WHERE date = '{fecha_ayer}' AND SUBSTRING(CAST(time AS TEXT), 1, 2) = '{hora_proxima_str}'"
                df_vol_ayer_prox = pd.read_sql_query(text(q_vol_ayer_prox), conn)
                vol_ayer_prox = df_vol_ayer_prox['vol'].iloc[0] if not df_vol_ayer_prox.empty and pd.notna(df_vol_ayer_prox['vol'].iloc[0]) else 0
                
                vol_predicho = int(vol_ayer_prox * tendencia_dia)
                if vol_predicho == 0: 
                    vol_predicho = int(vol_acum_hoy / max(1, hora_actual - 6))
                
                q_stats_hoy = f"""
                    SELECT 
                        COUNT(DISTINCT agent) as agentes_activos,
                        AVG(EXTRACT(EPOCH FROM CAST(talk_time AS INTERVAL))) as tmo_promedio
                    FROM base_llamadas_migraciones 
                    WHERE date = '{fecha_simulada}' 
                    AND SUBSTRING(CAST(time AS TEXT), 1, 2) = '{hora_simulada_str}'
                    AND talk_time IS NOT NULL
                """
                stats_hoy = pd.read_sql_query(text(q_stats_hoy), conn)
                
                # BLINDAJE: Si no hubo llamadas en la hora, asumimos 1 agente y 120s TMO para no romper matemáticas
                if not stats_hoy.empty:
                    agentes_activos = stats_hoy['agentes_activos'].iloc[0] if pd.notna(stats_hoy['agentes_activos'].iloc[0]) else 1
                    tmo_promedio = stats_hoy['tmo_promedio'].iloc[0] if pd.notna(stats_hoy['tmo_promedio'].iloc[0]) else 120
                else:
                    agentes_activos, tmo_promedio = 1, 120
                
                tmo_promedio = min(max(tmo_promedio, 60), 600) 
                llamadas_por_agente = 3600 / tmo_promedio
                
                capacidad_instalada = int(agentes_activos * llamadas_por_agente * 5.0) 
                if capacidad_instalada < 100: capacidad_instalada = 100
                
                severidad_traf = 'ALTA' if vol_predicho > capacidad_instalada else 'INFO'
                tipo_alerta_traf = '[PREDICTIVO] Riesgo de Desbordamiento' if severidad_traf == 'ALTA' else '[PREDICTIVO] Estado de Tráfico'
                
                desc_trafico = f"Según el comportamiento histórico del día, se proyectan {vol_predicho} llamadas entre las {hora_simulada_str}:00 y las {hora_proxima_str}:00 hrs. Con {agentes_activos} agentes conectados, la capacidad operativa máxima de la plataforma se estima en {capacidad_instalada} llamadas."
                
                alertas_predictivas.append({
                    'origen_datos': 'Migraciones',
                    'tipo_alerta': tipo_alerta_traf,
                    'severidad': severidad_traf,
                    'descripcion': desc_trafico,
                    'identificador_registro': f"PRED-VOL-{fecha_simulada}-{hora_simulada_str}",
                    'call_date': fecha_simulada,
                    'call_time': f"{hora_simulada_str}:00:00", 
                    'fecha_deteccion': fecha_actual_completa
                })
            
            # =======================================================
            # MODELO 2: CONTROL DE METAS GTR
            # =======================================================
            meta_diaria = 160
            q_ventas_hoy = f"SELECT COUNT(*) as ventas_hoy FROM base_ventas_migraciones WHERE fecha_de_venta = '{fecha_simulada}' AND SUBSTRING(CAST(time AS TEXT), 1, 2) <= '{hora_simulada_str}' AND (contactado ILIKE '%migraci%n%' OR contactado ILIKE '%portabilidad%' OR contactado ILIKE '%linea nueva%')"
            
            # BLINDAJE: Control de nulos en ventas
            df_ventas = pd.read_sql_query(text(q_ventas_hoy), conn)
            ventas_hoy = df_ventas['ventas_hoy'].iloc[0] if not df_ventas.empty and pd.notna(df_ventas['ventas_hoy'].iloc[0]) else 0
            
            ventas_faltantes = meta_diaria - ventas_hoy
            horas_transcurridas = max(1, hora_actual - 7 + 1)
            horas_restantes = max(1, 19 - hora_actual - 1)
            
            if horas_restantes > 0 and horas_transcurridas > 0:
                velocidad_actual = ventas_hoy / horas_transcurridas
                ritmo_necesario = ventas_faltantes / horas_restantes if ventas_faltantes > 0 else 0
                
                porcentaje_avance = (ventas_hoy / meta_diaria) * 100
                
                severidad_gtr = 'MEDIA' if velocidad_actual < ritmo_necesario else 'INFO'
                tipo_alerta_gtr = '[PREDICTIVO] Alerta de Incumplimiento Meta GTR' if severidad_gtr == 'MEDIA' else '[PREDICTIVO] Seguimiento Meta GTR'
                
                alertas_predictivas.append({
                    'origen_datos': 'Migraciones',
                    'tipo_alerta': tipo_alerta_gtr,
                    'severidad': severidad_gtr,
                    'descripcion': f"Avance GTR al {porcentaje_avance:.1f}%. Su velocidad de ventas actual es de {velocidad_actual:.1f} ventas/hora. Para cumplir con la meta de {meta_diaria} requiere un ritmo de {ritmo_necesario:.1f} ventas por hora.",
                    'identificador_registro': f"PRED-META-{fecha_simulada}-{hora_simulada_str}",
                    'call_date': fecha_simulada,
                    'call_time': f"{hora_simulada_str}:00:00",
                    'fecha_deteccion': fecha_actual_completa
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
                    print(f"   🔮 [PREDICTIVO] {len(alertas_nuevas)} reporte(s) inyectado(s) y ordenado(s) a las {hora_simulada_str}:00.")
                except Exception:
                    with engine.begin() as conn:
                        alertas_nuevas.to_sql('ml_alertas_globales', conn, if_exists='append', index=False)
                    print(f"   🔮 [PREDICTIVO] {len(alertas_nuevas)} reporte(s) inyectado(s) a las {hora_simulada_str}:00.")
            
    except Exception as e:
        print(f"   ❌ Error predictivo: {e}")


def analizar_migraciones(engine, modo, tz_colombia):
    fecha_actual_completa = datetime.now(tz_colombia).strftime("%Y-%m-%d %H:%M:%S")

    if modo == 'horario':
        print("\n🔍 [MIGRACIONES - LIVE] Ejecutando análisis en tiempo real (Arquitectura Lambda)...")
        
        try:
            with engine.connect() as conn:
                res = conn.execute(text("SELECT MAX(date), MAX(SUBSTRING(CAST(time AS TEXT), 1, 2)) FROM base_llamadas_migraciones WHERE talk_time IS NOT NULL")).fetchone()
                # BLINDAJE: Si la tabla viva está completamente vacía (inicio de día o sin llamadas), salimos limpio
                if res[0] is None:
                    print("   ⚠️ [MIGRACIONES] No hay datos en la tabla viva para analizar.")
                    return
                fecha_sim = str(res[0])
                hora_sim = str(res[1]).zfill(2)
        except Exception as e:
            print(f"   ❌ Error al obtener fecha/hora de la base viva: {e}")
            return
            
        try:
            with engine.connect() as conn:
                resp_agentes = pd.read_sql_query(text("SELECT id, cedula, five9, asesor FROM dim_agentes"), conn)
            mapa_agentes = {}
            for _, ag in resp_agentes.iterrows():
                nom = str(ag.get("asesor", "")).strip()
                ced_real = str(ag.get("cedula", "")).strip().replace('.0', '')
                if nom and nom.lower() not in ["none", "null", ""]:
                    ced, id_int, f9 = str(ag.get("cedula", "")).strip().replace('.0', ''), str(ag.get("id", "")).strip().replace('.0', ''), str(ag.get("five9", "")).strip().replace('.0', '')
                    datos_ag = {"nombre": nom, "cedula": ced_real}
                    if ced and ced != 'None': mapa_agentes[ced] = datos_ag
                    if id_int and id_int != 'None': mapa_agentes[id_int] = datos_ag
                    if f9 and f9 != 'None': mapa_agentes[f9] = datos_ag
        except:
            mapa_agentes = {}

        print(f"   ⌚ Analizando franja de las {hora_sim}:00 hrs del {fecha_sim}...")
        
        try:
            q_live = f"""
                SELECT call_id, agent, talk_time, disposition, date, time 
                FROM base_llamadas_migraciones 
                WHERE date = '{fecha_sim}' 
                AND SUBSTRING(CAST(time AS TEXT), 1, 2) <= '{hora_sim}' 
                AND talk_time IS NOT NULL AND talk_time != 'NaN'
            """
            with engine.connect() as conn:
                df_live = pd.read_sql_query(text(q_live), conn)
            
            # BLINDAJE: Solo corremos IF si hay al menos 10 datos en total y > 1 tras limpieza
            if not df_live.empty and len(df_live) >= 10:
                df_live['segundos_hablados'] = pd.to_timedelta(df_live['talk_time'], errors='coerce').dt.total_seconds()
                df_live = df_live.dropna(subset=['segundos_hablados']) 
                
                if len(df_live) > 1:
                    df_live['prediccion_ia'] = IsolationForest(n_estimators=100, contamination=0.03, random_state=42).fit_predict(df_live[['segundos_hablados']])
                    
                    anomalias_filtradas = []
                    for _, row in df_live.iterrows():
                        hora_registro = str(row['time'])[:2]
                        if hora_registro != hora_sim: continue
                        
                        segundos, disp = row['segundos_hablados'], str(row['disposition']).upper()
                        if row['prediccion_ia'] != -1: continue
                        
                        es_venta = ("VENTA" in disp or "ACEPTA" in disp) and segundos < 30
                        es_buzon = ("BUZON" in disp or "ANSWERING MACHINE" in disp or "NO ANSWER" in disp) and segundos > 45
                        es_extrema = (segundos > 900 or segundos < 5)

                        if es_venta or es_buzon or es_extrema:
                            as_id_raw = str(row['agent']).strip().replace('.0', '')
                            info_ag = mapa_agentes.get(as_id_raw, {"nombre": "Sin Asignación", "cedula": as_id_raw})
                            
                            if segundos > 60:
                                duracion_str = f"{round(segundos / 60, 1)} min"
                            else:
                                duracion_str = f"{round(segundos, 1)} seg"
                                
                            descripcion = f"Agente {info_ag['nombre']} (CC: {info_ag['cedula']}) tipificó '{row['disposition']}' con duración de {duracion_str}."

                            anomalias_filtradas.append({
                                'call_id': row['call_id'], 'asesor_id': info_ag['cedula'], 'disposition': row['disposition'],
                                'segundos': segundos, 'tipo_alerta': "Venta Exprés Atípica (<30s)" if es_venta else ("Buzón/No Contesta Prolongado" if es_buzon else "Desviación Extrema de TMO"),
                                'severidad': 'ALTA' if es_venta else 'MEDIA', 'date': row['date'], 'time': row['time'], 'descripcion': descripcion
                            })

                    if anomalias_filtradas:
                        alertas_df = pd.DataFrame(anomalias_filtradas)
                        alertas_df['origen_datos'] = 'Migraciones'
                        alertas_df['identificador_registro'] = alertas_df['call_id'].astype(str)
                        alertas_df['call_date'] = alertas_df['date'].values
                        alertas_df['call_time'] = alertas_df['time'].values
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
                                print(f"   🔍 [MICRO] {len(alertas_nuevas)} TMOs anómalos (IF) registrados y ordenados a las {hora_sim}:00.")
                            except Exception:
                                with engine.begin() as conn:
                                    alertas_nuevas.to_sql('ml_alertas_globales', conn, if_exists='append', index=False)
                                print(f"   🔍 [MICRO] {len(alertas_nuevas)} TMOs anómalos (IF) registrados a las {hora_sim}:00.")
                else:
                    print("   ⚠️ Datos limpios insuficientes en esta hora para procesar Isolation Forest en Migraciones.")
            else:
                print("   ⚠️ Volumen de llamadas inferior a 10. No se ejecutará Isolation Forest para evitar sesgos.")
            
            analizar_tendencia_horaria(engine, fecha_sim, hora_sim, fecha_actual_completa)
            ejecutar_modelos_predictivos(engine, fecha_sim, hora_sim, fecha_actual_completa)
            
        except Exception as e: print(f"   ❌ Error en análisis live del {fecha_sim} a las {hora_sim}:00 - {e}")

    elif modo == 'cierre':
        print("\n🧠 [MIGRACIONES - CIERRE] Ejecutando análisis de cierre histórico (K-Means)...")
        
        try:
            with engine.connect() as conn:
                res = conn.execute(text("SELECT MAX(date) FROM hist_base_llamadas_migraciones")).fetchone()
                fecha_cierre = str(res[0]) if res[0] else datetime.now(tz_colombia).strftime("%Y-%m-%d")
        except:
            fecha_cierre = datetime.now(tz_colombia).strftime("%Y-%m-%d")

        try:
            # 1. Obtenemos las llamadas para el TMO promedio
            q_hist_llamadas = f"SELECT call_id, agent, talk_time, date, time FROM hist_base_llamadas_migraciones WHERE agent IS NOT NULL AND agent != '[None]' AND date = '{fecha_cierre}'"
            with engine.connect() as conn:
                df_llamadas = pd.read_sql_query(text(q_hist_llamadas), conn)
            
            if df_llamadas.empty or len(df_llamadas) < 50: return

            df_llamadas['segundos_hablados'] = pd.to_timedelta(df_llamadas['talk_time'], errors='coerce').dt.total_seconds().fillna(0)
            agentes_llamadas = df_llamadas.groupby('agent').agg(total_llamadas=('call_id', 'count'), tmo_promedio=('segundos_hablados', 'mean')).reset_index()

            # 2. Obtenemos las VENTAS OFICIALES como única fuente de verdad
            try:
                q_hist_ventas = f"SELECT cedula_del_agente as cedula_del_agent, COUNT(*) as total_ventas FROM base_ventas_migraciones WHERE fecha_de_venta = '{fecha_cierre}' GROUP BY cedula_del_agente"
                with engine.connect() as conn:
                    df_ventas = pd.read_sql_query(text(q_hist_ventas), conn)
            except Exception:
                q_hist_ventas = f"SELECT cedula_del_agent, COUNT(*) as total_ventas FROM base_ventas_migraciones WHERE fecha_de_venta = '{fecha_cierre}' GROUP BY cedula_del_agent"
                with engine.connect() as conn:
                    df_ventas = pd.read_sql_query(text(q_hist_ventas), conn)

            # 3. Cruzamos (Merge) usando la cédula y calculamos la efectividad real
            agentes_llamadas['agent'] = agentes_llamadas['agent'].astype(str)
            df_ventas['cedula_del_agent'] = df_ventas['cedula_del_agent'].astype(str)
            agentes_kpi = pd.merge(agentes_llamadas, df_ventas, left_on='agent', right_on='cedula_del_agent', how='left')
            agentes_kpi['total_ventas'] = agentes_kpi['total_ventas'].fillna(0)
            agentes_kpi['efectividad'] = (agentes_kpi['total_ventas'] / agentes_kpi['total_llamadas']) * 100
            
            agentes_filtrados = agentes_kpi[(agentes_kpi['total_llamadas'] > 5) & (~agentes_kpi['agent'].isin(['0', '0.0', 'None', '', 'nan']))].copy()

            # BLINDAJE: K-Means(3) requiere al menos 3 agentes analizables
            if len(agentes_filtrados) >= 3:
                agentes_filtrados['cluster_id'] = KMeans(n_clusters=3, random_state=42, n_init=10).fit_predict(StandardScaler().fit_transform(agentes_filtrados[['efectividad', 'tmo_promedio']]))
                cluster_medias = agentes_filtrados.groupby('cluster_id')['efectividad'].mean().sort_values()
                nombres_clusters = {cluster_medias.index[0]: 'Área de Oportunidad (Bajo Cierre)', cluster_medias.index[1]: 'Estándar (Conversadores)', cluster_medias.index[2]: 'Francotiradores (Alta Efectividad)'}
                agentes_filtrados['cluster_nombre'] = agentes_filtrados['cluster_id'].map(nombres_clusters)

                insights_df = pd.DataFrame()
                insights_df['fecha_analisis'] = [fecha_cierre] * len(agentes_filtrados)
                insights_df['tipo_insight'] = ['Perfilamiento K-Means'] * len(agentes_filtrados)
                insights_df['agente'] = agentes_filtrados['agent'].values
                insights_df['cluster_nombre'] = agentes_filtrados['cluster_nombre'].values
                insights_df['metrica_principal'] = round(agentes_filtrados['efectividad'], 2).values
                insights_df['metrica_secundaria'] = round(agentes_filtrados['tmo_promedio'], 2).values
                insights_df['fecha_ejecucion'] = fecha_actual_completa
                insights_df['descripcion_insight'] = [f"Agente clasificado en '{r['cluster_nombre']}' con {round(r['efectividad'], 2)}% de efectividad y TMO de {round(r['tmo_promedio'], 1)} seg." for _, r in agentes_filtrados.iterrows()]

                try:
                    with engine.begin() as conn: 
                        conn.execute(text(f"DELETE FROM ml_insights_migraciones WHERE fecha_analisis = '{fecha_cierre}'"))
                except: pass
                
                with engine.begin() as conn:
                    insights_df.to_sql('ml_insights_migraciones', conn, if_exists='append', index=False)
                print(f"   ✅ Clasificados {len(insights_df)} agentes de Migraciones para el {fecha_cierre}.")
            else:
                print(f"   ⚠️ Menos de 3 agentes activos para ejecutar K-Means en {fecha_cierre}.")
        except Exception as e: print(f"   ❌ Error cierre {fecha_cierre}: {e}")