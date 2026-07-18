import json
from datetime import datetime, timedelta
import pytest
from app import db, FlightLog, MaintenanceLog, FuelLog, OilAnalysis, Users
from app import serialize_model, deserialize_model, perform_sync

@pytest.fixture(scope="function")
def test_sync_db(app, seed_db):
    """Seed DB and prepare environment for sync testing."""
    with app.app_context():
        # Ensure sync metadata fields are populated
        from app import migrate_db
        migrate_db()
        yield

def test_metadata_fields(app, test_sync_db):
    """Verify that metadata fields exist and behave correctly."""
    with app.app_context():
        flight = FlightLog.query.execution_options(include_deleted=True).first()
        assert flight.uuid is not None
        assert flight.updated_at is not None
        assert flight.is_deleted is False

def test_soft_delete_filtering(app, test_sync_db):
    """Verify that soft-deleted items are excluded from normal queries but included when bypassed."""
    with app.app_context():
        # Count flights initially
        count_active = FlightLog.query.count()
        assert count_active > 0

        # Soft delete the first flight
        flight = FlightLog.query.first()
        flight.is_deleted = True
        db.session.commit()

        # Count active flights again
        assert FlightLog.query.count() == count_active - 1

        # Count including deleted
        all_flights = FlightLog.query.execution_options(include_deleted=True).all()
        assert len(all_flights) == count_active

def test_api_sync_endpoint(app, client, test_sync_db):
    """Test the /api/sync endpoint handles inserts and updates."""
    # Let's mock a client payload sending a new flight log
    new_uuid = "12345678-abcd-ef01-2345-6789abcdef01"
    now_str = datetime.utcnow().isoformat()
    
    payload = {
        "last_sync_time": None,
        "changes": {
            "flight_log": [
                {
                    "uuid": new_uuid,
                    "date": "2026-07-18T12:00:00",
                    "takeoff_airport": "KPDX",
                    "landing_airport": "KSFO",
                    "hobbs": 250.0,
                    "tach": 240.0,
                    "hobbs_delta": 2.5,
                    "tach_delta": 2.2,
                    "landings": 1,
                    "notes": "Sync test flight",
                    "updated_at": now_str,
                    "is_deleted": False
                }
            ],
            "maintenance_entries": [],
            "fuel_tracker": [],
            "oil_analysis": []
        }
    }

    # Post to api/sync
    response = client.post("/api/sync", json=payload)
    assert response.status_code == 200
    res_data = response.json
    assert res_data["status"] == "success"
    assert "server_time" in res_data
    
    # Check that it was inserted in the database
    with app.app_context():
        inserted = FlightLog.query.execution_options(include_deleted=True).filter_by(uuid=new_uuid).first()
        assert inserted is not None
        assert inserted.takeoff_airport == "KPDX"
        assert inserted.notes == "Sync test flight"

def test_conflict_resolution_latest_timestamp_wins(app, client, test_sync_db):
    """Test conflict resolution where the newer updated_at timestamp wins."""
    with app.app_context():
        # Get a flight and update its local data
        flight = FlightLog.query.first()
        flight_uuid = flight.uuid
        
        # Older remote update: should be ignored
        older_time = (flight.updated_at - timedelta(hours=1)).isoformat()
        payload_older = {
            "last_sync_time": None,
            "changes": {
                "flight_log": [
                    {
                        "uuid": flight_uuid,
                        "date": flight.date.isoformat(),
                        "takeoff_airport": "KOLD",
                        "landing_airport": flight.landing_airport,
                        "updated_at": older_time,
                        "is_deleted": False
                    }
                ],
                "maintenance_entries": [],
                "fuel_tracker": [],
                "oil_analysis": []
            }
        }
        
    response = client.post("/api/sync", json=payload_older)
    assert response.status_code == 200
    
    # Verify that takeoff_airport did NOT change because the remote update was older
    with app.app_context():
        flight_check = FlightLog.query.filter_by(uuid=flight_uuid).first()
        assert flight_check.takeoff_airport != "KOLD"

    # Newer remote update: should overwrite
    newer_time = (datetime.utcnow() + timedelta(hours=1)).isoformat()
    payload_newer = {
        "last_sync_time": None,
        "changes": {
            "flight_log": [
                {
                    "uuid": flight_uuid,
                    "date": flight_check.date.isoformat(),
                    "takeoff_airport": "KNEW",
                    "landing_airport": flight_check.landing_airport,
                    "updated_at": newer_time,
                    "is_deleted": False
                }
            ],
            "maintenance_entries": [],
            "fuel_tracker": [],
            "oil_analysis": []
        }
    }
    
    response = client.post("/api/sync", json=payload_newer)
    assert response.status_code == 200
    
    # Verify that takeoff_airport was overwritten since remote update was newer
    with app.app_context():
        flight_check = FlightLog.query.filter_by(uuid=flight_uuid).first()
        assert flight_check.takeoff_airport == "KNEW"
