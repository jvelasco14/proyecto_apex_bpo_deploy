import pandas as pd
import numpy as np
import os
import shutil
import uuid
import pytz
import re  
from datetime import datetime
from sqlalchemy import create_engine
import warnings

warnings.filterwarnings('ignore')

def normalizar_y_limpiar_datos(df):
    """
    Capa de Calidad de Datos (Data Cleansing) - Nivel Producción
    Aplica reglas universales sin importar qué archivo esté procesando.
    """
    print("Aplicando reglas universales de limpieza de datos...")
    
    # REGLA 1: Normalización de nombres de columnas
    df.columns = df.columns.str.strip().str.lower().str.replace(' ', '_')
    df.columns = df.columns.str.replace('.', '').str.replace('(', '').str.replace(')', '')
    df.columns = df.columns.str.replace('unnamed:_', 'unnamed_')
    df.columns = df.columns.str.replace('__', '_')

    # Prevenir colisión con Primary Key de Supabase
    if 'id' in df.columns:
        df.rename(columns={'id': 'id_original'}, inplace=True)
        
    # REGLA 2: Eliminación de Columnas Fantasma y Residuales
    columnas_basura = [
        'unicos/reapertura', 'segmento', 'horario', 'intervalos',
        '00:05:00', '300', '00:10:00', '600', '00:20:00', '1200',
        'llave', 'cc'
    ]
    columnas_a_borrar = [col for col in columnas_basura if col in df.columns]
    if columnas_a_borrar:
        df.drop(columns=columnas_a_borrar, inplace=True)
        print(f"   🗑️ Columnas fantasma eliminadas: {columnas_a_borrar}")

    columnas_unnamed = [col for col in df.columns if str(col).startswith('unnamed')]
    if columnas_unnamed:
        df.drop(columns=columnas_unnamed, inplace=True)
        print(f"   🗑️ Columnas Unnamed eliminadas: {len(columnas_unnamed)}")
        
    columnas_fecha = [col for col in df.columns if re.match(r'^202\d-\d{2}-\d{2}', str(col))]
    if columnas_fecha:
        df.drop(columns=columnas_fecha, inplace=True)
        print(f"   🗑️️ Columnas de fecha residuales eliminadas: {columnas_fecha}")
    # ---------------------------------------------------------

    # REGLA 3: Borrar SOLO filas completamente vacías (evitando drop_duplicates)
    df = df.dropna(how='all')

    # REGLA 4: Convertir "Falsos Nulos" a nulos reales
    valores_nulos_sistema = ['[None]', 'N/A', 'n/a', 'NaN', 'null', '']
    df.replace(valores_nulos_sistema, np.nan, inplace=True)

    # REGLA 5: Imputación Inteligente por Tipo de Dato
    for col in df.columns:
        if df[col].dtype == 'object':
            # Si es columna de texto: limpiar espacios invisibles y rellenar nulos
            df[col] = df[col].astype(str).str.strip()
            df[col] = df[col].replace(['nan', 'None'], 'No Registrado') 
            df[col] = df[col].fillna('No Registrado')
        else:
            # Si es columna numérica (int, float): rellenar con ceros para no dañar las matemáticas
            df[col] = df[col].fillna(0)

    #Invertir el orden para que lo más antiguo (00:01) quede arriba y entre primero
    df = df.iloc[::-1].reset_index(drop=True)
    return df

