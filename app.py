import os
from dotenv import load_dotenv

from fastapi import FastAPI, Request, Form, Depends, HTTPException, status, Response, APIRouter
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import uvicorn
from supabase import create_client, Client
from sklearn.ensemble import IsolationForest
import pandas as pd
from datetime import date, datetime
import numpy as np
import re
import pytz
from datetime import date, datetime

load_dotenv() # Carga las variables del archivo .env
# ==========================================
# 🔗 CONEXIÓN A LA BASE DE DATOS (SUPABASE)
# ==========================================
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# 🔑 SÚPER CLIENTE ADMIN (Para crear usuarios y enviar correos)
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
supabase_admin: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# ==========================================
# 🧠 FUNCIÓN MAESTRA DE MAPEO DE AGENTES
# ==========================================
def get_agentes_maps():
    try:
        resp = supabase.table("dim_agentes").select("id, cedula, five9, asesor").limit(10000).execute()
        mapa_nombres = {}  
        mapa_cedulas = {}  
        for ag in (resp.data or []):
            nom = str(ag.get("asesor") or "").strip()
            ced = str(ag.get("cedula") or "").strip().replace('.0', '')
            id_int = str(ag.get("id") or "").strip().replace('.0', '')
            f9 = str(ag.get("five9") or "").strip().replace('.0', '')
            
            if nom:
                if ced and ced != 'None': 
                    mapa_nombres[ced] = nom
                    mapa_cedulas[nom.lower()] = ced
                    mapa_cedulas[ced] = ced
                if id_int and id_int != 'None': 
                    mapa_nombres[id_int] = nom
                    mapa_cedulas[id_int] = ced
                if f9 and f9 != 'None': 
                    mapa_nombres[f9] = nom
                    mapa_cedulas[f9] = ced
        return mapa_nombres, mapa_cedulas
    except: return {}, {}

# ==========================================
# 🚀 INICIALIZACIÓN DEL SERVIDOR FASTAPI
# ==========================================
app = FastAPI(title="GTR Analytics - Apex")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates_ia")

async def verificar_sesion(request: Request):
    token = request.cookies.get("access_token")
    if not token: raise HTTPException(status_code=status.HTTP_307_TEMPORARY_REDIRECT, headers={"Location": "/login"})
    try:
        res = supabase.auth.get_user(token)
        if not res or not res.user: raise HTTPException(status_code=status.HTTP_307_TEMPORARY_REDIRECT, headers={"Location": "/login"})
        return res.user
    except Exception: raise HTTPException(status_code=status.HTTP_307_TEMPORARY_REDIRECT, headers={"Location": "/login"})

rutas_protegidas = APIRouter(dependencies=[Depends(verificar_sesion)])

# ==========================================
# 🩺 HEALTH CHECK (Monitoreo del Servidor)
# ==========================================
@app.get("/health")
async def health_check():
    return {"status": "ok", "message": "GTR Analytics funcionando correctamente"}

# ==========================================

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = None):
    return templates.TemplateResponse(request=request, name="login.html", context={"request": request, "error": error})

@app.post("/login")
async def procesar_login(response: Response, email: str = Form(...), password: str = Form(...)):
    try:
        auth_response = supabase.auth.sign_in_with_password({"email": email, "password": password})
        token = auth_response.session.access_token
        redirect_response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
        redirect_response.set_cookie(key="access_token", value=token, httponly=True, samesite="lax", secure=False, max_age=28800)
        return redirect_response
    except Exception as e:
        return RedirectResponse(url="/login?error=credenciales_invalidas", status_code=status.HTTP_302_FOUND)

@app.get("/logout")
async def logout():
    redirect_response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    redirect_response.delete_cookie("access_token")
    try: supabase.auth.sign_out()
    except Exception: pass
    return redirect_response

# =========================================================================
# 1. RUTA DEL FRONTEND (GLOBAL OVERVIEW) - CONSOLIDADO GERENCIAL
# =========================================================================
@rutas_protegidas.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, fecha: str = None):
    fecha_consulta = fecha if fecha else "2025-06-26" 
    vol_mig = vol_ret = vol_rrss = 0
    conv_mig = conv_ret = 0
    promotores = detractores = encuestas = 0
    alertas_ia = []
    mapa_nombres, _ = get_agentes_maps()

    try:
        r_mig = supabase.table("vw_rt_embudo_llamadas").select("total_base").eq("date", fecha_consulta).execute()
        if r_mig.data: vol_mig = r_mig.data[0].get("total_base", 0)
        r_v_mig = supabase.table("vw_rt_ventas_consolidadas").select("ventas_totales").eq("date", fecha_consulta).execute()
        if r_v_mig.data: conv_mig = r_v_mig.data[0].get("ventas_totales", 0)
    except Exception: pass

    try:
        r_ret = supabase.table("vw_ret_rt_embudo").select("total_base, retenciones").eq("date", fecha_consulta).execute()
        if r_ret.data:
            vol_ret = r_ret.data[0].get("total_base", 0)
            conv_ret = r_ret.data[0].get("retenciones", 0)
    except Exception: pass

    try:
        r_rrss = supabase.table("vw_hist_rrss_eod_matriz").select("ofrecidas, promotores, detractores, pasivos").eq("fecha_real", fecha_consulta).execute()
        if r_rrss.data:
            vol_rrss = sum(int(row.get("ofrecidas", 0)) for row in r_rrss.data)
            promotores = sum(int(row.get("promotores", 0)) for row in r_rrss.data)
            detractores = sum(int(row.get("detractores", 0)) for row in r_rrss.data)
            encuestas = sum(int(row.get("promotores", 0)) + int(row.get("pasivos", 0)) + int(row.get("detractores", 0)) for row in r_rrss.data)
    except Exception: pass

    try:
        r_alertas = supabase.table("ml_alertas_globales").select("*").eq("call_date", fecha_consulta).order("fecha_deteccion", desc=True).execute()
        if r_alertas.data: alertas_ia = r_alertas.data
    except Exception: pass

    trafico_total = vol_mig + vol_ret + vol_rrss
    conversiones_totales = conv_mig + conv_ret
    nps_global = round(((promotores - detractores) / encuestas) * 100, 1) if encuestas > 0 else 0
    tasa_anomalias = round((len(alertas_ia) / trafico_total) * 100, 2) if trafico_total > 0 else 0

    conteo_frentes = {"Migraciones": 0, "Retenciones": 0, "RRSS": 0}
    for alerta in alertas_ia:
        origen = str(alerta.get("origen_datos", "")).lower()
        if "migracion" in origen: conteo_frentes["Migraciones"] += 1; alerta["origen_datos"] = "Migraciones Inbound"
        elif "retencion" in origen: conteo_frentes["Retenciones"] += 1; alerta["origen_datos"] = "Retenciones Outbound"
        elif "chat" in origen or "rrss" in origen or "redes" in origen: conteo_frentes["RRSS"] += 1; alerta["origen_datos"] = "Redes Sociales (Chat)"
            
        as_id_raw = str(alerta.get("asesor_id") or "").strip().replace('.0', '')
        if not as_id_raw or as_id_raw in ["None", "N/A", "nan"]:
            match = re.search(r'CC:\s*(\w+)', str(alerta.get("descripcion", "")))
            if not match: match = re.search(r'ID:\s*(\w+)', str(alerta.get("descripcion", "")))
            if match: as_id_raw = match.group(1)
            
        alerta["asesor_id_limpio"] = as_id_raw if as_id_raw else "N/A"
        alerta["nombre_asesor"] = mapa_nombres.get(alerta["asesor_id_limpio"], "Sin Asignación (No en BD)") if alerta["asesor_id_limpio"] != "N/A" else "Desconocido"

        alertas_ia.sort(key=lambda x: str(x.get("call_time", "")), reverse=True)
    
    contexto_datos = {
        "request": request, "titulo": "Global Overview", "menu_activo": "global",
        "fecha_consulta": fecha_consulta, "volumen_total": trafico_total,
        "vol_migraciones": vol_mig, "vol_retenciones": vol_ret, "vol_rrss": vol_rrss,
        "conversiones_totales": conversiones_totales, "nps_global": nps_global, "tasa_anomalias": tasa_anomalias,
        "total_alertas": len(alertas_ia), "alertas": alertas_ia,
        "datos_dona": [conteo_frentes["Migraciones"], conteo_frentes["Retenciones"], conteo_frentes["RRSS"]],
        "datos_barras": [vol_mig, vol_ret, vol_rrss]
    }
    return templates.TemplateResponse(request=request, name="webdash.html", context=contexto_datos)


