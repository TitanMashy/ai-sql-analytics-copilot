EXAMPLE_QUERIES = {
    "active_vehicle_count": (
        "SELECT COUNT(*) AS active_vehicle_count FROM vehicles WHERE status = 'active'"
    ),
    "total_revenue": (
        "SELECT SUM(total_amount) AS total_revenue FROM invoices WHERE status <> 'cancelled'"
    ),
    "top_customers_by_revenue": """
        SELECT c.company_name, SUM(i.total_amount) AS total_revenue
        FROM customers c
        JOIN invoices i ON i.customer_id = c.id
        WHERE i.status <> 'cancelled'
        GROUP BY c.id, c.company_name
        ORDER BY total_revenue DESC
        LIMIT 10
    """,
    "monthly_revenue": """
        SELECT DATE_TRUNC('month', invoice_date) AS revenue_month,
               SUM(total_amount) AS total_revenue
        FROM invoices
        WHERE status <> 'cancelled'
        GROUP BY revenue_month
        ORDER BY revenue_month
    """,
    "average_trip_distance": (
        "SELECT AVG(distance_km) AS average_trip_distance_km "
        "FROM trips WHERE trip_status = 'completed'"
    ),
    "highest_idle_vehicles": """
        SELECT v.registration_number, AVG(t.idle_time_minutes) AS average_idle_minutes
        FROM vehicles v
        JOIN trips t ON t.vehicle_id = v.id
        GROUP BY v.id, v.registration_number
        ORDER BY average_idle_minutes DESC
        LIMIT 10
    """,
    "fuel_consumption_by_vehicle": """
         SELECT v.registration_number, SUM(f.liters) AS total_liters,
             SUM(f.total_cost) AS total_fuel_cost
        FROM vehicles v
        JOIN fuel_records f ON f.vehicle_id = v.id
        GROUP BY v.id, v.registration_number
        ORDER BY total_liters DESC
        LIMIT 10
    """,
    "maintenance_cost_by_customer": """
        SELECT c.company_name, SUM(m.cost) AS maintenance_cost
        FROM customers c
        JOIN maintenance_records m ON m.customer_id = c.id
        GROUP BY c.id, c.company_name
        ORDER BY maintenance_cost DESC
    """,
}
