import os
import time
from playwright.sync_api import Playwright, sync_playwright, expect

def run(playwright: Playwright, es_fin_de_dia: bool = False) -> None:
    print("===================================================")
    print("🤖 INICIANDO ROBOT EXTRACTOR (RPA CARI AI)")
    print("===================================================")
    
    # 1. PREPARAR CARPETA DE DESCARGAS
    carpeta_descargas = "descargas_bot"
    os.makedirs(carpeta_descargas, exist_ok=True)
    print(f"📁 Carpeta de descargas lista en: {carpeta_descargas}/")

    browser = playwright.chromium.launch(headless=True, slow_mo=400)
    context = browser.new_context(accept_downloads=True)
    page = context.new_page()

    # Manejador automático de alertas (Para cuando tenga que borrar el historial)
    page.on("dialog", lambda dialog: dialog.accept())

    try:
        # 2. LOGIN
        print("\n🌐 Navegando a Cari AI y haciendo Login...")
        page.goto("http://127.0.0.1:5000/")
        
        # Esperamos un segundo a que el diseño Glassmorphism termine de cargar
        time.sleep(1) 
        
        # ¡CORREGIDO! El nuevo name en login.html es "usuario", no "email"
        page.locator("input[name='usuario']").fill("jvelasco@apex.com") 
        
        try: 
            page.locator("input[name='password']").fill("12345678*") 
        except: 
            pass 
            
        # ¡CORREGIDO! El nuevo texto del botón en login.html es "Ingresar"
        page.get_by_role("button", name="Ingresar").click() 
        time.sleep(1)

        def asegurar_menu_abierto():
            # Si el link de Base Transaccional no es visible, abre el menú principal
            if not page.locator("a", has_text="Base Transaccional (Chat)").is_visible():
                page.locator("a").filter(has_text="Reportes Operativos").wait_for(state="visible", timeout=15000)
                page.locator("a").filter(has_text="Reportes Operativos").click()
                time.sleep(0.5)

        # 3. LISTA DE LOS 8 REPORTES A EXTRAER (ACTUALIZADA)
        reportes_a_extraer = [
            #"Base Transaccional (Chat)",
            #"Base Encuestas",
            "Base Llamadas Migraciones",
            "Base Ventas Migraciones",  
            "Base Outbound (Llamada)",
            "Base NPS RRSS",
            "Base Tipificaciones RRSS",
            "Chats y Monetización RRSS"
        ]

        # 4. BUCLE DE GENERACIÓN DE REPORTES (ITERACIÓN 8 VECES)
        print("\n⏳ Iniciando Lote de Extracción...")
        for reporte in reportes_a_extraer:
            asegurar_menu_abierto()
            
            # Clic en el nombre del reporte
            page.locator("a").filter(has_text=reporte).wait_for(state="visible", timeout=15000)
            page.locator("a").filter(has_text=reporte).click()
            time.sleep(0.5)
            
            # Seleccionar "hora" en el desplegable de RPA de la vista ACTIVA
            page.locator("div.view-section:visible select[name='rango_fecha']").select_option("hora")
            
            # Clic en Generar Reporte de la vista ACTIVA
            page.locator("div.view-section:visible button:has-text('Generar Reporte')").click()
            print(f"   ⚙️️ Generado: {reporte}")
            time.sleep(1) # Esperar recarga y redirección a exportados

        # 5. IR A BANDEJA, FILTRAR Y DESCARGAR
        print("\n📥 Abriendo la bandeja de Reportes Exportados...")
        asegurar_menu_abierto()
        page.locator("a").filter(has_text="Reportes Exportados").wait_for(state="visible", timeout=15000)
        page.locator("a").filter(has_text="Reportes Exportados").click()
        time.sleep(1)

        # Filtrar solo los de la "Última Hora"
        print("Filtrando registros por 'Última Hora'...")
        page.locator("#filtro-historial").select_option("hora")
        page.locator("button:has-text('Buscar')").click()
        time.sleep(1) # Esperamos que el JavaScript oculte las filas

        # Identificar las filas VISIBLES después del filtro
        filas_visibles = page.locator("tr.historial-row:visible")
        cantidad_descargas = filas_visibles.count()
        print(f"    Se encontraron {cantidad_descargas} reportes listos para descargar.")

        # Descargar uno por uno
        for i in range(cantidad_descargas):
            with page.expect_download() as download_info:
                # Clic en el botón "Descargar CSV" de esa fila en específico
                filas_visibles.nth(i).locator("a:has-text('Descargar CSV')").click()
            
            descarga = download_info.value
            ruta_final = os.path.join(carpeta_descargas, descarga.suggested_filename)
            descarga.save_as(ruta_final)
            print(f"Descargado: {descarga.suggested_filename}")

        # 6. LIMPIEZA DE FIN DE DÍA (SI APLICA)
        if es_fin_de_dia:
            print("\n🧹 Límite horario alcanzado (Fin de Día). Limpiando historial del servidor...")
            # Volver a "dia" para ver todo
            page.locator("#filtro-historial").select_option("dia")
            page.locator("button:has-text('Buscar')").click()
            time.sleep(0.5)
            # Clic en Borrar (el listener de diálogo que pusimos arriba aceptará automáticamente la alerta)
            page.locator("button:has-text('Borrar Historial')").click()
            time.sleep(1)
            print("   ✨ Historial borrado exitosamente.")

        # 7. CERRAR SESIÓN
        print("\n🔒 Cerrando sesión de forma segura...")
        page.locator(".dropdown-toggle").click() # Clic en el perfil superior derecho
        time.sleep(0.5)
        page.locator("a:has-text('Cerrar Sesión')").click()
        
        print("\n🎉 ¡Proceso RPA completado con éxito al 100%!")

    except Exception as e:
        print(f"\n❌ Ocurrió un error crítico en el RPA: {e}")

    finally:
        context.close()
        browser.close()

if __name__ == "__main__":
    # Si lo corres directo, es_fin_de_dia será False por defecto. 
    # Para probar el borrado manual cambia el valor a True aquí abajo:
    with sync_playwright() as playwright:
        run(playwright, es_fin_de_dia=False)