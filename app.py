from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_mysqldb import MySQL
from werkzeug.security import generate_password_hash, check_password_hash
from flask import jsonify
from datetime import datetime
import random

app = Flask(__name__)
app.secret_key = "simple_secret_key"
app.config['SESSION_PERMANENT'] = False
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = 3600  # 1 hour

def clean_input(value):
    if not value:
        return ""
    return value.strip()

# MySQL config
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = ''
app.config['MYSQL_DB'] = 'pharmacon'

mysql = MySQL(app)

# Low stock threshold
LOW_STOCK_THRESHOLD = 10

def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session or session.get('role') != 'admin':
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

def cashier_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'role' not in session or session['role'] != 'cashier':
            return redirect(url_for('cashier_login'))
        if 'user_id' not in session:
            session.clear()
            return redirect(url_for('cashier_login'))
        return f(*args, **kwargs)
    return decorated_function

# =============================
# ADMIN LOGIN (Default)
# =============================

@app.route('/')
def index():
    return redirect(url_for('admin_login'))

@app.route('/admin_login', methods=['GET', 'POST'])
def admin_login():
    if 'user' in session and session.get('role') == 'admin':
        return redirect(url_for('admin_dashboard'))

    if request.method == 'POST':
        username = clean_input(request.form.get('username'))
        password = clean_input(request.form.get('password'))

        if username == "" or password == "":
            flash("All fields are required", "error")
            return redirect(url_for('admin_login'))

        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM admins WHERE username=%s", (username,))
        admin = cur.fetchone()
        cur.close()

        # Create default admin if none exists
        if not admin:
            cur = mysql.connection.cursor()
            cur.execute("SELECT COUNT(*) FROM admins")
            count = cur.fetchone()[0]
            cur.close()
            if count == 0:
                hashed = generate_password_hash('admin123')
                cur = mysql.connection.cursor()
                cur.execute("INSERT INTO admins (username, password, full_name) VALUES (%s, %s, %s)", ('admin', hashed, 'System Administrator'))
                mysql.connection.commit()
                cur.close()
                cur = mysql.connection.cursor()
                cur.execute("SELECT * FROM admins WHERE username='admin'")
                admin = cur.fetchone()
                cur.close()
            else:
                flash("Invalid username or password", "error")
                return redirect(url_for('admin_login'))
        
        if admin and (password == admin[2] or check_password_hash(admin[2], password)):
            session['user'] = admin[1]
            session['role'] = 'admin'
            return redirect(url_for('admin_dashboard'))
        else:
            flash("Invalid login credentials", "error")
            return redirect(url_for('admin_login'))

    return render_template('admin_login.html')

# =============================
# ADMIN DASHBOARD
# =============================

@app.route('/admin')
@admin_required
def admin_dashboard():
    cur = mysql.connection.cursor()
    
    cur.execute("SELECT * FROM cashiers")
    cashiers = cur.fetchall()

    cur.execute("""
        SELECT c.id, c.full_name, c.username, ca.login_time
        FROM cashiers c
        JOIN cashier_activity ca ON c.id = ca.cashier_id
        WHERE ca.logout_time IS NULL
        ORDER BY ca.login_time DESC
    """)
    active_cashiers = cur.fetchall()

    cur.execute("""
        SELECT c.full_name, c.username, ca.login_time, ca.logout_time
        FROM cashier_activity ca
        JOIN cashiers c ON c.id = ca.cashier_id
        ORDER BY ca.login_time DESC
        LIMIT 10
    """)
    activity_logs = cur.fetchall()
    
    cur.execute("SELECT COUNT(*) FROM products WHERE stock <= %s", (LOW_STOCK_THRESHOLD,))
    low_stock_count = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM products WHERE expiration_date <= CURDATE() + INTERVAL 30 DAY AND expiration_date IS NOT NULL")
    expiring_count = cur.fetchone()[0]
    
    cur.close()

    return render_template('admin_dashboard.html',
                           cashiers=cashiers,
                           active_cashiers=active_cashiers,
                           activity_logs=activity_logs,
                           low_stock_count=low_stock_count,
                           expiring_count=expiring_count,
                           active_main='admin',
                           active_sub='dashboard')

