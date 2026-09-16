import math

from leaddesk.models import Depot, ServiceabilityResult

EARTH_RADIUS_MILES = 3958.8

# radius_miles is per-depot: Houston's denser contractor coverage supports a
# wider viable radius than El Paso's. TODO: confirm these with ops — placeholders.
DEPOTS: dict[str, Depot] = {
    "el_paso": Depot(name="el_paso", latitude=31.7619, longitude=-106.4850, radius_miles=300),
    "houston": Depot(name="houston", latitude=29.7604, longitude=-95.3698, radius_miles=400),
}

# Start with ~10 zips per market plus a few out-of-range ones for testing
ZIP_COORDS: dict[str, tuple[float, float]] = {
    "79901": (31.7587, -106.4869),   # El Paso
    "79907": (31.7088, -106.3169),   # El Paso east
    "88001": (32.3199, -106.7637),   # Las Cruces NM
    "77002": (29.7563, -95.3648),    # Houston
    "77494": (29.7460, -95.8299),    # Katy
    "78201": (29.4661, -98.5133),    # San Antonio
}

def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
  """Great-circle distance between two points. This is for determining the service area not for calculating delivery fee"""

  lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])

  dlat = lat2 - lat1
  dlon = lon2 - lon1

  a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2)**2
  c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

  return EARTH_RADIUS_MILES * c

def is_serviceable(zipcode: str) -> ServiceabilityResult:
    """Find the nearest depot within the service radius.

    Uses straight-line distance — suitable for a service-area yes/no,
    NOT for delivery pricing, which needs road distance.
    """
    if not zipcode.isdigit() or len(zipcode) != 5:
        raise ValueError(f"malformed zipcode: {zipcode!r}")

    if zipcode not in ZIP_COORDS:
        return ServiceabilityResult(
            servable=False, reason="unknown_zipcode"
        )

    dest_lat, dest_lon = ZIP_COORDS[zipcode]

    depot, distance = min(
        (
            (depot, haversine_miles(depot.latitude, depot.longitude, dest_lat, dest_lon))
            for depot in DEPOTS.values()
        ),
        key=lambda pair: pair[1],
    )

    if distance > depot.radius_miles:
        return ServiceabilityResult(
            servable=False,
            depot=depot.name,
            distance_miles=round(distance, 1),
            reason="outside_service_radius",
        )

    return ServiceabilityResult(
        servable=True, depot=depot.name, distance_miles=round(distance, 1)
    )
