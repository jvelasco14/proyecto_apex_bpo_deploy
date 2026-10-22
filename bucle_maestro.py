import os
import time
import requests
import pytz
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright
from sqlalchemy import create_engine, text

import bot_scraper
import motor_etl
from ia_migraciones import analizar_migraciones
from ia_retenciones import analizar_retenciones
from ia_rrss import analizar_rrss

# ==========================================
# ⚙️ CONFIGURACIÓN DEL ORQUESTADOR
# ==========================================
API_URL = "http://127.0.0.1:5000/api/set_hora/"

# Lotes de extracción simulados en Cari AI
LOTE_INICIAL = 6   # Simula las 06:00 (Genera corte hasta 06:59) -> Corre a las 07:00 físicas
LOTE_FINAL = 16    # Simula las 16:00 (Genera corte hasta 16:59) -> Corre a las 17:00 físicas

TIEMPO_ESPERA_ENTRE_HORAS = 60    # MODO TESIS: Segundos rápidos entre horas para la demostración
# TIEMPO_ESPERA_ENTRE_HORAS = 3600 # MODO PRODUCCIÓN: Descomentar para esperar 60 minutos reales

TIEMPO_ESPERA_REINICIO = 300    # MODO TESIS: 5 minutos de pausa al final de la jornada

DB_URL = "postgresql://postgres.vdvmyueufdfviztmribf:Velasco14062000**@aws-1-us-east-1.pooler.supabase.com:5432/postgres"

# FECHA QUEMADA DE PRUEBA (Para evitar que se borre el verdadero histórico de Supabase)
FECHA_PRUEBA = '2025-06-26'

# Tablas de la Capa Viva que SIEMPRE se vacían al 100% cada día a la medianoche (Capa Speed)
TABLAS_VIVAS = [
    'base_llamadas_migraciones',
    'base_ventas_migraciones',
    'base_rete_out',
    'base_nps_rrss',
    'base_tipificaciones_rrss',
    'chats_monetizacion_rrss'
]

# ==========================================
# 📦 FUNCIONES DE CIERRE ESCALONADO
# ==========================================
def cierre_retenciones(engine, tz):
    print("\n📦 [15:00] CIERRE RETENCIONES: Copiando tabla viva al histórico...")
    try:
        with engine.begin() as conn:
            query_rete = """
            INSERT INTO hist_base_rete_out (
                call_id, date, "time", call_type, campaign, agent, ani, dnis, 
                queue_wait_time, talk_time, after_call_work_time, hold_time, 
                disposition, wom_inbid_ekia, etl_origen_archivo, etl_lote_ejecucion, etl_fecha_carga_col
            )
            SELECT 
                call_id, date, "time", call_type, campaign, agent, ani, dnis, 
                queue_wait_time, talk_time, after_call_work_time, hold_time, 
                disposition, wom_inbid_ekia, etl_origen_archivo, etl_lote_ejecucion, etl_fecha_carga_col
            FROM base_rete_out;
            """
            conn.execute(text(query_rete))
            print("   ✅ Migración de datos al histórico completada.")
            
        print("🧠 Ejecutando IA de Cierre (K-Means) para Retenciones...")
        analizar_retenciones(engine, 'cierre', tz)
        print("   ✅ Cierre de Retenciones completado.")
    except Exception as e: print(f"   ❌ Error en cierre de Retenciones: {e}")