# =========================================================================
# 2. RUTA: MIGRACIONES RT
# =========================================================================
@rutas_protegidas.get("/migraciones/rt", response_class=HTMLResponse)
async def migraciones_rt(request: Request, fecha: str = None):
    # ----- CONFIGURACIÓN DE FECHA -----
    # 1. PARA PRODUCCIÓN REAL (Descomentar en la vida real):
    # zona_colombia = pytz.timezone('America/Bogota')
    # fecha_hoy_real = datetime.now(zona_colombia).strftime("%Y-%m-%d")
    
    # 2. PARA LA SUSTENTACIÓN DE TESIS (Data estática):
    fecha_hoy_real = "2025-06-26" 
    # ----------------------------------
    
    fecha_consulta = fecha if fecha else fecha_hoy_real
    es_historico = fecha_consulta != fecha_hoy_real
    mapa_nombres, mapa_cedulas = get_agentes_maps()
    
    try:
        resp_embudo = supabase.table("vw_rt_embudo_llamadas").select("*").eq("date", fecha_consulta).execute()
        data_embudo = resp_embudo.data[0] if resp_embudo.data else {"total_base": 0, "contacto_cliente": 0, "contacto_favorable": 0}
        total_base, contacto_cliente, contacto_favorable = data_embudo.get("total_base", 0), data_embudo.get("contacto_cliente", 0), data_embudo.get("contacto_favorable", 0)

        resp_ventas = supabase.table("vw_rt_ventas_consolidadas").select("*").eq("date", fecha_consulta).execute()
        data_ventas = resp_ventas.data[0] if resp_ventas.data else {"ventas_totales": 0, "ventas_migraciones": 0, "ventas_portabilidad": 0, "ventas_linea_nueva": 0}
        ventas_totales = data_ventas.get("ventas_totales", 0)
        tipos_venta = {"Migraciones": data_ventas.get("ventas_migraciones", 0), "Portabilidad": data_ventas.get("ventas_portabilidad", 0), "Linea Nueva": data_ventas.get("ventas_linea_nueva", 0)}

        # =================================================================
        # 1. Verificar si la operación ya cerró (Buscando el K-Means de cierre)
        # =================================================================
        operacion_cerrada = False
        try:
            resp_cierre = supabase.table("ml_insights_migraciones").select("id", count="exact").eq("fecha_analisis", fecha_consulta).execute()
            if resp_cierre.count and resp_cierre.count > 0:
                operacion_cerrada = True
        except: pass
        # =================================================================

        resp_agentes = supabase.table("vw_rt_agentes_leaderboard").select("*").eq("date", fecha_consulta).execute()
        lista_agentes, activos_llamada = [], 0
        for ag in (resp_agentes.data or []):
            marcaciones, ventas, efectivas_2m = ag.get("marcaciones", 0), ag.get("ventas", 0), ag.get("llamadas_efectivas", 0)
            efec = min((ventas / efectivas_2m * 100), 100.0) if efectivas_2m > 0 else 0
            
            # 2. Si la operación NO ha cerrado y NO es histórico, sumamos los activos
            if marcaciones > 0 and not es_historico and not operacion_cerrada: 
                activos_llamada += 1
                
            lista_agentes.append({"id": ag.get("asesor_id", ""), "nombre": ag.get("nombre", "Desconocido"), "supervisor": ag.get("supervisor", "Sin Supervisor"), "marcaciones": marcaciones, "llamadas_efectivas": efectivas_2m, "ventas": ventas, "efectividad": round(efec, 2)})
            
        lista_agentes.sort(key=lambda x: (x["ventas"], x["efectividad"], x["marcaciones"]), reverse=True)
        total_agentes_activos = max(1, len(lista_agentes))
        libres_pausa = max(0, total_agentes_activos - activos_llamada)

        resp_motivos = supabase.table("vw_rt_motivos_llamada").select("*").eq("date", fecha_consulta).order("cantidad", desc=True).limit(5).execute()
        rt_nombres_motivos, rt_valores_motivos = [], []
        for m in (resp_motivos.data or []):
            motivo_limpio = {"NO ANSWER": "Sin Respuesta", "CALLER DISCONNECTED": "Cliente Cuelga", "CLIENTE CUELGA": "Cliente Cuelga", "HANGUP": "Colgó / Cortó", "ANSWERING MACHINE": "Buzón de Voz", "BUZON": "Buzón de Voz", "ACEPTA": "Acepta / Interesado", "VENTA": "Venta Exitosa"}.get(str(m.get("motivo", "")).upper(), str(m.get("motivo", "")).title())
            rt_nombres_motivos.append(motivo_limpio)
            rt_valores_motivos.append(m.get("cantidad", 0))

        resp_horas = supabase.table("vw_rt_distribucion_horas").select("*").eq("date", fecha_consulta).execute()
        distribucion_horas = {f"{h:02d}:00": 0 for h in range(8, 18)}
        for h in (resp_horas.data or []):
            hora = h.get("hora_llamada", "")
            if hora in distribucion_horas: distribucion_horas[hora] = h.get("volumen", 0)

    except Exception as e:
        total_base = contacto_cliente = contacto_favorable = ventas_totales = activos_llamada = libres_pausa = 0
        tipos_venta = {"Migraciones": 0, "Portabilidad": 0, "Linea Nueva": 0}
        lista_agentes, rt_nombres_motivos, rt_valores_motivos, distribucion_horas = [], [], [], {f"{h:02d}:00": 0 for h in range(8, 18)}

    dispersion_data = [{"x": 160 + (i * 15) % 120, "y": ag["ventas"], "r": max(ag["marcaciones"] * 1.5, 4)} for i, ag in enumerate(lista_agentes)]
    alertas_rt_ml, asesores_anomalos_ids = [], set()
    
    try:
        # ✔️ CORRECCIÓN: SIN LÍMITE (Trae TODO el día)
        resp_ml = supabase.table("ml_alertas_globales").select("*").ilike("origen_datos", "%Migracion%").eq("call_date", fecha_consulta).order("fecha_deteccion", desc=True).execute()
        for alerta in (resp_ml.data or []):
            desc_limpia = str(alerta.get("descripcion", "")).replace("BuzÃ³n", "Buzón").replace("MigraciÃ³n", "Migración").replace("Ã³", "ó").replace("Ã±", "ñ").replace("Ã¡", "á")
            alerta["descripcion"] = desc_limpia
            
            as_id = str(alerta.get("asesor_id", "")).strip().replace('.0', '')
            if not as_id or as_id in ["None", "N/A"]:
                match = re.search(r'CC:\s*(\w+)', desc_limpia)
                if not match: match = re.search(r'ID:\s*(\w+)', desc_limpia)
                if match: as_id = match.group(1)
            
            cc_real = mapa_cedulas.get(as_id.lower(), as_id) if as_id else "N/A"
            alerta["asesor_id"] = cc_real
            if cc_real != "N/A": asesores_anomalos_ids.add(cc_real)

            c_date, c_time = alerta.get("call_date", ""), alerta.get("call_time", "")
            alerta["fecha_deteccion"] = f"{c_date} {c_time} (Llamada)" if c_date and c_time else str(alerta.get("fecha_deteccion", "")).replace("T", " ")[:19]
            alertas_rt_ml.append(alerta)
    except: pass

    alertas_rt_ml.sort(key=lambda x: str(x.get("call_time", "")), reverse=True)

    alertas_macro_ml = []
    try:
        resp_macro = supabase.table("ml_alertas_macro").select("*").ilike("origen_datos", "%Migracion%").eq("call_date", fecha_consulta).execute()
        for m in (resp_macro.data or []):
            if m.get("call_date") and m.get("call_time"): m["fecha_deteccion"] = f"{m['call_date']} {m['call_time']} (Franja Horaria)"
            alertas_macro_ml.append(m)
        alertas_macro_ml.sort(key=lambda x: (str(x.get("call_date", "")), str(x.get("call_time", ""))), reverse=True)
    except: pass

    contexto = {
        "request": request, "titulo": "MIGRACIONES INBOUND", "menu_activo": "rt",
        "fecha_consulta": fecha_consulta, "es_historico": es_historico, "fecha_hoy_real": fecha_hoy_real, 
        "embudo": {"total_base": total_base, "contacto_cliente": contacto_cliente, "pct_contacto": round((contacto_cliente / total_base * 100) if total_base > 0 else 0, 2), "contacto_favorable": contacto_favorable, "pct_favorable": round((contacto_favorable / contacto_cliente * 100) if contacto_cliente > 0 else 0, 2), "ventas": ventas_totales, "pct_venta_favorable": round((ventas_totales / contacto_favorable * 100) if contacto_favorable > 0 else 0, 2), "pct_venta_contacto": round((ventas_totales / contacto_cliente * 100) if contacto_cliente > 0 else 0, 2), "efectividad_acida": round((ventas_totales / total_base * 100) if total_base > 0 else 0, 2)},
        "desglose_ventas": tipos_venta, "rt_nombres_motivos": rt_nombres_motivos, "rt_valores_motivos": rt_valores_motivos,
        "horas_labels": list(distribucion_horas.keys()), "horas_valores": list(distribucion_horas.values()),
        "estado_agentes": [activos_llamada, libres_pausa], "dispersion_agentes": dispersion_data,
        "alertas_rt_ml": alertas_rt_ml, "alertas_macro_ml": alertas_macro_ml, 
        "asesores_anomalos_ids": asesores_anomalos_ids, "agentes": lista_agentes
    }
    return templates.TemplateResponse(request=request, name="migraciones_rt.html", context=contexto)


