# Invoice Manager

A Flask-based application for managing invoices, products and vendors. The project comes with a comprehensive test suite using `pytest`.

## Installation

1. **Clone the repository**
   ```bash
   git clone <repo-url>
   cd InvoiceManager
   ```
2. **Create a virtual environment** (recommended)
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```
3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

## Required Environment Variables

The application requires several variables to be present in your environment:

- `SECRET_KEY` – Flask secret key used for sessions.
- `ADMIN_EMAIL` – email address for the initial administrator account.
- `ADMIN_PASS` – password for the administrator account.
- `GST` – GST number to display on invoices (optional).

These can be placed in a `.env` file or exported in your shell before starting the app.

## Running the Application

After installing the dependencies and setting the environment variables, start the development server with:

```bash
python run.py
```

The application uses a local SQLite database located at `inventory.db` and creates `uploads` and `backups` directories automatically on startup.

## Features
- Manage items, products, and invoices.
- User authentication and admin features.
- Reporting and backups.

## Test Defaults

When running `pytest`, the fixtures in `tests/conftest.py` set up several default values so the application can start without manual configuration:

- `SECRET_KEY` defaults to `"testsecret"`
- `ADMIN_EMAIL` defaults to `"admin@example.com"`
- `ADMIN_PASS` defaults to `"adminpass"`
- A temporary SQLite database `inventory.db` is created in a temporary directory
- Two GL codes (`4000` and `5000`) are populated if none exist

These defaults are provided for convenience during testing, but you can override any of the environment variables by exporting your own values before running the tests.


## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
