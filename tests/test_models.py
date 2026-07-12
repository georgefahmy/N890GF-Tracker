"""
Tests for database models and business logic functions.

Covers: Model CRUD, recompute_flight_history, check_auto_maintenance,
        calculate_overdue_items, get_upcoming_maintenance, calc_per_hour_cost
"""

from datetime import datetime, timedelta

import pytest


class TestFlightLogModel:
    """Tests for FlightLog model creation and field access."""

    def test_create_flight_log(self, app, seed_db):
        from app import FlightLog

        with app.app_context():
            flight = FlightLog.query.filter_by(takeoff_airport="KSJC", landing_airport="KRHV").first()
            assert flight is not None
            assert flight.takeoff_airport == "KSJC"
            assert flight.landing_airport == "KRHV"
            assert flight.hobbs == 100.0

    def test_flight_log_count(self, app, seed_db):
        from app import FlightLog

        with app.app_context():
            count = FlightLog.query.count()
            assert count == 3

    def test_flight_log_ordering(self, app, seed_db):
        from app import FlightLog

        with app.app_context():
            flights = FlightLog.query.order_by(FlightLog.hobbs.asc()).all()
            assert flights[0].hobbs < flights[-1].hobbs


class TestMaintenanceLogModel:
    """Tests for MaintenanceLog model."""

    def test_create_maintenance_log(self, app, seed_db):
        from app import MaintenanceLog

        with app.app_context():
            mx = MaintenanceLog.query.filter_by(
                recurrent_item="Oil Change"
            ).first()
            assert mx is not None
            assert mx.tach_time == 90.0
            assert mx.category == "Engine"

    def test_maintenance_log_count(self, app, seed_db):
        from app import MaintenanceLog

        with app.app_context():
            count = MaintenanceLog.query.count()
            assert count == 3


class TestFuelLogModel:
    """Tests for FuelLog model."""

    def test_create_fuel_log(self, app, seed_db):
        from app import FuelLog

        with app.app_context():
            fuel = FuelLog.query.first()
            assert fuel is not None
            assert fuel.gallons == 15.0
            assert fuel.total_cost == 97.50

    def test_fuel_cost_calculation(self, app, seed_db):
        from app import FuelLog

        with app.app_context():
            fuel = FuelLog.query.first()
            expected_cost = round(fuel.gallons * fuel.price_per_gallon, 2)
            assert fuel.total_cost == expected_cost


class TestUsersModel:
    """Tests for Users model."""

    def test_user_exists(self, app, seed_db):
        from app import Users

        with app.app_context():
            user = Users.query.filter_by(username="testpilot").first()
            assert user is not None
            assert user.username == "testpilot"

    def test_user_is_user_mixin(self, app, seed_db):
        from app import Users

        with app.app_context():
            user = Users.query.first()
            # UserMixin provides is_authenticated, is_active, etc.
            assert user.is_authenticated
            assert user.is_active


class TestBannedIPsModel:
    """Tests for BannedIPs model."""

    def test_create_banned_ip(self, app):
        from app import db, BannedIPs

        with app.app_context():
            ban = BannedIPs(
                ip="192.168.1.100",
                username="baduser",
                ban_time=1000.0,
                count=3,
            )
            db.session.add(ban)
            db.session.commit()

            result = BannedIPs.query.filter_by(ip="192.168.1.100").first()
            assert result is not None
            assert result.count == 3


class TestRecomputeFlightHistory:
    """Tests for recompute_flight_history() — hobbs/tach delta recalculation."""

    def test_deltas_calculated_correctly(self, app, seed_db):
        from app import recompute_flight_history, FlightLog

        with app.app_context():
            recompute_flight_history()
            flights = FlightLog.query.order_by(
                FlightLog.date.asc(), FlightLog.id.asc()
            ).all()

            # First flight: delta should be 0
            assert flights[0].hobbs_delta == 0.0
            assert flights[0].tach_delta == 0.0

            # Second flight: delta = 101.5 - 100.0 = 1.5
            assert flights[1].hobbs_delta == 1.5
            assert flights[1].tach_delta == 1.3

            # Third flight: delta = 103.0 - 101.5 = 1.5
            assert flights[2].hobbs_delta == 1.5
            assert flights[2].tach_delta == 1.5

    def test_no_flights_does_not_crash(self, app):
        from app import recompute_flight_history

        with app.app_context():
            # No flights in empty DB
            recompute_flight_history()  # Should not raise