# =========================================================================
# 3. RUTA: MIGRACIONES EOD
# =========================================================================
@rutas_protegidas.get("/migraciones/eod", response_class=HTMLResponse)
async def migraciones_eod(request: Request, fecha: str = None):
    fecha_eod_str = fecha if fecha else "2025-06-26" 
    mapa_nombres, _ = get_agentes_maps()
    
    try:
        resp_kpis = supabase.table("vw_mig_eod_kpis").select("*").eq("date", fecha_eod_str).execute()
        data_kpis = resp_kpis.data[0] if resp_kpis.data else {"total_marcaciones": 0, "tmo_promedio": 0}
        eod_total_marcaciones = data_kpis.get("total_marcaciones", 0)
        eod_tmo_promedio = round(data_kpis.get("tmo_promedio", 0) or 0, 1)

        resp_ventas = supabase.table("vw_rt_ventas_consolidadas").select("*").eq("date", fecha_eod_str).execute()
        eod_ventas_totales = resp_ventas.data[0].get("ventas_totales", 0) if resp_ventas.data else 0

        resp_agentes = supabase.table("vw_mig_eod_agentes").select("*").eq("date", fecha_eod_str).execute()
        lista_asesores_eod = [{"asesor": ag.get("asesor_id", ""), "marcaciones": ag.get("marcaciones", 0), "ventas": ag.get("ventas", 0), "efectividad": round(ag.get("efectividad", 0), 2)} for ag in (resp_agentes.data or [])]
        eod_agentes_activos = len(lista_asesores_eod)
        eod_top_asesores = sorted(lista_asesores_eod, key=lambda x: (x["ventas"], x["efectividad"]), reverse=True)
        eod_bottom_asesores = sorted(lista_asesores_eod, key=lambda x: (x["ventas"], x["efectividad"]))

        resp_motivos = supabase.table("vw_mig_eod_motivos").select("*").eq("date", fecha_eod_str).order("cantidad", desc=True).limit(5).execute()
        eod_disp_labels = [m.get("motivo", "") for m in (resp_motivos.data or [])]
        eod_disp_valores = [m.get("cantidad", 0) for m in (resp_motivos.data or [])]

        resp_horas = supabase.table("vw_mig_eod_horas").select("*").eq("date", fecha_eod_str).execute()
        distribucion_horas = {f"{h:02d}:00": 0 for h in range(7, 19)}
        for h in (resp_horas.data or []):
            if h.get("hora_llamada", "") in distribucion_horas: distribucion_horas[h.get("hora_llamada", "")] = h.get("volumen", 0)

        resp_insights = supabase.table("ml_insights_migraciones").select("*").eq("fecha_analisis", fecha_eod_str).execute()
        insights_kmeans = [i for i in (resp_insights.data or []) if str(i.get("agente", "")).strip() not in ["0", "0.0", "None", "", "nan"]]
        insights_kmeans = sorted(insights_kmeans, key=lambda x: float(x.get("metrica_principal", 0)), reverse=True)
        
        for k in insights_kmeans:
            ag_raw = str(k.get("agente", "")).strip()
            k["nombre_asesor"] = mapa_nombres.get(ag_raw, ag_raw)

        resp_crudas = supabase.table("hist_base_llamadas_migraciones").select("id", count="exact").eq("date", fecha_eod_str).execute()
        eod_llamadas_crudas = resp_crudas.count if resp_crudas.count else 0

    except Exception as e:
        eod_total_marcaciones = eod_tmo_promedio = eod_ventas_totales = eod_agentes_activos = eod_llamadas_crudas = 0
        eod_disp_labels, eod_disp_valores, distribucion_horas, eod_top_asesores, eod_bottom_asesores, insights_kmeans = [], [], {f"{h:02d}:00": 0 for h in range(7, 19)}, [], [], []

    contexto_eod = {
        "request": request, "titulo": "Migraciones (Inbound)", "menu_activo": "migraciones_eod",
        "eod_fecha_analisis": fecha_eod_str, "eod_ventas_totales": eod_ventas_totales,
        "eod_llamadas_crudas": eod_llamadas_crudas,
        "eod_efectividad_acida": round((eod_ventas_totales / eod_total_marcaciones) * 100, 2) if eod_total_marcaciones > 0 else 0,
        "eod_total_marcaciones": eod_total_marcaciones, "eod_tmo_promedio": eod_tmo_promedio, "eod_agentes_activos": eod_agentes_activos,
        "eod_horas_labels": list(distribucion_horas.keys()), "eod_horas_valores": list(distribucion_horas.values()),
        "eod_disp_labels": eod_disp_labels, "eod_disp_valores": eod_disp_valores,
        "eod_top_asesores": eod_top_asesores, "eod_bottom_asesores": eod_bottom_asesores, "insights_kmeans": insights_kmeans
    }
    return templates.TemplateResponse(request=request, name="migraciones_eod.html", context=contexto_eod)

# =========================================================================
# 4. RUTA: MIGRACIONES ML
# =========================================================================
@rutas_protegidas.get("/migraciones/ml", response_class=HTMLResponse)
async def migraciones_ml(request: Request, fecha: str = None):
    fecha_analisis_str = fecha if fecha else "2025-06-26"
    mapa_nombres, _ = get_agentes_maps()
    
    try:
        resp_kmeans = supabase.table("ml_insights_migraciones").select("*").eq("fecha_analisis", fecha_analisis_str).execute()
        kmeans_limpio = [k for k in (resp_kmeans.data or []) if str(k.get("agente", "")).strip() not in ["0", "0.0", "None", "", "nan"]]
        
        for k in kmeans_limpio:
            ag_raw = str(k.get("agente", "")).strip()
            k["nombre_asesor"] = mapa_nombres.get(ag_raw, ag_raw)
            
        # ✔️ CORRECCIÓN: ILIKE PARA UNIFICAR CRITERIOS CON RT
        resp_if = supabase.table("ml_alertas_globales").select("*").ilike("origen_datos", "%Migracion%").eq("call_date", fecha_analisis_str).execute()
        if_data = resp_if.data if resp_if.data else []
        freq_dict = {}
        for alerta in if_data: freq_dict[alerta.get("tipo_alerta", "Desconocida")] = freq_dict.get(alerta.get("tipo_alerta", "Desconocida"), 0) + 1
        
        resp_macro = supabase.table("ml_alertas_macro").select("*").ilike("origen_datos", "%Migracion%").eq("call_date", fecha_analisis_str).execute()
        macro_data = resp_macro.data if resp_macro.data else []
        for m in macro_data:
            if m.get("call_date") and m.get("call_time"): m["fecha_deteccion"] = f"{m['call_date']} {m['call_time']} (Franja Horaria)"
        macro_data.sort(key=lambda x: (str(x.get("call_date", "")), str(x.get("call_time", ""))), reverse=True)
        
    except Exception as e:
        kmeans_limpio, freq_dict, if_data, macro_data = [], {}, [], []

    scatter_alto_rendimiento, scatter_estandar, scatter_oportunidad = [], [], []
    for k in kmeans_limpio:
        punto = {"x": float(k.get("metrica_secundaria") or 0), "y": float(k.get("metrica_principal") or 0), "agente": k.get("nombre_asesor", "")}
        cluster = str(k.get("cluster_nombre", ""))
        if "Francotiradores" in cluster or "Estrella" in cluster: scatter_alto_rendimiento.append(punto)
        elif "Estándar" in cluster: scatter_estandar.append(punto)
        else: scatter_oportunidad.append(punto)

    contexto_ml = {
        "request": request, "titulo": "Migraciones Inbound", "menu_activo": "ml_migraciones",
        "fecha_analisis": fecha_analisis_str, "total_agentes_perfilados": len(kmeans_limpio),
        "total_micro_anomalias": len(if_data), "total_macro_anomalias": len(macro_data),
        "scatter_alto_rendimiento": scatter_alto_rendimiento, "scatter_estandar": scatter_estandar,
        "scatter_oportunidad": scatter_oportunidad, "labels_anomalias": list(freq_dict.keys()),
        "valores_anomalias": list(freq_dict.values()), "macro_data": macro_data,
        "insights_kmeans": sorted(kmeans_limpio, key=lambda x: float(x.get("metrica_principal", 0)), reverse=True),
        "if_ultimas_alertas": sorted(if_data, key=lambda x: str(x.get("call_time", "")), reverse=True) 
    }
    return templates.TemplateResponse(request=request, name="migraciones_ml.html", context=contexto_ml)