@app.route('/admin/cashier_logs')
@admin_required
def cashier_logs():
    cur = mysql.connection.cursor()
    
    cur.execute("""
        SELECT c.full_name, c.username, ca.login_time, ca.logout_time
        FROM cashier_activity ca
        JOIN cashiers c ON c.id = ca.cashier_id
        ORDER BY ca.login_time DESC
    """)
    activity_logs = cur.fetchall()
    
    cur.execute("SELECT COUNT(*) FROM products WHERE stock <= %s", (LOW_STOCK_THRESHOLD,))
    low_stock_count = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM products WHERE expiration_date <= CURDATE() + INTERVAL 30 DAY AND expiration_date IS NOT NULL")
    expiring_count = cur.fetchone()[0]
    
    cur.close()

    return render_template('admin_cashier_logs.html', 
                           activity_logs=activity_logs,
                           low_stock_count=low_stock_count,
                           expiring_count=expiring_count,
                           active_main='dashboard', 
                           active_sub='cashier_logs')

# =============================
# NOTIFICATIONS API
# =============================

@app.route('/api/notifications')
@admin_required
def get_notifications():
    cur = mysql.connection.cursor()
    
    cur.execute("""
        SELECT id, product_name, stock, barcode 
        FROM products 
        WHERE stock <= %s
        ORDER BY stock ASC
        LIMIT 10
    """, (LOW_STOCK_THRESHOLD,))
    low_stock = cur.fetchall()
    
    cur.execute("""
        SELECT id, product_name, expiration_date, barcode
        FROM products 
        WHERE expiration_date <= CURDATE() + INTERVAL 30 DAY 
        AND expiration_date IS NOT NULL
        ORDER BY expiration_date ASC
        LIMIT 10
    """)
    expiring = cur.fetchall()
    
    cur.close()
    
    return jsonify({
        'low_stock': [{'id': p[0], 'name': p[1], 'stock': p[2], 'barcode': p[3]} for p in low_stock],
        'expiring': [{'id': p[0], 'name': p[1], 'expiry': str(p[2]), 'barcode': p[3]} for p in expiring]
    })

# =============================
# CATALOG
# =============================

@app.route('/all_products')
@admin_required
def all_products():
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM products")
    products = cur.fetchall()
    
    cur.execute("SELECT COUNT(*) FROM products WHERE stock <= %s", (LOW_STOCK_THRESHOLD,))
    low_stock_count = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM products WHERE expiration_date <= CURDATE() + INTERVAL 30 DAY AND expiration_date IS NOT NULL")
    expiring_count = cur.fetchone()[0]
    
    cur.close()
    return render_template('all_products.html', products=products,
                           low_stock_count=low_stock_count,
                           expiring_count=expiring_count,
                           active_main='catalog', active_sub='all_products')

@app.route('/add_product', methods=['GET', 'POST'])
@admin_required
def add_product():
    cur = mysql.connection.cursor()

    if request.method == 'POST':
        barcode = request.form.get('barcode')
        name = request.form.get('product_name')
        category_name = request.form.get('category')  # From template: category
        p_type = 'medical' if category_name == 'Medical' else 'non_medical'
        price = request.form.get('price')
        stock = request.form.get('stock')
        expiry = request.form.get('expiration_date') or None  # From template: expiration_date

        # Get category_id from category name
        cur = mysql.connection.cursor()
        cur.execute("SELECT id FROM categories WHERE category_name=%s", (category_name,))
        cat_result = cur.fetchone()
        category_id = cat_result[0] if cat_result else None
        
        try:
            # Check if product exists with same name, barcode AND expiration date
            cur.execute("""
                SELECT id, stock FROM products 
                WHERE product_name = %s AND barcode = %s AND expiration_date = %s
            """, (name, barcode, expiry))
            existing = cur.fetchone()
            
            if existing:
                # Update stock if product exists with same expiry
                new_stock = existing[1] + int(stock)
                cur.execute("UPDATE products SET stock = %s WHERE id = %s", (new_stock, existing[0]))
                product_id = existing[0]
                flash(f"Stock updated! Added {stock} units. Total: {new_stock}", "success")
            else:
                # Insert new product if different expiry or new product
                query = """
                    INSERT INTO products (product_name, barcode, category_id, type, price, stock, expiration_date) 
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """
                cur.execute(query, (name, barcode, category_id, p_type, price, stock, expiry))
                product_id = cur.lastrowid
                flash("Product registered and stock movement logged!", "success")
            
            # Log stock movement
            movement_query = """
                INSERT INTO stock_movements (product_id, movement_type, quantity, reason) 
                VALUES (%s, 'IN', %s, 'Stock Addition')
            """
            cur.execute(movement_query, (product_id, stock))
            
            mysql.connection.commit()
            cur.close()
            return redirect(url_for('add_product'))
            
        except Exception as e:
            mysql.connection.rollback()
            flash(f"Error: {str(e)}", "error")

    try:
        cur.execute("SELECT id, category_name FROM categories ORDER BY category_name ASC")
        categories = cur.fetchall()
    except Exception as e:
        categories = []
        flash(f"Error loading categories: {str(e)}", "error")
    finally:
        cur.close()
    
    cur = mysql.connection.cursor()
    cur.execute("SELECT COUNT(*) FROM products WHERE stock <= %s", (LOW_STOCK_THRESHOLD,))
    low_stock_count = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM products WHERE expiration_date <= CURDATE() + INTERVAL 30 DAY AND expiration_date IS NOT NULL")
    expiring_count = cur.fetchone()[0]
    cur.close()
    
    return render_template('add_product.html', 
                           categories=categories, 
                           low_stock_count=low_stock_count,
                           expiring_count=expiring_count,
                           active_main='catalog', 
                           active_sub='add_product')

