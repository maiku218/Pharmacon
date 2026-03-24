from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_mysqldb import MySQL
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import random

app = Flask(__name__)
app.secret_key = "simple_secret_key"
app.config['SESSION_PERMANENT'] = True  # Session persists on browser close
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = False  # Set to True in production with HTTPS
app.config['PERMANENT_SESSION_LIFETIME'] = 86400  # 24 hours - session lasts 24 hours

# Use separate cookies for admin and cashier
app.config['SESSION_COOKIE_NAME'] = 'pharmacon_session'

# Add datetime to template context
from datetime import datetime
@app.context_processor
def inject_datetime():
    return dict(datetime=datetime)

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
        if 'admin_user' not in session or session.get('role') != 'admin':
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

def cashier_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'role' not in session or session['role'] != 'cashier':
            return redirect(url_for('cashier_login'))
        if 'cashier_id' not in session:
            session.pop('cashier_user', None)
            session.pop('cashier_id', None)
            session.pop('role', None)
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
    if 'admin_user' in session and session.get('role') == 'admin':
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
            session['admin_user'] = admin[1]
            session['admin_id'] = admin[0]
            session['role'] = 'admin'
            session.permanent = True  # Session persists on refresh
            
            # Log admin login activity
            cur = mysql.connection.cursor()
            ip_address = request.remote_addr
            if request.headers.get('X-Forwarded-For'):
                ip_address = request.headers.get('X-Forwarded-For')
            
            try:
                cur.execute("""
                    INSERT INTO admin_activity (admin_id, action, ip_address, details)
                    VALUES (%s, %s, %s, %s)
                """, (admin[0], 'Admin Login', ip_address, f'Admin {admin[1]} logged in'))
                mysql.connection.commit()
            except:
                pass  # Table might not exist yet
            cur.close()
            
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
        SELECT c.full_name, c.username, ca.login_time, ca.logout_time, ca.ip_address
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