# =========================================================================
# 5. RUTA: RETENCIONES RT
# =========================================================================
@rutas_protegidas.get("/retenciones/rt", response_class=HTMLResponse)
async def retenciones_rt(request: Request, fecha: str = None):
    # ----- CONFIGURACIÓN DE FECHA -----
    # 1. PARA PRODUCCIÓN REAL (Descomentar en la vida real):
    # zona_colombia = pytz.timezone('America/Bogota')
    # fecha_hoy_real = datetime.now(zona_colombia).strftime("%Y-%m-%d")
    
    # 2. PARA LA SUSTENTACIÓN DE TESIS (Data estática):
    fecha_hoy_real = "2025-06-26" 
    # ----------------------------------
    
    fecha_consulta = fecha if fecha else fecha_hoy_real
    es_historico = fecha_consulta != fecha_hoy_real
    mapa_nombres, mapa_cedulas = get_agentes_maps()
    
    try:
        resp_embudo = supabase.table("vw_ret_rt_embudo").select("*").eq("date", fecha_consulta).execute()
        data_embudo = resp_embudo.data[0] if resp_embudo.data else {"total_base": 0, "numero_llamados": 0, "contacto_cliente": 0, "contacto_favorable": 0, "retenciones": 0}
        total_base = data_embudo.get("total_base", 0)
        numero_llamados = data_embudo.get("numero_llamados", 0)
        contacto_cliente = data_embudo.get("contacto_cliente", 0)
        contacto_favorable = data_embudo.get("contacto_favorable", 0)
        retenciones = data_embudo.get("retenciones", 0)

        # =================================================================
        # 1. Verificar si la operación ya cerró (Buscando el K-Means de cierre)
        # =================================================================
        operacion_cerrada = False
        try:
            resp_cierre = supabase.table("ml_insights_retenciones").select("id", count="exact").eq("fecha_analisis", fecha_consulta).execute()
            if resp_cierre.count and resp_cierre.count > 0:
                operacion_cerrada = True
        except: pass
        # =================================================================

        resp_agentes = supabase.table("vw_ret_rt_agentes").select("*").eq("date", fecha_consulta).execute()
        lista_agentes, activos_llamada = [], 0
        for ag in (resp_agentes.data or []):
            marcaciones, ventas, efectivas = ag.get("marcaciones", 0), ag.get("retenciones", 0), ag.get("llamadas_efectivas", 0)
            efec = min((ventas / efectivas * 100), 100.0) if efectivas > 0 else 0
            
            # 2. Si la operación NO ha cerrado y NO es histórico, sumamos los activos
            if marcaciones > 0 and not es_historico and not operacion_cerrada: 
                activos_llamada += 1
                
            lista_agentes.append({"id": ag.get("asesor_id", ""), "nombre": ag.get("nombre", "Desconocido"), "supervisor": ag.get("supervisor", "Sin Supervisor"), "marcaciones": marcaciones, "llamadas_efectivas": efectivas, "ventas": ventas, "efectividad": round(efec, 2)})
            
        lista_agentes.sort(key=lambda x: (x["ventas"], x["efectividad"], x["marcaciones"]), reverse=True)
        total_agentes_activos = max(1, len(lista_agentes))
        libres_pausa = max(0, total_agentes_activos - activos_llamada)

        resp_motivos = supabase.table("vw_ret_rt_motivos").select("*").eq("date", fecha_consulta).order("cantidad", desc=True).limit(5).execute()
        traduccion_disposiciones = {"NO ANSWER": "Sin Respuesta", "HANGUP": "Colgó / Cortó", "ANSWERING MACHINE": "Buzón de Voz"}
        rt_nombres_motivos, rt_valores_motivos = [], []
        for m in (resp_motivos.data or []):
            rt_nombres_motivos.append(traduccion_disposiciones.get(str(m.get("tipificacion", "")).upper(), str(m.get("tipificacion", "")).title()))
            rt_valores_motivos.append(m.get("cantidad", 0))

        resp_horas = supabase.table("vw_ret_rt_horas").select("*").eq("date", fecha_consulta).execute()
        distribucion_horas = {f"{h:02d}:00": 0 for h in range(8, 18)}
        for h in (resp_horas.data or []):
            if h.get("hora_llamada", "") in distribucion_horas: distribucion_horas[h.get("hora_llamada", "")] = h.get("volumen", 0)

    except Exception as e:
        total_base = numero_llamados = contacto_cliente = contacto_favorable = retenciones = activos_llamada = libres_pausa = 0
        lista_agentes, rt_nombres_motivos, rt_valores_motivos, distribucion_horas = [], [], [], {f"{h:02d}:00": 0 for h in range(8, 18)}

    dispersion_data = [{"x": 160 + (i * 15) % 120, "y": ag["ventas"], "r": max(ag["marcaciones"] * 1.5, 4)} for i, ag in enumerate(lista_agentes)]

    alertas_rt_ml, asesores_anomalos_ids = [], set()
    try:
        resp_ml = supabase.table("ml_alertas_globales").select("*").ilike("origen_datos", "%Retenciones%").eq("call_date", fecha_consulta).order("fecha_deteccion", desc=True).execute()
        for alerta in (resp_ml.data or []):
            desc_limpia = str(alerta.get("descripcion", "")).replace("BuzÃ³n", "Buzón").replace("RetenciÃ³n", "Retención").replace("Ã³", "ó").replace("Ã±", "ñ").replace("Ã¡", "á")
            alerta["descripcion"] = desc_limpia

            as_id = str(alerta.get("asesor_id", "")).strip().replace('.0', '')
            if not as_id or as_id in ["None", "N/A"]:
                match = re.search(r'CC:\s*(\w+)', desc_limpia)
                if not match: match = re.search(r'ID:\s*(\w+)', desc_limpia)
                if match: as_id = match.group(1)
            
            cc_real = mapa_cedulas.get(as_id.lower(), as_id) if as_id else "N/A"
            alerta["asesor_id"] = cc_real  
            if cc_real != "N/A": asesores_anomalos_ids.add(cc_real)

            c_date, c_time = alerta.get("call_date"), alerta.get("call_time")
            alerta["fecha_deteccion"] = f"{c_date} {c_time}" if c_date and c_time else str(alerta.get("fecha_deteccion", "")).replace("T", " ")[:19]
            alertas_rt_ml.append(alerta)
    except Exception as e: pass

    alertas_rt_ml.sort(key=lambda x: str(x.get("call_time", "")), reverse=True)

    
    contexto = {
        "request": request, "titulo": "Retenciones Outbound", "menu_activo": "rt_retenciones",
        "fecha_consulta": fecha_consulta, "es_historico": es_historico, "fecha_hoy_real": fecha_hoy_real,
        "embudo": {"total_base": total_base, "numero_llamados": numero_llamados, "barridos": round((numero_llamados / total_base), 2) if total_base > 0 else 0, "contacto_cliente": contacto_cliente, "pct_contacto": round((contacto_cliente / total_base * 100) if total_base > 0 else 0, 2), "contacto_favorable": contacto_favorable, "pct_favorable": round((contacto_favorable / contacto_cliente * 100) if contacto_cliente > 0 else 0, 2), "retenciones": retenciones, "pct_ret_favorable": round((retenciones / contacto_favorable * 100) if contacto_favorable > 0 else 0, 2), "pct_ret_contacto": round((retenciones / contacto_cliente * 100) if contacto_cliente > 0 else 0, 2), "efectividad_acida": round((retenciones / total_base * 100) if total_base > 0 else 0, 2)},
        "rt_nombres_motivos": rt_nombres_motivos, "rt_valores_motivos": rt_valores_motivos,
        "horas_labels": list(distribucion_horas.keys()), "horas_valores": list(distribucion_horas.values()),
        "estado_agentes": [activos_llamada, libres_pausa], "dispersion_agentes": dispersion_data,
        "alertas_rt_ml": alertas_rt_ml, "asesores_anomalos_ids": asesores_anomalos_ids, "agentes": lista_agentes
    }
    return templates.TemplateResponse(request=request, name="retenciones_rt.html", context=contexto)