@app.route('/delete_product/<int:id>', methods=['POST'])
@admin_required
def delete_product(id):
    cur = mysql.connection.cursor()
    cur.execute("DELETE FROM products WHERE id=%s", (id,))
    mysql.connection.commit()
    cur.close()
    flash("Product deleted successfully", "success")
    return redirect(url_for('all_products'))

# =============================
# SALES
# =============================

@app.route('/medical_sales')
@admin_required
def medical_sales():
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM sales WHERE product_type='medical'")
    sales = cur.fetchall()
    
    cur.execute("SELECT COUNT(*) FROM products WHERE stock <= %s", (LOW_STOCK_THRESHOLD,))
    low_stock_count = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM products WHERE expiration_date <= CURDATE() + INTERVAL 30 DAY AND expiration_date IS NOT NULL")
    expiring_count = cur.fetchone()[0]
    
    # Get daily sales for chart (last 30 days)
    cur.execute("""
        SELECT DATE(sale_date) as day, SUM(total_amount) as daily_total
        FROM sales
        WHERE product_type='medical' AND sale_date >= CURDATE() - INTERVAL 30 DAY AND sale_status = 'Completed'
        GROUP BY DATE(sale_date)
        ORDER BY day ASC
    """)
    chart_data = cur.fetchall()
    chart_labels = [str(row[0]) for row in chart_data]
    chart_values = [float(row[1]) for row in chart_data]
    
    cur.close()
    return render_template('sales_medical.html', sales=sales,
                           low_stock_count=low_stock_count,
                           expiring_count=expiring_count,
                           chart_labels=chart_labels, chart_values=chart_values,
                           active_main='sales', active_sub='medical_sales')

