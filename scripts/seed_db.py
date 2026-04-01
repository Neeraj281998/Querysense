import asyncio
import asyncpg
import random
from datetime import datetime, timedelta

import os
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://querysense:querysense@localhost:5432/querysense")
# DATABASE_URL = "postgresql://querysense:querysense@localhost:5432/querysense"


async def seed():
    conn = await asyncpg.connect(DATABASE_URL)
    print("Connected to database.")

    # ── Drop existing tables ─────────────────────────────────────────────────
    await conn.execute("""
        DROP TABLE IF EXISTS order_items CASCADE;
        DROP TABLE IF EXISTS orders CASCADE;
        DROP TABLE IF EXISTS products CASCADE;
        DROP TABLE IF EXISTS categories CASCADE;
        DROP TABLE IF EXISTS users CASCADE;
    """)
    print("Dropped existing tables.")

    # ── Create tables (intentionally missing indexes) ────────────────────────
    await conn.execute("""
        CREATE TABLE users (
            id          SERIAL PRIMARY KEY,
            email       VARCHAR(255) UNIQUE NOT NULL,
            name        VARCHAR(255) NOT NULL,
            created_at  TIMESTAMP DEFAULT NOW()
        );

        CREATE TABLE categories (
            id      SERIAL PRIMARY KEY,
            name    VARCHAR(100) NOT NULL,
            slug    VARCHAR(100) UNIQUE NOT NULL
        );

        CREATE TABLE products (
            id          SERIAL PRIMARY KEY,
            name        VARCHAR(255) NOT NULL,
            price       DECIMAL(10,2) NOT NULL,
            category_id INTEGER REFERENCES categories(id),
            stock       INTEGER DEFAULT 0,
            created_at  TIMESTAMP DEFAULT NOW()
        );

        CREATE TABLE orders (
            id          SERIAL PRIMARY KEY,
            user_id     INTEGER REFERENCES users(id),
            status      VARCHAR(50) DEFAULT 'pending',
            total       DECIMAL(10,2) DEFAULT 0,
            created_at  TIMESTAMP DEFAULT NOW()
        );

        CREATE TABLE order_items (
            id          SERIAL PRIMARY KEY,
            order_id    INTEGER REFERENCES orders(id),
            product_id  INTEGER REFERENCES products(id),
            quantity    INTEGER NOT NULL,
            price       DECIMAL(10,2) NOT NULL
        );
    """)
    print("Created tables.")

    # ── Seed categories (100 rows) ───────────────────────────────────────────
    category_names = [
        "Electronics", "Clothing", "Books", "Home & Garden", "Sports",
        "Toys", "Beauty", "Automotive", "Food", "Office",
    ]
    for i, name in enumerate(category_names):
        await conn.execute(
            "INSERT INTO categories (name, slug) VALUES ($1, $2)",
            name, name.lower().replace(" & ", "-").replace(" ", "-")
        )
    print("Seeded categories.")

    # ── Seed users (10,000 rows) ─────────────────────────────────────────────
    print("Seeding users (10,000)...")
    users_data = [
        (f"user{i}@example.com", f"User Number {i}")
        for i in range(1, 10001)
    ]
    await conn.executemany(
        "INSERT INTO users (email, name) VALUES ($1, $2)",
        users_data
    )
    print("Seeded users.")

    # ── Seed products (1,000 rows) ───────────────────────────────────────────
    print("Seeding products (1,000)...")
    products_data = [
        (
            f"Product {i}",
            round(random.uniform(5.0, 500.0), 2),
            random.randint(1, 10),
            random.randint(0, 1000),
        )
        for i in range(1, 1001)
    ]
    await conn.executemany(
        "INSERT INTO products (name, price, category_id, stock) VALUES ($1, $2, $3, $4)",
        products_data
    )
    print("Seeded products.")

    # ── Seed orders (50,000 rows) ────────────────────────────────────────────
    print("Seeding orders (50,000) — this takes ~10 seconds...")
    base_date = datetime.now() - timedelta(days=365)
    orders_data = [
        (
            random.randint(1, 10000),
            random.choice(["pending", "completed", "cancelled", "shipped"]),
            round(random.uniform(10.0, 1000.0), 2),
            base_date + timedelta(days=random.randint(0, 365)),
        )
        for i in range(1, 50001)
    ]
    await conn.executemany(
        "INSERT INTO orders (user_id, status, total, created_at) VALUES ($1, $2, $3, $4)",
        orders_data
    )
    print("Seeded orders.")

    # ── Seed order_items (200,000 rows in chunks) ────────────────────────────
    print("Seeding order_items (200,000) in chunks...")
    chunk_size = 5000
    total = 200000
    inserted = 0

    for chunk_start in range(0, total, chunk_size):
        chunk = [
            (
                random.randint(1, 50000),
                random.randint(1, 1000),
                random.randint(1, 5),
                round(random.uniform(5.0, 500.0), 2),
            )
            for _ in range(chunk_size)
        ]
        await conn.executemany(
            "INSERT INTO order_items (order_id, product_id, quantity, price) VALUES ($1, $2, $3, $4)",
            chunk
        )
        inserted += chunk_size
        print(f"  {inserted:,} / {total:,} rows inserted...")

    print("Seeded order_items.")

    # ── Final count ──────────────────────────────────────────────────────────
    counts = await conn.fetch("""
        SELECT 'users' as tbl, COUNT(*) FROM users
        UNION ALL
        SELECT 'categories', COUNT(*) FROM categories
        UNION ALL
        SELECT 'products', COUNT(*) FROM products
        UNION ALL
        SELECT 'orders', COUNT(*) FROM orders
        UNION ALL
        SELECT 'order_items', COUNT(*) FROM order_items
    """)

    print("\n── Seed complete ──────────────────────────────")
    for row in counts:
        print(f"  {row['tbl']:20} {row['count']:>10,} rows")
    print("───────────────────────────────────────────────")
    print("\nDatabase is ready. No indexes added intentionally.")
    print("QuerySense will find and fix the slow queries.\n")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(seed())