def cierre_rrss(engine, tz):
    print("\n📦 [16:00] CIERRE REDES SOCIALES: Copiando tablas vivas al histórico...")
    try:
        with engine.begin() as conn:
            # 1. Migración de Chats Monetización
            query_chats = """
            INSERT INTO hist_chats_monetizacion_rrss (
                id_original, "cola_de_atención", "id_conversación", bot, canal, 
                nombre_del_cliente, identificacion_del_cliente, tipo_de_cliente, 
                fecha_inicio, "fecha_asignación", "fecha_atención", tiempo_en_espera, 
                tiempo_primera_respuesta, "tiempo_de_asignación", tiempo_conversacion, 
                "fecha_finalización", "duración", cerrado_por, agente, skill, 
                recibida_por, login_agente, etl_origen_archivo, etl_lote_ejecucion, etl_fecha_carga_col
            )
            SELECT 
                id_original, "cola_de_atención", "id_conversación", bot, canal, 
                nombre_del_cliente, identificacion_del_cliente, tipo_de_cliente, 
                fecha_inicio, "fecha_asignación", "fecha_atención", tiempo_en_espera, 
                tiempo_primera_respuesta, "tiempo_de_asignación", tiempo_conversacion, 
                "fecha_finalización", "duración", cerrado_por, agente, skill, 
                recibida_por, login_agente, etl_origen_archivo, etl_lote_ejecucion, etl_fecha_carga_col
            FROM chats_monetizacion_rrss;
            """
            conn.execute(text(query_chats))
            
            # 2. Migración de NPS
            query_nps = """
            INSERT INTO hist_base_nps_rrss (
                id_cliente, bot, fecha_de_registro, "id_de_conversación", "id_conversación_con_agente", 
                codigo_ekia, agente, experiencia, "resolución_bot", "recomendación", "resolución", 
                "satisfacción", datos_de_origen, canal, custom_type, "satisfacción_bot", 
                "recomendación_bot", "solución_bot", comentarios_bot, etl_origen_archivo, 
                etl_lote_ejecucion, etl_fecha_carga_col
            )
            SELECT 
                id_cliente, bot, fecha_de_registro, "id_de_conversación", "id_conversación_con_agente", 
                codigo_ekia, agente, experiencia, "resolución_bot", "recomendación", "resolución", 
                "satisfacción", datos_de_origen, canal, custom_type, "satisfacción_bot", 
                "recomendación_bot", "solución_bot", comentarios_bot, etl_origen_archivo, 
                etl_lote_ejecucion, etl_fecha_carga_col
            FROM base_nps_rrss;
            """
            conn.execute(text(query_nps))
            
            # 3. Migración de Tipificaciones
            query_tipificaciones = """
            INSERT INTO hist_base_tipificaciones_rrss (
                id_cliente, fecha_de_registro, "id_conversación", canal, id_solicitud_pendiente, 
                "ekia_código", id_agente, etl_origen_archivo, etl_lote_ejecucion, etl_fecha_carga_col
            )
            SELECT 
                id_cliente, fecha_de_registro, "id_conversación", canal, id_solicitud_pendiente, 
                "ekia_código", id_agente, etl_origen_archivo, etl_lote_ejecucion, etl_fecha_carga_col
            FROM base_tipificaciones_rrss;
            """
            conn.execute(text(query_tipificaciones))
            print("   ✅ Migración de datos al histórico completada.")
            
        print("🧠 Ejecutando IA de Cierre (K-Means) para Redes Sociales...")
        analizar_rrss(engine, 'cierre', tz)
        print("   ✅ Cierre de Redes Sociales completado.")
    except Exception as e: print(f"   ❌ Error en cierre de RRSS: {e}")

def cierre_migraciones(engine, tz):
    print("\n📦 [17:00] CIERRE MIGRACIONES: Copiando tablas vivas al histórico...")
    try:
        with engine.begin() as conn:
            # 1. Migración de Llamadas de Migraciones
            query_llamadas = """
            INSERT INTO hist_base_llamadas_migraciones (
                call_id, date, "time", call_type, campaign, agent, ani, dnis, 
                queue_wait_time, talk_time, after_call_work_time, hold_time, 
                disposition, wom_inbid_ekia, etl_origen_archivo, etl_lote_ejecucion, etl_fecha_carga_col
            )
            SELECT 
                call_id, date, "time", call_type, campaign, agent, ani, dnis, 
                queue_wait_time, talk_time, after_call_work_time, hold_time, 
                disposition, wom_inbid_ekia, etl_origen_archivo, etl_lote_ejecucion, etl_fecha_carga_col
            FROM base_llamadas_migraciones;
            """
            conn.execute(text(query_llamadas))
            
            # 2. Migración de Ventas de Migraciones
            query_ventas = """
            INSERT INTO hist_base_ventas_migraciones (
                marca_temporal, nombre_del_asesor, cedula_del_agente, msisdn, 
                cedula_del_cliente, numero_linea_gestionada, gestion, contactado, 
                plan_vendido, canal_de_venta, supervisor, base_de_gestion, 
                fecha_de_venta, mes, dia, etl_origen_archivo, etl_lote_ejecucion, 
                etl_fecha_carga_col, "time"
            )
            SELECT 
                marca_temporal, nombre_del_asesor, cedula_del_agente, msisdn, 
                cedula_del_cliente, numero_linea_gestionada, gestion, contactado, 
                plan_vendido, canal_de_venta, supervisor, base_de_gestion, 
                fecha_de_venta, mes, dia, etl_origen_archivo, etl_lote_ejecucion, 
                etl_fecha_carga_col, "time"
            FROM base_ventas_migraciones;
            """
            conn.execute(text(query_ventas))
            print("   ✅ Migración de datos al histórico completada.")
            
        print("🧠 Ejecutando IA de Cierre (K-Means) para Migraciones...")
        analizar_migraciones(engine, 'cierre', tz)
        print("   ✅ Cierre de Migraciones completado.")
    except Exception as e: print(f"   ❌ Error en cierre de Migraciones: {e}")


