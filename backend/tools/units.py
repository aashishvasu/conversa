"""Unit conversion constants and logic for the calculator tool."""

import math

from .conversa_tool import ToolFailed

# Unit conversion definitions: (category, conversion_factor_to_base_unit)
UNITS: dict[str, tuple[str, float]] = {
    # length (base: m)
    "nm": ("length", 1e-9),
    "um": ("length", 1e-6),
    "mm": ("length", 1e-3),
    "cm": ("length", 1e-2),
    "m": ("length", 1.0),
    "km": ("length", 1e3),
    "in": ("length", 0.0254),
    "ft": ("length", 0.3048),
    "yd": ("length", 0.9144),
    "mi": ("length", 1609.344),
    "nmi": ("length", 1852.0),

    # mass (base: kg)
    "mg": ("mass", 1e-6),
    "g": ("mass", 1e-3),
    "kg": ("mass", 1.0),
    "t": ("mass", 1000.0),
    "oz": ("mass", 0.028349523125),
    "lb": ("mass", 0.45359237),
    "st": ("mass", 6.35029318),
    "ton": ("mass", 907.18474),

    # duration (base: s)
    "ns": ("duration", 1e-9),
    "us": ("duration", 1e-6),
    "ms": ("duration", 1e-3),
    "s": ("duration", 1.0),
    "min": ("duration", 60.0),
    "h": ("duration", 3600.0),
    "d": ("duration", 86400.0),
    "wk": ("duration", 604800.0),

    # data_size (base: bit = b; case sensitive)
    "b": ("data_size", 1.0),
    "B": ("data_size", 8.0),
    "kb": ("data_size", 1e3),
    "kB": ("data_size", 8e3),
    "Mb": ("data_size", 1e6),
    "MB": ("data_size", 8e6),
    "Gb": ("data_size", 1e9),
    "GB": ("data_size", 8e9),
    "Tb": ("data_size", 1e12),
    "TB": ("data_size", 8e12),
    "Pb": ("data_size", 1e15),
    "PB": ("data_size", 8e15),
    "Kib": ("data_size", 1024.0),
    "KiB": ("data_size", 8192.0),
    "Mib": ("data_size", 1024.0 ** 2),
    "MiB": ("data_size", 8.0 * 1024.0 ** 2),
    "Gib": ("data_size", 1024.0 ** 3),
    "GiB": ("data_size", 8.0 * 1024.0 ** 3),
    "Tib": ("data_size", 1024.0 ** 4),
    "TiB": ("data_size", 8.0 * 1024.0 ** 4),
    "Pib": ("data_size", 1024.0 ** 5),
    "PiB": ("data_size", 8.0 * 1024.0 ** 5),

    # speed (base: m/s)
    "m/s": ("speed", 1.0),
    "km/h": ("speed", 1.0 / 3.6),
    "mph": ("speed", 0.44704),
    "knot": ("speed", 0.5144444444444445),
    "ft/s": ("speed", 0.3048),

    # area (base: m2)
    "mm2": ("area", 1e-6),
    "cm2": ("area", 1e-4),
    "m2": ("area", 1.0),
    "ha": ("area", 1e4),
    "km2": ("area", 1e6),
    "in2": ("area", 0.00064516),
    "ft2": ("area", 0.09290304),
    "yd2": ("area", 0.83612736),
    "ac": ("area", 4046.8564224),
    "mi2": ("area", 2589988.110336),

    # volume (base: m3, US customary labeled explicitly)
    "ml": ("volume", 1e-6),
    "l": ("volume", 1e-3),
    "L": ("volume", 1e-3),
    "m3": ("volume", 1.0),
    "tsp_us": ("volume", 4.92892159375e-6),
    "tbsp_us": ("volume", 1.478676478125e-5),
    "fl_oz_us": ("volume", 2.95735295625e-5),
    "cup_us": ("volume", 0.0002365882365),
    "pt_us": ("volume", 0.000473176473),
    "qt_us": ("volume", 0.000946352946),
    "gal_us": ("volume", 0.003785411784),
    "in3": ("volume", 1.6387064e-5),
    "ft3": ("volume", 0.028316846592),

    # pressure (base: Pa)
    "Pa": ("pressure", 1.0),
    "kPa": ("pressure", 1000.0),
    "MPa": ("pressure", 1e6),
    "bar": ("pressure", 1e5),
    "mbar": ("pressure", 100.0),
    "psi": ("pressure", 6894.757293168),
    "atm": ("pressure", 101325.0),
    "torr": ("pressure", 101325.0 / 760.0),
    "mmHg": ("pressure", 101325.0 / 760.0),

    # energy (base: J)
    "J": ("energy", 1.0),
    "kJ": ("energy", 1e3),
    "MJ": ("energy", 1e6),
    "cal": ("energy", 4.184),
    "kcal": ("energy", 4184.0),
    "Wh": ("energy", 3600.0),
    "kWh": ("energy", 3.6e6),
    "eV": ("energy", 1.602176634e-19),
    "BTU": ("energy", 1055.05585262),
}

