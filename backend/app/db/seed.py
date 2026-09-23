from __future__ import annotations

import argparse
import random
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import insert, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.entities import (
    Customer,
    Driver,
    FuelRecord,
    Invoice,
    MaintenanceRecord,
    Payment,
    SeedRun,
    Subscription,
    Trip,
    User,
    Vehicle,
    VehicleLocation,
)

SEED_NAME = "fleet_demo_v1"
SEED_RANDOM = 20260923
CUSTOMER_COUNT = 100
VEHICLE_COUNT = 1_000
DRIVER_COUNT = 500
TRIP_COUNT = 50_000
LOCATION_COUNT = 20_000
FUEL_COUNT = 20_000
MAINTENANCE_COUNT = 10_000
INVOICE_COUNT = 10_000
PAYMENT_COUNT = 20_000
SUBSCRIPTION_COUNT = 100
MONEY = Decimal("0.01")
START_DATE = datetime(2024, 1, 1, tzinfo=UTC)
END_DATE = datetime(2025, 12, 31, 23, 59, tzinfo=UTC)

CITIES = [
    ("Austin", "Texas"),
    ("Boston", "Massachusetts"),
    ("Chicago", "Illinois"),
    ("Denver", "Colorado"),
    ("Houston", "Texas"),
    ("Miami", "Florida"),
    ("New York", "New York"),
    ("Phoenix", "Arizona"),
    ("Seattle", "Washington"),
    ("Atlanta", "Georgia"),
]
MANUFACTURERS = [
    ("Ford", ["Transit", "F-150"]),
    ("Toyota", ["HiAce", "Hilux"]),
    ("Volvo", ["FH", "FM"]),
    ("Tata", ["Ace", "Ultra"]),
]
VEHICLE_TYPES = ["van", "truck", "pickup", "bus"]
FUEL_TYPES = ["diesel", "petrol", "cng", "electric"]
LOCATIONS = ["Warehouse", "Distribution Center", "Customer Site", "Depot", "Service Hub"]
MAINTENANCE_TYPES = [
    "routine service",
    "oil change",
    "tire replacement",
    "brake inspection",
    "annual service",
]
PLANS = [
    ("Starter", Decimal("99.00")),
    ("Growth", Decimal("249.00")),
    ("Enterprise", Decimal("599.00")),
]


def _random_datetime(rng: random.Random) -> datetime:
    seconds = int((END_DATE - START_DATE).total_seconds())
    return START_DATE + timedelta(seconds=rng.randrange(seconds))


def _random_date(rng: random.Random) -> date:
    return _random_datetime(rng).date()


def _money(value: Decimal | float | int) -> Decimal:
    return Decimal(str(value)).quantize(MONEY, rounding=ROUND_HALF_UP)


def _bulk_insert(session: Session, model: type[Any], rows: list[dict[str, Any]]) -> None:
    session.execute(insert(model), rows)


