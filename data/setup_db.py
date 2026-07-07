from __future__ import annotations

import argparse
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

import duckdb
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "ecommerce.db"


def build_customers() -> pd.DataFrame:
    rows = [
        (1, "Ava", "Patel", "ava.patel@example.com", "US", date(2024, 1, 12), True),
        (2, "Noah", "Kim", "noah.kim@example.com", "US", date(2024, 2, 3), True),
        (3, "Mia", "Garcia", "mia.garcia@example.com", "CA", date(2024, 2, 15), True),
        (4, "Liam", "Smith", "liam.smith@example.com", "UK", date(2024, 3, 4), True),
        (5, "Sophia", "Jones", "sophia.jones@example.com", "AU", date(2024, 3, 18), False),
        (6, "Ethan", "Brown", "ethan.brown@example.com", "US", date(2024, 4, 1), True),
        (7, "Olivia", "Davis", "olivia.davis@example.com", "DE", date(2024, 4, 22), True),
        (8, "Lucas", "Wilson", "lucas.wilson@example.com", "FR", date(2024, 5, 9), True),
        (9, "Isla", "Moore", "isla.moore@example.com", "US", date(2024, 5, 21), True),
        (10, "Jackson", "Taylor", "jackson.taylor@example.com", "CA", date(2024, 6, 8), True),
        (11, "Zoe", "Anderson", "zoe.anderson@example.com", "NZ", date(2024, 6, 19), True),
        (12, "Henry", "Thomas", "henry.thomas@example.com", "US", date(2024, 7, 2), True),
    ]
    return pd.DataFrame(
        rows,
        columns=[
            "customer_id",
            "first_name",
            "last_name",
            "email",
            "country",
            "created_at",
            "is_active",
        ],
    )


def build_products() -> pd.DataFrame:
    rows = [
        (1, "Wireless Mouse", "Accessories", 29.99, 11.20, 48, True),
        (2, "Mechanical Keyboard", "Accessories", 89.99, 41.00, 18, True),
        (3, "USB-C Hub", "Accessories", 49.99, 18.75, 35, True),
        (4, "Noise-Canceling Headphones", "Audio", 199.99, 92.00, 9, True),
        (5, "4K Monitor", "Displays", 329.99, 210.00, 7, True),
        (6, "Laptop Stand", "Accessories", 39.99, 14.50, 52, True),
        (7, "Desk Lamp", "Office", 24.99, 9.25, 61, True),
        (8, "Webcam", "Accessories", 74.99, 31.00, 4, True),
        (9, "Ergonomic Chair", "Furniture", 249.99, 132.00, 5, True),
        (10, "Portable SSD", "Storage", 119.99, 68.00, 13, False),
    ]
    return pd.DataFrame(
        rows,
        columns=[
            "product_id",
            "product_name",
            "category",
            "unit_price",
            "unit_cost",
            "stock_qty",
            "is_active",
        ],
    )


def build_orders() -> pd.DataFrame:
    rows = [
        (1, 1, datetime(2024, 7, 3, 9, 15), "completed", "card", "US"),
        (2, 2, datetime(2024, 7, 3, 12, 40), "completed", "paypal", "US"),
        (3, 3, datetime(2024, 7, 4, 8, 5), "completed", "card", "CA"),
        (4, 4, datetime(2024, 7, 4, 14, 20), "pending", "card", "UK"),
        (5, 6, datetime(2024, 7, 5, 10, 0), "completed", "apple_pay", "US"),
        (6, 7, datetime(2024, 7, 5, 16, 35), "refunded", "card", "DE"),
        (7, 8, datetime(2024, 7, 6, 11, 10), "completed", "paypal", "FR"),
        (8, 9, datetime(2024, 7, 6, 15, 55), "completed", "card", "US"),
        (9, 10, datetime(2024, 7, 7, 9, 30), "completed", "card", "CA"),
        (10, 11, datetime(2024, 7, 7, 13, 45), "canceled", "card", "NZ"),
        (11, 12, datetime(2024, 7, 8, 17, 5), "completed", "paypal", "US"),
        (12, 1, datetime(2024, 7, 9, 10, 25), "completed", "card", "US"),
    ]
    return pd.DataFrame(
        rows,
        columns=[
            "order_id",
            "customer_id",
            "order_date",
            "status",
            "payment_method",
            "shipping_country",
        ],
    )


