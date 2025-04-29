from ppi_client.ppi import PPI
from ppi_client.models.instrument import Instrument
import pandas as pd
import numpy as np
from datetime import datetime
import matplotlib.pyplot as plt
from scipy.stats import norm
import os
from dotenv import load_dotenv
import json
import sys

# Cargar variables de entorno (necesitarás crear un archivo .env con tus credenciales)
load_dotenv()

# Configuración
PUBLIC_KEY = os.getenv("PPI_PUBLIC_KEY")
PRIVATE_KEY = os.getenv("PPI_PRIVATE_KEY")

# Inicializar cliente PPI (False para producción, True para sandbox)
ppi = PPI(sandbox=False)

def get_ggal_options():
    """Obtener todas las opciones de GGAL disponibles"""
    # Obtener todos los instrumentos de opciones
    # Utilizamos search_instruments con filtro para opciones de GGAL
    ggal_options = []
    
    try:
        # Buscar opciones de GGAL
        options = load_or_fetch("opciones_ggal.json","GGA")

        # Filtrar solo las opciones (las opciones suelen tener V o C en el símbolo para put o call)
        for instr in options:
            if 'ticker' in instr and instr['ticker'].startswith('GFG') and ('V' in instr['ticker'] or 'C' in instr['ticker']):
                ggal_options.append(instr)
                
        return ggal_options
    except Exception as e:
        print(f"Error buscando opciones de GGAL: {e}")
                

def get_option_details(options_list):
    """Obtener detalles completos de cada opción"""
    options_data = []
    
    for option in options_list:
        ticker = option['ticker']
        
        try:
            # Obtener datos de mercado
            ticker_data = ppi.marketdata.current(ticker, "OPCIONES", "A-24HS")
            option_price = ticker_data['price']
            if not (option_price >0):
                print(f"Precio de opción no válido para {ticker}: {option_price}")
                continue
            # Extraer información de la opción
            is_call = 'C' in ticker
            option_type = 'CALL' if is_call else 'PUT'
            
            # Extraer strike price y fecha de vencimiento
            # Formato típico: Opción venta GGAL AR$ 8300.00 Vto. 15/08/2025  /// GGAL-MM-XXXC/V donde MM es mes y XXX es precio strike
            parts = option['description'].split(' ')
            if len(parts) < 6:
                print(f"Formato de símbolo no reconocido: {ticker}")
                continue
                
            try:
                strike_part = parts[4]                                    
                strike_price = float(strike_part)
                
                # Parsear la fecha de vencimiento
                # Asumiendo formato típico mes-año (por ejemplo, 05-23 para mayo 2023)
                expiry_date = parts[6]
                expiry_date = datetime.strptime(expiry_date, "%d/%m/%Y")
                
                options_data.append({
                    'ticker': ticker,
                    'type': option_type,
                    'strike': strike_price,
                    'expiry': expiry_date,
                    'price': option_price
                })
                print(f"Procesada opción: {ticker}, precio: {option_price}, strike: {strike_price}")
            except Exception as e:
                print(f"Error procesando opción {ticker}: {e}")
        except Exception as e:
            print(f"Error obteniendo datos de mercado para {ticker}: {e}")
    
    return options_data

def get_underlying_price():
    """Obtener el precio actual de GGAL"""
    try:
        ggal_data = ppi.marketdata.current("GGAL", "ACCIONES", "A-24HS")
        if ggal_data and 'price' in ggal_data:
            return ggal_data['price']
    except Exception as e:
        print(f"Error obteniendo precio de GGAL: {e}")        
    
    return None