# ==========================================
# 🧹 FUNCIÓN DE REINICIO NOCTURNO
# ==========================================
def reiniciar_entorno(engine):
    print("\n🧹 [REINICIO NOCTURNO] Aplicando limpieza de la Capa Speed (Vivas)...")
    try:
        with engine.begin() as conn:
            # 1. Truncar (vaciar a cero) todas las tablas de la Capa Viva para el nuevo día
            for tabla in TABLAS_VIVAS:
                conn.execute(text(f"TRUNCATE TABLE {tabla};"))
            print("   ✅ Capa Speed (Vivas) vaciada correctamente.")
            
            # =========================================================
            # ⚠️ LÓGICA DE PRUEBA: BORRADO DE HISTÓRICOS (MODO TESIS)
            # =========================================================
            # NOTA PARA PRODUCCIÓN: Eliminar o comentar este bloque en el entorno real.
            # En producción NUNCA se borran los históricos, ya que son la memoria del BPO.
            
            # 📞 Migraciones Histórico (Llamadas y Ventas)
            conn.execute(text(f"DELETE FROM hist_base_llamadas_migraciones WHERE date = '{FECHA_PRUEBA}';"))
            conn.execute(text(f"DELETE FROM hist_base_llamadas_migraciones WHERE date = '2025-05-26';"))
            conn.execute(text(f"DELETE FROM hist_base_ventas_migraciones WHERE fecha_de_venta = '{FECHA_PRUEBA}';"))
            
            # 📞 Retenciones Histórico
            conn.execute(text(f"DELETE FROM hist_base_rete_out WHERE date = '{FECHA_PRUEBA}';"))
            
            # 💬 Redes Sociales Histórico (Sincronizado con las columnas reales: fecha_de_registro)
            conn.execute(text(f"DELETE FROM hist_chats_monetizacion_rrss WHERE CAST(fecha_inicio AS TEXT) LIKE '{FECHA_PRUEBA}%';"))
            conn.execute(text(f"DELETE FROM hist_base_nps_rrss WHERE CAST(fecha_de_registro AS TEXT) LIKE '{FECHA_PRUEBA}%';"))
            conn.execute(text(f"DELETE FROM hist_base_tipificaciones_rrss WHERE CAST(fecha_de_registro AS TEXT) LIKE '{FECHA_PRUEBA}%';"))
            
            # 🧠 Clustering K-Means (Perfilamiento de agentes)
            conn.execute(text(f"DELETE FROM ml_insights_migraciones WHERE fecha_analisis = '{FECHA_PRUEBA}';"))
            conn.execute(text(f"DELETE FROM ml_insights_retenciones WHERE fecha_analisis = '{FECHA_PRUEBA}';"))
            conn.execute(text(f"DELETE FROM ml_insights_rrss WHERE fecha_analisis = '{FECHA_PRUEBA}';"))
            
            # 🚨 Isolation Forest & Anomalías Macro (Alertas)
            conn.execute(text(f"DELETE FROM ml_alertas_globales WHERE call_date = '{FECHA_PRUEBA}';"))
            conn.execute(text(f"DELETE FROM ml_alertas_macro WHERE call_date = '{FECHA_PRUEBA}';"))
            
            print(f"   ✅ Limpieza selectiva del histórico ({FECHA_PRUEBA}) completada.")
            # =========================================================
            
    except Exception as e:
        print(f"   ❌ Error en el reinicio de la base de datos: {e}")

    print("\n🗑️ Vaciando carpetas locales de procesamiento...")
    carpetas = ['descargas_bot', 'historico_procesados']
    for carpeta in carpetas:
        if os.path.exists(carpeta):
            for archivo in os.listdir(carpeta):
                ruta_archivo = os.path.join(carpeta, archivo)
                try:
                    if os.path.isfile(ruta_archivo): os.unlink(ruta_archivo)
                except Exception: pass
    print("   ✅ Carpetas locales limpias. El sistema está listo para un nuevo día.")