@app.route('/sales_dashboard')
@admin_required
def sales_dashboard():
    """Admin sales dashboard with all views"""
    cur = mysql.connection.cursor()
    
    cur.execute("SELECT COUNT(*) FROM products WHERE stock <= %s", (LOW_STOCK_THRESHOLD,))
    low_stock_count = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM products WHERE expiration_date <= CURDATE() + INTERVAL 30 DAY AND expiration_date IS NOT NULL")
    expiring_count = cur.fetchone()[0]
    
    # Daily sales (today)
    cur.execute("""
        SELECT IFNULL(SUM(total_amount), 0), COUNT(*) 
        FROM sales 
        WHERE DATE(sale_date) = CURDATE() AND sale_status = 'Completed'
    """)
    daily = cur.fetchone()
    daily_sales = float(daily[0]) if daily[0] else 0
    daily_count = daily[1] if daily[1] else 0
    
    # Weekly sales (last 7 days)
    cur.execute("""
        SELECT IFNULL(SUM(total_amount), 0), COUNT(*) 
        FROM sales 
        WHERE sale_date >= CURDATE() - INTERVAL 7 DAY AND sale_status = 'Completed'
    """)
    weekly = cur.fetchone()
    weekly_sales = float(weekly[0]) if weekly[0] else 0
    weekly_count = weekly[1] if weekly[1] else 0
    
    # Monthly sales (this month)
    cur.execute("""
        SELECT IFNULL(SUM(total_amount), 0), COUNT(*) 
        FROM sales 
        WHERE MONTH(sale_date) = MONTH(CURDATE()) AND YEAR(sale_date) = YEAR(CURDATE()) AND sale_status = 'Completed'
    """)
    monthly = cur.fetchone()
    monthly_sales = float(monthly[0]) if monthly[0] else 0
    monthly_count = monthly[1] if monthly[1] else 0
    
    # Yearly sales (this year)
    cur.execute("""
        SELECT IFNULL(SUM(total_amount), 0), COUNT(*) 
        FROM sales 
        WHERE YEAR(sale_date) = YEAR(CURDATE()) AND sale_status = 'Completed'
    """)
    yearly = cur.fetchone()
    yearly_sales = float(yearly[0]) if yearly[0] else 0
    yearly_count = yearly[1] if yearly[1] else 0
    
    # Overall sales
    cur.execute("""
        SELECT IFNULL(SUM(total_amount), 0), COUNT(*) 
        FROM sales WHERE sale_status = 'Completed'
    """)
    overall = cur.fetchone()
    overall_sales = float(overall[0]) if overall[0] else 0
    overall_count = overall[1] if overall[1] else 0
    
    # Popular products (top 10)
    cur.execute("""
        SELECT p.product_name, SUM(si.quantity) as total_qty, SUM(si.quantity * si.price) as total_sales
        FROM sale_items si
        JOIN products p ON si.product_id = p.id
        GROUP BY p.id, p.product_name
        ORDER BY total_qty DESC
        LIMIT 10
    """)
    popular = cur.fetchall()
    
    # Daily sales for chart (last 30 days)
    cur.execute("""
        SELECT DATE(sale_date) as day, SUM(total_amount) as daily_total
        FROM sales
        WHERE sale_date >= CURDATE() - INTERVAL 30 DAY AND sale_status = 'Completed'
        GROUP BY DATE(sale_date)
        ORDER BY day ASC
    """)
    chart_data = cur.fetchall()
    chart_labels = [str(row[0]) for row in chart_data]
    chart_values = [float(row[1]) for row in chart_data]
    
    cur.close()
    
    return render_template('sales_dashboard.html',
                           low_stock_count=low_stock_count,
                           expiring_count=expiring_count,
                           daily_sales=daily_sales, daily_count=daily_count,
                           weekly_sales=weekly_sales, weekly_count=weekly_count,
                           monthly_sales=monthly_sales, monthly_count=monthly_count,
                           yearly_sales=yearly_sales, yearly_count=yearly_count,
                           overall_sales=overall_sales, overall_count=overall_count,
                           popular=popular,
                           chart_labels=chart_labels, chart_values=chart_values,
                           active_main='sales', active_sub='sales_dashboard')

@app.route('/non_medical_sales')
@admin_required
def non_medical_sales():
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM sales WHERE product_type='non_medical'")
    sales = cur.fetchall()
    
    cur.execute("SELECT COUNT(*) FROM products WHERE stock <= %s", (LOW_STOCK_THRESHOLD,))
    low_stock_count = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM products WHERE expiration_date <= CURDATE() + INTERVAL 30 DAY AND expiration_date IS NOT NULL")
    expiring_count = cur.fetchone()[0]
    
    # Get daily sales for chart (last 30 days)
    cur.execute("""
        SELECT DATE(sale_date) as day, SUM(total_amount) as daily_total
        FROM sales
        WHERE product_type='non_medical' AND sale_date >= CURDATE() - INTERVAL 30 DAY AND sale_status = 'Completed'
        GROUP BY DATE(sale_date)
        ORDER BY day ASC
    """)
    chart_data = cur.fetchall()
    chart_labels = [str(row[0]) for row in chart_data]
    chart_values = [float(row[1]) for row in chart_data]
    
    cur.close()
    return render_template('sales_non_medical.html', sales=sales,
                           low_stock_count=low_stock_count,
                           expiring_count=expiring_count,
                           chart_labels=chart_labels, chart_values=chart_values,
                           active_main='sales', active_sub='non_medical_sales')

# =============================
# INVENTORY
# =============================

@app.route('/out_of_stock')
@admin_required
def out_of_stock():
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM products WHERE stock <= %s", (LOW_STOCK_THRESHOLD,))
    products = cur.fetchall()
    
    cur.execute("SELECT COUNT(*) FROM products WHERE stock <= %s", (LOW_STOCK_THRESHOLD,))
    low_stock_count = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM products WHERE expiration_date <= CURDATE() + INTERVAL 30 DAY AND expiration_date IS NOT NULL")
    expiring_count = cur.fetchone()[0]
    
    cur.close()
    return render_template('inventory_out_of_stock.html', products=products,
                           low_stock_count=low_stock_count,
                           expiring_count=expiring_count,
                           active_main='inventory', active_sub='out_of_stock')