def build_order_items() -> pd.DataFrame:
    rows = [
        (1, 1, 1, 2, 27.99, 0.0),
        (2, 1, 6, 1, 39.99, 0.0),
        (3, 2, 2, 1, 89.99, 0.10),
        (4, 2, 3, 1, 47.99, 0.0),
        (5, 3, 5, 1, 329.99, 0.0),
        (6, 3, 8, 2, 71.99, 0.05),
        (7, 5, 4, 1, 189.99, 0.0),
        (8, 5, 7, 2, 22.49, 0.0),
        (9, 6, 9, 1, 249.99, 0.15),
        (10, 7, 1, 1, 29.99, 0.0),
        (11, 7, 3, 2, 49.99, 0.0),
        (12, 8, 10, 1, 119.99, 0.0),
        (13, 8, 6, 1, 39.99, 0.0),
        (14, 9, 2, 1, 89.99, 0.0),
        (15, 9, 4, 1, 199.99, 0.0),
        (16, 11, 7, 3, 23.99, 0.1),
        (17, 11, 1, 1, 28.99, 0.0),
        (18, 12, 5, 1, 319.99, 0.03),
    ]
    return pd.DataFrame(
        rows,
        columns=[
            "order_item_id",
            "order_id",
            "product_id",
            "quantity",
            "unit_price",
            "discount_pct",
        ],
    )


def create_schema(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE TABLE customers (
            customer_id INTEGER PRIMARY KEY,
            first_name VARCHAR NOT NULL,
            last_name VARCHAR NOT NULL,
            email VARCHAR NOT NULL UNIQUE,
            country VARCHAR NOT NULL,
            created_at DATE NOT NULL,
            is_active BOOLEAN NOT NULL
        );

        CREATE TABLE products (
            product_id INTEGER PRIMARY KEY,
            product_name VARCHAR NOT NULL,
            category VARCHAR NOT NULL,
            unit_price DECIMAL(10, 2) NOT NULL,
            unit_cost DECIMAL(10, 2) NOT NULL,
            stock_qty INTEGER NOT NULL,
            is_active BOOLEAN NOT NULL
        );

        CREATE TABLE orders (
            order_id INTEGER PRIMARY KEY,
            customer_id INTEGER NOT NULL,
            order_date TIMESTAMP NOT NULL,
            status VARCHAR NOT NULL,
            payment_method VARCHAR NOT NULL,
            shipping_country VARCHAR NOT NULL
        );

        CREATE TABLE order_items (
            order_item_id INTEGER PRIMARY KEY,
            order_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            unit_price DECIMAL(10, 2) NOT NULL,
            discount_pct DECIMAL(5, 2) NOT NULL
        );
        """
    )


def load_table(connection: duckdb.DuckDBPyConnection, table_name: str, frame: pd.DataFrame) -> None:
    connection.register(f"{table_name}_df", frame)
    connection.execute(f"INSERT INTO {table_name} SELECT * FROM {table_name}_df")
    connection.unregister(f"{table_name}_df")


def validate_seed_data(connection: duckdb.DuckDBPyConnection) -> None:
    checks: Iterable[tuple[str, str]] = [
        ("customers", "SELECT COUNT(*) FROM customers"),
        ("products", "SELECT COUNT(*) FROM products"),
        ("orders", "SELECT COUNT(*) FROM orders"),
        ("order_items", "SELECT COUNT(*) FROM order_items"),
        (
            "join coverage",
            """
            SELECT COUNT(*)
            FROM orders o
            JOIN customers c ON c.customer_id = o.customer_id
            JOIN order_items oi ON oi.order_id = o.order_id
            JOIN products p ON p.product_id = oi.product_id
            """,
        ),
        (
            "low stock products",
            "SELECT COUNT(*) FROM products WHERE stock_qty <= 5",
        ),
    ]
    for label, query in checks:
        result = connection.execute(query).fetchone()
        print(f"{label}: {result[0]}")


def seed_database(db_path: Path) -> None:
    if db_path.exists():
        db_path.unlink()

    connection = duckdb.connect(str(db_path))
    try:
        create_schema(connection)
        load_table(connection, "customers", build_customers())
        load_table(connection, "products", build_products())
        load_table(connection, "orders", build_orders())
        load_table(connection, "order_items", build_order_items())

        connection.execute(
            """
            CREATE VIEW order_facts AS
            SELECT
                o.order_id,
                o.order_date,
                o.status,
                o.payment_method,
                o.shipping_country,
                c.customer_id,
                c.first_name,
                c.last_name,
                c.country AS customer_country,
                p.product_id,
                p.product_name,
                p.category,
                oi.quantity,
                oi.unit_price,
                oi.discount_pct,
                ROUND(oi.quantity * oi.unit_price * (1 - oi.discount_pct), 2) AS line_total
            FROM orders o
            JOIN customers c ON c.customer_id = o.customer_id
            JOIN order_items oi ON oi.order_id = o.order_id
            JOIN products p ON p.product_id = oi.product_id;
            """
        )

        validate_seed_data(connection)
    finally:
        connection.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create and seed the ecommerce DuckDB database.")
    parser.add_argument(
        "--db-path",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"Path to the DuckDB file (default: {DEFAULT_DB_PATH})",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.db_path.parent.mkdir(parents=True, exist_ok=True)
    seed_database(args.db_path)
    print(f"Seeded DuckDB database at {args.db_path}")


if __name__ == "__main__":
    main()