# ==========================================
# 🚀 MOTOR PRINCIPAL
# ==========================================
def iniciar_orquestador():
    print("===================================================")
    print(" 🚀 INICIANDO ORQUESTADOR CENTRAL (Arquitectura Lambda)")
    print("===================================================")
    
    engine = create_engine(DB_URL)
    tz_colombia = pytz.timezone('America/Bogota')
    
    while True: 
        # Ciclo intradía
        for lote in range(LOTE_INICIAL, LOTE_FINAL + 1):
            hora_fisica_ejecucion = lote + 1 
            lote_str = str(lote).zfill(2)
            hora_fisica_str = str(hora_fisica_ejecucion).zfill(2)
            
            print(f"\n" + "="*60)
            print(f" 🕒 HORA DEL ROBOT: {hora_fisica_str}:00 | Extrayendo corte de {lote_str}:59")
            print("="*60)
            
            # 1. Avanzar el reloj del Simulador Cari AI (Modo Prueba)
            # En producción, esto no es necesario si el bot extrae la "última hora" del CRM real.
            try:
                requests.get(f"{API_URL}{lote_str}")
            except Exception as e:
                print(f"❌ Error conectando a Cari AI. Asegúrate de tener app_dashboard.py corriendo: {e}")
                return 

            # 2. RPA: Extraer la data
            with sync_playwright() as playwright:
                bot_scraper.run(playwright, es_fin_de_dia=(lote == LOTE_FINAL))
            
            # 3. ETL: Limpiar, transformar y subir a tablas vivas
            print(f"\n⚙️ Despertando Motor ETL para la hora {hora_fisica_str}:00...")
            motor_etl.ejecutar_etl()
            
            # 4. INTELIGENCIA ARTIFICIAL (Modo Horario)
            print(f"\n🔍 Ejecutando Motores de IA Horaria (Micro-anomalías y Predictivo)...")
            analizar_migraciones(engine, 'horario', tz_colombia)
            analizar_retenciones(engine, 'horario', tz_colombia)
            analizar_rrss(engine, 'horario', tz_colombia)
            
            # 5. CIERRES ESCALONADOS
            if hora_fisica_ejecucion == 15:
                cierre_retenciones(engine, tz_colombia)
            
            elif hora_fisica_ejecucion == 16:
                cierre_rrss(engine, tz_colombia)
                
            elif hora_fisica_ejecucion == 17:
                cierre_migraciones(engine, tz_colombia)
                
                print(f"\n🌙 TODAS LAS OPERACIONES FINALIZADAS (17:00 HRS).")
                
                # =========================================================
                # ⚠️ LÓGICA DE REPOSO NOCTURNO Y REINICIO
                # =========================================================
                
                # --- MODO TESIS (Simulación Rápida) ---
                print(f"⏳ [MODO TESIS] Entrando en reposo de {TIEMPO_ESPERA_REINICIO/60} minutos...")
                time.sleep(TIEMPO_ESPERA_REINICIO)
                
                # --- MODO PRODUCCIÓN REAL (Descomentar en la vida real) ---
                # Esta lógica calcula exactamente cuántos segundos faltan 
                # desde el momento actual hasta las 23:59:59 y pone el script a dormir.
                #
                # ahora = datetime.now(tz_colombia)
                # medianoche = ahora.replace(hour=23, minute=59, second=59, microsecond=0)
                # segundos_hasta_medianoche = (medianoche - ahora).total_seconds()
                #
                # if segundos_hasta_medianoche > 0:
                #     print(f"⏳ [MODO PRODUCCIÓN] Reposo. Despertando a las 23:59:59 (Faltan {int(segundos_hasta_medianoche/3600)} horas)...")
                #     time.sleep(segundos_hasta_medianoche)
                
                # =========================================================
                
                # Ejecutar el vaciado de tablas vivas (y borrado condicionado de prueba)
                reiniciar_entorno(engine)
                print("\n🌅 ¡Fin de ciclo! Iniciando un nuevo día operativo...")
                break # Rompe el for para reiniciar el while principal (Nuevo día)
                
            # 6. Pausa normal entre horas intradía
            if hora_fisica_ejecucion < 17:
                print(f"\n⏳ Ciclo de las {hora_fisica_str}:00 completado. Esperando {TIEMPO_ESPERA_ENTRE_HORAS}s...")
                time.sleep(TIEMPO_ESPERA_ENTRE_HORAS)

if __name__ == "__main__":
    iniciar_orquestador()