def black_scholes(S, K, T, r, sigma, option_type='call'):
    """
    Calcular el precio teórico de una opción usando Black-Scholes
    
    Parámetros:
    S: Precio del activo subyacente
    K: Precio de ejercicio
    T: Tiempo hasta el vencimiento (en años)
    r: Tasa libre de riesgo
    sigma: Volatilidad implícita
    option_type: 'call' o 'put'
    """
    d1 = (np.log(S/K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    
    if option_type.lower() == 'call':
        price = S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    else:
        price = K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
        
    return price

def calculate_implied_volatility(market_price, S, K, T, r, option_type='call'):
    """
    Calcular la volatilidad implícita usando el método de bisección
    """
    precision = 0.0001
    max_iterations = 100
    
    # Valores iniciales para la bisección
    sigma_low = 0.01
    sigma_high = 5.0
    
    for i in range(max_iterations):
        sigma_mid = (sigma_low + sigma_high) / 2
        price = black_scholes(S, K, T, r, sigma_mid, option_type)
        
        if abs(price - market_price) < precision:
            return sigma_mid
        
        if price > market_price:
            sigma_high = sigma_mid
        else:
            sigma_low = sigma_mid
            
    return (sigma_low + sigma_high) / 2

def analyze_options(options_data, underlying_price):
    """
    Analizar opciones y encontrar las que están subvaluadas
    """
    # Definir parámetros (ajustar según el mercado argentino)
    r = 0.45  # Tasa libre de riesgo anual (ajustar según BADLAR o similar)
    average_iv = 0.65  # Volatilidad promedio estimada para GGAL
    
    today = datetime.now()
    
    results = []
    
    for option in options_data:
        try:
            # Calcular tiempo hasta vencimiento en años
            days_to_expiry = (option['expiry'] - today).days
            if days_to_expiry <= 0:
                continue
                
            T = days_to_expiry / 365.0
            
            # Obtener valores
            S = underlying_price
            K = option['strike']
            market_price = option['price']
            option_type = 'call' if option['type'] == 'CALL' else 'put'
            
            # Calcular volatilidad implícita
            try:
                implied_vol = calculate_implied_volatility(market_price, S, K, T, r, option_type)
            except Exception as e:
                implied_vol = None
                print(f"Error calculando volatilidad implícita para {option['ticker']}: {e}")
                
            # Calcular precio teórico
            theoretical_price = black_scholes(S, K, T, r, average_iv, option_type)
            
            # Calcular diferencia
            if market_price > 0:
                price_diff_pct = (theoretical_price - market_price) / market_price * 100
            else:
                price_diff_pct = 0
                
            results.append({
                'ticker': option['ticker'],
                'type': option['type'],
                'strike': K,
                'expiry': option['expiry'].strftime('%Y-%m-%d'),
                'days_to_expiry': days_to_expiry,
                'market_price': market_price,
                'theoretical_price': theoretical_price,
                'price_diff_pct': price_diff_pct,
                'implied_volatility': implied_vol,
                'is_cheap': price_diff_pct > 10  # Consideramos barata si está 10% bajo el precio teórico
            })
                
        except Exception as e:
            print(f"Error analizando opción {option['ticker']}: {e}")
    
    return pd.DataFrame(results)

def load_or_fetch(file,ticker):
    if os.path.exists(file) and os.path.getsize(file) >0:
        print("\nGetting data from file")
        with open(file, 'r') as f:
            data = json.load(f)
    else:
        print("\nSearching instruments from API")
        data = ppi.marketdata.search_instrument(ticker, "", "", "OPCIONES")
        with open(file, 'w') as f:
            json.dump(data, f, indent=4)
    return data

def main():
    try:
        print("Iniciando sesión en PPI...")
        ppi.account.login_api(PUBLIC_KEY, PRIVATE_KEY)
        
        print("Obteniendo opciones de GGAL...")
        ggal_options = get_ggal_options()
        print(f"Se encontraron {len(ggal_options)} opciones relacionadas con GGAL")
                
        if len(ggal_options) == 0:
            print("No se encontraron opciones de GGAL. Finalizando.")
            return
            
        print("Obteniendo detalles de las opciones...")
        options_data = get_option_details(ggal_options)
        print(f"Se obtuvieron datos completos para {len(options_data)} opciones")
        
        if len(options_data) == 0:
            print("No se pudieron obtener detalles de las opciones. Finalizando.")
            return
            
        print("Obteniendo precio actual de GGAL...")
        underlying_price = get_underlying_price()
        print(f"Precio actual de GGAL: {underlying_price}")
        
        if not underlying_price:
            print("No se pudo obtener el precio de GGAL. Finalizando.")
            return
            
        print("Analizando opciones...")
        analysis = analyze_options(options_data, underlying_price)
        
        # Guardar todos los resultados
        analysis.to_csv('ggal_options_analysis.csv', index=False)
        print(f"Análisis guardado en 'ggal_options_analysis.csv'")
        
        # Mostrar opciones baratas
        if len(analysis) > 0:
            cheap_options = analysis[analysis['is_cheap']]
            cheap_options = cheap_options.sort_values('price_diff_pct', ascending=False)
            
            print("\n--- OPCIONES DE GGAL POTENCIALMENTE BARATAS ---")
            if len(cheap_options) > 0:
                print(cheap_options[['ticker', 'type', 'strike', 'expiry', 'market_price', 
                                  'theoretical_price', 'price_diff_pct', 'implied_volatility']])
                
                # Guardar las opciones baratas
                cheap_options.to_csv('ggal_cheap_options.csv', index=False)
                print(f"Opciones baratas guardadas en 'ggal_cheap_options.csv'")
                
                # Visualización
                plt.figure(figsize=(12, 6))
                plt.scatter(cheap_options['days_to_expiry'], cheap_options['price_diff_pct'], 
                          c=cheap_options['implied_volatility'], cmap='viridis', alpha=0.7, s=100)
                plt.colorbar(label='Volatilidad Implícita')
                plt.xlabel('Días hasta vencimiento')
                plt.ylabel('Diferencia de precio (%)')
                plt.title('Opciones de GGAL potencialmente subvaluadas')
                plt.grid(True, alpha=0.3)
                plt.savefig('ggal_options_analysis.png')
                print(f"Gráfico guardado en 'ggal_options_analysis.png'")
                if 'DISPLAY' in os.environ:
                    plt.show()
            else:
                print("No se encontraron opciones baratas según los criterios establecidos.")
        else:
            print("No se pudieron analizar las opciones.")
            
    except Exception as e:
        print(f"Error en la ejecución: {e}")

if __name__ == "__main__":
    main()