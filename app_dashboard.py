import io
import os
import pandas as pd
import numpy as np
from flask import Flask, render_template, request, redirect, url_for, send_file, session, jsonify
import warnings

warnings.filterwarnings('ignore')

app = Flask(__name__)
app.secret_key = 'apex_bpo_secret_2026'

# ==========================================
# 🧠 MEMORIA CENTRAL
# ==========================================
DATOS = {
    #'chat_cddiario': None,
    #'encuestas_cddiario': None,
    'llamadas_migraciones': None,
    'rete_out': None,
    'nps_rrss': None,
    'tipificaciones_rrss': None,
    'chats_monetizacion_rrss': None,
    'ventas_migraciones': None 
}

HORA_ACTUAL_SIMULADA = "06"
reportes_generados = []
FECHA_SIMULACION = "2025-06-26" 
FECHA_ARCHIVO_STR = "26062025" 

def extraer_hora_inteligente(df):
    for posible in ['time', 'hora', 'date', 'fecha', 'fecha inicio', 'fecha de registro']:
        for col in df.columns:
            if posible in str(col).lower():
                s = df[col].astype(str)
                hora = s.str.extract(r'(\d{2}):\d{2}:\d{2}', expand=False)
                if hora.dropna().empty:
                    hora = s.str.extract(r'(\d{2}):\d{2}', expand=False)
                
                if not hora.dropna().empty:
                    return hora
    return pd.Series([None] * len(df))

def cargar_datos_crudos(ruta_archivo):
    try:
        df = pd.read_csv(ruta_archivo, sep=',', encoding='utf-8-sig', low_memory=False)
        df['HORA_CORTE'] = extraer_hora_inteligente(df)
        df = df.dropna(subset=['HORA_CORTE'])
        df = df.fillna('')
        return df
    except Exception as e:
        print(f"❌ Error leyendo {ruta_archivo}: {e}")
        return pd.DataFrame()

def inicializar_memoria():
    print(f"⚙️ INICIANDO SERVIDOR CARI AI (CARGANDO Y LIMPIANDO 8 ARCHIVOS)...")
    directorio_actual = os.path.dirname(os.path.abspath(__file__))
    ruta_base = os.path.join(directorio_actual, 'base_datos_interna')
    
    #DATOS['chat_cddiario'] = cargar_datos_crudos(os.path.join(ruta_base, 'base_chat_cddiario_26062025.csv'))
    #DATOS['encuestas_cddiario'] = cargar_datos_crudos(os.path.join(ruta_base, 'base_encuestas_cddiario_26062025.csv'))
    DATOS['llamadas_migraciones'] = cargar_datos_crudos(os.path.join(ruta_base, 'base_llamadas_migraciones_26062025.csv'))
    DATOS['rete_out'] = cargar_datos_crudos(os.path.join(ruta_base, 'base_rete_out_26062025.csv'))
    DATOS['nps_rrss'] = cargar_datos_crudos(os.path.join(ruta_base, 'base_nps_rrss_26062025.csv'))
    DATOS['tipificaciones_rrss'] = cargar_datos_crudos(os.path.join(ruta_base, 'base_tipificaciones_rrss_26062025.csv'))
    DATOS['chats_monetizacion_rrss'] = cargar_datos_crudos(os.path.join(ruta_base, 'chats_monetizacion_rrss_26062025.csv'))
    
    # 🌟 AHORA VENTAS USA EL CARGADOR ESTÁNDAR PORQUE YA TIENE LA COLUMNA 'time'
    DATOS['ventas_migraciones'] = cargar_datos_crudos(os.path.join(ruta_base, 'ventas_26062025.csv'))
    
    print("✅ ¡Las 6 bases de datos fueron cargadas, depuradas y fragmentadas exitosamente!")

inicializar_memoria()

# ==========================================
# 🕹️ API DEL RELOJ MAESTRO
# ==========================================
@app.route('/api/set_hora/<nueva_hora>', methods=['GET'])
def set_hora(nueva_hora):
    global HORA_ACTUAL_SIMULADA
    HORA_ACTUAL_SIMULADA = nueva_hora.zfill(2)
    return jsonify({"status": "success", "mensaje": f"Reloj avanzado a las {HORA_ACTUAL_SIMULADA}:00", "hora_actual": HORA_ACTUAL_SIMULADA})