# =========================================================================
# 6. RUTA: RETENCIONES EOD
# =========================================================================
@rutas_protegidas.get("/retenciones/eod", response_class=HTMLResponse)
async def retenciones_eod(request: Request, fecha: str = None):
    mapa_nombres, _ = get_agentes_maps()
    try:
        resp_fechas = supabase.table("vw_ret_eod_kpis").select("fecha").execute()
        fechas_disp = sorted(list(set([f["fecha"] for f in (resp_fechas.data or []) if f["fecha"]])), reverse=True)
        fecha_str = fecha if fecha else (fechas_disp[0] if fechas_disp else "2025-06-26")

        resp_kpis = supabase.table("vw_ret_eod_kpis").select("*").eq("fecha", fecha_str).execute()
        data_kpis = resp_kpis.data[0] if resp_kpis.data else {}
        total_base, numero_llamados, contacto_cliente, contacto_favorable, retenciones = data_kpis.get("total_base", 0), data_kpis.get("marcaciones", 0), data_kpis.get("contacto_cliente", 0), data_kpis.get("contacto_favorable", 0), data_kpis.get("retenciones", 0)

        embudo = {
            "total_base": total_base, "numero_llamados": numero_llamados, "barridos": round(numero_llamados / total_base, 1) if total_base > 0 else 0,
            "contacto_cliente": contacto_cliente, "pct_contacto": round((contacto_cliente / total_base) * 100, 1) if total_base > 0 else 0,
            "contacto_favorable": contacto_favorable, "retenciones": retenciones,
            "pct_ret_favorable": round((retenciones / contacto_favorable) * 100, 1) if contacto_favorable > 0 else 0, "efectividad_acida": round((retenciones / total_base) * 100, 1) if total_base > 0 else 0
        }

        resp_horas = supabase.table("vw_ret_eod_horas").select("*").eq("fecha", fecha_str).order("hora").execute()
        horas_labels = [f"{h['hora']}:00" for h in (resp_horas.data or [])]
        horas_valores = [h.get("volumen") or 0 for h in (resp_horas.data or [])]

        resp_motivos = supabase.table("vw_ret_eod_motivos").select("*").eq("fecha", fecha_str).order("volumen", desc=True).limit(10).execute()
        nombres_motivos, valores_motivos = [m.get("tipificacion", "Desconocido") for m in (resp_motivos.data or [])], [m.get("volumen", 0) for m in (resp_motivos.data or [])]

        resp_agentes = supabase.table("vw_ret_eod_agentes").select("*").eq("fecha", fecha_str).execute()
        agentes_eod = resp_agentes.data if resp_agentes.data else []
        for ag in agentes_eod:
            efec, ret = ag.get("llamadas_efectivas") or 0, ag.get("retenciones") or 0
            ag["efectividad"] = round((ret / efec) * 100, 1) if efec > 0 else 0
        agentes_eod.sort(key=lambda x: x.get("retenciones") or 0, reverse=True)
        eod_agentes_activos = len(agentes_eod)

        # --- NUEVOS STATS: TMO Y LLAMADAS CRUDAS ---
        try:
            resp_tmo = supabase.table("vw_ret_eod_tmo").select("tmo_promedio").eq("fecha", fecha_str).execute()
            eod_tmo_promedio = round(resp_tmo.data[0].get("tmo_promedio", 0) or 0, 1) if resp_tmo.data else 0
        except Exception:
            eod_tmo_promedio = 0

        try:
            resp_crudas = supabase.table("hist_base_rete_out").select("id", count="exact").eq("date", fecha_str).execute()
            eod_llamadas_crudas = resp_crudas.count if resp_crudas.count else 0
        except Exception:
            eod_llamadas_crudas = 0

        resp_insights = supabase.table("ml_insights_retenciones").select("*").eq("fecha_analisis", fecha_str).execute()
        insights_ia = [i for i in (resp_insights.data or []) if str(i.get("agente", "")).strip() not in ["0", "0.0", "None", "", "nan"]]
        for k in insights_ia: k["nombre_asesor"] = mapa_nombres.get(str(k.get("agente", "")).strip(), k.get("agente", ""))
        insights_ia = sorted(insights_ia, key=lambda x: float(x.get("metrica_principal", 0)), reverse=True)
        
    except Exception as e:
        fecha_str = "2025-06-26"
        fechas_disp, horas_labels, horas_valores, nombres_motivos, valores_motivos, agentes_eod, insights_ia = [], [], [], [], [], [], []
        embudo = {"total_base": 0, "numero_llamados": 0, "barridos": 0, "contacto_cliente": 0, "pct_contacto": 0, "contacto_favorable": 0, "retenciones": 0, "pct_ret_favorable": 0, "efectividad_acida": 0}
        eod_tmo_promedio = eod_llamadas_crudas = eod_agentes_activos = 0

    contexto = {
        "request": request, "titulo": "Retenciones Outbound", "menu_activo": "eod_retenciones",
        "fecha_seleccionada": fecha_str, "fechas_disponibles": fechas_disp, "embudo": embudo,
        "horas_labels": horas_labels, "horas_valores": horas_valores, "nombres_motivos": nombres_motivos,
        "valores_motivos": valores_motivos, "agentes": agentes_eod, "insights_ia": insights_ia,
        "eod_tmo_promedio": eod_tmo_promedio, "eod_llamadas_crudas": eod_llamadas_crudas, "eod_agentes_activos": eod_agentes_activos
    }
    return templates.TemplateResponse(request=request, name="retenciones_eod.html", context=contexto)

# =========================================================================
# 7. RUTA: RETENCIONES ML
# =========================================================================
@rutas_protegidas.get("/retenciones/ml", response_class=HTMLResponse)
async def retenciones_ml(request: Request, fecha: str = None):
    fecha_analisis_str = fecha if fecha else "2025-06-26"
    mapa_nombres, _ = get_agentes_maps()
    
    try:
        resp_kmeans = supabase.table("ml_insights_retenciones").select("*").eq("fecha_analisis", fecha_analisis_str).execute()
        kmeans_limpio = [k for k in (resp_kmeans.data or []) if str(k.get("agente", "")).strip() not in ["0", "0.0", "None", "", "nan"]]
        for k in kmeans_limpio: k["nombre_asesor"] = mapa_nombres.get(str(k.get("agente", "")).strip(), k.get("agente", ""))
        
        # ✔️ CORRECCIÓN: ILIKE PARA UNIFICAR CRITERIOS CON RT
        resp_if = supabase.table("ml_alertas_globales").select("*").ilike("origen_datos", "%Retenciones%").eq("call_date", fecha_analisis_str).execute()
        if_data = resp_if.data if resp_if.data else []
        freq_dict = {}
        for alerta in if_data: freq_dict[alerta.get("tipo_alerta", "Desconocida")] = freq_dict.get(alerta.get("tipo_alerta", "Desconocida"), 0) + 1
            
    except Exception as e:
        kmeans_limpio, if_data, freq_dict = [], [], {}

    scatter_alto_rendimiento, scatter_estandar, scatter_oportunidad = [], [], []
    for k in kmeans_limpio:
        punto = {"x": float(k.get("metrica_secundaria") or 0), "y": float(k.get("metrica_principal") or 0), "agente": k.get("nombre_asesor", "")}
        cluster = str(k.get("cluster_nombre", ""))
        if "Estrella" in cluster or "Top Performers" in cluster: scatter_alto_rendimiento.append(punto)
        elif "Estándar" in cluster: scatter_estandar.append(punto)
        else: scatter_oportunidad.append(punto)

    contexto_ml = {
        "request": request, "titulo": "Retenciones Outbound", "menu_activo": "ml_retenciones",
        "fecha_analisis": fecha_analisis_str, "total_agentes_perfilados": len(kmeans_limpio),
        "total_micro_anomalias": len(if_data), "scatter_alto_rendimiento": scatter_alto_rendimiento,
        "scatter_estandar": scatter_estandar, "scatter_oportunidad": scatter_oportunidad,
        "labels_anomalias": list(freq_dict.keys()), "valores_anomalias": list(freq_dict.values()),
        "insights_kmeans": sorted(kmeans_limpio, key=lambda x: float(x.get("metrica_principal", 0)), reverse=True),
        "if_ultimas_alertas": sorted(if_data, key=lambda x: str(x.get("call_time", "")), reverse=True) 
    }
    return templates.TemplateResponse(request=request, name="retenciones_ml.html", context=contexto_ml)