@app.route('/expiring_medical')
@admin_required
def expiring_medical():
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM products WHERE expiration_date <= CURDATE() + INTERVAL 30 DAY AND expiration_date IS NOT NULL")
    products = cur.fetchall()
    
    cur.execute("SELECT COUNT(*) FROM products WHERE stock <= %s", (LOW_STOCK_THRESHOLD,))
    low_stock_count = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM products WHERE expiration_date <= CURDATE() + INTERVAL 30 DAY AND expiration_date IS NOT NULL")
    expiring_count = cur.fetchone()[0]
    
    cur.close()
    return render_template('inventory_expiring.html', products=products,
                           low_stock_count=low_stock_count,
                           expiring_count=expiring_count,
                           active_main='inventory', active_sub='expiring_medical')

# =============================
# ADMIN MANAGEMENT
# =============================

@app.route('/register_cashier', methods=['GET','POST'])
@admin_required
def register_cashier():
    cur = mysql.connection.cursor()
    
    cur.execute("SELECT COUNT(*) FROM products WHERE stock <= %s", (LOW_STOCK_THRESHOLD,))
    low_stock_count = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM products WHERE expiration_date <= CURDATE() + INTERVAL 30 DAY AND expiration_date IS NOT NULL")
    expiring_count = cur.fetchone()[0]
    
    if request.method == 'POST':
        username = clean_input(request.form.get('username'))
        full_name = clean_input(request.form.get('full_name'))
        password = clean_input(request.form.get('password'))

        if username == "" or full_name == "" or password == "":
            flash("All fields are required", "error")
            return redirect(url_for('register_cashier'))

        cur.execute("SELECT id FROM cashiers WHERE username=%s", (username,))
        if cur.fetchone():
            cur.close()
            flash("Username already exists", "error")
            return redirect(url_for('register_cashier'))

        hashed_password = generate_password_hash(password)

        cur.execute("""
            INSERT INTO cashiers (full_name, username, password)
            VALUES (%s, %s, %s)
        """, (full_name, username, hashed_password))

        mysql.connection.commit()
        cur.close()

        flash("Cashier registered successfully", "success")
        return redirect(url_for('register_cashier'))

    cur.close()
    return render_template('register_cashier.html',
                           low_stock_count=low_stock_count,
                           expiring_count=expiring_count,
                           active_main='management', 
                           active_sub='register_cashier')


@app.route('/delete_cashier', methods=['GET','POST'])
@admin_required
def delete_cashier():
    cur = mysql.connection.cursor()
    
    cur.execute("SELECT COUNT(*) FROM products WHERE stock <= %s", (LOW_STOCK_THRESHOLD,))
    low_stock_count = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM products WHERE expiration_date <= CURDATE() + INTERVAL 30 DAY AND expiration_date IS NOT NULL")
    expiring_count = cur.fetchone()[0]
    
    if request.method == 'POST':
        cashier_id = request.form['id']
        cur.execute("DELETE FROM cashiers WHERE id=%s", (cashier_id,))
        mysql.connection.commit()
        flash("Cashier deleted successfully", "success")

    cur.execute("SELECT * FROM cashiers")
    cashiers = cur.fetchall()
    cur.close()
    return render_template('delete_cashier.html', cashiers=cashiers,
                           low_stock_count=low_stock_count,
                           expiring_count=expiring_count,
                           active_main='management', active_sub='delete_cashier')

