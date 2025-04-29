from ppi_client.ppi import PPI
from ppi_client.models.instrument import Instrument
import pandas as pd
import numpy as np
from datetime import datetime
import os
from dotenv import load_dotenv
import time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Cargar variables de entorno (necesitarás crear un archivo .env con tus credenciales)
load_dotenv()

# Configuración
PUBLIC_KEY = os.getenv("PPI_PUBLIC_KEY")
PRIVATE_KEY = os.getenv("PPI_PRIVATE_KEY")

# Configuración de email para alertas (opcional)
EMAIL_USER = os.getenv("EMAIL_USER", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
EMAIL_RECIPIENT = os.getenv("EMAIL_RECIPIENT", "")

# Umbral de oportunidad de arbitraje (%)
THRESHOLD = float(os.getenv("THRESHOLD", "1.5"))

class ArbitrajeDolar:
    def __init__(self):
        # Inicializar cliente PPI (False para producción, True para sandbox)
        self.ppi = PPI(sandbox=False)
        self.login()
        
        # Definir instrumentos a analizar
        self.bonos = {
            "AL30": {"local": "AL30", "ccl": "AL30C", "mep": "AL30D"},
            "AL35": {"local": "AL35", "ccl": "AL35C", "mep": "AL35D"},
            "GD30": {"local": "GD30", "ccl": "GD30C", "mep": "GD30D"},
            "GD35": {"local": "GD35", "ccl": "GD35C", "mep": "GD35D"},
            "GD38": {"local": "GD38", "ccl": "GD38C", "mep": "GD38D"},
            "GD41": {"local": "GD41", "ccl": "GD41C", "mep": "GD41D"},
        }
        
        # CEDEARs comunes (símbolo local y NYSE)
        self.cedears = {
            "AAPL": {"local": "AAPL", "usa": "AAPLD"},
            "MSFT": {"local": "MSFT", "usa": "MSFTD"},
            "AMZN": {"local": "AMZN", "usa": "AMZND"},            
            "META": {"local": "META", "usa": "METAD"},
            "TSLA": {"local": "TSLA", "usa": "TSLAD"},
            "NVDA": {"local": "NVDA", "usa": "NVDAD"},
            "KO": {"local": "KO", "usa": "KOD"},            
            "PFE": {"local": "PFE", "usa": "PFED"},
        }
        
        # Ratios de conversión de los CEDEARs 
        # (número de acciones que representa cada CEDEAR)
        self.ratios_cedear = {
            "AAPL": 1,
            "MSFT": 1,
            "AMZN": 1,
            "GOOGL": 1,
            "META": 1,
            "TSLA": 1,
            "NVDA": 1,
            "KO": 1,
            "DIS": 1,
            "PFE": 1,
        }
        
        # Almacenar resultados
        self.resultados = []
        
    def login(self):
        """Iniciar sesión en PPI"""
        print("Iniciando sesión en PPI...")
        self.ppi.account.login_api(PUBLIC_KEY, PRIVATE_KEY)
    
    def obtener_cotizacion(self, ticker, mercado="BONOS", plazo="A-24HS"):
        """Obtener la cotización actual de un instrumento"""
        try:
            data = self.ppi.marketdata.current(ticker, mercado, plazo)
            if not data:
                print(f"No se pudo obtener datos para {ticker}")
                return None
            return data
        except Exception as e:
            print(f"Error al obtener cotización de {ticker}: {e}")
            return None
    
    def calcular_dolar_implicito_bonos(self):
        """Calcular dólar implícito para bonos (MEP y CCL)"""
        print("\n=== CALCULANDO DÓLAR IMPLÍCITO EN BONOS ===")
        resultados_bonos = []
        
        for bono, tickers in self.bonos.items():
            try:
                # Obtener cotizaciones
                cotiz_local = self.obtener_cotizacion(tickers["local"])
                cotiz_ccl = self.obtener_cotizacion(tickers["ccl"])
                cotiz_mep = self.obtener_cotizacion(tickers["mep"])
                
                if not all([cotiz_local, cotiz_ccl, cotiz_mep]):
                    continue
                
                # Calcular dólar CCL
                precio_local = cotiz_local.get('price', 0)
                precio_ccl = cotiz_ccl.get('price', 0)
                
                if precio_local > 0 and precio_ccl > 0:
                    dolar_ccl = precio_local / precio_ccl
                    resultados_bonos.append({
                        "tipo": "CCL",
                        "instrumento": bono,
                        "ticker_ars": tickers["local"],
                        "precio_ars": precio_local,
                        "ticker_usd": tickers["ccl"],
                        "precio_usd": precio_ccl,
                        "dolar_implicito": dolar_ccl
                    })
                
                # Calcular dólar MEP
                precio_mep = cotiz_mep.get('price', 0)
                if precio_local > 0 and precio_mep > 0:
                    dolar_mep = precio_local / precio_mep
                    resultados_bonos.append({
                        "tipo": "MEP",
                        "instrumento": bono,
                        "ticker_ars": tickers["local"],
                        "precio_ars": precio_local,
                        "ticker_usd": tickers["mep"],
                        "precio_usd": precio_mep,
                        "dolar_implicito": dolar_mep
                    })
                
            except Exception as e:
                print(f"Error al procesar bono {bono}: {e}")
        
        # Ordenar por dólar implícito
        resultados_bonos = sorted(resultados_bonos, key=lambda x: x["dolar_implicito"])
        
        # Mostrar resultados
        df_bonos = pd.DataFrame(resultados_bonos)
        if not df_bonos.empty:
            df_bonos["dolar_implicito"] = df_bonos["dolar_implicito"].round(2)
            print(df_bonos[["tipo", "instrumento", "dolar_implicito"]])
        
        return resultados_bonos
    
    def calcular_dolar_implicito_cedears(self):
        """Calcular dólar CCL implícito para CEDEARs"""
        print("\n=== CALCULANDO DÓLAR IMPLÍCITO EN CEDEARS ===")
        resultados_cedears = []
        
        for cedear, tickers in self.cedears.items():
            try:
                # Obtener cotizaciones
                cotiz_local = self.obtener_cotizacion(tickers["local"], "CEDEARS", "A-48HS")
                cotiz_usa = self.obtener_cotizacion(tickers["usa"], "CEDEARS", "A-48HS")
                
                if not all([cotiz_local, cotiz_usa]):
                    continue
                
                precio_local = cotiz_local.get('price', 0)
                precio_usa = cotiz_usa.get('price', 0)
                ratio = self.ratios_cedear.get(cedear, 1)
                
                if precio_local > 0 and precio_usa > 0:
                    # Ajustamos el precio local según el ratio de conversión
                    dolar_implicito = (precio_local / ratio) / precio_usa
                    resultados_cedears.append({
                        "tipo": "CEDEAR",
                        "instrumento": cedear,
                        "ticker_ars": tickers["local"],
                        "precio_ars": precio_local,
                        "ticker_usd": tickers["usa"],
                        "precio_usd": precio_usa,
                        "ratio": ratio,
                        "dolar_implicito": dolar_implicito
                    })
            
            except Exception as e:
                print(f"Error al procesar CEDEAR {cedear}: {e}")
        
        # Ordenar por dólar implícito
        resultados_cedears = sorted(resultados_cedears, key=lambda x: x["dolar_implicito"])
        
        # Mostrar resultados
        df_cedears = pd.DataFrame(resultados_cedears)
        if not df_cedears.empty:
            df_cedears["dolar_implicito"] = df_cedears["dolar_implicito"].round(2)
            print(df_cedears[["instrumento", "dolar_implicito", "ratio"]])
        
        return resultados_cedears
    
    def encontrar_oportunidades(self, resultados_bonos, resultados_cedears):
        """Identificar oportunidades de arbitraje"""
        print("\n=== OPORTUNIDADES DE ARBITRAJE ===")
        oportunidades = []
        
        if not resultados_bonos or not resultados_cedears:
            print("No hay suficientes datos para encontrar oportunidades")
            return oportunidades
            
        # Obtener el bono con dólar más bajo y más alto
        min_bono = min(resultados_bonos, key=lambda x: x["dolar_implicito"])
        max_bono = max(resultados_bonos, key=lambda x: x["dolar_implicito"])
        
        # Obtener el CEDEAR con dólar más bajo y más alto
        min_cedear = min(resultados_cedears, key=lambda x: x["dolar_implicito"])
        max_cedear = max(resultados_cedears, key=lambda x: x["dolar_implicito"])
        
        # Arbitraje 1: Comprar bono con dólar más bajo y vender CEDEAR con dólar más alto
        if min_bono["dolar_implicito"] < max_cedear["dolar_implicito"]:
            diferencia_pct = (max_cedear["dolar_implicito"] / min_bono["dolar_implicito"] - 1) * 100
            if diferencia_pct >= THRESHOLD:
                oportunidades.append({
                    "tipo": "Bono → CEDEAR",
                    "instrumento_compra": min_bono["instrumento"],
                    "ticker_compra": min_bono["ticker_ars"],
                    "precio_compra": min_bono["precio_ars"],
                    "dolar_compra": min_bono["dolar_implicito"],
                    "instrumento_venta": max_cedear["instrumento"],
                    "ticker_venta": max_cedear["ticker_ars"],
                    "precio_venta": max_cedear["precio_ars"],
                    "dolar_venta": max_cedear["dolar_implicito"],
                    "diferencia_pct": diferencia_pct,
                    "estrategia": f"1) Comprar {min_bono['ticker_ars']} a ${min_bono['precio_ars']:.2f}\n"
                                  f"2) Vender {min_bono['ticker_usd']} por USD\n"
                                  f"3) Comprar {max_cedear['ticker_usd']} con USD\n"
                                  f"4) Vender {max_cedear['ticker_ars']} a ${max_cedear['precio_ars']:.2f}"
                })
        
        # Arbitraje 2: Comprar CEDEAR con dólar más bajo y vender bono con dólar más alto
        if min_cedear["dolar_implicito"] < max_bono["dolar_implicito"]:
            diferencia_pct = (max_bono["dolar_implicito"] / min_cedear["dolar_implicito"] - 1) * 100
            if diferencia_pct >= THRESHOLD:
                oportunidades.append({
                    "tipo": "CEDEAR → Bono",
                    "instrumento_compra": min_cedear["instrumento"],
                    "ticker_compra": min_cedear["ticker_ars"],
                    "precio_compra": min_cedear["precio_ars"],
                    "dolar_compra": min_cedear["dolar_implicito"],
                    "instrumento_venta": max_bono["instrumento"],
                    "ticker_venta": max_bono["ticker_ars"],
                    "precio_venta": max_bono["precio_ars"],
                    "dolar_venta": max_bono["dolar_implicito"],
                    "diferencia_pct": diferencia_pct,
                    "estrategia": f"1) Comprar {min_cedear['ticker_ars']} a ${min_cedear['precio_ars']:.2f}\n"
                                  f"2) Vender {min_cedear['ticker_usd']} por USD\n"
                                  f"3) Comprar {max_bono['ticker_usd']} con USD\n"
                                  f"4) Vender {max_bono['ticker_ars']} a ${max_bono['precio_ars']:.2f}"
                })
        
        # Arbitraje entre bonos (si hay una diferencia significativa)
        if max_bono["dolar_implicito"] > min_bono["dolar_implicito"]:
            diferencia_pct = (max_bono["dolar_implicito"] / min_bono["dolar_implicito"] - 1) * 100
            if diferencia_pct >= THRESHOLD:
                oportunidades.append({
                    "tipo": "Bono → Bono",
                    "instrumento_compra": min_bono["instrumento"],
                    "ticker_compra": min_bono["ticker_ars"],
                    "precio_compra": min_bono["precio_ars"],
                    "dolar_compra": min_bono["dolar_implicito"],
                    "instrumento_venta": max_bono["instrumento"],
                    "ticker_venta": max_bono["ticker_ars"],
                    "precio_venta": max_bono["precio_ars"],
                    "dolar_venta": max_bono["dolar_implicito"],
                    "diferencia_pct": diferencia_pct,
                    "estrategia": f"1) Comprar {min_bono['ticker_ars']} a ${min_bono['precio_ars']:.2f}\n"
                                  f"2) Vender {min_bono['ticker_usd']} por USD\n"
                                  f"3) Comprar {max_bono['ticker_usd']} con USD\n"
                                  f"4) Vender {max_bono['ticker_ars']} a ${max_bono['precio_ars']:.2f}"
                })
        
        # Arbitraje entre CEDEARs (si hay una diferencia significativa)
        if max_cedear["dolar_implicito"] > min_cedear["dolar_implicito"]:
            diferencia_pct = (max_cedear["dolar_implicito"] / min_cedear["dolar_implicito"] - 1) * 100
            if diferencia_pct >= THRESHOLD:
                oportunidades.append({
                    "tipo": "CEDEAR → CEDEAR",
                    "instrumento_compra": min_cedear["instrumento"],
                    "ticker_compra": min_cedear["ticker_ars"],
                    "precio_compra": min_cedear["precio_ars"],
                    "dolar_compra": min_cedear["dolar_implicito"],
                    "instrumento_venta": max_cedear["instrumento"],
                    "ticker_venta": max_cedear["ticker_ars"],
                    "precio_venta": max_cedear["precio_ars"],
                    "dolar_venta": max_cedear["dolar_implicito"],
                    "diferencia_pct": diferencia_pct,
                    "estrategia": f"1) Comprar {min_cedear['ticker_ars']} a ${min_cedear['precio_ars']:.2f}\n"
                                  f"2) Vender {min_cedear['ticker_usd']} por USD\n"
                                  f"3) Comprar {max_cedear['ticker_usd']} con USD\n"
                                  f"4) Vender {max_cedear['ticker_ars']} a ${max_cedear['precio_ars']:.2f}"
                })
        
        # Ordenar oportunidades por diferencia porcentual
        oportunidades = sorted(oportunidades, key=lambda x: x["diferencia_pct"], reverse=True)
        
        # Mostrar resultados
        if oportunidades:
            df_oportunidades = pd.DataFrame(oportunidades)
            print(df_oportunidades[["tipo", "instrumento_compra", "instrumento_venta", "diferencia_pct"]])
            
            # Mostrar estrategias detalladas
            print("\n=== ESTRATEGIAS DETALLADAS ===")
            for i, op in enumerate(oportunidades):
                print(f"\nOportunidad #{i+1}: {op['tipo']} ({op['diferencia_pct']:.2f}%)")
                print(f"Comprar: {op['instrumento_compra']} con dólar implícito ${op['dolar_compra']:.2f}")
                print(f"Vender: {op['instrumento_venta']} con dólar implícito ${op['dolar_venta']:.2f}")
                print("\nPasos:")
                print(op["estrategia"])
                print("-" * 50)
        else:
            print("No se encontraron oportunidades de arbitraje que superen el umbral de rentabilidad.")
        
        return oportunidades
    
    def enviar_alerta_email(self, oportunidades):
        """Enviar alertas por email (opcional)"""
        if not EMAIL_USER or not EMAIL_PASSWORD or not EMAIL_RECIPIENT:
            return False
        
        if not oportunidades:
            return False
        
        try:
            msg = MIMEMultipart()
            msg['From'] = EMAIL_USER
            msg['To'] = EMAIL_RECIPIENT
            msg['Subject'] = f"Alerta de Arbitraje - {len(oportunidades)} oportunidades detectadas"
            
            body = "Oportunidades de arbitraje detectadas:\n\n"
            for i, op in enumerate(oportunidades):
                body += f"Oportunidad #{i+1}: {op['tipo']} ({op['diferencia_pct']:.2f}%)\n"
                body += f"Comprar: {op['instrumento_compra']} con dólar implícito ${op['dolar_compra']:.2f}\n"
                body += f"Vender: {op['instrumento_venta']} con dólar implícito ${op['dolar_venta']:.2f}\n"
                body += "\nPasos:\n"
                body += op["estrategia"]
                body += "\n" + "-" * 30 + "\n\n"
            
            msg.attach(MIMEText(body, 'plain'))
            
            server = smtplib.SMTP('smtp.gmail.com', 587)
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASSWORD)
            text = msg.as_string()
            server.sendmail(EMAIL_USER, EMAIL_RECIPIENT, text)
            server.quit()
            
            print(f"\nAlerta enviada a {EMAIL_RECIPIENT}")
            return True
        
        except Exception as e:
            print(f"Error al enviar email: {e}")
            return False
    
    def ejecutar(self):
        """Ejecutar el análisis completo"""
        try:
            # Calcular dólares implícitos
            resultados_bonos = self.calcular_dolar_implicito_bonos()
            resultados_cedears = self.calcular_dolar_implicito_cedears()
            
            # Encontrar oportunidades
            oportunidades = self.encontrar_oportunidades(resultados_bonos, resultados_cedears)
            
            # Enviar alertas si es necesario
            if oportunidades and (EMAIL_USER and EMAIL_PASSWORD and EMAIL_RECIPIENT):
                self.enviar_alerta_email(oportunidades)
                
            return {
                "bonos": resultados_bonos,
                "cedears": resultados_cedears,
                "oportunidades": oportunidades
            }
            
        except Exception as e:
            print(f"Error en la ejecución: {e}")
            return None


def main():
    """Función principal"""
    print("=== ARBITRAJE DE DÓLAR IMPLÍCITO ===")
    print("Fecha y hora:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("-" * 50)
    
    # Modo de ejecución única
    arbitraje = ArbitrajeDolar()
    resultado = arbitraje.ejecutar()
    
    # Para ejecución periódica, descomentar el siguiente código:
    """
    while True:
        try:
            arbitraje = ArbitrajeDolar()
            resultado = arbitraje.ejecutar()
            
            # Esperar cierto tiempo antes de la próxima ejecución (en segundos)
            wait_time = 300  # 5 minutos
            print(f"\nEsperando {wait_time} segundos para la próxima actualización...")
            time.sleep(wait_time)
            
        except KeyboardInterrupt:
            print("\nPrograma interrumpido por el usuario")
            break
        except Exception as e:
            print(f"Error en el ciclo principal: {e}")
            time.sleep(60)  # Esperar 1 minuto antes de reintentar
    """

if __name__ == "__main__":
    main()