# =========================================================================
# 8. RUTA: REDES SOCIALES (RRSS) RT
# =========================================================================
@rutas_protegidas.get("/rrss/rt", response_class=HTMLResponse)
async def rrss_rt(request: Request, fecha: str = None, segmento_filtro: str = 'General'):
    # ----- CONFIGURACIÓN DE FECHA -----
    # 1. PARA PRODUCCIÓN REAL (Descomentar en la vida real):
    # zona_colombia = pytz.timezone('America/Bogota')
    # fecha_hoy_real = datetime.now(zona_colombia).strftime("%Y-%m-%d")
    
    # 2. PARA LA SUSTENTACIÓN DE TESIS (Data estática):
    fecha_hoy_real = "2025-06-26" 
    # ----------------------------------
    
    fecha_consulta = fecha if fecha else fecha_hoy_real
    es_historico = fecha_consulta != fecha_hoy_real
    mapa_nombres, mapa_cedulas = get_agentes_maps()
    
    try:
        resp_master = supabase.table("vw_rrss_master_unificada").select("*").eq("fecha_real", fecha_consulta).execute()
        df_master = pd.DataFrame(resp_master.data if resp_master.data else [])

        if not df_master.empty:
            df_filtrado = df_master[df_master['segmento'] == segmento_filtro].copy() if segmento_filtro != 'General' else df_master.copy()
            df_atendidos = df_filtrado[df_filtrado['es_atendido'] == 1].copy()
            df_atendidos['tmo_seg'] = pd.to_numeric(df_atendidos['tmo_seg'], errors='coerce').fillna(0)
            
            ofrecidas_totales, atendidas_totales = len(df_filtrado), len(df_atendidos)
            chats_pendientes = ofrecidas_totales - atendidas_totales
            tmo_promedio = round(df_atendidos['tmo_seg'].mean(), 1) if not df_atendidos.empty else 0
            asa_promedio = round(df_atendidos['asa_seg'].mean(), 1) if not df_atendidos.empty else 0
            sla_vivo = round((df_atendidos['cumple_umbral'].sum() / atendidas_totales) * 100, 1) if atendidas_totales > 0 else 0

            if not df_atendidos.empty:
                df_atendidos['canal_seguro'] = df_atendidos['canal_final'].replace([None, '', 'NaN'], 'RRSS')
                labels_canal = df_atendidos['canal_seguro'].value_counts().index.tolist()
                valores_canal = [int(v) for v in df_atendidos['canal_seguro'].value_counts().values]
            else: labels_canal, valores_canal = [], []

            df_atendidos['agente_seguro'] = df_atendidos['agente'].replace([None, '', 'NaN'], 'Sin Asignar')
            agentes_vivo = df_atendidos.groupby('agente_seguro').agg(chats=('id_conversacion', 'count'), tmo_actual=('tmo_seg', 'mean')).reset_index().sort_values(by='chats', ascending=False).head(15)
            agentes_vivo['tmo_actual'] = agentes_vivo['tmo_actual'].round(1)
            agentes_vivo.rename(columns={'agente_seguro': 'Agente'}, inplace=True)
            lista_agentes = agentes_vivo.to_dict('records')

            df_matriz = df_filtrado.groupby('canal_final').agg(ofrecidas=('id_conversacion', 'count'), atendidas=('es_atendido', 'sum'), atendidas_4min=('cumple_umbral', 'sum')).reset_index()
            if not df_atendidos.empty:
                promedios = df_atendidos.groupby('canal_final').agg(tmo=('tmo_seg', 'mean'), asa=('asa_seg', 'mean')).reset_index()
                df_matriz = pd.merge(df_matriz, promedios, on='canal_final', how='left').fillna(0)
            else: df_matriz['tmo'], df_matriz['asa'] = 0, 0

            df_matriz['sla'] = np.where(df_matriz['atendidas'] > 0, round((df_matriz['atendidas_4min'] / df_matriz['atendidas']) * 100, 1), 0)
            df_matriz['tmo'], df_matriz['asa'] = df_matriz['tmo'].round(1), df_matriz['asa'].round(1)
            matriz_rt = df_matriz.to_dict('records')

            df_horas = df_filtrado.groupby('hora_bloque').agg(ofrecidas=('id_conversacion', 'count'), atendidas=('es_atendido', 'sum')).reset_index().sort_values('hora_bloque') 
            df_horas['hora_limpia'] = df_horas['hora_bloque'].astype(str).str[:5] 
            desglose_horas = df_horas.to_dict('records')
        else:
            chats_pendientes = atendidas_totales = tmo_promedio = asa_promedio = sla_vivo = 0
            labels_canal, valores_canal, lista_agentes, matriz_rt, desglose_horas = [], [], [], [], []

    except Exception as e:
        chats_pendientes = atendidas_totales = tmo_promedio = asa_promedio = sla_vivo = 0
        labels_canal, valores_canal, lista_agentes, matriz_rt, desglose_horas = [], [], [], [], []

    try:
        response_alertas = supabase.table("ml_alertas_globales").select("*").ilike("origen_datos", "%Redes Sociales%").eq("call_date", fecha_consulta).order("fecha_deteccion", desc=True).execute()
        alertas_ml = response_alertas.data if response_alertas.data else []
        for alerta in alertas_ml:
            c_date, c_time = alerta.get('call_date', ''), str(alerta.get('call_time', ''))[:8] 
            alerta['fecha_formateada'] = f"{c_date} {c_time}" if c_date and c_time else str(alerta.get('fecha_deteccion', ''))[:16].replace('T', ' ')
            
            as_id = str(alerta.get("asesor_id", "")).strip().replace('.0', '')
            if not as_id or as_id in ["None", "N/A"]:
                match = re.search(r'CC:\s*(\w+)', str(alerta.get("descripcion", "")))
                if not match: match = re.search(r'ID:\s*(\w+)', str(alerta.get("descripcion", "")))
                if match: as_id = match.group(1)
            alerta["asesor_id"] = mapa_cedulas.get(as_id.lower(), as_id) if as_id else "N/A"
    except Exception as e: alertas_ml = []
    alertas_ml.sort(key=lambda x: str(x.get("call_time", "")), reverse=True)

    contexto_rt = {
        "request": request, "titulo": "Redes Sociales", "menu_activo": "rt_rrss",
        "fecha_consulta": fecha_consulta, "es_historico": es_historico, "fecha_hoy_real": fecha_hoy_real,
        "segmento_activo": segmento_filtro, "chats_pendientes": chats_pendientes, "chats_atendidos": atendidas_totales, 
        "asa_vivo": asa_promedio, "tmo_vivo": tmo_promedio, "sla_vivo": sla_vivo,
        "labels_canal": labels_canal, "valores_canal": valores_canal, "agentes_vivo": lista_agentes,
        "matriz_rt": matriz_rt, "desglose_horas": desglose_horas, "alertas_ml": alertas_ml 
    }
    return templates.TemplateResponse(request=request, name="rrss_rt.html", context=contexto_rt)

