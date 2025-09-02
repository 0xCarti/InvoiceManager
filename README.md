# Invoice Manager

A Flask-based application for managing invoices, products and vendors. The project comes with a comprehensive test suite using `pytest`.

## Installation

You can perform the steps below manually or run one of the setup scripts provided in the repository. `setup.sh` works on Linux/macOS and `setup.ps1` works on Windows. Each script optionally accepts a repository URL and target directory, clones the project, installs dependencies and prepares a `.env` file.


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
- `PORT` – port the web server listens on (optional, defaults to 5000).
- `SMTP_HOST` – hostname of your SMTP server.
- `SMTP_PORT` – port for the SMTP server (defaults to 25).
- `SMTP_USERNAME` – username for SMTP authentication.
- `SMTP_PASSWORD` – password for SMTP authentication.
- `SMTP_SENDER` – email address used as the sender.
- `SMTP_USE_TLS` – set to `true` to enable TLS.

These SMTP variables enable password reset emails. Configure them in your `.env` file if you want users to reset forgotten passwords.

The GST number can now be set from the application control panel after installation.

These can be placed in a `.env` file or exported in your shell before starting the app.

## Running the Application

After installing the dependencies and setting the environment variables, start the development server with:

```bash
python run.py
```

Set `PORT` in your environment to change the port (default `5000`).

The application uses a local SQLite database located at `inventory.db` and creates `uploads` and `backups` directories automatically on startup.

## Docker Setup

The project includes a `Dockerfile` and a `docker-compose.yml` to make running
the application in a container straightforward on Linux and Windows. Create a
`.env` file containing the environment variables described above. You can also
specify the port the app will use by adding a `PORT` variable to `.env` (or by
exporting it in your shell) before starting the service:

```bash
docker compose up --build
```

The repository includes an `import_files` directory containing example CSV files
that can be used as templates for data imports.

The web interface will be available at `http://localhost:$PORT` (default `5000`). Uploaded files,
import templates, backups and the SQLite database are stored on the host so data
persists across container restarts.

## Running Tests

The project includes a suite of `pytest` tests. Execute them with:

```bash
pytest
```

The tests automatically set the necessary environment variables, so no additional setup is required.

## Features
- Manage items, products, and invoices.
- User authentication and admin features.
- Reporting and backups.

## Data Import

Administrators can quickly seed the database by uploading CSV files from the
**Control Panel → Data Imports** page. Example templates are available in the
`import_files` directory at the project root if you want to use them as a
starting point:

- `example_gl_codes.csv`
- `example_locations.csv` – includes a `products` column listing product names
  separated by semicolons. The import will fail if any product name cannot be
  matched exactly.
- `example_products.csv` – may include a `recipe` column listing item names with
  quantities and units separated by semicolons (e.g. `Buns:2:each;Patties:1:each`). The import will
  fail if any item name or unit cannot be matched exactly.
- `example_items.csv` – includes optional `cost`, `base_unit`, `gl_code` and `units`
  columns. The `units` column lists unit name and factor pairs separated by
  semicolons (e.g. `each:1;case:12`). The first unit becomes the receiving and
  transfer default. The `gl_code` column should reference an existing GL code.
- `example_customers.csv`
- `example_vendors.csv`
- `example_users.csv`

Visit **Control Panel → Data Imports** in the web interface, choose the
appropriate CSV file, and click the corresponding button to import each
dataset.

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

