from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'inactive', 'suspended')", name="ck_customers_status"
        ),
        Index("ix_customers_status", "status"),
        Index("ix_customers_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    company_name: Mapped[str] = mapped_column(String(200), nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(100), nullable=False)
    country: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)

    users: Mapped[list["User"]] = relationship(back_populates="customer")
    vehicles: Mapped[list["Vehicle"]] = relationship(back_populates="customer")
    drivers: Mapped[list["Driver"]] = relationship(back_populates="customer")
    trips: Mapped[list["Trip"]] = relationship(back_populates="customer")
    fuel_records: Mapped[list["FuelRecord"]] = relationship(back_populates="customer")
    maintenance_records: Mapped[list["MaintenanceRecord"]] = relationship(back_populates="customer")
    invoices: Mapped[list["Invoice"]] = relationship(back_populates="customer")
    payments: Mapped[list["Payment"]] = relationship(back_populates="customer")
    subscriptions: Mapped[list["Subscription"]] = relationship(back_populates="customer")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'inactive', 'invited')", name="ck_users_status"),
        Index("ix_users_customer_id", "customer_id"),
        Index("ix_users_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)

    customer: Mapped[Customer] = relationship(back_populates="users")


class Vehicle(Base):
    __tablename__ = "vehicles"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'inactive', 'maintenance', 'retired')", name="ck_vehicles_status"
        ),
        CheckConstraint(
            "fuel_type IN ('diesel', 'petrol', 'cng', 'electric')", name="ck_vehicles_fuel_type"
        ),
        Index("ix_vehicles_customer_id", "customer_id"),
        Index("ix_vehicles_status", "status"),
        Index("ix_vehicles_customer_status", "customer_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    registration_number: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    vehicle_type: Mapped[str] = mapped_column(String(50), nullable=False)
    manufacturer: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    fuel_type: Mapped[str] = mapped_column(String(20), nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    purchase_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    customer: Mapped[Customer] = relationship(back_populates="vehicles")
    trips: Mapped[list["Trip"]] = relationship(back_populates="vehicle")
    locations: Mapped[list["VehicleLocation"]] = relationship(back_populates="vehicle")
    fuel_records: Mapped[list["FuelRecord"]] = relationship(back_populates="vehicle")
    maintenance_records: Mapped[list["MaintenanceRecord"]] = relationship(back_populates="vehicle")


class Driver(Base):
    __tablename__ = "drivers"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'inactive', 'suspended')", name="ck_drivers_status"),
        Index("ix_drivers_customer_id", "customer_id"),
        Index("ix_drivers_status", "status"),
        Index("ix_drivers_license_expiry", "license_expiry"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    phone: Mapped[str] = mapped_column(String(30), nullable=False)
    license_number: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    license_expiry: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    customer: Mapped[Customer] = relationship(back_populates="drivers")
    trips: Mapped[list["Trip"]] = relationship(back_populates="driver")


class Trip(Base):
    __tablename__ = "trips"
    __table_args__ = (
        CheckConstraint("distance_km >= 0", name="ck_trips_distance_nonnegative"),
        CheckConstraint("fuel_consumed_liters >= 0", name="ck_trips_fuel_nonnegative"),
        CheckConstraint("idle_time_minutes >= 0", name="ck_trips_idle_nonnegative"),
        CheckConstraint(
            "trip_status IN ('completed', 'cancelled', 'in_progress')", name="ck_trips_status"
        ),
        CheckConstraint("end_time IS NULL OR end_time >= start_time", name="ck_trips_time_order"),
        Index("ix_trips_customer_id", "customer_id"),
        Index("ix_trips_vehicle_id", "vehicle_id"),
        Index("ix_trips_driver_id", "driver_id"),
        Index("ix_trips_start_time", "start_time"),
        Index("ix_trips_customer_start_time", "customer_id", "start_time"),
        Index("ix_trips_status", "trip_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False
    )
    driver_id: Mapped[int] = mapped_column(
        ForeignKey("drivers.id", ondelete="CASCADE"), nullable=False
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    start_location: Mapped[str] = mapped_column(String(200), nullable=False)
    end_location: Mapped[str] = mapped_column(String(200), nullable=False)
    distance_km: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    fuel_consumed_liters: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    idle_time_minutes: Mapped[int] = mapped_column(nullable=False)
    trip_status: Mapped[str] = mapped_column(String(20), nullable=False)

    vehicle: Mapped[Vehicle] = relationship(back_populates="trips")
    driver: Mapped[Driver] = relationship(back_populates="trips")
    customer: Mapped[Customer] = relationship(back_populates="trips")


class VehicleLocation(Base):
    __tablename__ = "vehicle_locations"
    __table_args__ = (
        CheckConstraint("latitude BETWEEN -90 AND 90", name="ck_locations_latitude"),
        CheckConstraint("longitude BETWEEN -180 AND 180", name="ck_locations_longitude"),
        CheckConstraint("speed_kmph >= 0", name="ck_locations_speed_nonnegative"),
        Index("ix_vehicle_locations_vehicle_id", "vehicle_id"),
        Index("ix_vehicle_locations_recorded_at", "recorded_at"),
        Index("ix_vehicle_locations_vehicle_recorded_at", "vehicle_id", "recorded_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False
    )
    latitude: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)
    longitude: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)
    speed_kmph: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    vehicle: Mapped[Vehicle] = relationship(back_populates="locations")


class FuelRecord(Base):
    __tablename__ = "fuel_records"
    __table_args__ = (
        CheckConstraint("liters > 0", name="ck_fuel_liters_positive"),
        CheckConstraint("price_per_liter >= 0", name="ck_fuel_price_nonnegative"),
        CheckConstraint("total_cost >= 0", name="ck_fuel_total_nonnegative"),
        Index("ix_fuel_records_vehicle_id", "vehicle_id"),
        Index("ix_fuel_records_customer_id", "customer_id"),
        Index("ix_fuel_records_fuel_date", "fuel_date"),
        Index("ix_fuel_records_customer_date", "customer_id", "fuel_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    fuel_date: Mapped[date] = mapped_column(Date, nullable=False)
    liters: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    price_per_liter: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    total_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    vehicle: Mapped[Vehicle] = relationship(back_populates="fuel_records")
    customer: Mapped[Customer] = relationship(back_populates="fuel_records")


class MaintenanceRecord(Base):
    __tablename__ = "maintenance_records"
    __table_args__ = (
        CheckConstraint("cost >= 0", name="ck_maintenance_cost_nonnegative"),
        CheckConstraint(
            "status IN ('scheduled', 'completed', 'cancelled')", name="ck_maintenance_status"
        ),
        Index("ix_maintenance_records_vehicle_id", "vehicle_id"),
        Index("ix_maintenance_records_customer_id", "customer_id"),
        Index("ix_maintenance_records_date", "maintenance_date"),
        Index("ix_maintenance_records_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    maintenance_date: Mapped[date] = mapped_column(Date, nullable=False)
    maintenance_type: Mapped[str] = mapped_column(String(100), nullable=False)
    cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)

    vehicle: Mapped[Vehicle] = relationship(back_populates="maintenance_records")
    customer: Mapped[Customer] = relationship(back_populates="maintenance_records")


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_invoices_amount_nonnegative"),
        CheckConstraint("tax_amount >= 0", name="ck_invoices_tax_nonnegative"),
        CheckConstraint("total_amount >= amount", name="ck_invoices_total_covers_amount"),
        CheckConstraint(
            "status IN ('paid', 'pending', 'overdue', 'cancelled')", name="ck_invoices_status"
        ),
        Index("ix_invoices_customer_id", "customer_id"),
        Index("ix_invoices_invoice_date", "invoice_date"),
        Index("ix_invoices_status", "status"),
        Index("ix_invoices_customer_date", "customer_id", "invoice_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)

    customer: Mapped[Customer] = relationship(back_populates="invoices")
    payments: Mapped[list["Payment"]] = relationship(back_populates="invoice")


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
        CheckConstraint(
            "payment_method IN ('bank_transfer', 'credit_card', 'direct_debit', 'cash')",
            name="ck_payments_method",
        ),
        CheckConstraint("status IN ('paid', 'pending', 'failed')", name="ck_payments_status"),
        Index("ix_payments_invoice_id", "invoice_id"),
        Index("ix_payments_customer_id", "customer_id"),
        Index("ix_payments_payment_date", "payment_date"),
        Index("ix_payments_status", "status"),
        Index("ix_payments_customer_date", "customer_id", "payment_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    payment_method: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)

    invoice: Mapped[Invoice] = relationship(back_populates="payments")
    customer: Mapped[Customer] = relationship(back_populates="payments")


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        CheckConstraint("monthly_price >= 0", name="ck_subscriptions_price_nonnegative"),
        CheckConstraint(
            "status IN ('active', 'paused', 'cancelled', 'expired')", name="ck_subscriptions_status"
        ),
        CheckConstraint(
            "end_date IS NULL OR end_date >= start_date", name="ck_subscriptions_date_order"
        ),
        Index("ix_subscriptions_customer_id", "customer_id"),
        Index("ix_subscriptions_status", "status"),
        Index("ix_subscriptions_start_date", "start_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    plan_name: Mapped[str] = mapped_column(String(50), nullable=False)
    monthly_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), nullable=False)

    customer: Mapped[Customer] = relationship(back_populates="subscriptions")


class SeedRun(Base):
    __tablename__ = "seed_runs"

    seed_name: Mapped[str] = mapped_column(String(100), primary_key=True)
    seeded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
