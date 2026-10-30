# Bench-only: the server with rain forced on and roads fully wet (RRT_RAIN=0 keeps it dry).
import os, sys
from theroadragetrip import weather as w
if os.environ.get("RRT_RAIN", "1") == "1":
    init = w.WeatherSystem.__init__
    def patched(self, weather_type=None, season=w.Season.SUMMER):
        init(self, w.WeatherType.RAIN, season)
        self.wetness = 1.0
        self.is_thunderstorm = False
    w.WeatherSystem.__init__ = patched
    upd = w.WeatherSystem.update
    def update(self, *a, **k):
        upd(self, *a, **k); self.weather_type = w.WeatherType.RAIN; self.wetness = 1.0
    w.WeatherSystem.update = update
else:
    upd = w.WeatherSystem.update
    def update(self, *a, **k):
        upd(self, *a, **k); self.weather_type = w.WeatherType.CLEAR; self.wetness = 0.0
    w.WeatherSystem.update = update
from theroadragetrip.server.__main__ import main
sys.argv[0] = "server"
main()
