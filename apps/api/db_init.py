"""Initialize the database tables."""

from apps.api.models.database import init_db

if __name__ == "__main__":
    print("Initializing database...")
    init_db()
    print("Database initialized.")
else:
    init_db()