class TestCheckAutoMaintenance:
    """Tests for check_auto_maintenance() — automatic oil change reminders."""

    def test_no_auto_oil_change_when_recent(self, app, seed_db):
        from app import check_auto_maintenance, MaintenanceLog

        with app.app_context():
            # Current tach is 97.8, last oil change at 90.0
            # Delta = 7.8 < 25 hrs, so no auto reminder
            initial_count = MaintenanceLog.query.filter_by(
                recurrent_item="Oil Change"
            ).count()
            check_auto_maintenance()
            new_count = MaintenanceLog.query.filter_by(
                recurrent_item="Oil Change"
            ).count()
            assert new_count == initial_count

    def test_auto_oil_change_triggers_when_overdue(self, app, seed_db):
        from app import db, check_auto_maintenance, MaintenanceLog, FlightLog

        with app.app_context():
            # Add a flight that pushes tach past the 25hr interval
            high_tach_flight = FlightLog(
                date=datetime(2024, 6, 1),
                takeoff_airport="KSJC",
                landing_airport="KRHV",
                hobbs=130.0,
                tach=120.0,  # 120 - 90 = 30 hrs since oil change
                landings=1,
            )
            db.session.add(high_tach_flight)
            db.session.commit()

            initial_count = MaintenanceLog.query.filter_by(
                recurrent_item="Oil Change"
            ).count()
            check_auto_maintenance()
            new_count = MaintenanceLog.query.filter_by(
                recurrent_item="Oil Change"
            ).count()
            assert new_count == initial_count + 1


class TestCalculateOverdueItems:
    """Tests for calculate_overdue_items() — overdue maintenance detection."""

    def test_oil_change_not_overdue_when_recent(self, app, seed_db):
        from app import calculate_overdue_items

        with app.app_context():
            overdue = calculate_overdue_items()
            assert "Oil Change" not in overdue

    def test_condition_inspection_overdue_after_365_days(self, app, seed_db):
        from app import calculate_overdue_items

        with app.app_context():
            # Condition inspection was done 60 days before base_date (2024-01-15)
            # So it was done on 2023-11-16. If today > 2024-11-15, it's overdue.
            # Since today is the actual current date (2026+), it IS overdue.
            overdue = calculate_overdue_items()
            assert "Condition Inspection" in overdue

    def test_returns_empty_when_everything_current(self, app):
        from app import db, MaintenanceLog, FlightLog, calculate_overdue_items

        with app.app_context():
            # Add very recent maintenance entries
            today = datetime.today()
            db.session.add(
                MaintenanceLog(
                    date=today,
                    tach_time=100.0,
                    airframe_time=100.0,
                    recurrent_item="Condition Inspection",
                    category="Airframe",
                )
            )
            db.session.add(
                MaintenanceLog(
                    date=today,
                    tach_time=100.0,
                    airframe_time=100.0,
                    recurrent_item="Oil Change",
                    category="Engine",
                )
            )
            db.session.add(
                FlightLog(
                    date=today,
                    hobbs=100.0,
                    tach=100.0,
                    landings=1,
                )
            )
            db.session.commit()

            overdue = calculate_overdue_items()
            assert "Condition Inspection" not in overdue
            assert "Oil Change" not in overdue


class TestGetUpcomingMaintenance:
    """Tests for get_upcoming_maintenance()."""

    def test_returns_dict_structure(self, app, seed_db):
        from app import get_upcoming_maintenance

        with app.app_context():
            result = get_upcoming_maintenance()
            assert "cond_due" in result
            assert "cond_status_class" in result
            assert "oil_due" in result
            assert "oil_status_class" in result

    def test_oil_due_shows_hours(self, app, seed_db):
        from app import get_upcoming_maintenance

        with app.app_context():
            result = get_upcoming_maintenance()
            # Oil change at 90.0, interval 25hrs => next due at 115.0
            assert "115.0 hrs" in result["oil_due"]

    def test_defaults_when_no_data(self, app):
        from app import get_upcoming_maintenance

        with app.app_context():
            result = get_upcoming_maintenance()
            assert result["cond_due"] == "--"
            assert result["oil_due"] == "--"


class TestOilAnalysisModel:
    """Tests for OilAnalysis model."""

    def test_create_oil_analysis(self, app):
        from app import db, OilAnalysis

        with app.app_context():
            entry = OilAnalysis(
                date_sampled=datetime(2024, 6, 1).date(),
                sample_no=1.0,
                oil_hrs=25.0,
                engine_hrs=500.0,
                iron=5.0,
                copper=2.0,
                chromium=0.5,
                aluminum=3.0,
                nickel=0.1,
                lead=1.0,
                diagnosis="Normal wear",
            )
            db.session.add(entry)
            db.session.commit()

            result = OilAnalysis.query.first()
            assert result.iron == 5.0
            assert result.diagnosis == "Normal wear"
            assert result.tail_number == "N890GF"
