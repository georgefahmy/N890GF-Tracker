"""
Shared pytest fixtures for the N890GF tracker test suite.

Provides:
- app: Flask app configured with in-memory SQLite and TESTING=True
- client: Flask test client
- auth_client: Pre-authenticated test client (bypasses login)
- seed_db: Populates test DB with sample data
"""

import os
import sys
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch
from werkzeug.security import generate_password_hash

# Ensure project root is importable
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


@pytest.fixture(scope="function")
def app():
    """Create a Flask application configured for testing with in-memory SQLite."""
    # Patch environment before importing app to prevent side effects
    with patch.dict(os.environ, {}, clear=False):
        # We need to reconfigure the app for testing.
        # Import the app module's components directly.
        from app import app as flask_app, db

        flask_app.config.update(
            {
                "TESTING": True,
                "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                "WTF_CSRF_ENABLED": False,
                "LOGIN_DISABLED": False,
                "SERVER_NAME": "localhost",
                "SECRET_KEY": "test-secret-key",
                "MAX_CONTENT_LENGTH": 50 * 1024 * 1024,
            }
        )

        with flask_app.app_context():
            db.create_all()
            yield flask_app
            db.session.remove()
            db.drop_all()


@pytest.fixture(scope="function")
def client(app):
    """Flask test client."""
    return app.test_client()


@pytest.fixture(scope="function")
def db_session(app):
    """Provide direct access to the SQLAlchemy db session."""
    from app import db

    with app.app_context():
        yield db.session


@pytest.fixture(scope="function")
def seed_db(app):
    """Populate the test database with sample data."""
    from app import db, Users, FlightLog, MaintenanceLog, FuelLog

    with app.app_context():
        # Create test user
        user = Users(
            username="testpilot",
            password_hash=generate_password_hash("testpass123"),
        )
        db.session.add(user)

        # Create flight logs
        base_date = datetime(2024, 1, 15)
        flights = [
            FlightLog(
                date=base_date,
                takeoff_airport="KSJC",
                landing_airport="KRHV",
                hobbs=100.0,
                tach=95.0,
                hobbs_delta=0.0,
                tach_delta=0.0,
                landings=2,
                notes="Test flight 1",
            ),
            FlightLog(
                date=base_date + timedelta(days=7),
                takeoff_airport="KRHV",
                landing_airport="KSJC",
                hobbs=101.5,
                tach=96.3,
                hobbs_delta=1.5,
                tach_delta=1.3,
                landings=1,
                notes="Test flight 2",
            ),
            FlightLog(
                date=base_date + timedelta(days=14),
                takeoff_airport="KSJC",
                landing_airport="KPAO",
                hobbs=103.0,
                tach=97.8,
                hobbs_delta=1.5,
                tach_delta=1.5,
                landings=3,
                notes="Test flight 3",
            ),
        ]
        db.session.add_all(flights)

        # Create maintenance logs
        mx_entries = [
            MaintenanceLog(
                date=base_date - timedelta(days=30),
                tach_time=90.0,
                airframe_time=90.0,
                recurrent_item="Oil Change",
                category="Engine",
                notes="Oil change at 90 hrs",
            ),
            MaintenanceLog(
                date=base_date - timedelta(days=60),
                tach_time=80.0,
                airframe_time=80.0,
                recurrent_item="Condition Inspection",
                category="Airframe",
                notes="Annual condition inspection",
            ),
            MaintenanceLog(
                date=base_date - timedelta(days=10),
                tach_time=94.0,
                airframe_time=94.0,
                recurrent_item="Nav Data Update",
                category="Avionics",
                notes="Nav database update",
            ),
        ]
        db.session.add_all(mx_entries)

        # Create fuel logs
        fuel_entries = [
            FuelLog(
                date=base_date,
                hobbs=100.0,
                gallons=15.0,
                price_per_gallon=6.50,
                total_cost=97.50,
                gal_per_hour=8.5,
            ),
            FuelLog(
                date=base_date + timedelta(days=14),
                hobbs=103.0,
                gallons=12.0,
                price_per_gallon=6.75,
                total_cost=81.00,
                gal_per_hour=8.0,
            ),
        ]
        db.session.add_all(fuel_entries)

        db.session.commit()
        yield


@pytest.fixture(scope="function")
def auth_client(app, client, seed_db):
    """A test client that is already logged in as the test user."""
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["_user_id"] = "1"

    # Also perform actual login to set flask-login session state
    client.post(
        "/login",
        data={"username": "testpilot", "password": "testpass123"},
        follow_redirects=True,
    )
    return client
