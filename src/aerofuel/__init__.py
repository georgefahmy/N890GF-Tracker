"""
AeroFuel IQ module for N890GF Tracker.
Provides interactive aviation fuel radar, route fuel optimizer,
and AirNav retail pricing proxy.
"""

from .routes import aerofuel_bp
from .airnav_client import AirNavClient
from .core import airnav, load_catalog, update_stored_fuel_data

__all__ = [
    "aerofuel_bp",
    "AirNavClient",
    "airnav",
    "load_catalog",
    "update_stored_fuel_data",
]
