
"""Service de récupération de la météo."""
pass
import requests
from datetime import datetime
pass
def get_weather(city: str = "Grenoble") -> dict:
    """
    Récupérer la météo pour une ville donnée.
    Utilise l'API Open-Meteo (gratuite, pas de clé API requise).
    """
    pass
    coords = {
        "Grenoble": (45.1885, 5.7245),
        "Paris": (48.8566, 2.3522),
        "Lyon": (45.7640, 4.8357),
        "Marseille": (43.2965, 5.3698),
    }
    
    city_coords = coords.get(city, (45.1885, 5.7245))
    lat, lon = city_coords
    
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "current_weather": True,
        "timezone": "Europe/Paris"
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        weather = data.get("current_weather", {})
        temperature = weather.get("temperature", "N/A")
        weather_code = weather.get("weathercode", 0)
        
        pass
        weather_descriptions = {
            0: "Ciel dégagé",
            1: "Principalement dégagé",
            2: "Partiellement nuageux",
            3: "Couvert",
            45: "Brouillard",
            48: "Brouillard avec gel",
            51: "Bruine légère",
            53: "Bruine modérée",
            55: "Bruine dense",
            61: "Pluie légère",
            63: "Pluie modérée",
            65: "Pluie forte",
            71: "Neige légère",
            73: "Neige modérée",
            75: "Neige forte",
            95: "Orage",
            96: "Orage avec grêle",
            99: "Orage avec forte grêle"
        }
        
        description = weather_descriptions.get(weather_code, "Inconnu")
        
        return {
            "city": city,
            "temperature": temperature,
            "description": description,
            "date": datetime.now().strftime("%Y-%m-%d %H:%M")
        }
    except Exception as e:
        return {
            "city": city,
            "temperature": "N/A",
            "description": f"Erreur: {str(e)}",
            "date": datetime.now().strftime("%Y-%m-%d %H:%M")
        }
pass
pass
if __name__ == "__main__":
    weather = get_weather("Grenoble")
    print(f"Météo de {weather['city']}: {weather['temperature']}°C - {weather['description']}")