# =========================================================================
# 9. RUTA: REDES SOCIALES (RRSS) EOD
# =========================================================================
@rutas_protegidas.get("/rrss/eod", response_class=HTMLResponse)
async def rrss_eod(request: Request, fecha: str = None):
    fecha_seleccionada = fecha if fecha else "2025-06-26"
    tramos_tmo = {"0-5 min": 0, "5-10 min": 0, "10-20 min": 0, "Mas 20 min": 0} 
    mapa_nombres, _ = get_agentes_maps()
    
    if "/" in fecha_seleccionada:
        partes = fecha_seleccionada.split("/")
        if len(partes) == 3 and len(partes[2]) == 4: fecha_seleccionada = f"{partes[2]}-{partes[0].zfill(2)}-{partes[1].zfill(2)}"

    try:
        resp_matriz = supabase.table("vw_hist_rrss_eod_matriz").select("*").eq("fecha_real", fecha_seleccionada).execute()
        df_matriz = pd.DataFrame(resp_matriz.data if resp_matriz.data else [])
        resp_master = supabase.table("vw_hist_rrss_master").select("*").eq("fecha_real", fecha_seleccionada).execute()
        df_master = pd.DataFrame(resp_master.data if resp_master.data else [])

        # Cálculo de agentes logueados únicos para RRSS EOD
        eod_agentes_activos = 0
        if not df_master.empty and 'agente' in df_master.columns:
            agentes_validos = df_master['agente'].dropna().astype(str).str.strip()
            agentes_validos = agentes_validos[~agentes_validos.isin(['', 'None', 'nan', '0', '0.0', 'Sin Asignar'])]
            eod_agentes_activos = agentes_validos.nunique()

        if not df_matriz.empty:
            ofrecidas_totales, atendidas_totales = int(df_matriz['ofrecidas'].sum()), int(df_matriz['atendidas'].sum())
            atend_4m_totales = int(df_matriz['atendidas_4min'].sum())
            
            df_atendidos = df_master[df_master['es_atendido'] == 1]
            tmo_promedio = round(df_atendidos['tmo_seg'].mean(), 1) if not df_atendidos.empty else 0
            asa_promedio = round(df_atendidos['asa_seg'].mean(), 1) if not df_atendidos.empty else 0
            sla_global = round((atend_4m_totales / atendidas_totales) * 100, 1) if atendidas_totales > 0 else 0

            df_unicos = df_matriz[df_matriz['canal_final'].str.contains('Unicos|Monetizacion', case=False, na=False)].copy()
            df_reaperturas = df_matriz[df_matriz['canal_final'].str.contains('Reapertura', case=False, na=False)].copy()
            df_unicos['canal_final'] = df_unicos['canal_final'].str.replace(' Unicos', '', regex=False).str.strip()
            df_reaperturas['canal_final'] = df_reaperturas['canal_final'].str.replace(' Reapertura', '', regex=False).str.strip()
            lista_unicos, lista_reaperturas = df_unicos.to_dict('records'), df_reaperturas.to_dict('records')

            df_agg = df_matriz.copy()
            df_agg['canal_puro'] = df_agg['canal_final'].str.replace(' Unicos', '').str.replace(' Reapertura', '').str.strip()
            df_general = df_agg.groupby('canal_puro').agg({'ofrecidas': 'sum', 'atendidas': 'sum', 'atendidas_4min': 'sum', 'frcst': 'sum', 'promotores': 'sum', 'detractores': 'sum', 'pasivos': 'sum'}).reset_index()
            promedios_gen = df_master[df_master['es_atendido']==1].groupby('canal_final').agg(tmo=('tmo_seg', 'mean'), asa=('asa_seg', 'mean')).reset_index().rename(columns={'canal_final': 'canal_puro'})
            df_general = pd.merge(df_general, promedios_gen, on='canal_puro', how='left').fillna(0)
            df_general['sla'] = np.where(df_general['atendidas'] > 0, round((df_general['atendidas_4min'] / df_general['atendidas']) * 100, 1), 0)
            df_general['tmo'], df_general['asa'] = df_general['tmo'].round(1), df_general['asa'].round(1)
            df_general.rename(columns={'canal_puro': 'canal_final'}, inplace=True)
            lista_general = df_general.to_dict('records')

            if not df_atendidos.empty:
                for tmo in df_atendidos['tmo_seg']:
                    if tmo <= 300: tramos_tmo['0-5 min'] += 1
                    elif tmo <= 600: tramos_tmo['5-10 min'] += 1
                    elif tmo <= 1200: tramos_tmo['10-20 min'] += 1
                    else: tramos_tmo['Mas 20 min'] += 1
            
            valores_nps = [int(df_matriz['promotores'].sum()), int(df_matriz['pasivos'].sum()), int(df_matriz['detractores'].sum())]
            if sum(valores_nps) == 0: valores_nps = [0, 0, 0]

            trafico = df_master.groupby('hora_bloque').agg(ofrecidas=('id_conversacion', 'count'), atendidas=('es_atendido', 'sum')).reset_index().sort_values('hora_bloque')
            labels_horas = trafico['hora_bloque'].astype(str).str[:5].tolist()
            data_ofrecidas = [int(x) for x in trafico['ofrecidas'].tolist()]
            data_atendidas = [int(x) for x in trafico['atendidas'].tolist()]

        else:
            ofrecidas_totales = atendidas_totales = tmo_promedio = asa_promedio = sla_global = 0
            lista_general, lista_unicos, lista_reaperturas, labels_horas, data_ofrecidas, data_atendidas, valores_nps = [], [], [], [], [], [], [0, 0, 0]

        try:
            resp_insights = supabase.table("ml_insights_rrss").select("*").eq("fecha_analisis", fecha_seleccionada).execute()
            insights_kmeans = [i for i in (resp_insights.data or []) if str(i.get("agente", "")).strip() not in ["0", "0.0", "None", "", "nan"]]
            for k in insights_kmeans: k["nombre_asesor"] = mapa_nombres.get(str(k.get("agente", "")).strip(), k.get("agente", ""))
            insights_kmeans = sorted(insights_kmeans, key=lambda x: float(x.get("metrica_principal", 0)), reverse=True)
        except: insights_kmeans = []

    except Exception as e:
        ofrecidas_totales = atendidas_totales = tmo_promedio = asa_promedio = sla_global = eod_agentes_activos = 0
        lista_general, lista_unicos, lista_reaperturas, labels_horas, data_ofrecidas, data_atendidas, insights_kmeans, valores_nps = [], [], [], [], [], [], [], [0, 0, 0]

    contexto_eod = {
        "request": request, "titulo": "Redes Sociales", "menu_activo": "eod_rrss",
        "fecha_seleccionada": fecha_seleccionada, "ofrecidas": ofrecidas_totales,
        "atendidas": atendidas_totales, "tmo": tmo_promedio, "asa": asa_promedio, "sla": sla_global,
        "matriz_general": lista_general, "matriz_unicos": lista_unicos, "matriz_reaperturas": lista_reaperturas,
        "labels_horas": labels_horas, "data_ofrecidas": data_ofrecidas, "data_atendidas": data_atendidas,
        "valores_nps": valores_nps, "insights_kmeans": insights_kmeans, "tramos_tmo": tramos_tmo,
        "eod_agentes_activos": eod_agentes_activos
    }
    return templates.TemplateResponse(request=request, name="rrss_eod.html", context=contexto_eod)