def ejecutar_etl():
    print("===================================================")
    print("⚙️ INICIANDO MOTOR ETL (GOBERNANZA DE DATOS)")
    print("===================================================")
    
    carpeta_descargas = 'descargas_bot'
    carpeta_historico = 'historico_procesados'
    os.makedirs(carpeta_historico, exist_ok=True)
    
    # Zona horaria de Colombia
    tz_colombia = pytz.timezone('America/Bogota')
    lote_id = str(uuid.uuid4())[:8]
    
    # CONEXIÓN A LA BASE DE DATOS
    db_url = "postgresql+psycopg2://postgres.vdvmyueufdfviztmribf:Velasco14062000**@aws-1-us-east-1.pooler.supabase.com:5432/postgres"
    engine = create_engine(db_url)
    print("🔗 Conectado exitosamente a PostgreSQL en Supabase")
    
    archivos_procesados = 0
    registros_auditoria = []

    try:
        archivos_csv = [f for f in os.listdir(carpeta_descargas) if f.endswith('.csv')]
        
        if not archivos_csv:
            print("📭 No hay archivos nuevos en la carpeta de descargas.")
            return

        for archivo in archivos_csv:
            ruta_archivo = os.path.join(carpeta_descargas, archivo)
            inicio_proc = datetime.now(tz_colombia)
            print(f"\n⏳ Procesando y subiendo: {archivo}...")
            
            # Carga del CSV
            df = pd.read_csv(ruta_archivo, encoding='utf-8-sig', low_memory=False)
            
            # --- LIMPIEZA Y GOBERNANZA ---
            df = normalizar_y_limpiar_datos(df)

            # 🔪 GUILLOTINA DE COLUMNAS (Automatización Pura)
            # Cortar columnas manuales de la plantilla si existen
            columna_corte = 'cuenta_atendido'
            if columna_corte in df.columns:
                indice = df.columns.get_loc(columna_corte)
                df = df.iloc[:, :indice]
                print(f"   🔪 Guillotina activada: Se eliminaron las columnas calculadas desde '{columna_corte}' en adelante.")

            # =========================================================
            # 🛡️ ESCUDOS Y PARCHES DE SEGURIDAD (FASE 4.5)
            # =========================================================
            
            # 🛠️ PARCHE: CORRECCIÓN DE FORMATOS RAROS DE TIEMPO (ej. "22 days")
            if 'día' in df.columns:
                df['día'] = df['día'].astype(str).str.extract(r'(\d+)')[0]
                df['día'] = pd.to_numeric(df['día'], errors='coerce').fillna(0).astype(int)
                
            if 'mes' in df.columns:
                df['mes'] = pd.to_numeric(df['mes'], errors='coerce').fillna(0).astype(int)
                
            if 'año' in df.columns:
                df['año'] = pd.to_numeric(df['año'], errors='coerce').fillna(0).astype(int)

            # 🔨 HACK DE INGENIERÍA: FORZAR CORRECCIÓN DE FECHAS REBELDES (SOLO PARA MONETIZACIÓN)
            archivo_lower = archivo.lower()
            if 'chats_monetizacion' in archivo_lower:
                print("   🔧 Aplicando parche de fechas al archivo de Monetización RRSS...")
                
                # Forzar el día 26 en todas las columnas de fecha
                columnas_de_fecha = ['fecha_inicio', 'fecha_asignación', 'fecha_atención', 'fecha_finalización']
                for col in columnas_de_fecha:
                    if col in df.columns:
                        df[col] = df[col].astype(str)
                        df[col] = df[col].str.replace('2025-06-22', '2025-06-26', regex=False)
                        df[col] = df[col].str.replace('22/06/2025', '26/06/2025', regex=False)
                        df[col] = df[col].str.replace('2025/06/22', '2025/06/26', regex=False)
                        df[col] = df[col].replace(['nan', 'NaN', 'None', 'NaT', ''], None)
                
                # Obligar a las columnas numéricas a tener el valor correcto
                if 'año' in df.columns: df['año'] = 2025
                if 'mes' in df.columns: df['mes'] = 6
                if 'día' in df.columns: df['día'] = 26
                if 'condición' in df.columns: df['condición'] = '20250626'
            
            # 🌟 NUEVO PARCHE: VENTAS MIGRACIONES
            # Alineación estricta de nombres con el esquema de base_ventas_migraciones
            if 'ventas_migraciones' in archivo_lower:
                print("   🔧 Aplicando parche de alineación de columnas para Ventas Migraciones...")
                
                # Renombramos las columnas del CSV normalizado para que coincidan con la DB
                renombres_ventas = {
                    'cédula_del_agente': 'cedula_del_agente',
                    'cédula_del_cliente': 'cedula_del_cliente',
                    'número_de_la_línea_a_portar,_migrar_o_línea_nueva_activada': 'numero_linea_gestionada',
                    'día': 'dia' 
                }
                df.rename(columns=renombres_ventas, inplace=True)
                
                # Agregamos la columna 'gestion' que está en Supabase pero no en el CSV (Asignamos valor por defecto o nulo)
                if 'gestion' not in df.columns:
                    df['gestion'] = 'Migración Inbound' # Valor lógico asignado por negocio
            # =========================================================
            
            # --- AGREGAR COLUMNAS DE AUDITORÍA ---
            df['etl_origen_archivo'] = archivo
            df['etl_lote_ejecucion'] = lote_id
            df['etl_fecha_carga_col'] = inicio_proc.strftime("%Y-%m-%d %H:%M:%S")
            
            # --- RUTEO A TABLAS EN SUPABASE ---
            if 'chat' in archivo_lower and 'cddiario' in archivo_lower:
                tabla_dinamica = 'base_chat_cddiario'
            elif 'encuestas' in archivo_lower and 'cddiario' in archivo_lower:
                tabla_dinamica = 'base_encuestas_cddiario'
            elif 'llamadas' in archivo_lower or 'migraciones' in archivo_lower and not 'ventas' in archivo_lower:
                tabla_dinamica = 'base_llamadas_migraciones'
            elif 'rete_out' in archivo_lower:
                tabla_dinamica = 'base_rete_out'
            elif 'nps_rrss' in archivo_lower:
                tabla_dinamica = 'base_nps_rrss'
            elif 'chats_monetizacion' in archivo_lower or 'chats_rrss' in archivo_lower:
                tabla_dinamica = 'chats_monetizacion_rrss'
                
                # 🔥 ESCUDO FINAL PARA RRSS: Garantizar que a la BD solo entren las columnas del DDL
                columnas_permitidas = [
                    'id_original', 'cola_de_atención', 'id_conversación', 'bot', 'canal', 
                    'nombre_del_cliente', 'identificacion_del_cliente', 'tipo_de_cliente', 
                    'fecha_inicio', 'fecha_asignación', 'fecha_atención', 'tiempo_en_espera', 
                    'tiempo_primera_respuesta', 'tiempo_de_asignación', 'tiempo_conversacion', 
                    'fecha_finalización', 'duración', 'cerrado_por', 'agente', 'skill', 
                    'recibida_por', 'login_agente',
                    'etl_origen_archivo', 'etl_lote_ejecucion', 'etl_fecha_carga_col'
                ]
                df = df[[c for c in df.columns if c in columnas_permitidas]]
                
            elif 'tipificaciones' in archivo_lower:
                tabla_dinamica = 'base_tipificaciones_rrss'
            
            # 🌟 Ruteo para la nueva tabla de ventas
            elif 'ventas_migraciones' in archivo_lower:
                tabla_dinamica = 'base_ventas_migraciones'
                
                # Nota: 'base_de_gestión' mantendrá la tilde de la normalización a menos que la base diga 'base_de_gestion'
                if 'base_de_gestión' in df.columns:
                    df.rename(columns={'base_de_gestión': 'base_de_gestion'}, inplace=True)
                
                # ESCUDO ESTRICTO: Dejar solo las columnas que exige Supabase (AÑADIDO 'time')
                columnas_permitidas_ventas = [
                    'marca_temporal', 'nombre_del_asesor', 'cedula_del_agente', 'msisdn',
                    'cedula_del_cliente', 'numero_linea_gestionada', 'gestion', 'contactado',
                    'plan_vendido', 'canal_de_venta', 'supervisor', 'base_de_gestion', 'fecha_de_venta',
                    'mes', 'dia', 'time', 'etl_origen_archivo', 'etl_lote_ejecucion', 'etl_fecha_carga_col'
                ]
                
                # Retenemos únicamente las columnas permitidas
                df = df[[c for c in df.columns if c in columnas_permitidas_ventas]]
            else:
                print(f"   ⚠️ Archivo no reconocido para ruteo: {archivo}. Se ignorará.")
                continue 
                
            # --- INYECCIÓN EN SUPABASE ---
            # 1. Capa Dinámica
            df.to_sql(tabla_dinamica, engine, if_exists='append', index=False)
            
            # --- REGISTRO PARA AUDITORÍA ---
            registros_auditoria.append({
                'lote_id': lote_id,
                'archivo_procesado': archivo,
                'tabla_destino': tabla_dinamica,
                'cantidad_filas': len(df),
                'fecha_ejecucion_col': inicio_proc.strftime("%Y-%m-%d %H:%M:%S"),
                'estado': 'EXITOSO'
            })
            
            # --- MOVER AL HISTÓRICO LOCAL ---
            timestamp_str = inicio_proc.strftime("%Y%m%d_%H%M%S")
            nuevo_nombre = f"PROCESADO_{timestamp_str}_{archivo}"
            shutil.move(ruta_archivo, os.path.join(carpeta_historico, nuevo_nombre))
            archivos_procesados += 1
            print(f"   ✅ Se inyectaron {len(df)} registros en {tabla_dinamica}.")

    except Exception as e:
        print(f"\n❌ Error Crítico en el ETL: {e}")
        registros_auditoria.append({
            'lote_id': lote_id,
            'archivo_procesado': 'Error de Lote',
            'tabla_destino': 'ERROR',
            'cantidad_filas': 0,
            'fecha_ejecucion_col': datetime.now(tz_colombia).strftime("%Y-%m-%d %H:%M:%S"),
            'estado': f'ERROR: {str(e)[:200]}'
        })
    finally:
        # Inyectar log de auditoría
        if registros_auditoria:
            df_auditoria = pd.DataFrame(registros_auditoria)
            df_auditoria.to_sql('etl_auditoria', engine, if_exists='append', index=False)
            print("📊 Tabla de trazabilidad 'etl_auditoria' actualizada.")
            
        print(f"🚀 ETL Finalizado. {archivos_procesados} archivo(s) procesado(s).")

if __name__ == "__main__":
    ejecutar_etl()