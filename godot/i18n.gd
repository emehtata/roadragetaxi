class_name I18n
extends RefCounted

const FI := {
	"choose_language": "VALITSE KIELI", "choose_start": "Valitse pelitapa", "career": "Ura",
	"gig_driver": "Keikkakuski", "settings": "Asetukset", "hint_enter_taxi": "Painamalla F pääset sisään taksiisi", "hint_start_engine": "Käynnistä moottori painamalla E", "weather_forecast_24h": "Arvioitu sää seuraavalle 24 tunnille", "press_any_key_start": "Paina mitä tahansa aloittaaksesi", "weather_source_observed": "havainto", "weather_source_forecast": "ennuste", "start_time": "ALOITUSAIKA", "year": "Vuosi", "month": "Kuukausi", "day": "Päivä", "hour": "Tunti", "minute": "Minuutti", "now": "Nyt", "start": "Aloita", "historical_weather": "Historiallinen sää (FMI)", "quit": "Lopeta peli",
	"choose_city": "VALITSE KAUPUNKI", "drive": "Aloita", "back": "Takaisin",
	"master_volume": "Kokonaisäänenvoimakkuus", "game_volume": "Peliäänet",
	"environment_volume": "Ympäristöäänet", "ui_volume": "Käyttöliittymän äänet",
	"loading": "LADATAAN", "starting": "Käynnistetään simulaatiota…", "start_failed": "KÄYNNISTYS EPÄONNISTUI",
	"start_failed_detail": "Python-simulaatiota ei voitu käynnistää", "paused": "PELI TAUOLLA",
	"resume": "Jatka peliä", "main_menu": "Alkuvalikko", "score": "Pisteet", "on_foot": "jalan",
	"road_wet": "%s, tie %d%% märkä", "weather_clear": "Selkeää", "weather_rain": "Sadetta",
	"weather_slush": "Räntää", "weather_snow": "Lumisadetta", "weather_thunderstorm": "Ukkosta",
	"no_fare": "Ei kyytiä – %d ajettu", "passenger": "Asiakas", "pick_up": "Nouda %s paikasta %s",
	"walking_taxi": "%s kävelee taksille", "drive_to": "Vie %s osoitteeseen %s", "road": "Tie",
	"off_road": "Maastossa", "limit": "Rajoitus", "on": "PÄÄLLÄ", "off": "POIS",
	"streets": "KADUT", "all": "KAIKKI", "hint_foot": "F taksiin · WASD kävele · P puhelin",
	"hint_engine": "E käynnistä moottori · F ulos · P puhelin",
	"hint_drive": "WASD aja · SPACE rattiraivo · F ulos · E moottori · G tankkaa · K kaista-avustin %s · V rajoitin %s · B valoavustin %s · N navigointi %s · L nimet %s · J junat · P puhelin · C kompassi · F1 ohje · +/- zoom",
	"controls_help": "OHJAIMET\n\nWASD / nuolet   Aja tai kävele      Shift   Juokse\nF   Mene taksiin / poistu           E   Moottori\nP   Puhelin                          1–3 / Enter / X   Puhelimen valinnat\nSpace   Rattiraivo                   G   Tankkaa\nR   Palauta taksi                   X   Peru kyyti\nT   Nollaa matkamittari             K   Kaista-avustin\nV   Nopeusrajoitin                  B   Valoavustin\nN   Navigointi                      C   Kompassi\nJ   Junataulu                       L   Nimet\n+ / -   Zoom                        Esc   Tauko\nF1   Sulje ohje                     F3   Diagnostiikka",
	"train_hint": "Juna-aikataulut saatavilla. Paina J.   ", "next_trains": "Saapuvat junat",
	"departing_trains": "Lähtevät junat", "track": "raide", "driver": "Kuljettaja", "passenger_speaker": "Matkustaja",
	"city_summary": "Kaupungin yhteenveto", "city_complete": "Tämä kaupunki on suoritettu.",
	"fares_completed": "Ajetut keikat: %d", "next_city": "Seuraava kaupunki: %s",
	"career_complete": "Ura suoritettu! Helsinki on valloitettu.", "career_score": "Uran kokonaispisteet: %d",
	"waiting": "Odotetaan simulaatiota osoitteessa %s:%d …",
	"trip": "Matka", "odometer": "Mittari", "in_water": "Vedessä: %.1f s", "fuel": "POLTTOAINE",
	"refuel_price": "G: TANKKAA  %.2f €/L", "rage": "Rattiraivo: %d%%", "pickup": "NOUTO",
	"dropoff": "PERILLE", "destination": "Määränpää", "nausea": "Oksettaa!",
}

static func text(key: String, language: String, fallback: String) -> String:
	return FI.get(key, fallback) if language == "fi" else fallback

static func weather(value: String, language: String) -> String:
	return text("weather_" + value, language, value.capitalize())