@app.route('/edit_cashier', methods=['POST'])
@admin_required
def edit_cashier():
    cashier_id = request.form.get('id')
    full_name = clean_input(request.form.get('full_name'))
    username = clean_input(request.form.get('username'))
    status = request.form.get('status')
    password = clean_input(request.form.get('password'))

    if full_name == "" or username == "" or status == "":
        flash("Full name, username, and status are required", "error")
        return redirect(url_for('delete_cashier'))

    cur = mysql.connection.cursor()

    cur.execute("SELECT id FROM cashiers WHERE username=%s AND id!=%s", (username, cashier_id))
    if cur.fetchone():
        cur.close()
        flash("Username already exists", "error")
        return redirect(url_for('delete_cashier'))

    try:
        if password != "":
            hashed_pw = generate_password_hash(password)
            cur.execute("""
                UPDATE cashiers 
                SET full_name=%s, username=%s, password=%s, status=%s
                WHERE id=%s
            """, (full_name, username, hashed_pw, status, cashier_id))
        else:
            cur.execute("""
                UPDATE cashiers 
                SET full_name=%s, username=%s, status=%s
                WHERE id=%s
            """, (full_name, username, status, cashier_id))

        mysql.connection.commit()
        flash("Cashier updated successfully!", "success")

    except Exception as e:
        mysql.connection.rollback()
        flash(f"Error: {str(e)}", "error")

    finally:
        cur.close()

    return redirect(url_for('delete_cashier'))

@app.route('/change_admin_password', methods=['GET','POST'])
@admin_required
def change_admin_password():
    cur = mysql.connection.cursor()
    
    cur.execute("SELECT COUNT(*) FROM products WHERE stock <= %s", (LOW_STOCK_THRESHOLD,))
    low_stock_count = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM products WHERE expiration_date <= CURDATE() + INTERVAL 30 DAY AND expiration_date IS NOT NULL")
    expiring_count = cur.fetchone()[0]
    cur.close()
    
    if request.method == 'POST':
        old_pass = request.form['old_password']
        new_pass = request.form['new_password']

        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM admins WHERE username=%s", (session['user'],))
        admin = cur.fetchone()

        if admin and check_password_hash(admin[2], old_pass):
            hashed = generate_password_hash(new_pass)
            cur.execute("UPDATE admins SET password=%s WHERE username=%s", (hashed, session['user']))
            mysql.connection.commit()
            flash("Password updated successfully", "success")
        else:
            flash("Old password is incorrect", "error")
        cur.close()
        return redirect(url_for('change_admin_password'))

    return render_template('change_admin_password.html',
                           low_stock_count=low_stock_count,
                           expiring_count=expiring_count,
                           active_main='management', active_sub='change_admin_password')

# =============================
# CASHIER LOGIN
# =============================

@app.route('/cashier_login', methods=['GET', 'POST'])
def cashier_login():
    if 'user' in session and session.get('role') == 'cashier':
        return redirect(url_for('cashier_dashboard'))

    if request.method == 'POST':
        username = clean_input(request.form.get('username'))
        password = clean_input(request.form.get('password'))

        if username == "" or password == "":
            flash("All fields are required", "error")
            return redirect(url_for('cashier_login'))

        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM cashiers WHERE username=%s", (username,))
        cashier = cur.fetchone()
        cur.close()

        if cashier and check_password_hash(cashier[3], password):
            session['user'] = cashier[1]
            session['user_id'] = cashier[0]
            session['role'] = 'cashier'
            
            cur = mysql.connection.cursor()
            cur.execute("INSERT INTO cashier_activity (cashier_id, login_time) VALUES (%s, NOW())", (session['user_id'],))
            mysql.connection.commit()
            cur.close()
            
            return redirect(url_for('cashier_dashboard'))
        else:
            flash("Invalid login credentials", "error")
            return redirect(url_for('cashier_login'))

    return render_template('cashier_login.html')


@app.route('/active_cashiers')
@admin_required
def get_active_cashiers():
    cur = mysql.connection.cursor()
    
    cur.execute("SELECT id, full_name, username FROM cashiers")
    cashiers = cur.fetchall()
    
    cur.execute("""
        SELECT c.username, ca.login_time
        FROM cashiers c
        JOIN cashier_activity ca ON c.id = ca.cashier_id
        WHERE ca.logout_time IS NULL
    """)
    active_data = {row[0]: row[1] for row in cur.fetchall()}
    cur.close()

    cashier_list = []
    for c in cashiers:
        login_time = active_data.get(c[2], None)
        cashier_list.append({
            'id': c[0],
            'full_name': c[1],
            'username': c[2],
            'status': 'Online' if c[2] in active_data else 'Offline',
            'login_time': str(login_time) if login_time else None
        })

    return jsonify(cashier_list)

# =============================
# CASHIER DASHBOARD
# =============================

