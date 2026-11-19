# SRI VISHNU MOBILES – Billing Software

A Flask + SQLite billing and inventory website with a dark dashboard inspired by the supplied reference screenshot.

## Features
- Dashboard sales summary and recent bills
- Product catalogue with customer, reseller and wholesale prices
- Categories and brands
- Customer and supplier records
- New bill with multiple items, discount, payment type and automatic stock deduction
- Printable invoice
- Bill search/history
- Manual stock IN / OUT with movement history
- Purchase record log

## Windows setup
1. Extract the ZIP file.
2. Open the extracted `Sri_Vishnu_Mobiles_Billing` folder.
3. Double-click `run_windows.bat`.
4. Wait for Flask to start. Open `http://127.0.0.1:5000` in Chrome.

Alternative PowerShell commands:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

Then open `http://127.0.0.1:5000`.

## Database
The SQLite database `billing.db` is created automatically the first time the app starts. Back up this file regularly. Do not delete it if you want to keep your bills and products.

## Shop details
The shop name and phone number are currently set in `app.py` / `base.html` context:
- SRI VISHNU MOBILES
- 8270238293

Change the address or other invoice details in `templates/invoice.html` as required.

## Important
This starter project is intended to run on a trusted local shop computer/network. Before exposing it to the public internet or hosting it online, configure a strong `SECRET_KEY`, production deployment, authentication/user roles, HTTPS, and scheduled database backups. The starter currently has no login screen.


## Login and user roles
This version includes login protection, Admin and Staff roles, password hashing, CSRF protection, account activation/deactivation, and password changes.

### Required Render environment variables
Set these in Render → Web Service → Environment before first deployment:
- `SECRET_KEY`: a long random secret (32+ random characters).
- `ADMIN_USERNAME`: first administrator username (for example `owner`).
- `ADMIN_PASSWORD`: unique password of at least 12 characters.

The first admin account is created automatically on first startup. Never commit secrets to GitHub. After login, create staff accounts from **User Accounts**.

Admin can manage products, categories, brands, stock, purchases, suppliers and users. Staff can use dashboard, bills, invoices and customer records. All pages require login.

Render Start Command: `gunicorn app:app`

**Database warning:** SQLite currently lives beside `app.py`. Render's ordinary filesystem is ephemeral. Attach a persistent disk and configure the database path to that disk, or migrate to a managed database, before entering real business records.