# ==========================================
# 🖥️ RUTAS FRONTEND
# ==========================================
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = request.form.get('usuario')
        if usuario:
            session['usuario_logueado'] = usuario
            return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('usuario_logueado', None)
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    if 'usuario_logueado' not in session:
        return redirect(url_for('login'))
    
    hora_hasta_num = int(HORA_ACTUAL_SIMULADA) + 1
    
    # 🌟 CORRECCIÓN: Lógica inteligente para formato 12 horas y AM/PM
    am_pm = "pm" if hora_hasta_num >= 12 and hora_hasta_num < 24 else "am"
    hora_12 = hora_hasta_num % 12
    if hora_12 == 0:
        hora_12 = 12
        
    hora_12_str = str(hora_12).zfill(2)
    etiqueta_hora = f"Hasta las {hora_12_str}:00 {am_pm}"


    def obtener_vista(tipo):
        df = DATOS[tipo]
        if df is None or df.empty: return [], []
        
        if HORA_ACTUAL_SIMULADA == "06":
            horas_madrugada = [str(h).zfill(2) for h in range(7)]
            df_hora = df[df['HORA_CORTE'].isin(horas_madrugada)]
        else:
            df_hora = df[df['HORA_CORTE'] == HORA_ACTUAL_SIMULADA]
            
        cols = [c for c in df_hora.columns if c != 'HORA_CORTE']
        return cols, df_hora[cols].head(15).values.tolist()

    
    cab_migraciones, dat_migraciones = obtener_vista('llamadas_migraciones')
    cab_rete_out, dat_rete_out = obtener_vista('rete_out')
    cab_nps_rrss, dat_nps_rrss = obtener_vista('nps_rrss')
    cab_tipi_rrss, dat_tipi_rrss = obtener_vista('tipificaciones_rrss')
    cab_chats_rrss, dat_chats_rrss = obtener_vista('chats_monetizacion_rrss')
    cab_ventas, dat_ventas = obtener_vista('ventas_migraciones')

    return render_template('dashboard.html', 
                           usuario=session['usuario_logueado'], 
                           reportes=reportes_generados,
                           hora_simulacion=etiqueta_hora,
                           cab_migraciones=cab_migraciones, dat_migraciones=dat_migraciones,
                           cab_rete_out=cab_rete_out, dat_rete_out=dat_rete_out,
                           cab_nps_rrss=cab_nps_rrss, dat_nps_rrss=dat_nps_rrss,
                           cab_tipi_rrss=cab_tipi_rrss, dat_tipi_rrss=dat_tipi_rrss,
                           cab_chats_rrss=cab_chats_rrss, dat_chats_rrss=dat_chats_rrss,
                           cab_ventas=cab_ventas, dat_ventas=dat_ventas)

@app.route('/generar_reporte', methods=['POST'])
def generar_reporte():
    if 'usuario_logueado' not in session:
        return redirect(url_for('login'))

    tipo_reporte = request.form.get('tipo_reporte')
    
    nombres_dict = {
        #'chat_cddiario': "Base Chat CD Diario",
        #'encuestas_cddiario': "Encuestas CD Diario",
        'llamadas_migraciones': "Llamadas Migraciones",
        'rete_out': "Retenciones Outbound",
        'nps_rrss': "NPS Redes Sociales",
        'tipificaciones_rrss': "Tipificaciones RRSS",
        'chats_monetizacion_rrss': "Chats y Monetización RRSS",
        'ventas_migraciones': "Base Ventas Migraciones"
    }
    
    hora_hasta_num = int(HORA_ACTUAL_SIMULADA) + 1
    
    # 🌟 CORRECCIÓN: Lógica inteligente para formato 12 horas y AM/PM
    am_pm = "pm" if hora_hasta_num >= 12 and hora_hasta_num < 24 else "am"
    hora_12 = hora_hasta_num % 12
    if hora_12 == 0:
        hora_12 = 12
        
    hora_12_str = str(hora_12).zfill(2)
    hora_24_str = str(hora_hasta_num).zfill(2) # Para conservar el identificador de la hora en formato 24h
    
    nuevo_reporte = {
        "id": 901170 + len(reportes_generados),
        "tipo": tipo_reporte,
        "nombre": f"{nombres_dict.get(tipo_reporte, 'Reporte')} - Hasta las {hora_12_str}:00 {am_pm}",
        "fecha": f"{FECHA_SIMULACION} {hora_24_str}:00:00",
        "estado": "Terminado", 
        "usuario": session['usuario_logueado'],
        "hora_corte": hora_24_str 
    }
    reportes_generados.insert(0, nuevo_reporte)
    return redirect(url_for('dashboard'))

@app.route('/descargar_csv/<int:id_reporte>/<tipo>')
def descargar_csv(id_reporte, tipo):
    df_completo = DATOS.get(tipo)
    if df_completo is None or df_completo.empty:
        return "Error: Base de datos no disponible."

    if HORA_ACTUAL_SIMULADA == "06":
        horas_madrugada = [str(h).zfill(2) for h in range(7)]
        df_filtrado = df_completo[df_completo['HORA_CORTE'].isin(horas_madrugada)].copy()
    else:
        df_filtrado = df_completo[df_completo['HORA_CORTE'] == HORA_ACTUAL_SIMULADA].copy()
    
    df_limpio = df_filtrado.drop(columns=['HORA_CORTE'], errors='ignore')
    
    output = io.StringIO()
    df_limpio.to_csv(output, index=False, encoding='utf-8-sig')
    mem_file = io.BytesIO()
    mem_file.write(output.getvalue().encode('utf-8-sig'))
    mem_file.seek(0)
    
    nombres_archivos_base = {
        #'chat_cddiario': 'base_chat_cddiario',
        #'encuestas_cddiario': 'base_encuestas_cddiario',
        'llamadas_migraciones': 'base_llamadas_migraciones',
        'rete_out': 'base_rete_out',
        'nps_rrss': 'base_nps_rrss',
        'tipificaciones_rrss': 'base_tipificaciones_rrss',
        'chats_monetizacion_rrss': 'chats_monetizacion_rrss',
        'ventas_migraciones': 'base_ventas_migraciones'
    }
    
    base_name = nombres_archivos_base.get(tipo, tipo)
    hora_hasta_str = str(int(HORA_ACTUAL_SIMULADA) + 1).zfill(2)
    nombre_final = f"{base_name}_{FECHA_ARCHIVO_STR}_{hora_hasta_str}00.csv"
    
    return send_file(mem_file, mimetype='text/csv', as_attachment=True, download_name=nombre_final)

@app.route('/borrar_historial', methods=['POST'])
def borrar_historial():
    reportes_generados.clear()
    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=True)