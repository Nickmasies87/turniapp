import os
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, send_file
import csv
from fpdf import FPDF
from supabase import create_client, Client

app = Flask(__name__)

# Configurazione Supabase con le tue chiavi
SUPABASE_URL = "https://zuzlirmfbupeljdbrhzr.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inp1emxpcm1mYnVwZWxqZGJyaHpyIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDg5MDM2MTgsImV4cCI6MjA2NDQ3OTYxOH0.aeNIL3Jw6kfocG3-CtSUjn6AR1dXHcvyj750tt1DpQQ"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Funzioni di supporto
def format_datetime(iso_str):
    if iso_str == 'In corso':
        return iso_str
    dt = datetime.fromisoformat(iso_str)
    return dt.strftime("%d/%m/%Y %H:%M")

def calculate_duration(start, end):
    if not end or end == 'In corso':
        return None
        
    start_dt = datetime.fromisoformat(start)
    end_dt = datetime.fromisoformat(end)
    duration = end_dt - start_dt
    hours, remainder = divmod(duration.total_seconds(), 3600)
    minutes, _ = divmod(remainder, 60)
    return f"{int(hours)}h {int(minutes)}m"

# API per gestire i dipendenti
@app.route('/api/employees', methods=['GET', 'POST', 'DELETE'])
def manage_employees():
    if request.method == 'GET':
        response = supabase.table('employees').select('*').execute()
        return jsonify(response.data)
    
    elif request.method == 'POST':
        data = request.json
        name = data['name'].strip()
        
        # Controlla se il dipendente esiste già
        existing = supabase.table('employees').select('id').eq('name', name).execute()
        if existing.data:
            return jsonify({"status": "error", "message": "Dipendente già esistente"}), 400
        
        # Inserisci il nuovo dipendente
        response = supabase.table('employees').insert({"name": name}).execute()
        return jsonify({"status": "success", "id": response.data[0]['id']})
    
    elif request.method == 'DELETE':
        data = request.json
        employee_id = data['id']
        
        # Elimina il dipendente
        supabase.table('employees').delete().eq('id', employee_id).execute()
        return jsonify({"status": "success"})

# API per gestire i turni
@app.route('/api/toggle_shift', methods=['POST'])
def toggle_shift():
    data = request.json
    employee_id = data['id']
    
    # Cerca un turno aperto
    response = supabase.table('shifts') \
        .select('*') \
        .eq('employee_id', employee_id) \
        .is_('end_time', 'null') \
        .execute()
    
    current_time = datetime.now().isoformat()
    
    if response.data:
        # Chiudi il turno esistente
        shift_id = response.data[0]['id']
        supabase.table('shifts') \
            .update({'end_time': current_time}) \
            .eq('id', shift_id) \
            .execute()
    else:
        # Apri un nuovo turno
        supabase.table('shifts') \
            .insert({
                'employee_id': employee_id,
                'start_time': current_time
            }).execute()
    
    return jsonify({"status": "success"})

@app.route('/api/toggle_all_shifts', methods=['POST'])
def toggle_all_shifts():
    data = request.json
    action = data['action']
    current_time = datetime.now().isoformat()
    
    if action == 'start':
        # Termina tutti i turni aperti
        supabase.table('shifts') \
            .update({'end_time': current_time}) \
            .is_('end_time', 'null') \
            .execute()
        
        # Prendi tutti i dipendenti
        employees = supabase.table('employees').select('id').execute()
        
        # Inizia nuovi turni per tutti
        for employee in employees.data:
            supabase.table('shifts') \
                .insert({
                    'employee_id': employee['id'],
                    'start_time': current_time
                }).execute()
    
    elif action == 'end':
        # Termina tutti i turni aperti
        supabase.table('shifts') \
            .update({'end_time': current_time}) \
            .is_('end_time', 'null') \
            .execute()
    
    return jsonify({"status": "success"})

@app.route('/api/shift_status', methods=['GET'])
def shift_status():
    # Trova tutti i turni aperti
    response = supabase.table('shifts') \
        .select('employee_id') \
        .is_('end_time', 'null') \
        .execute()
    
    active_shifts = {shift['employee_id']: True for shift in response.data}
    
    # Prendi tutti i dipendenti
    employees = supabase.table('employees').select('id').execute()
    
    # Crea lo status per ogni dipendente
    status = {emp['id']: emp['id'] in active_shifts for emp in employees.data}
    return jsonify(status)

@app.route('/api/generate_report', methods=['POST'])
def generate_report():
    data = request.json
    employee_id = data.get('id', 'all')
    report_type = data['report_type']
    format = data['format']
    
    today = datetime.now().date()
    
    # Calcola il periodo del report
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
    
    # Converti le date in datetime per includere l'intera giornata
    start_datetime = datetime.combine(start_date, datetime.min.time())
    end_datetime = datetime.combine(end_date, datetime.max.time())
    
    # Costruisci la query
    query = supabase.table('shifts') \
        .select('*, employees(name)') \
        .gte('start_time', start_datetime.isoformat()) \
        .lte('start_time', end_datetime.isoformat()) \
        .order('start_time', desc=False)
    
    if employee_id != 'all':
        query = query.eq('employee_id', employee_id)
    
    response = query.execute()
    shifts = response.data
    
    # Formatta i risultati
    results = []
    for shift in shifts:
        employee_name = shift['employees']['name'] if shift.get('employees') else "Sconosciuto"
        start_time = shift['start_time']
        end_time = shift['end_time'] or "In corso"
        
        results.append({
            'employee': employee_name,
            'start': start_time,
            'end': end_time,
            'duration': calculate_duration(start_time, end_time)
        })
    
    # Genera il report
    if format == 'csv':
        return generate_csv(results)
    elif format == 'pdf':
        employee_name = "Tutti i dipendenti" if employee_id == 'all' else results[0]['employee'] if results else "Nessun dipendente"
        return generate_pdf(results, employee_name, report_type, start_date, end_date)

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

def generate_pdf(data, employee, report_type, start_date, end_date):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, "Line Mode Srl - Report Turni", 0, 1, 'C')
    pdf.ln(5)
    
    pdf.set_font("Arial", size=12)
    pdf.cell(0, 10, f"Dipendente: {employee}", 0, 1)
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

@app.route('/')
def index():
    return send_file('../public/index.html')

if __name__ == '__main__':
    app.run(debug=True)