@app.route('/cashier')
@cashier_required
def cashier_dashboard():
    cur = mysql.connection.cursor()
    
    cur.execute("""
        SELECT IFNULL(SUM(total_amount), 0) as total, COUNT(*) as count
        FROM sales 
        WHERE cashier_id = %s AND DATE(sale_date) = CURDATE() AND sale_status = 'Completed'
    """, (session['user_id'],))
    today_data = cur.fetchone()
    today_total = today_data[0] if today_data else 0
    today_count = today_data[1] if today_data else 0

    cur.execute("""
        SELECT sale_date, receipt_number, total_amount, sale_status 
        FROM sales 
        WHERE cashier_id = %s
        ORDER BY sale_date DESC 
        LIMIT 5
    """, (session['user_id'],))

    recent_sales = cur.fetchall()
    cur.close()

    return render_template('cashier_dashboard.html', 
                           recent_sales=recent_sales,
                           today_total=today_total,
                           today_count=today_count)

@app.route('/cashier_history')
@cashier_required
def cashier_history():
    cur = mysql.connection.cursor()

    # Get daily sales (last 30 days for chart)
    cur.execute("""
        SELECT DATE(sale_date) as sale_day,
               IFNULL(SUM(total_amount),0) as total_sales,
               COUNT(id) as total_transactions
        FROM sales
        WHERE cashier_id = %s
        AND sale_status = 'Completed'
        AND DATE(sale_date) >= CURDATE() - INTERVAL 30 DAY
        GROUP BY DATE(sale_date)
        ORDER BY sale_day ASC
    """, (session['user_id'],))
    daily_data = cur.fetchall()

    labels = [str(row[0]) for row in daily_data]
    sales_values = [float(row[1]) for row in daily_data]
    transaction_counts = [int(row[2]) for row in daily_data]

    # Get today's transactions only
    cur.execute("""
        SELECT id, receipt_number, total_amount, sale_date
        FROM sales
        WHERE cashier_id = %s
        AND DATE(sale_date) = CURDATE()
        AND sale_status = 'Completed'
        ORDER BY sale_date DESC
    """, (session['user_id'],))
    sales = cur.fetchall()

    sales_data = []
    for sale in sales:
        sale_id = sale[0]
        cur.execute("""
            SELECT si.quantity, si.price, p.product_name
            FROM sale_items si
            LEFT JOIN products p ON si.product_id = p.id
            WHERE si.sale_id = %s
        """, (sale_id,))
        items = cur.fetchall()
        sales_data.append({
            "id": sale[0],
            "receipt_number": sale[1],
            "total_amount": float(sale[2]),
            "sale_date": sale[3],
            "items": items
        })

    cur.close()
    return render_template(
        "cashier_history.html",
        sales=sales_data,
        chart_labels=labels,
        chart_sales=sales_values,
        chart_transactions=transaction_counts
    )

@app.route('/search_product')
@cashier_required
def search_product():
    query = request.args.get('q')
    cur = mysql.connection.cursor()

    cur.execute("""
        SELECT id, product_name, price, stock, barcode, expiration_date
        FROM products
        WHERE (product_name LIKE %s OR barcode LIKE %s)
        AND stock > 0
        ORDER BY product_name, expiration_date
        LIMIT 10
    """, (f"%{query}%", f"%{query}%"))

    products = cur.fetchall()
    cur.close()

    result = []
    for p in products:
        expiry = p[5].strftime('%m/%d/%Y') if p[5] else 'N/A'
        result.append({
            "id": p[0],
            "name": p[1],
            "price": float(p[2]),
            "stock": p[3],
            "barcode": p[4],
            "expiry": expiry
        })

    return jsonify(result)

@app.route('/api/products')
@cashier_required
def api_products():
    """API endpoint for live product updates"""
    cur = mysql.connection.cursor()
    cur.execute("SELECT id, product_name, price, stock, barcode, expiration_date FROM products WHERE stock > 0 ORDER BY product_name, expiration_date")
    products = cur.fetchall()
    cur.close()
    
    result = []
    for p in products:
        expiry = p[5].strftime('%m/%d/%Y') if p[5] else 'N/A'
        result.append({
            "id": p[0],
            "name": p[1],
            "price": float(p[2]),
            "stock": p[3],
            "barcode": p[4],
            "expiry": expiry
        })
    return jsonify(result)

