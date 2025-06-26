"""Initialize InvoiceManager database and admin user."""

from app import create_app

if __name__ == "__main__":
    create_app([])
    print("Initialization complete.")