def generate_seed_rows(seed: int = SEED_RANDOM) -> dict[type[Any], list[dict[str, Any]]]:
    rng = random.Random(seed)
    customer_rows: list[dict[str, Any]] = []
    customer_city: dict[int, tuple[str, str]] = {}

    for customer_id in range(1, CUSTOMER_COUNT + 1):
        city, state = CITIES[(customer_id - 1) % len(CITIES)]
        customer_city[customer_id] = (city, state)
        company_prefix = ["Northstar", "BluePeak", "Summit", "Harbor", "Cedar"][customer_id % 5]
        customer_rows.append(
            {
                "id": customer_id,
                "name": f"Customer Contact {customer_id:03d}",
                "email": f"contact{customer_id:03d}@fleetco.example",
                "company_name": f"{company_prefix} Logistics {customer_id:03d}",
                "city": city,
                "state": state,
                "country": "United States",
                "created_at": _random_datetime(rng),
                "status": rng.choices(["active", "inactive", "suspended"], [88, 9, 3])[0],
            }
        )

    user_rows = []
    user_id = 1
    for customer_id in range(1, CUSTOMER_COUNT + 1):
        for user_number in range(1, rng.randint(2, 5) + 1):
            user_rows.append(
                {
                    "id": user_id,
                    "customer_id": customer_id,
                    "name": f"Fleet User {customer_id:03d}-{user_number}",
                    "email": f"user{user_id:04d}@fleetco.example",
                    "role": "admin"
                    if user_number == 1
                    else rng.choice(["dispatcher", "analyst", "operator"]),
                    "created_at": _random_datetime(rng),
                    "status": rng.choices(["active", "inactive", "invited"], [88, 8, 4])[0],
                }
            )
            user_id += 1

    vehicle_rows = []
    vehicle_customer: dict[int, int] = {}
    for vehicle_id in range(1, VEHICLE_COUNT + 1):
        customer_id = rng.randint(1, CUSTOMER_COUNT)
        vehicle_customer[vehicle_id] = customer_id
        city, state = customer_city[customer_id]
        manufacturer, models = rng.choice(MANUFACTURERS)
        vehicle_rows.append(
            {
                "id": vehicle_id,
                "customer_id": customer_id,
                "registration_number": f"FLEET-{vehicle_id:05d}",
                "vehicle_type": rng.choice(VEHICLE_TYPES),
                "manufacturer": manufacturer,
                "model": rng.choice(models),
                "fuel_type": rng.choices(FUEL_TYPES, [45, 25, 15, 15])[0],
                "city": city,
                "state": state,
                "status": rng.choices(
                    ["active", "inactive", "maintenance", "retired"], [76, 10, 10, 4]
                )[0],
                "purchase_date": date(2021, 1, 1) + timedelta(days=rng.randrange(1_460)),
                "created_at": _random_datetime(rng),
            }
        )

    driver_rows = []
    drivers_by_customer: dict[int, list[int]] = {
        customer_id: [] for customer_id in range(1, CUSTOMER_COUNT + 1)
    }
    for driver_id in range(1, DRIVER_COUNT + 1):
        customer_id = ((driver_id - 1) % CUSTOMER_COUNT) + 1
        drivers_by_customer[customer_id].append(driver_id)
        driver_rows.append(
            {
                "id": driver_id,
                "customer_id": customer_id,
                "name": f"Driver {driver_id:04d}",
                "phone": f"+1-555-{driver_id // 1000:03d}-{driver_id % 1000:04d}",
                "license_number": f"LIC-{driver_id:06d}",
                "license_expiry": date(2026, 1, 1) + timedelta(days=rng.randrange(1_095)),
                "status": rng.choices(["active", "inactive", "suspended"], [90, 7, 3])[0],
                "created_at": _random_datetime(rng),
            }
        )

    trip_rows = []
    for trip_id in range(1, TRIP_COUNT + 1):
        vehicle_id = rng.randint(1, VEHICLE_COUNT)
        customer_id = vehicle_customer[vehicle_id]
        start_time = _random_datetime(rng)
        trip_status = rng.choices(["completed", "cancelled", "in_progress"], [91, 5, 4])[0]
        end_time = (
            None
            if trip_status == "in_progress"
            else start_time + timedelta(minutes=rng.randint(20, 720))
        )
        distance = _money(rng.uniform(2, 850))
        trip_rows.append(
            {
                "id": trip_id,
                "vehicle_id": vehicle_id,
                "driver_id": rng.choice(drivers_by_customer[customer_id]),
                "customer_id": customer_id,
                "start_time": start_time,
                "end_time": end_time,
                "start_location": rng.choice(LOCATIONS),
                "end_location": rng.choice(LOCATIONS),
                "distance_km": distance,
                "fuel_consumed_liters": _money(float(distance) * rng.uniform(0.06, 0.18)),
                "idle_time_minutes": rng.randint(0, 90),
                "trip_status": trip_status,
            }
        )

    location_rows = []
    for location_id in range(1, LOCATION_COUNT + 1):
        vehicle_id = rng.randint(1, VEHICLE_COUNT)
        city, _ = customer_city[vehicle_customer[vehicle_id]]
        city_offset = CITIES.index((city, customer_city[vehicle_customer[vehicle_id]][1]))
        location_rows.append(
            {
                "id": location_id,
                "vehicle_id": vehicle_id,
                "latitude": _money(25 + city_offset * 2.1 + rng.uniform(-0.4, 0.4)),
                "longitude": _money(-122 + city_offset * 2.5 + rng.uniform(-0.4, 0.4)),
                "speed_kmph": _money(rng.uniform(0, 110)),
                "recorded_at": _random_datetime(rng),
            }
        )

    fuel_rows = []
    for fuel_id in range(1, FUEL_COUNT + 1):
        vehicle_id = rng.randint(1, VEHICLE_COUNT)
        liters = _money(rng.uniform(15, 180))
        price = _money(rng.uniform(1.10, 4.25))
        fuel_rows.append(
            {
                "id": fuel_id,
                "vehicle_id": vehicle_id,
                "customer_id": vehicle_customer[vehicle_id],
                "fuel_date": _random_date(rng),
                "liters": liters,
                "price_per_liter": price,
                "total_cost": _money(liters * price),
            }
        )

    maintenance_rows = []
    for maintenance_id in range(1, MAINTENANCE_COUNT + 1):
        vehicle_id = rng.randint(1, VEHICLE_COUNT)
        maintenance_rows.append(
            {
                "id": maintenance_id,
                "vehicle_id": vehicle_id,
                "customer_id": vehicle_customer[vehicle_id],
                "maintenance_date": _random_date(rng),
                "maintenance_type": rng.choice(MAINTENANCE_TYPES),
                "cost": _money(rng.uniform(75, 2_500)),
                "description": "Scheduled fleet maintenance and inspection",
                "status": rng.choices(["scheduled", "completed", "cancelled"], [15, 80, 5])[0],
            }
        )

    invoice_rows = []
    payment_rows = []
    for invoice_id in range(1, INVOICE_COUNT + 1):
        customer_id = rng.randint(1, CUSTOMER_COUNT)
        invoice_date = _random_date(rng)
        due_date = invoice_date + timedelta(days=30)
        amount = _money(rng.uniform(150, 12_000))
        tax_amount = _money(amount * Decimal("0.08"))
        total_amount = amount + tax_amount
        invoice_status = rng.choices(["paid", "pending", "overdue", "cancelled"], [55, 25, 15, 5])[
            0
        ]
        invoice_rows.append(
            {
                "id": invoice_id,
                "customer_id": customer_id,
                "invoice_date": invoice_date,
                "due_date": due_date,
                "amount": amount,
                "tax_amount": tax_amount,
                "total_amount": total_amount,
                "status": invoice_status,
            }
        )
        first_payment = _money(total_amount / 2)
        for part in range(2):
            payment_rows.append(
                {
                    "id": (invoice_id - 1) * 2 + part + 1,
                    "invoice_id": invoice_id,
                    "customer_id": customer_id,
                    "payment_date": due_date + timedelta(days=part * 8 + rng.randint(-3, 5)),
                    "amount": first_payment if part == 0 else total_amount - first_payment,
                    "payment_method": rng.choice(
                        ["bank_transfer", "credit_card", "direct_debit", "cash"]
                    ),
                    "status": "paid"
                    if invoice_status == "paid"
                    else rng.choices(["paid", "pending", "failed"], [35, 50, 15])[0],
                }
            )

    subscription_rows = []
    for customer_id in range(1, SUBSCRIPTION_COUNT + 1):
        plan_name, monthly_price = rng.choice(PLANS)
        subscription_rows.append(
            {
                "id": customer_id,
                "customer_id": customer_id,
                "plan_name": plan_name,
                "monthly_price": monthly_price,
                "start_date": date(2024, 1, 1) + timedelta(days=rng.randrange(365)),
                "end_date": None,
                "status": rng.choices(["active", "paused", "cancelled", "expired"], [76, 7, 10, 7])[
                    0
                ],
            }
        )

    return {
        Customer: customer_rows,
        User: user_rows,
        Vehicle: vehicle_rows,
        Driver: driver_rows,
        Trip: trip_rows,
        VehicleLocation: location_rows,
        FuelRecord: fuel_rows,
        MaintenanceRecord: maintenance_rows,
        Invoice: invoice_rows,
        Payment: payment_rows,
        Subscription: subscription_rows,
    }


