import sys
from sqlalchemy import create_engine
import pytz
import warnings
from ia_migraciones import analizar_migraciones
from ia_rrss import analizar_rrss
from ia_retenciones import analizar_retenciones   

warnings.filterwarnings('ignore')
def ejecutar_motor_ia_completo(modo='horario'):
    print("===================================================")
    print(f"INICIANDO ORQUESTADOR DE IA - MODO: {modo.upper()}")
    print("===================================================")
    # 1. Configuración global
    tz_colombia = pytz.timezone('America/Bogota')
    db_url = "postgresql+psycopg2://postgres.vdvmyueufdfviztmribf:Velasco14062000**@aws-1-us-east-1.pooler.supabase.com:5432/postgres"
    try:
        engine = create_engine(db_url)
        print("🔗 Conectado exitosamente a Supabase para inyectar Machine Learning.")
    except Exception as e:
        print(f"❌ Error crítico de conexión a la base de datos: {e}")
        return 
    # Módulo 1: Migraciones
    analizar_migraciones(engine, modo, tz_colombia)
        # Módulo 2: Redes Sociales (Pendiente de activar)
    analizar_rrss(engine, modo, tz_colombia)
        # Módulo 3: Retenciones Outbound (Pendiente de activar)
    analizar_retenciones(engine, modo, tz_colombia)
    print("\nProceso Analítico Orquestado Finalizado.")
    print("===================================================")

if __name__ == "__main__":
    # Permite recibir el modo desde la terminal (ej. python motor_ia.py horario)
    modo_ejecucion = sys.argv[1] if len(sys.argv) > 1 else 'horario'
    ejecutar_motor_ia_completo(modo_ejecucion)