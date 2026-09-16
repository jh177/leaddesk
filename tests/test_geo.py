import pytest

from leaddesk.geo import haversine_miles, is_serviceable


class TestHaversineMiles:
    @pytest.mark.parametrize(
        "lat1,lon1,lat2,lon2,expected",
        [
            (31.7619, -106.4850, 29.7604, -95.3698, 665.0),  # El Paso → Houston
            (31.7619, -106.4850, 31.7619, -106.4850, 0.0),   # same point
        ],
    )
    def test_known_distances(self, lat1, lon1, lat2, lon2, expected):
        assert haversine_miles(lat1, lon1, lat2, lon2) == pytest.approx(
            expected, rel=0.02
        )


class TestIsServiceable:
    def test_el_paso_zip_matches_el_paso_depot(self):
        result = is_serviceable("79901")
        assert result.servable
        assert result.depot == "el_paso"
        assert result.distance_miles < 5

    def test_houston_zip_matches_houston_depot(self):
        result = is_serviceable("77002")
        assert result.servable
        assert result.depot == "houston"

    def test_las_cruces_routes_to_el_paso(self):
        result = is_serviceable("88001")
        assert result.servable
        assert result.depot == "el_paso"

    def test_san_antonio_routes_to_houston(self):
        result = is_serviceable("78201")
        assert result.depot == "houston"

    def test_unknown_zipcode_is_not_servable(self):
        result = is_serviceable("99501")
        assert not result.servable
        assert result.reason == "unknown_zipcode"

    def test_malformed_zipcode_raises(self):
        with pytest.raises(ValueError, match="malformed"):
            is_serviceable("abc")

    def test_short_zipcode_raises(self):
        with pytest.raises(ValueError, match="malformed"):
            is_serviceable("7990")