# =========================================================================
# 10. RUTA: REDES SOCIALES (RRSS) ML
# =========================================================================
@rutas_protegidas.get("/rrss/ml", response_class=HTMLResponse)
async def rrss_ml(request: Request, fecha: str = None):
    fecha_analisis_str = fecha if fecha else "2025-06-26"
    mapa_nombres, _ = get_agentes_maps()
    
    try:
        resp_kmeans = supabase.table("ml_insights_rrss").select("*").eq("fecha_analisis", fecha_analisis_str).execute()
        kmeans_limpio = [k for k in (resp_kmeans.data or []) if str(k.get("agente", "")).strip() not in ["0", "0.0", "None", "", "nan"]]
        
        for k in kmeans_limpio:
            ag_raw = str(k.get("agente", "")).strip()
            k["nombre_asesor"] = mapa_nombres.get(ag_raw, ag_raw)
            
        # ✔️ CORRECCIÓN: ILIKE PARA UNIFICAR CRITERIOS CON RT
        resp_if = supabase.table("ml_alertas_globales").select("*").ilike("origen_datos", "%Redes Sociales%").eq("call_date", fecha_analisis_str).execute()
        if_data = resp_if.data if resp_if.data else []
        freq_dict = {}
        for alerta in if_data:
            tipo_limpio = str(alerta.get("tipo_alerta", "Desconocida")).replace("Ã³", "ó").replace("Ã±", "ñ").replace("Ã¡", "á").replace("Ã©", "é").replace("Ã", "í")
            freq_dict[tipo_limpio] = freq_dict.get(tipo_limpio, 0) + 1
            c_date, c_time = alerta.get('call_date', ''), str(alerta.get('call_time', ''))[:8]
            alerta['fecha_formateada'] = f"{c_date} {c_time}" if c_date and c_time else str(alerta.get('fecha_deteccion', ''))[:16].replace('T', ' ')
            
    except Exception as e:
        kmeans_limpio, if_data, freq_dict = [], [], {}

    scatter_alto_rendimiento, scatter_estandar, scatter_oportunidad = [], [], []
    for k in kmeans_limpio:
        punto = {"x": float(k.get("metrica_secundaria") or 0), "y": float(k.get("metrica_principal") or 0), "agente": k.get("nombre_asesor", "")}
        cluster = str(k.get("cluster_nombre", ""))
        if "Estrella" in cluster or "Alto" in cluster: scatter_alto_rendimiento.append(punto)
        elif "Estándar" in cluster or "Estandar" in cluster: scatter_estandar.append(punto)
        else: scatter_oportunidad.append(punto)

    contexto_ml = {
        "request": request, "titulo": "Redes Sociales", "menu_activo": "ml_rrss",
        "fecha_analisis": fecha_analisis_str, "total_agentes_perfilados": len(kmeans_limpio),
        "total_micro_anomalias": len(if_data), "scatter_alto_rendimiento": scatter_alto_rendimiento,
        "scatter_estandar": scatter_estandar, "scatter_oportunidad": scatter_oportunidad,
        "labels_anomalias": list(freq_dict.keys()), "valores_anomalias": list(freq_dict.values()),
        "insights_kmeans": sorted(kmeans_limpio, key=lambda x: float(x.get("metrica_principal", 0)), reverse=True),
        "if_ultimas_alertas": sorted(if_data, key=lambda x: str(x.get("call_time", "")), reverse=True) 
    }
    return templates.TemplateResponse(request=request, name="rrss_ml.html", context=contexto_ml)


# =========================================================================
# RUTA INTERNA: ACTUALIZAR META GTR EN SUPABASE
# =========================================================================
@rutas_protegidas.post("/api/config/meta")
async def actualizar_meta(request: Request, campana: str = Form(...), meta: int = Form(...)):
    try:
        # Upsert: Si la campaña existe, la actualiza. Si no, la crea.
        supabase.table("config_metas_gtr").upsert({"campana": campana, "meta_diaria": meta}).execute()
        # Puedes redirigir a la misma página del dashboard para que recargue con la nueva meta
        return RedirectResponse(url=request.headers.get("referer", "/"), status_code=303)
    except Exception as e:
        print(f"❌ Error guardando meta en Supabase: {e}")
        return RedirectResponse(url=request.headers.get("referer", "/"), status_code=303)
    
# =========================================================================
# 12. RUTA: 🔎 AGENT ANALYTICS (BUSCADOR DE RENDIMIENTO HISTÓRICO)
# =========================================================================
@rutas_protegidas.get("/analytics/agente", response_class=HTMLResponse)
async def agent_analytics(request: Request, cedula: str = None):
    datos_agente = None
    alertas_agente = []
    
    if cedula:
        try:
            resp_agente = supabase.table("vw_aa_resumen_agente").select("*").eq("asesor_id", cedula).execute()
            if resp_agente.data:
                datos_agente = resp_agente.data[0]
            
            resp_alertas = supabase.table("ml_alertas_globales").select("*").eq("asesor_id", cedula).order("call_date", desc=True).order("call_time", desc=True).execute()
            alertas_agente = resp_alertas.data if resp_alertas.data else []
            
            for alerta in alertas_agente:
                c_date, c_time = alerta.get('call_date', ''), str(alerta.get('call_time', ''))[:8]
                alerta['fecha_formateada'] = f"{c_date} {c_time}" if c_date and c_time else str(alerta.get('fecha_deteccion', ''))[:16].replace('T', ' ')
                
        except Exception as e:
            print(f"❌ Error consultando Agent Analytics para {cedula}: {e}")
            
    contexto_aa = {
        "request": request,
        "titulo": "Agent Analytics",
        "menu_activo": "agent_analytics",
        "cedula_buscada": cedula,
        "agente": datos_agente,
        "alertas": alertas_agente
    }
    
    return templates.TemplateResponse(request=request, name="agent_analytics.html", context=contexto_aa)

# =========================================================================
# 13. RUTA: 🛡️ SYSTEM ADMINISTRATOR (GESTIÓN DE USUARIOS REAL)
# =========================================================================
@rutas_protegidas.get("/admin/usuarios", response_class=HTMLResponse)
async def gestion_usuarios(request: Request, msg: str = None):
    try:
        resp = supabase.table("usuarios_plataforma").select("*").order("id").execute()
        usuarios_activos = resp.data if resp.data else []
    except Exception as e:
        print(f"❌ Error cargando usuarios: {e}")
        usuarios_activos = []
    
    contexto_admin = {
        "request": request,
        "titulo": "Gestión de Usuarios",
        "menu_activo": "admin_usuarios",
        "usuarios": usuarios_activos,
        "msg": msg
    }
    return templates.TemplateResponse(request=request, name="gestion_usuarios.html", context=contexto_admin)

@rutas_protegidas.post("/admin/usuarios/crear")
async def crear_usuario(request: Request, nombre: str = Form(...), email: str = Form(...), password: str = Form(...), rol: str = Form(...)):
    try:
        supabase_admin.auth.admin.create_user({
            "email": email,
            "password": password,
            "email_confirm": True
        })
        
        nuevo_usuario = {
            "nombre": nombre,
            "email": email,
            "rol": rol,
            "estado": "Activo",
            "ultimo_acceso": "Nunca"
        }
        supabase.table("usuarios_plataforma").insert(nuevo_usuario).execute()
        
        return RedirectResponse(url="/admin/usuarios?msg=creado", status_code=status.HTTP_302_FOUND)
        
    except Exception as e:
        print(f"❌ Error al crear usuario en Supabase: {e}")
        return RedirectResponse(url="/admin/usuarios?msg=error", status_code=status.HTTP_302_FOUND)

@rutas_protegidas.get("/admin/usuarios/eliminar/{user_id}")
async def eliminar_usuario(request: Request, user_id: int):
    try:
        resp_usuario = supabase.table("usuarios_plataforma").select("email").eq("id", user_id).execute()
        
        if resp_usuario.data:
            correo_eliminar = resp_usuario.data[0].get("email")
            try:
                lista_auth = supabase_admin.auth.admin.list_users()
                for usuario_auth in lista_auth:
                    if usuario_auth.email == correo_eliminar:
                        supabase_admin.auth.admin.delete_user(usuario_auth.id)
                        print(f"✅ ¡Destrucción completa! {correo_eliminar} borrado de Supabase Auth.")
                        break
            except Exception as auth_err:
                print(f"⚠️ Error al borrar de Auth (quizás ya fue eliminado manualmente): {auth_err}")
        
        supabase.table("usuarios_plataforma").delete().eq("id", user_id).execute()
        
        return RedirectResponse(url="/admin/usuarios?msg=eliminado", status_code=status.HTTP_302_FOUND)
        
    except Exception as e:
        print(f"❌ Error eliminando usuario en ambas capas: {e}")
        return RedirectResponse(url="/admin/usuarios?msg=error", status_code=status.HTTP_302_FOUND)

# ==========================================
# 🔌 CONEXIÓN DEL ROUTER VIP A LA APP (DEBE IR AL FINAL DE TODO)
# ==========================================
app.include_router(rutas_protegidas)

if __name__ == "__main__":
    print("🚀 Arrancando servidor FastAPI industrial...")
    uvicorn.run("app:app", host="0.0.0.0", port=8090, reload=True)
    