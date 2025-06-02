 
from flask import Flask, jsonify, request, send_file, g
from datetime import datetime, timedelta
import sqlite3
import csv
from fpdf import FPDF
import os

app = Flask(__name__, static_folder='public', static_url_path='')

DATABASE = 'turni.db'

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
    return db

def init_db():
    with app.app_context():
        db = get_db()
        cursor = db.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS shifts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL,
                start TEXT NOT NULL,
                end TEXT,
                FOREIGN KEY (employee_id) REFERENCES employees (id)
            )
        ''')
        db.commit()

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

@app.route('/api/employees', methods=['GET', 'POST', 'DELETE'])
def manage_employees():
    db = get_db()
    cursor = db.cursor()
    
    if request.method == 'GET':
        cursor.execute('SELECT id, name FROM employees')
        employees = [{'id': row[0], 'name': row[1]} for row in cursor.fetchall()]
        return jsonify(employees)
    
    elif request.method == 'POST':
        data = request.json
        name = data['name'].strip()
        
        try:
            cursor.execute('INSERT INTO employees (name) VALUES (?)', (name,))
            db.commit()
            return jsonify({"status": "success", "id": cursor.lastrowid})
        except sqlite3.IntegrityError:
            return jsonify({"status": "error", "message": "Dipendente già esistente"}), 400
    
    elif request.method == 'DELETE':
        data = request.json
        employee_id = data['id']
        
        try:
            cursor.execute('DELETE FROM shifts WHERE employee_id = ?', (employee_id,))
            cursor.execute('DELETE FROM employees WHERE id = ?', (employee_id,))
            db.commit()
            return jsonify({"status": "success"})
        except:
            return jsonify({"status": "error"}), 500

@app.route('/api/toggle_shift', methods=['POST'])
def toggle_shift():
    data = request.json
    employee_id = data['id']
    
    db = get_db()
    cursor = db.cursor()
    
    # Cerca turno aperto
    cursor.execute('''
        SELECT id, start FROM shifts 
        WHERE employee_id = ? AND end IS NULL
    ''', (employee_id,))
    open_shift = cursor.fetchone()
    
    current_time = datetime.now().isoformat()
    
    if open_shift:
        # Chiudi turno
        cursor.execute('''
            UPDATE shifts SET end = ? 
            WHERE id = ?
        ''', (current_time, open_shift[0]))
    else:
        # Apri nuovo turno
        cursor.execute('''
            INSERT INTO shifts (employee_id, start) 
            VALUES (?, ?)
        ''', (employee_id, current_time))
    
    db.commit()
    return jsonify({"status": "success"})

@app.route('/api/toggle_all_shifts', methods=['POST'])
def toggle_all_shifts():
    data = request.json
    action = data['action']
    current_time = datetime.now().isoformat()
    
    db = get_db()
    cursor = db.cursor()
    
    if action == 'start':
        # Termina eventuali turni aperti
        cursor.execute('UPDATE shifts SET end = ? WHERE end IS NULL', (current_time,))
        
        # Inizia nuovi turni per tutti
        employees = cursor.execute('SELECT id FROM employees').fetchall()
        for emp in employees:
            cursor.execute('''
                INSERT INTO shifts (employee_id, start) 
                VALUES (?, ?)
            ''', (emp[0], current_time))
    
    elif action == 'end':
        # Termina tutti i turni aperti
        cursor.execute('UPDATE shifts SET end = ? WHERE end IS NULL', (current_time,))
    
    db.commit()
    return jsonify({"status": "success"})

@app.route('/api/shift_status', methods=['GET'])
def shift_status():
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute('''
        SELECT e.id, s.end IS NULL 
        FROM employees e
        LEFT JOIN shifts s ON e.id = s.employee_id AND s.end IS NULL
    ''')
    
    status = {row[0]: bool(row[1]) for row in cursor.fetchall()}
    return jsonify(status)

@app.route('/api/generate_report', methods=['POST'])
def generate_report():
    data = request.json
    employee_id = data.get('id', 'all')
    report_type = data['report_type']
    format = data['format']
    
    today = datetime.now().date()
    
    if report_type == 'daily':
        start_date = today
        end_date = today
    elif report_type == 'weekly':
        start_date = today - timedelta(days=today.weekday())
        end_date = start_date + timedelta(days=6)
    elif report_type == 'monthly':
        start_date = today.replace(day=1)
        end_date = (today.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    else:
        start_date = datetime.fromisoformat(data['start_date']).date()
        end_date = datetime.fromisoformat(data['end_date']).date()
    
    db = get_db()
    cursor = db.cursor()
    
    query = '''
        SELECT 
            e.name,
            s.start,
            s.end,
            (strftime('%s', s.end) - strftime('%s', s.start)) AS duration_seconds
        FROM shifts s
        JOIN employees e ON s.employee_id = e.id
        WHERE DATE(s.start) BETWEEN ? AND ?
    '''
    
    params = [start_date.isoformat(), end_date.isoformat()]
    
    if employee_id != 'all':
        query += ' AND e.id = ?'
        params.append(employee_id)
    
    cursor.execute(query, params)
    results = []
    
    for row in cursor.fetchall():
        start = row[1]
        end = row[2] or "In corso"
        duration_seconds = row[3]
        
        if duration_seconds:
            hours = duration_seconds // 3600
            minutes = (duration_seconds % 3600) // 60
            duration = f"{hours}h {minutes}m"
        else:
            duration = None
        
        results.append({
            'employee': row[0],
            'start': start,
            'end': end,
            'duration': duration
        })
    
    if format == 'csv':
        return generate_csv(results)
    elif format == 'pdf':
        return generate_pdf(results, employee_id, report_type, start_date, end_date)

def generate_csv(data):
    csv_file = 'report.csv'
    with open(csv_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Dipendente', 'Inizio', 'Fine', 'Durata'])
        for row in data:
            writer.writerow([
                row['employee'],
                row['start'],
                row['end'],
                row['duration'] or 'N/A'
            ])
    return send_file(csv_file, as_attachment=True)

def generate_pdf(data, employee_id, report_type, start_date, end_date):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, "Line Mode Srl - Report Turni", 0, 1, 'C')
    pdf.ln(5)
    
    pdf.set_font("Arial", size=12)
    
    if employee_id == 'all':
        employee_text = "Tutti i dipendenti"
    else:
        db = get_db()
        cursor = db.cursor()
        cursor.execute('SELECT name FROM employees WHERE id = ?', (employee_id,))
        employee_text = cursor.fetchone()[0]
    
    pdf.cell(0, 10, f"Dipendente: {employee_text}", 0, 1)
    pdf.cell(0, 10, f"Periodo: {report_type.capitalize()} ({start_date} - {end_date})", 0, 1)
    pdf.ln(10)
    
    if data:
        col_widths = [60, 40, 40, 30]
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(col_widths[0], 10, "Dipendente", 1)
        pdf.cell(col_widths[1], 10, "Inizio", 1)
        pdf.cell(col_widths[2], 10, "Fine", 1)
        pdf.cell(col_widths[3], 10, "Durata", 1, 1)
        
        pdf.set_font("Arial", size=10)
        for row in data:
            pdf.cell(col_widths[0], 10, row['employee'], 1)
            pdf.cell(col_widths[1], 10, format_datetime(row['start']), 1)
            pdf.cell(col_widths[2], 10, format_datetime(row['end']) if row['end'] != 'In corso' else "In corso", 1)
            pdf.cell(col_widths[3], 10, row['duration'] or 'N/A', 1, 1)
    else:
        pdf.cell(0, 10, "Nessun turno trovato nel periodo selezionato", 0, 1)
    
    pdf_file = 'report.pdf'
    pdf.output(pdf_file)
    return send_file(pdf_file, as_attachment=True)

def format_datetime(iso_str):
    if iso_str == 'In corso':
        return iso_str
    dt = datetime.fromisoformat(iso_str)
    return dt.strftime("%d/%m/%Y %H:%M")

if __name__ == '__main__':
    init_db()
    app.run(debug=True)