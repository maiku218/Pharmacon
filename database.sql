-- PharmaCon Database Schema
-- Run this SQL to create the database and tables

-- Create database
CREATE DATABASE IF NOT EXISTS pharmacon;
USE pharmacon;

-- Admins table
CREATE TABLE IF NOT EXISTS admins (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(100) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL,
    full_name VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Cashiers table
CREATE TABLE IF NOT EXISTS cashiers (
    id INT AUTO_INCREMENT PRIMARY KEY,
    full_name VARCHAR(100),
    username VARCHAR(100) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL,
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Cashier Activity (login/logout tracking) - UPDATED with IP address
CREATE TABLE IF NOT EXISTS cashier_activity (
    id INT AUTO_INCREMENT PRIMARY KEY,
    cashier_id INT NOT NULL,
    login_time DATETIME NOT NULL,
    logout_time DATETIME DEFAULT NULL,
    ip_address VARCHAR(45) DEFAULT NULL,
    FOREIGN KEY (cashier_id) REFERENCES cashiers(id) ON DELETE CASCADE
);

-- Admin Activity (detailed admin actions tracking) - NEW
CREATE TABLE IF NOT EXISTS admin_activity (
    id INT AUTO_INCREMENT PRIMARY KEY,
    admin_id INT NOT NULL,
    action VARCHAR(100) NOT NULL,
    ip_address VARCHAR(45) DEFAULT NULL,
    details TEXT,
    activity_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (admin_id) REFERENCES admins(id) ON DELETE CASCADE
);

-- Categories table
CREATE TABLE IF NOT EXISTS categories (
    id INT AUTO_INCREMENT PRIMARY KEY,
    category_name VARCHAR(100) NOT NULL,
    description TEXT
);

-- Products table
CREATE TABLE IF NOT EXISTS products (
    id INT AUTO_INCREMENT PRIMARY KEY,
    product_name VARCHAR(200) NOT NULL,
    barcode VARCHAR(100) DEFAULT NULL,
    category_id INT,
    product_type VARCHAR(50) DEFAULT 'medical',
    price DECIMAL(10,2) NOT NULL,
    stock INT DEFAULT 0,
    expiration_date DATE DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (category_id) REFERENCES categories(id)
);

-- Stock Movements table
CREATE TABLE IF NOT EXISTS stock_movements (
    id INT AUTO_INCREMENT PRIMARY KEY,
    product_id INT NOT NULL,
    movement_type VARCHAR(10) NOT NULL,
    quantity INT NOT NULL,
    reason VARCHAR(100),
    movement_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
);

-- Sales table
CREATE TABLE IF NOT EXISTS sales (
    id INT AUTO_INCREMENT PRIMARY KEY,
    receipt_number VARCHAR(50) UNIQUE NOT NULL,
    cashier_id INT NOT NULL,
    total_amount DECIMAL(10,2) NOT NULL,
    sale_status VARCHAR(20) DEFAULT 'Completed',
    product_type VARCHAR(20) DEFAULT 'medical',
    sale_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (cashier_id) REFERENCES cashiers(id)
);

-- Sale Items table
CREATE TABLE IF NOT EXISTS sale_items (
    id INT AUTO_INCREMENT PRIMARY KEY,
    sale_id INT NOT NULL,
    product_id INT NOT NULL,
    quantity INT NOT NULL,
    price DECIMAL(10,2) NOT NULL,
    FOREIGN KEY (sale_id) REFERENCES sales(id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(id)
);

-- Insert default admin (username: admin, password: admin123)
INSERT INTO admins (username, password, full_name) 
VALUES ('admin', 'scrypt:32768:8:1$rJfOriv0msJHOVQT$00f8266d42bd6a0b3d79d169bf1e83c468b54300170fb5fbc2d83fd6780326ef612b61310f4d54fb955fabe72d240a538739f0559a1674036faa3cb6b118090d', 'System Administrator');

-- Insert sample categories
INSERT INTO categories (category_name, description) VALUES 
('Medical', 'Medical products and medicines'),
('Non-Medical', 'Supplies and hygiene products');

-- Fix: Update product types to use correct case ('Medical', 'Non-Medical')
-- This fixes the case sensitivity issue where products were stored as lowercase
UPDATE products SET product_type = 'Medical' WHERE product_type = 'medical';
UPDATE products SET product_type = 'Non-Medical' WHERE product_type = 'non_medical';

-- Fix: Update sales product_type to use correct case
-- This ensures sales are properly categorized in reports
UPDATE sales SET product_type = 'Medical' WHERE product_type = 'medical';
UPDATE sales SET product_type = 'Non-Medical' WHERE product_type = 'non_medical';