def seed_database(session: Session, seed: int = SEED_RANDOM) -> bool:
    if session.scalar(select(SeedRun).where(SeedRun.seed_name == SEED_NAME)) is not None:
        return False
    session.rollback()

    rows_by_model = generate_seed_rows(seed)
    with session.begin():
        for model in [
            Customer,
            User,
            Vehicle,
            Driver,
            Trip,
            VehicleLocation,
            FuelRecord,
            MaintenanceRecord,
            Invoice,
            Payment,
            Subscription,
        ]:
            _bulk_insert(session, model, rows_by_model[model])
        session.add(SeedRun(seed_name=SEED_NAME, seeded_at=datetime.now(UTC)))
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            for table_name in [
                "customers",
                "users",
                "vehicles",
                "drivers",
                "trips",
                "vehicle_locations",
                "fuel_records",
                "maintenance_records",
                "invoices",
                "payments",
                "subscriptions",
            ]:
                session.execute(
                    text(
                        f"SELECT setval(pg_get_serial_sequence('{table_name}', 'id'), "
                        f"COALESCE((SELECT MAX(id) FROM {table_name}), 1), true)"
                    )
                )
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the deterministic SaaS fleet dataset")
    parser.add_argument("--seed", type=int, default=SEED_RANDOM)
    args = parser.parse_args()
    get_settings()
    with SessionLocal() as session:
        seeded = seed_database(session, seed=args.seed)
    print("seeded" if seeded else "already seeded")


if __name__ == "__main__":
    main()