@app.route('/api/search_by_name')
def search_by_name():
    """API to search product by name for auto-fill"""
    query = request.args.get('q', '')
    if not query:
        return jsonify([])
    
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT id, product_name, barcode, price, category_id, expiration_date 
        FROM products 
        WHERE product_name LIKE %s 
        ORDER BY product_name, expiration_date
        LIMIT 5
    """, (f"%{query}%",))
    products = cur.fetchall()
    cur.close()
    
    result = []
    for p in products:
        expiry = p[5].strftime('%m/%d/%Y') if p[5] else 'N/A'
        result.append({
            "id": p[0],
            "name": p[1],
            "barcode": p[2],
            "price": float(p[3]) if p[3] else 0,
            "category_id": p[4],
            "expiry": expiry
        })
    return jsonify(result)

@app.route('/get_product/<barcode>')
@cashier_required
def get_product(barcode):
    cur = mysql.connection.cursor()

    cur.execute("""
        SELECT id, product_name, price, stock, barcode
        FROM products
        WHERE barcode = %s AND stock > 0
        LIMIT 1
    """, (barcode,))

    row = cur.fetchone()
    cur.close()

    if row:
        return jsonify({
            "success": True,
            "product": {
                "id": row[0],
                "name": row[1],
                "price": float(row[2]),
                "stock": row[3],
                "barcode": row[4]
            }
        })

    return jsonify({"success": False})

@app.route('/complete_sale', methods=['POST'])
@cashier_required
def complete_sale():
    data = request.get_json()
    items = data.get('items', [])
    
    if not items:
        return jsonify({'success': False, 'message': 'No items in cart'})
    
    cur = mysql.connection.cursor()
    
    receipt_number = f"REC-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}"
    total_amount = sum(item['price'] * item['quantity'] for item in items)
    
    if items:
        cur.execute("SELECT type FROM products WHERE id = %s", (items[0]['id'],))
        product_type = cur.fetchone()
        product_type = product_type[0] if product_type else 'non_medical'
    else:
        product_type = 'non_medical'
    
    cur.execute("""
        INSERT INTO sales (receipt_number, cashier_id, total_amount, sale_status, product_type, sale_date)
        VALUES (%s, %s, %s, 'Completed', %s, NOW())
    """, (receipt_number, session['user_id'], total_amount, product_type))
    
    sale_id = cur.lastrowid
    
    for item in items:
        cur.execute("""
            INSERT INTO sale_items (sale_id, product_id, quantity, price)
            VALUES (%s, %s, %s, %s)
        """, (sale_id, item['id'], item['quantity'], item['price']))
        
        cur.execute("""
            UPDATE products SET stock = stock - %s WHERE id = %s
        """, (item['quantity'], item['id']))
        
        cur.execute("""
            INSERT INTO stock_movements (product_id, movement_type, quantity, reason)
            VALUES (%s, 'OUT', %s, 'Sale')
        """, (item['id'], item['quantity']))
    
    mysql.connection.commit()
    cur.close()
    
    receipt_items = []
    for item in items:
        receipt_items.append({
            'name': item['name'],
            'quantity': item['quantity'],
            'price': item['price'],
            'subtotal': item['price'] * item['quantity']
        })
    
    return jsonify({
        'success': True,
        'receipt_number': receipt_number,
        'total': total_amount,
        'items': receipt_items,
        'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })

# =============================
# LOGOUT
# =============================

# Route to setup remote database access (run once)
@app.route('/setup_remote_db')
def setup_remote_db():
    """Grant remote access to root user - run this once from Computer 1"""
    try:
        cur = mysql.connection.cursor()
        # Create user for remote access with all privileges
        cur.execute("CREATE USER IF NOT EXISTS 'root'@'%' IDENTIFIED BY ''")
        cur.execute("GRANT ALL PRIVILEGES ON *.* TO 'root'@'%' WITH GRANT OPTION")
        cur.execute("FLUSH PRIVILEGES")
        cur.close()
        return "Database remote access granted! You can now connect from other computers."
    except Exception as e:
        return f"Error: {str(e)}"

@app.route('/logout')
def logout():
    role = session.get('role')
    user = session.get('user')

    if role == 'cashier':
        cur = mysql.connection.cursor()
        cur.execute("""
            UPDATE cashier_activity
            SET logout_time = NOW()
            WHERE cashier_id = (
                SELECT id FROM cashiers WHERE username=%s
            ) AND logout_time IS NULL
        """, (user,))
        mysql.connection.commit()
        cur.close()

    session.clear()

    if role == 'admin':
        return redirect(url_for('admin_login'))
    return redirect(url_for('cashier_login'))

# =============================
# RUN APP
# =============================

if __name__ == '__main__':
    app.run(debug=True)