AMBIGUOUS_UNITS = {
    "gal": "ambiguous volume unit: specify US customary explicitly as 'gal_us'",
    "pt": "ambiguous volume unit: specify US customary explicitly as 'pt_us'",
    "qt": "ambiguous volume unit: specify US customary explicitly as 'qt_us'",
    "cup": "ambiguous volume unit: specify US customary explicitly as 'cup_us'",
    "tbsp": "ambiguous volume unit: specify US customary explicitly as 'tbsp_us'",
    "tsp": "ambiguous volume unit: specify US customary explicitly as 'tsp_us'",
    "fl_oz": "ambiguous volume unit: specify US customary explicitly as 'fl_oz_us'",
}

TEMPERATURE_UNITS = {"C", "F", "K"}


def convert_units(value: float | int, from_unit: str, to_unit: str) -> dict[str, object]:
    if from_unit in AMBIGUOUS_UNITS:
        raise ToolFailed(AMBIGUOUS_UNITS[from_unit])
    if to_unit in AMBIGUOUS_UNITS:
        raise ToolFailed(AMBIGUOUS_UNITS[to_unit])

    numeric = float(value)
    if not math.isfinite(numeric):
        raise ToolFailed("conversion value must be finite")

    is_temp_from = from_unit in TEMPERATURE_UNITS
    is_temp_to = to_unit in TEMPERATURE_UNITS

    if is_temp_from or is_temp_to:
        if not (is_temp_from and is_temp_to):
            cat_from = "temperature" if is_temp_from else UNITS.get(from_unit, ("unknown", 0))[0]
            cat_to = "temperature" if is_temp_to else UNITS.get(to_unit, ("unknown", 0))[0]
            raise ToolFailed(f"cannot convert between {cat_from} and {cat_to}")

        if from_unit == "C":
            kelvin = numeric + 273.15
        elif from_unit == "F":
            kelvin = (numeric - 32.0) * 5.0 / 9.0 + 273.15
        else:
            kelvin = numeric

        if to_unit == "C":
            result = kelvin - 273.15
        elif to_unit == "F":
            result = (kelvin - 273.15) * 9.0 / 5.0 + 32.0
        else:
            result = kelvin

        result = round(result, 10)
        if not math.isfinite(result):
            raise ToolFailed("conversion result is not finite")
        return {
            "value": result,
            "from_unit": from_unit,
            "to_unit": to_unit,
            "category": "temperature",
        }

    if from_unit not in UNITS:
        raise ToolFailed(f"unknown unit: '{from_unit}'")
    if to_unit not in UNITS:
        raise ToolFailed(f"unknown unit: '{to_unit}'")

    cat_from, factor_from = UNITS[from_unit]
    cat_to, factor_to = UNITS[to_unit]
    if cat_from != cat_to:
        raise ToolFailed(f"cannot convert between {cat_from} and {cat_to}")

    converted = (numeric * factor_from) / factor_to
    if not math.isfinite(converted):
        raise ToolFailed("conversion result is not finite")
    return {
        "value": converted,
        "from_unit": from_unit,
        "to_unit": to_unit,
        "category": cat_from,
    }