@app.route('/admin/activity_logs')
@admin_required
def admin_activity_logs():
    """View detailed admin activity logs"""
    cur = mysql.connection.cursor()
    
    cur.execute("""
        SELECT a.username, aa.action, aa.ip_address, aa.details, aa.activity_time
        FROM admin_activity aa
        JOIN admins a ON aa.admin_id = a.id
        ORDER BY aa.activity_time DESC
        LIMIT 50
    """)
    admin_logs = cur.fetchall()
    
    cur.execute("SELECT COUNT(*) FROM products WHERE stock <= %s", (LOW_STOCK_THRESHOLD,))
    low_stock_count = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM products WHERE expiration_date <= CURDATE() + INTERVAL 30 DAY AND expiration_date IS NOT NULL")
    expiring_count = cur.fetchone()[0]
    
    cur.close()

    return render_template('admin_activity_logs.html', 
                           admin_logs=admin_logs,
                           low_stock_count=low_stock_count,
                           expiring_count=expiring_count,
                           active_main='dashboard', 
                           active_sub='activity_logs')

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
        # Check if it's an AJAX request
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.form.get('ajax') == 'true'
        
        barcode = request.form.get('barcode')
        name = request.form.get('product_name')
        category_name = request.form.get('category')  # From template: category
        
        # Validate required fields
        errors = []
        if not barcode or barcode.strip() == '':
            errors.append('Barcode is required')
        if not name or name.strip() == '':
            errors.append('Product name is required')
        if not category_name:
            errors.append('Category is required')
        if not request.form.get('price'):
            errors.append('Price is required')
        if not request.form.get('stock'):
            errors.append('Stock is required')
        
        if errors:
            error_msg = 'Error: ' + ', '.join(errors)
            if is_ajax:
                return jsonify({'success': False, 'message': error_msg})
            else:
                flash(error_msg, 'error')
                # Re-render page
                cur.execute("SELECT id, category_name FROM categories ORDER BY category_name ASC")
                categories = cur.fetchall()
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
        
        p_type = category_name  # 'Medical' or 'Non-Medical'
        
        # Convert to proper types
        try:
            price = float(request.form.get('price')) if request.form.get('price') else 0
            stock = int(request.form.get('stock')) if request.form.get('stock') else 0
        except ValueError as e:
            error_msg = f'Invalid price or stock value: {str(e)}'
            if is_ajax:
                return jsonify({'success': False, 'message': error_msg})
            else:
                flash(error_msg, 'error')
                cur.execute("SELECT id, category_name FROM categories ORDER BY category_name ASC")
                categories = cur.fetchall()
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
        
        expiry = request.form.get('expiration_date') or None  # From template: expiration_date

        # Get category_id from category name
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
                message = f"Stock updated! Added {stock} units. Total: {new_stock}"
                action = 'Stock Update'
            else:
                # Insert new product if different expiry or new product
                query = """
                    INSERT INTO products (product_name, barcode, category_id, type, price, stock, expiration_date) 
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """
                cur.execute(query, (name, barcode, category_id, p_type, price, stock, expiry))
                product_id = cur.lastrowid
                message = "Product registered and stock movement logged!"
                action = 'Add New Product'
            
            # Log stock movement
            movement_query = """
                INSERT INTO stock_movements (product_id, movement_type, quantity, reason) 
                VALUES (%s, 'IN', %s, 'Stock Addition')
            """
            cur.execute(movement_query, (product_id, stock))
            
            # Log admin activity
            ip_address = request.remote_addr
            if request.headers.get('X-Forwarded-For'):
                ip_address = request.headers.get('X-Forwarded-For')
            
            try:
                cur.execute("""
                    INSERT INTO admin_activity (admin_id, action, ip_address, details)
                    VALUES (%s, %s, %s, %s)
                """, (session.get('admin_id'), action, ip_address, f'{name} - {stock} units added'))
            except:
                pass  # Table might not exist yet
            
            mysql.connection.commit()
            cur.close()
            
            # Return JSON response for AJAX, render same page for normal form submission (to show flash message)
            if is_ajax:
                return jsonify({'success': True, 'message': message})
            else:
                flash(message, "success")
                # Create new cursor for rendering page
                cur = mysql.connection.cursor()
                try:
                    cur.execute("SELECT id, category_name FROM categories ORDER BY category_name ASC")
                    categories = cur.fetchall()
                except Exception as e:
                    categories = []
                    flash(f"Error loading categories: {str(e)}", "error")
                
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
            
        except Exception as e:
            mysql.connection.rollback()
            error_str = str(e)
            
            # Provide more specific error messages
            if 'Duplicate entry' in error_str:
                error_message = 'Error: Product with this barcode already exists! Use a different barcode or update the existing product.'
            elif 'foreign key constraint fails' in error_str.lower():
                error_message = 'Error: Invalid category selected. Please select a valid category.'
            elif 'stock_movements' in error_str.lower():
                error_message = 'Error: Could not log stock movement. Please try again.'
            else:
                error_message = f'Database Error: {error_str}'
            
            if is_ajax:
                return jsonify({'success': False, 'message': error_message})
            else:
                flash(error_message, "error")
                # Create new cursor for rendering page after error
                cur = mysql.connection.cursor()
                try:
                    cur.execute("SELECT id, category_name FROM categories ORDER BY category_name ASC")
                    categories = cur.fetchall()
                except Exception as ex:
                    categories = []
                    
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
    else:
        # GET request - load categories and counts
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
    
    # Get product info before deleting
    cur.execute("SELECT product_name FROM products WHERE id=%s", (id,))
    product_info = cur.fetchone()
    product_name = product_info[0] if product_info else 'Unknown'
    
    cur.execute("DELETE FROM products WHERE id=%s", (id,))
    mysql.connection.commit()
    
    # Log admin activity
    ip_address = request.remote_addr
    if request.headers.get('X-Forwarded-For'):
        ip_address = request.headers.get('X-Forwarded-For')
    
    try:
        cur.execute("""
            INSERT INTO admin_activity (admin_id, action, ip_address, details)
            VALUES (%s, %s, %s, %s)
        """, (session.get('admin_id'), 'Delete Product', ip_address, f'Deleted product: {product_name}'))
        mysql.connection.commit()
    except:
        pass
    
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
    
    # Get sales with product names
    cur.execute("""
        SELECT s.id, s.receipt_number, GROUP_CONCAT(p.product_name SEPARATOR ', ') as products, 
               s.total_amount, s.sale_status, s.product_type, s.sale_date
        FROM sales s
        LEFT JOIN sale_items si ON s.id = si.sale_id
        LEFT JOIN products p ON si.product_id = p.id
        WHERE s.product_type = 'Medical'
        GROUP BY s.id
        ORDER BY s.sale_date DESC
    """)
    sales = cur.fetchall()
    
    cur.execute("SELECT COUNT(*) FROM products WHERE stock <= %s", (LOW_STOCK_THRESHOLD,))
    low_stock_count = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM products WHERE expiration_date <= CURDATE() + INTERVAL 30 DAY AND expiration_date IS NOT NULL")
    expiring_count = cur.fetchone()[0]
    
    # Get daily sales for chart (last 30 days)
    cur.execute("""
        SELECT DATE(sale_date) as day, SUM(total_amount) as daily_total
        FROM sales
        WHERE product_type='Medical' AND sale_date >= CURDATE() - INTERVAL 30 DAY AND sale_status = 'Completed'
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
    
    # Daily sales (today) - Medical
    cur.execute("""
        SELECT IFNULL(SUM(total_amount), 0), COUNT(*) 
        FROM sales 
        WHERE DATE(sale_date) = CURDATE() AND sale_status = 'Completed' AND product_type = 'Medical'
    """)
    daily_medical = cur.fetchone()
    daily_medical_sales = float(daily_medical[0]) if daily_medical[0] else 0
    
    # Daily sales (today) - Non-Medical
    cur.execute("""
        SELECT IFNULL(SUM(total_amount), 0), COUNT(*) 
        FROM sales 
        WHERE DATE(sale_date) = CURDATE() AND sale_status = 'Completed' AND product_type = 'Non-Medical'
    """)
    daily_nonmedical = cur.fetchone()
    daily_nonmedical_sales = float(daily_nonmedical[0]) if daily_nonmedical[0] else 0
    
    daily_sales = daily_medical_sales + daily_nonmedical_sales
    daily_count = daily_medical[1] if daily_medical[1] else 0
    
    # Weekly sales (last 7 days) - Medical
    cur.execute("""
        SELECT IFNULL(SUM(total_amount), 0), COUNT(*) 
        FROM sales 
        WHERE sale_date >= CURDATE() - INTERVAL 7 DAY AND sale_status = 'Completed' AND product_type = 'Medical'
    """)
    weekly_medical = cur.fetchone()
    weekly_medical_sales = float(weekly_medical[0]) if weekly_medical[0] else 0
    
    # Weekly sales (last 7 days) - Non-Medical
    cur.execute("""
        SELECT IFNULL(SUM(total_amount), 0), COUNT(*) 
        FROM sales 
        WHERE sale_date >= CURDATE() - INTERVAL 7 DAY AND sale_status = 'Completed' AND product_type = 'Non-Medical'
    """)
    weekly_nonmedical = cur.fetchone()
    weekly_nonmedical_sales = float(weekly_nonmedical[0]) if weekly_nonmedical[0] else 0
    
    weekly_sales = weekly_medical_sales + weekly_nonmedical_sales
    weekly_count = weekly_medical[1] if weekly_medical[1] else 0
    
    # Monthly sales (this month) - Medical
    cur.execute("""
        SELECT IFNULL(SUM(total_amount), 0), COUNT(*) 
        FROM sales 
        WHERE MONTH(sale_date) = MONTH(CURDATE()) AND YEAR(sale_date) = YEAR(CURDATE()) AND sale_status = 'Completed' AND product_type = 'Medical'
    """)
    monthly_medical = cur.fetchone()
    monthly_medical_sales = float(monthly_medical[0]) if monthly_medical[0] else 0
    
    # Monthly sales (this month) - Non-Medical
    cur.execute("""
        SELECT IFNULL(SUM(total_amount), 0), COUNT(*) 
        FROM sales 
        WHERE MONTH(sale_date) = MONTH(CURDATE()) AND YEAR(sale_date) = YEAR(CURDATE()) AND sale_status = 'Completed' AND product_type = 'Non-Medical'
    """)
    monthly_nonmedical = cur.fetchone()
    monthly_nonmedical_sales = float(monthly_nonmedical[0]) if monthly_nonmedical[0] else 0
    
    monthly_sales = monthly_medical_sales + monthly_nonmedical_sales
    monthly_count = monthly_medical[1] if monthly_medical[1] else 0
    
    # Yearly sales (this year) - Medical
    cur.execute("""
        SELECT IFNULL(SUM(total_amount), 0), COUNT(*) 
        FROM sales 
        WHERE YEAR(sale_date) = YEAR(CURDATE()) AND sale_status = 'Completed' AND product_type = 'Medical'
    """)
    yearly_medical = cur.fetchone()
    yearly_medical_sales = float(yearly_medical[0]) if yearly_medical[0] else 0
    
    # Yearly sales (this year) - Non-Medical
    cur.execute("""
        SELECT IFNULL(SUM(total_amount), 0), COUNT(*) 
        FROM sales 
        WHERE YEAR(sale_date) = YEAR(CURDATE()) AND sale_status = 'Completed' AND product_type = 'Non-Medical'
    """)
    yearly_nonmedical = cur.fetchone()
    yearly_nonmedical_sales = float(yearly_nonmedical[0]) if yearly_nonmedical[0] else 0
    
    yearly_sales = yearly_medical_sales + yearly_nonmedical_sales
    yearly_count = yearly_medical[1] if yearly_medical[1] else 0
    
    # Overall sales - Medical
    cur.execute("""
        SELECT IFNULL(SUM(total_amount), 0), COUNT(*) 
        FROM sales WHERE sale_status = 'Completed' AND product_type = 'Medical'
    """)
    overall_medical = cur.fetchone()
    overall_medical_sales = float(overall_medical[0]) if overall_medical[0] else 0
    
    # Overall sales - Non-Medical
    cur.execute("""
        SELECT IFNULL(SUM(total_amount), 0), COUNT(*) 
        FROM sales WHERE sale_status = 'Completed' AND product_type = 'Non-Medical'
    """)
    overall_nonmedical = cur.fetchone()
    overall_nonmedical_sales = float(overall_nonmedical[0]) if overall_nonmedical[0] else 0
    
    overall_sales = overall_medical_sales + overall_nonmedical_sales
    overall_count = overall_medical[1] if overall_medical[1] else 0
    
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
    
    # Daily sales for chart - Medical (last 30 days)
    cur.execute("""
        SELECT DATE(sale_date) as day, SUM(total_amount) as daily_total
        FROM sales
        WHERE sale_date >= CURDATE() - INTERVAL 30 DAY AND sale_status = 'Completed' AND product_type = 'Medical'
        GROUP BY DATE(sale_date)
        ORDER BY day ASC
    """)
    chart_medical = cur.fetchall()
    medical_labels = [str(row[0]) for row in chart_medical]
    medical_values = [float(row[1]) for row in chart_medical]
    
    # Daily sales for chart - Non-Medical (last 30 days)
    cur.execute("""
        SELECT DATE(sale_date) as day, SUM(total_amount) as daily_total
        FROM sales
        WHERE sale_date >= CURDATE() - INTERVAL 30 DAY AND sale_status = 'Completed' AND product_type = 'Non-Medical'
        GROUP BY DATE(sale_date)
        ORDER BY day ASC
    """)
    chart_nonmedical = cur.fetchall()
    nonmedical_labels = [str(row[0]) for row in chart_nonmedical]
    nonmedical_values = [float(row[1]) for row in chart_nonmedical]
    
    # Use medical labels as primary
    chart_labels = medical_labels
    chart_values = medical_values
    
    cur.close()
    
    return render_template('sales_dashboard.html',
                           low_stock_count=low_stock_count,
                           expiring_count=expiring_count,
                           daily_sales=daily_sales, daily_count=daily_count,
                           daily_medical_sales=daily_medical_sales,
                           daily_nonmedical_sales=daily_nonmedical_sales,
                           weekly_sales=weekly_sales, weekly_count=weekly_count,
                           weekly_medical_sales=weekly_medical_sales,
                           weekly_nonmedical_sales=weekly_nonmedical_sales,
                           monthly_sales=monthly_sales, monthly_count=monthly_count,
                           monthly_medical_sales=monthly_medical_sales,
                           monthly_nonmedical_sales=monthly_nonmedical_sales,
                           yearly_sales=yearly_sales, yearly_count=yearly_count,
                           yearly_medical_sales=yearly_medical_sales,
                           yearly_nonmedical_sales=yearly_nonmedical_sales,
                           overall_sales=overall_sales, overall_count=overall_count,
                           overall_medical_sales=overall_medical_sales,
                           overall_nonmedical_sales=overall_nonmedical_sales,
                           popular=popular,
                           chart_labels=chart_labels, chart_values=chart_values,
                           medical_labels=medical_labels, medical_values=medical_values,
                           nonmedical_labels=nonmedical_labels, nonmedical_values=nonmedical_values,
                           active_main='sales', active_sub='sales_dashboard')

@app.route('/non_medical_sales')
@admin_required
def non_medical_sales():
    cur = mysql.connection.cursor()
    
    # Get sales with product names
    cur.execute("""
        SELECT s.id, s.receipt_number, GROUP_CONCAT(p.product_name SEPARATOR ', ') as products, 
               s.total_amount, s.sale_status, s.product_type, s.sale_date
        FROM sales s
        LEFT JOIN sale_items si ON s.id = si.sale_id
        LEFT JOIN products p ON si.product_id = p.id
        WHERE s.product_type = 'Non-Medical'
        GROUP BY s.id
        ORDER BY s.sale_date DESC
    """)
    sales = cur.fetchall()
    
    cur.execute("SELECT COUNT(*) FROM products WHERE stock <= %s", (LOW_STOCK_THRESHOLD,))
    low_stock_count = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM products WHERE expiration_date <= CURDATE() + INTERVAL 30 DAY AND expiration_date IS NOT NULL")
    expiring_count = cur.fetchone()[0]
    
    # Get daily sales for chart (last 30 days)
    cur.execute("""
        SELECT DATE(sale_date) as day, SUM(total_amount) as daily_total
        FROM sales
        WHERE product_type='Non-Medical' AND sale_date >= CURDATE() - INTERVAL 30 DAY AND sale_status = 'Completed'
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
    from datetime import date
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
                           active_main='inventory', active_sub='expiring_medical',
                           now=date.today)

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
        
        # Log admin activity
        ip_address = request.remote_addr
        if request.headers.get('X-Forwarded-For'):
            ip_address = request.headers.get('X-Forwarded-For')
        
        try:
            cur.execute("""
                INSERT INTO admin_activity (admin_id, action, ip_address, details)
                VALUES (%s, %s, %s, %s)
            """, (session.get('admin_id'), 'Register Cashier', ip_address, f'Registered cashier: {username}'))
            mysql.connection.commit()
        except:
            pass
        
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
        
        # Get cashier info before deleting
        cur.execute("SELECT username FROM cashiers WHERE id=%s", (cashier_id,))
        cashier_info = cur.fetchone()
        cashier_username = cashier_info[0] if cashier_info else 'Unknown'
        
        cur.execute("DELETE FROM cashiers WHERE id=%s", (cashier_id,))
        mysql.connection.commit()
        
        # Log admin activity
        ip_address = request.remote_addr
        if request.headers.get('X-Forwarded-For'):
            ip_address = request.headers.get('X-Forwarded-For')
        
        try:
            cur.execute("""
                INSERT INTO admin_activity (admin_id, action, ip_address, details)
                VALUES (%s, %s, %s, %s)
            """, (session.get('admin_id'), 'Delete Cashier', ip_address, f'Deleted cashier: {cashier_username}'))
            mysql.connection.commit()
        except:
            pass
        
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
        
        # Log admin activity
        ip_address = request.remote_addr
        if request.headers.get('X-Forwarded-For'):
            ip_address = request.headers.get('X-Forwarded-For')
        
        try:
            cur.execute("""
                INSERT INTO admin_activity (admin_id, action, ip_address, details)
                VALUES (%s, %s, %s, %s)
            """, (session.get('admin_id'), 'Update Cashier', ip_address, f'Updated cashier: {username}'))
            mysql.connection.commit()
        except:
            pass
        
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
            cur.execute("UPDATE admins SET password=%s WHERE username=%s", (hashed, session['admin_user']))
            mysql.connection.commit()
            
            # Log admin activity
            ip_address = request.remote_addr
            if request.headers.get('X-Forwarded-For'):
                ip_address = request.headers.get('X-Forwarded-For')
            
            try:
                cur.execute("""
                    INSERT INTO admin_activity (admin_id, action, ip_address, details)
                    VALUES (%s, %s, %s, %s)
                """, (session.get('admin_id'), 'Change Password', ip_address, 'Admin changed password'))
                mysql.connection.commit()
            except:
                pass
            
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
            session['cashier_user'] = cashier[1]
            session['cashier_id'] = cashier[0]
            session['role'] = 'cashier'
            session.permanent = True  # Session persists on refresh
            
            cur = mysql.connection.cursor()
            
            # Get IP address
            ip_address = request.remote_addr
            if request.headers.get('X-Forwarded-For'):
                ip_address = request.headers.get('X-Forwarded-For')
            
            # Log cashier login with IP address
            cur.execute("""
                INSERT INTO cashier_activity (cashier_id, login_time, ip_address)
                VALUES (%s, NOW(), %s)
            """, (cashier[0], ip_address))
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
    """, (session['cashier_id'],))
    today_data = cur.fetchone()
    today_total = today_data[0] if today_data else 0
    today_count = today_data[1] if today_data else 0

    cur.execute("""
        SELECT sale_date, receipt_number, total_amount, sale_status 
        FROM sales 
        WHERE cashier_id = %s
        ORDER BY sale_date DESC 
        LIMIT 5
    """, (session['cashier_id'],))

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
    """, (session['cashier_id'],))
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
    """, (session['cashier_id'],))
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
    
    # Separate items by type
    medical_items = []
    non_medical_items = []
    
    for item in items:
        cur.execute("SELECT product_type FROM products WHERE id = %s", (item['id'],))
        result = cur.fetchone()
        product_type = result[0] if result else 'Non-Medical'
        
        if product_type == 'Medical':
            medical_items.append(item)
        else:
            non_medical_items.append(item)
    
    receipt_numbers = []
    receipt_items = []
    total_amount = 0
    
    # Process Medical items - create separate sale record
    if medical_items:
        receipt_number = f"REC-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}"
        receipt_numbers.append(receipt_number)
        medical_total = sum(item['price'] * item['quantity'] for item in medical_items)
        total_amount += medical_total
        
        cur.execute("""
            INSERT INTO sales (receipt_number, cashier_id, total_amount, sale_status, product_type, sale_date)
            VALUES (%s, %s, %s, 'Completed', 'Medical', NOW())
        """, (receipt_number, session['cashier_id'], medical_total))
        
        sale_id = cur.lastrowid
        
        for item in medical_items:
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
            
            receipt_items.append({
                'name': item['name'],
                'quantity': item['quantity'],
                'price': item['price'],
                'subtotal': item['price'] * item['quantity']
            })
    
    # Process Non-Medical items - create separate sale record
    if non_medical_items:
        receipt_number = f"REC-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}"
        receipt_numbers.append(receipt_number)
        non_medical_total = sum(item['price'] * item['quantity'] for item in non_medical_items)
        total_amount += non_medical_total
        
        cur.execute("""
            INSERT INTO sales (receipt_number, cashier_id, total_amount, sale_status, product_type, sale_date)
            VALUES (%s, %s, %s, 'Completed', 'Non-Medical', NOW())
        """, (receipt_number, session['cashier_id'], non_medical_total))
        
        sale_id = cur.lastrowid
        
        for item in non_medical_items:
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
            
            receipt_items.append({
                'name': item['name'],
                'quantity': item['quantity'],
                'price': item['price'],
                'subtotal': item['price'] * item['quantity']
            })
    
    mysql.connection.commit()
    cur.close()
    
    # Return main receipt number (first one) for display
    main_receipt = receipt_numbers[0] if receipt_numbers else 'N/A'
    
    return jsonify({
        'success': True,
        'receipt_number': main_receipt,
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

@app.route('/admin_logout')
def admin_logout():
    """Admin logout - only clears admin session, does not affect cashier"""
    # Log admin activity
    if 'admin_user' in session:
        cur = mysql.connection.cursor()
        # Get IP address
        ip_address = request.remote_addr
        if request.headers.get('X-Forwarded-For'):
            ip_address = request.headers.get('X-Forwarded-For')
        
        cur.execute("""
            INSERT INTO admin_activity (admin_id, action, ip_address, details)
            VALUES (%s, %s, %s, %s)
        """, (session.get('admin_id'), 'Admin Logout', ip_address, 'Admin logged out'))
        mysql.connection.commit()
        cur.close()
    
    # Only clear admin session keys, keep cashier session intact
    session.pop('admin_user', None)
    session.pop('admin_id', None)
    session.pop('role', None)
    
    return redirect(url_for('admin_login'))

@app.route('/cashier_logout')
def cashier_logout():
    """Cashier logout - clears cashier session and logs activity"""
    if 'cashier_user' in session:
        cur = mysql.connection.cursor()
        cashier_id = session.get('cashier_id')
        
        # Get IP address
        ip_address = request.remote_addr
        if request.headers.get('X-Forwarded-For'):
            ip_address = request.headers.get('X-Forwarded-For')
        
        # Log the logout time in cashier_activity
        cur.execute("""
            UPDATE cashier_activity
            SET logout_time = NOW(),
                ip_address = COALESCE(ip_address, %s)
            WHERE cashier_id = %s AND logout_time IS NULL
        """, (ip_address, cashier_id))
        mysql.connection.commit()
        cur.close()
    
    # Only clear cashier session keys, keep admin session intact
    session.pop('cashier_user', None)
    session.pop('cashier_id', None)
    session.pop('role', None)
    
    return redirect(url_for('cashier_login'))

@app.route('/logout')
def logout():
    """Legacy logout - determines role and logs out appropriately"""
    role = session.get('role')
    
    if role == 'admin':
        return redirect(url_for('admin_logout'))
    elif role == 'cashier':
        return redirect(url_for('cashier_logout'))
    
    # If no role, just clear everything
    session.clear()
    return redirect(url_for('admin_login'))

# =============================
# RUN APP
# =============================

if __name__ == '__main__':
    app.run(debug=True)
