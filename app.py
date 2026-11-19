from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, abort, session, g
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from flask_wtf.csrf import CSRFProtect
import sqlite3, os
from datetime import datetime, date
from decimal import Decimal, InvalidOperation

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "billing.db")
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY")
if not app.secret_key:
    raise RuntimeError("Set SECRET_KEY environment variable before starting the application.")
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "1" if os.environ.get("RENDER") else "0") == "1",
    PERMANENT_SESSION_LIFETIME=__import__("datetime").timedelta(hours=8))
csrf = CSRFProtect(app)

@app.before_request
def require_login():
    if request.endpoint not in ("login", "static") and not session.get("user_id"):
        return redirect(url_for("login", next=request.path))
    if session.get("user_id"):
        g.current_user = {"id":session.get("user_id"), "username":session.get("username"), "role":session.get("role")}
    else:
        g.current_user = None

def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        if session.get("role") != "admin":
            abort(403)
        return view(*args, **kwargs)
    return wrapped

_db_initialized = False
@app.before_request
def ensure_database_initialized():
    global _db_initialized
    if not _db_initialized:
        init_db()
        _db_initialized = True

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','staff')),
            active INTEGER NOT NULL DEFAULT 1, created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE
        );
        CREATE TABLE IF NOT EXISTS brands (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE
        );
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, phone TEXT,
            address TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS suppliers (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, phone TEXT, address TEXT
        );
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, sku TEXT UNIQUE,
            category_id INTEGER, brand_id INTEGER, price REAL NOT NULL DEFAULT 0,
            reseller_price REAL NOT NULL DEFAULT 0, wholesale_price REAL NOT NULL DEFAULT 0,
            stock INTEGER NOT NULL DEFAULT 0, low_stock INTEGER NOT NULL DEFAULT 5,
            imei TEXT, serial_no TEXT,
            FOREIGN KEY(category_id) REFERENCES categories(id) ON DELETE SET NULL,
            FOREIGN KEY(brand_id) REFERENCES brands(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS bills (
            id INTEGER PRIMARY KEY AUTOINCREMENT, bill_no TEXT UNIQUE,
            customer_id INTEGER, customer_name TEXT, phone TEXT,
            subtotal REAL NOT NULL, discount REAL NOT NULL DEFAULT 0,
            total REAL NOT NULL, payment TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS bill_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT, bill_id INTEGER NOT NULL,
            product_id INTEGER, product_name TEXT NOT NULL, qty INTEGER NOT NULL,
            price REAL NOT NULL, line_total REAL NOT NULL,
            FOREIGN KEY(bill_id) REFERENCES bills(id) ON DELETE CASCADE,
            FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS stock_movements (
            id INTEGER PRIMARY KEY AUTOINCREMENT, product_id INTEGER,
            movement TEXT NOT NULL, qty INTEGER NOT NULL, note TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT, supplier TEXT, reference TEXT,
            total REAL DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """)
        if not con.execute("SELECT 1 FROM users WHERE role='admin' LIMIT 1").fetchone():
            admin_username=os.environ.get("ADMIN_USERNAME", "admin").strip()
            admin_password=os.environ.get("ADMIN_PASSWORD", "")
            if len(admin_password) < 12:
                raise RuntimeError("Set ADMIN_PASSWORD to at least 12 characters in Render Environment before first startup.")
            con.execute("INSERT INTO users(username,password_hash,role) VALUES(?,?, 'admin')",
                        (admin_username, generate_password_hash(admin_password)))
        if con.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == 0:
            con.executemany("INSERT INTO categories(name) VALUES (?)",
                            [("Mobiles",), ("Accessories",), ("Spare Parts",), ("Services",)])
        if con.execute("SELECT COUNT(*) FROM brands").fetchone()[0] == 0:
            con.executemany("INSERT INTO brands(name) VALUES (?)",
                            [("Samsung",), ("Apple",), ("Xiaomi",), ("Vivo",), ("Oppo",)])
        if con.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
            con.execute("""INSERT INTO products(name,sku,category_id,brand_id,price,reseller_price,wholesale_price,stock,low_stock)
                           VALUES ('USB Type-C Cable','ACC-001',2,1,150,125,110,25,5)""")

@app.context_processor
def inject_globals():
    return {"shop_name": "SRI VISHNU MOBILES", "shop_phone": "8270238293", "current_user": getattr(g, "current_user", None)}

@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"): return redirect(url_for("dashboard"))
    if request.method == "POST":
        username=request.form.get("username", "").strip(); password=request.form.get("password", "")
        with db() as con: user=con.execute("SELECT * FROM users WHERE username=? AND active=1", (username,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear(); session.permanent=True
            session.update(user_id=user["id"], username=user["username"], role=user["role"])
            target=request.form.get("next") or url_for("dashboard")
            if not target.startswith("/") or target.startswith("//"): target=url_for("dashboard")
            return redirect(target)
        flash("Incorrect username or password, or account inactive.", "error")
    return render_template("login.html")

@app.post("/logout")
def logout():
    session.clear(); return redirect(url_for("login"))

@app.route("/users", methods=["GET", "POST"])
@admin_required
def users():
    if request.method == "POST":
        username=request.form.get("username", "").strip(); password=request.form.get("password", ""); role=request.form.get("role", "staff")
        if not username or len(password)<12 or role not in ("admin", "staff"):
            flash("Enter username, valid role and a password of at least 12 characters.", "error")
        else:
            try:
                with db() as con: con.execute("INSERT INTO users(username,password_hash,role) VALUES(?,?,?)", (username,generate_password_hash(password),role))
                flash("User account created.", "success")
            except sqlite3.IntegrityError: flash("Username already exists.", "error")
        return redirect(url_for("users"))
    with db() as con: rows=con.execute("SELECT id,username,role,active,created_at FROM users ORDER BY id").fetchall()
    return render_template("users.html", users=rows)

@app.post("/users/<int:user_id>/toggle")
@admin_required
def toggle_user(user_id):
    if user_id == session.get("user_id"): flash("You cannot deactivate your own account.", "error")
    else:
        with db() as con: con.execute("UPDATE users SET active=CASE active WHEN 1 THEN 0 ELSE 1 END WHERE id=?", (user_id,))
        flash("Account status updated.", "success")
    return redirect(url_for("users"))

@app.route("/change-password", methods=["GET", "POST"])
def change_password():
    if request.method == "POST":
        old=request.form.get("old_password", ""); new=request.form.get("new_password", "")
        if len(new)<12: flash("New password must contain at least 12 characters.", "error")
        else:
            with db() as con: user=con.execute("SELECT password_hash FROM users WHERE id=?", (session["user_id"],)).fetchone()
            if user and check_password_hash(user["password_hash"], old):
                with db() as con: con.execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(new),session["user_id"]))
                session.clear(); flash("Password changed. Please log in again.", "success"); return redirect(url_for("login"))
            flash("Current password is incorrect.", "error")
    return render_template("change_password.html")

@app.route("/")
def dashboard():
    with db() as con:
        today = date.today().isoformat()
        today_sales = con.execute("SELECT COALESCE(SUM(total),0) FROM bills WHERE date(created_at)=?", (today,)).fetchone()[0]
        bills_today = con.execute("SELECT COUNT(*) FROM bills WHERE date(created_at)=?", (today,)).fetchone()[0]
        month_sales = con.execute("SELECT COALESCE(SUM(total),0) FROM bills WHERE strftime('%Y-%m',created_at)=?", (date.today().strftime("%Y-%m"),)).fetchone()[0]
        customers = con.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
        products = con.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        low_stock = con.execute("SELECT COUNT(*) FROM products WHERE stock <= low_stock").fetchone()[0]
        recent = con.execute("""SELECT b.*, COALESCE(b.customer_name,'Walk-in Customer') AS cname
                                FROM bills b ORDER BY b.id DESC LIMIT 8""").fetchall()
    return render_template("dashboard.html", today_sales=today_sales, bills_today=bills_today,
        month_sales=month_sales, customers=customers, products=products, low_stock=low_stock, recent=recent)

@app.route("/products", methods=["GET","POST"])
@admin_required
def products():
    with db() as con:
        if request.method == "POST":
            try:
                con.execute("""INSERT INTO products(name,sku,category_id,brand_id,price,reseller_price,wholesale_price,stock,low_stock,imei,serial_no)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (request.form["name"].strip(), request.form.get("sku") or None,
                     request.form.get("category_id") or None, request.form.get("brand_id") or None,
                     float(request.form.get("price") or 0), float(request.form.get("reseller_price") or 0),
                     float(request.form.get("wholesale_price") or 0), int(request.form.get("stock") or 0),
                     int(request.form.get("low_stock") or 5), request.form.get("imei"), request.form.get("serial_no")))
                flash("Product added successfully.", "success")
            except sqlite3.IntegrityError:
                flash("SKU already exists. Please use a different SKU.", "error")
            except (ValueError, KeyError):
                flash("Please check the product details.", "error")
            return redirect(url_for("products"))
        rows = con.execute("""SELECT p.*, c.name category, b.name brand FROM products p
                              LEFT JOIN categories c ON c.id=p.category_id LEFT JOIN brands b ON b.id=p.brand_id
                              ORDER BY p.id DESC""").fetchall()
        cats = con.execute("SELECT * FROM categories ORDER BY name").fetchall()
        brands = con.execute("SELECT * FROM brands ORDER BY name").fetchall()
    return render_template("products.html", products=rows, categories=cats, brands=brands)

@app.post("/products/<int:pid>/delete")
@admin_required
def delete_product(pid):
    with db() as con:
        con.execute("DELETE FROM products WHERE id=?", (pid,))
    flash("Product deleted.", "success")
    return redirect(url_for("products"))

@app.route("/catalogue/<kind>", methods=["GET","POST"])
@admin_required
def catalogue(kind):
    if kind not in ("categories","brands"):
        abort(404)
    table = kind
    title = "Categories" if kind == "categories" else "Brands"
    with db() as con:
        if request.method == "POST":
            name = request.form.get("name","").strip()
            if name:
                try:
                    con.execute(f"INSERT INTO {table}(name) VALUES (?)", (name,))
                    flash(f"{title[:-1]} added.", "success")
                except sqlite3.IntegrityError:
                    flash("That name already exists.", "error")
            return redirect(url_for("catalogue", kind=kind))
        rows = con.execute(f"SELECT * FROM {table} ORDER BY name").fetchall()
    return render_template("catalogue.html", rows=rows, title=title, kind=kind)

@app.post("/catalogue/<kind>/<int:item_id>/delete")
@admin_required
def delete_catalogue(kind, item_id):
    if kind not in ("categories","brands"): abort(404)
    with db() as con:
        con.execute(f"DELETE FROM {kind} WHERE id=?", (item_id,))
    flash("Entry deleted.", "success")
    return redirect(url_for("catalogue", kind=kind))

@app.route("/customers", methods=["GET","POST"])
def customers():
    with db() as con:
        if request.method == "POST":
            name = request.form.get("name","").strip()
            if name:
                con.execute("INSERT INTO customers(name,phone,address) VALUES(?,?,?)",
                            (name, request.form.get("phone"), request.form.get("address")))
                flash("Customer saved.", "success")
            return redirect(url_for("customers"))
        rows = con.execute("SELECT * FROM customers ORDER BY id DESC").fetchall()
    return render_template("customers.html", customers=rows)

@app.route("/suppliers", methods=["GET","POST"])
@admin_required
def suppliers():
    with db() as con:
        if request.method == "POST":
            if request.form.get("name","").strip():
                con.execute("INSERT INTO suppliers(name,phone,address) VALUES(?,?,?)",
                            (request.form["name"].strip(), request.form.get("phone"), request.form.get("address")))
                flash("Supplier saved.", "success")
            return redirect(url_for("suppliers"))
        rows = con.execute("SELECT * FROM suppliers ORDER BY id DESC").fetchall()
    return render_template("suppliers.html", suppliers=rows)

@app.route("/stock", methods=["GET","POST"])
@admin_required
def stock():
    with db() as con:
        if request.method == "POST":
            pid = int(request.form["product_id"]); qty = int(request.form["qty"])
            movement = request.form["movement"]
            if qty > 0 and movement in ("IN","OUT"):
                delta = qty if movement == "IN" else -qty
                current = con.execute("SELECT stock FROM products WHERE id=?", (pid,)).fetchone()
                if current and current["stock"] + delta >= 0:
                    con.execute("UPDATE products SET stock=stock+? WHERE id=?", (delta,pid))
                    con.execute("INSERT INTO stock_movements(product_id,movement,qty,note) VALUES(?,?,?,?)",
                                (pid,movement,qty,request.form.get("note")))
                    flash("Stock updated.", "success")
                else: flash("Not enough stock for this adjustment.", "error")
            return redirect(url_for("stock"))
        products = con.execute("SELECT id,name,stock FROM products ORDER BY name").fetchall()
        movements = con.execute("""SELECT m.*,p.name FROM stock_movements m LEFT JOIN products p ON p.id=m.product_id
                                   ORDER BY m.id DESC LIMIT 20""").fetchall()
    return render_template("stock.html", products=products, movements=movements)

@app.route("/new-bill", methods=["GET","POST"])
def new_bill():
    with db() as con:
        if request.method == "POST":
            try:
                customer_name = request.form.get("customer_name","").strip() or "Walk-in Customer"
                phone = request.form.get("phone","").strip()
                customer_id = None
                if phone:
                    found = con.execute("SELECT id FROM customers WHERE phone=? LIMIT 1", (phone,)).fetchone()
                    if found: customer_id = found["id"]
                ids = request.form.getlist("product_id[]")
                qtys = request.form.getlist("qty[]")
                prices = request.form.getlist("price[]")
                items=[]; subtotal=0
                for pid, q, p in zip(ids, qtys, prices):
                    if not pid: continue
                    qty=int(q); price=float(p)
                    product=con.execute("SELECT * FROM products WHERE id=?", (int(pid),)).fetchone()
                    if not product or qty < 1 or price < 0: raise ValueError("Invalid item")
                    if product["stock"] < qty: raise ValueError(f"Insufficient stock for {product['name']}")
                    line=qty*price; subtotal += line
                    items.append((product,qty,price,line))
                if not items: raise ValueError("Add at least one product")
                discount=max(0,float(request.form.get("discount") or 0))
                total=max(0,subtotal-discount)
                bill_no="SV-"+datetime.now().strftime("%y%m%d-%H%M%S")
                cur=con.execute("""INSERT INTO bills(bill_no,customer_id,customer_name,phone,subtotal,discount,total,payment)
                                   VALUES(?,?,?,?,?,?,?,?)""",
                                (bill_no,customer_id,customer_name,phone,subtotal,discount,total,request.form.get("payment","CASH")))
                bill_id=cur.lastrowid
                for product,qty,price,line in items:
                    con.execute("""INSERT INTO bill_items(bill_id,product_id,product_name,qty,price,line_total)
                                   VALUES(?,?,?,?,?,?)""",(bill_id,product["id"],product["name"],qty,price,line))
                    con.execute("UPDATE products SET stock=stock-? WHERE id=?", (qty,product["id"]))
                    con.execute("INSERT INTO stock_movements(product_id,movement,qty,note) VALUES(?,?,?,?)",
                                (product["id"],"OUT",qty,f"Sale {bill_no}"))
                flash("Bill created successfully.", "success")
                return redirect(url_for("invoice", bill_id=bill_id))
            except (ValueError, InvalidOperation) as e:
                flash(str(e) or "Please check bill details.", "error")
            except Exception:
                flash("Could not create bill. Please check the entered details.", "error")
        products=con.execute("SELECT id,name,price,reseller_price,wholesale_price,stock FROM products WHERE stock>0 ORDER BY name").fetchall()
        customers=con.execute("SELECT * FROM customers ORDER BY name").fetchall()
    return render_template("new_bill.html", products=products, customers=customers)

@app.route("/bills")
def bills():
    q=request.args.get("q","").strip()
    with db() as con:
        rows=con.execute("""SELECT * FROM bills WHERE bill_no LIKE ? OR customer_name LIKE ? OR phone LIKE ?
                            ORDER BY id DESC""",(f"%{q}%",f"%{q}%",f"%{q}%")).fetchall()
    return render_template("bills.html", bills=rows, q=q)

@app.route("/invoice/<int:bill_id>")
def invoice(bill_id):
    with db() as con:
        bill=con.execute("SELECT * FROM bills WHERE id=?", (bill_id,)).fetchone()
        if not bill: abort(404)
        items=con.execute("SELECT * FROM bill_items WHERE bill_id=?", (bill_id,)).fetchall()
    return render_template("invoice.html", bill=bill, items=items)

@app.route("/purchases", methods=["GET","POST"])
@admin_required
def purchases():
    with db() as con:
        if request.method=="POST":
            supplier=request.form.get("supplier","").strip()
            reference=request.form.get("reference","").strip()
            total=float(request.form.get("total") or 0)
            con.execute("INSERT INTO purchases(supplier,reference,total) VALUES(?,?,?)",(supplier,reference,total))
            flash("Purchase record saved. Update item stock separately in Stock.", "success")
            return redirect(url_for("purchases"))
        rows=con.execute("SELECT * FROM purchases ORDER BY id DESC").fetchall()
    return render_template("purchases.html", purchases=rows)

@app.route("/api/products")
def api_products():
    with db() as con:
        rows=con.execute("SELECT id,name,price,reseller_price,wholesale_price,stock FROM products WHERE stock>0 ORDER BY name").fetchall()
    return jsonify([dict(r) for r in rows])

@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404

if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
