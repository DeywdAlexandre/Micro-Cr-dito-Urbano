from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash
import os
import psycopg2
import hashlib
import datetime
from decimal import Decimal

app = Flask(__name__)
app.secret_key = 'sua_secret_key_aqui'

def get_db_connection():
    try:
        conn = psycopg2.connect(os.getenv('DATABASE_URL'))
        return conn
    except Exception as e:
        print(f"Erro ao conectar ao banco de dados: {e}")
        return None

# Funções de hash (mantidas)
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# Rotas de autenticação (mantidas)
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = hash_password(request.form['password'])

        conn = get_db_connection()
        if not conn:
            flash('Erro de conexão com o banco de dados.')
            return redirect(url_for('login'))

        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(
            'SELECT u.*, o.name as org_name FROM users u LEFT JOIN organizations o ON u.organization_id = o.id WHERE u.username = %s AND u.password = %s',
            (username, password)
        )
        user = cur.fetchone()
        cur.close()
        conn.close()

        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            session['organization_id'] = user['organization_id']
            session['org_name'] = user['org_name']
            if user['role'] == 'master':
                return redirect(url_for('admin_panel'))
            else:
                return redirect(url_for('dashboard'))
        else:
            flash('Usuário ou senha inválidos!')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# Middleware para verificar autenticação (mantido)
def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Função para verificar se é master admin (mantida)
def master_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or session.get('role') != 'master':
            flash('Acesso negado!')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Função para filtrar por organização (mantida)
def get_user_organization():
    return session.get('organization_id')

# Painel administrativo
@app.route('/admin')
@master_required
def admin_panel():
    conn = get_db_connection()
    if not conn:
        flash('Erro de conexão com o banco de dados.')
        return redirect(url_for('login'))

    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    current_month = datetime.date.today().strftime('%Y-%m')
    
    cur.execute('''
        SELECT o.*, COUNT(u.id) as user_count
        FROM organizations o
        LEFT JOIN users u ON o.id = u.organization_id
        WHERE o.id > 0
        GROUP BY o.id
        ORDER BY o.name
    ''')
    organizations = cur.fetchall()

    cur.execute('''
        SELECT u.*, o.name as org_name,
                ub.status as payment_status,
                ub.payment_date as last_payment,
                CASE
                    WHEN u.start_date <= CURRENT_DATE THEN 'active'
                    ELSE 'future'
                END as billing_status
        FROM users u
        JOIN organizations o ON u.organization_id = o.id
        LEFT JOIN user_billing ub ON u.id = ub.user_id AND ub.month_year = %s
        WHERE u.role != 'master'
        ORDER BY o.name, u.username
    ''', (current_month,))
    users = cur.fetchall()

    cur.execute('''
        SELECT SUM(amount) as total
        FROM user_billing
        WHERE month_year = %s AND status = 'paid'
    ''', (current_month,))
    monthly_revenue = cur.fetchone()['total'] or 0

    cur.execute('''
        SELECT COUNT(*) as count
        FROM user_billing
        WHERE status = 'overdue'
    ''')
    overdue_payments = cur.fetchone()['count'] or 0

    cur.execute('''
        SELECT ub.*, u.username, o.name as org_name
        FROM user_billing ub
        JOIN users u ON ub.user_id = u.id
        JOIN organizations o ON u.organization_id = o.id
        WHERE ub.status = 'paid'
        ORDER BY ub.payment_date DESC
        LIMIT 10
    ''')
    recent_payments = cur.fetchall()
    
    cur.close()
    conn.close()

    return render_template('admin_panel.html',
                           organizations=organizations,
                           users=users,
                           monthly_revenue=float(monthly_revenue),
                           overdue_payments=overdue_payments,
                           recent_payments=recent_payments)

@app.route('/admin/mark_payment_paid/<int:user_id>', methods=['POST'])
@master_required
def mark_payment_paid(user_id):
    current_month = datetime.date.today().strftime('%Y-%m')
    conn = get_db_connection()
    if not conn:
        return jsonify({'success': False, 'error': 'Erro de conexão com o banco de dados.'})
    cur = conn.cursor()

    try:
        cur.execute('SELECT monthly_fee, start_date FROM users WHERE id = %s', (user_id,))
        user = cur.fetchone()
        
        if user[1]:
            start_date = user[1]
            current_month_date = datetime.date.today().replace(day=1)
            
            if start_date > current_month_date:
                return jsonify({'success': False, 'error': 'Usuário ainda não deve ser cobrado neste mês'})

        cur.execute('''
            INSERT INTO user_billing (user_id, month_year, amount, payment_date, status, start_date)
            VALUES (%s, %s, %s, %s, 'paid', %s)
            ON CONFLICT (user_id, month_year) DO UPDATE SET amount = EXCLUDED.amount, payment_date = EXCLUDED.payment_date, status = EXCLUDED.status, start_date = EXCLUDED.start_date
        ''', (user_id, current_month, user[0], datetime.date.today(), user[1]))
        
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()

@app.route('/admin/delete_user/<int:user_id>', methods=['DELETE'])
@master_required
def delete_user(user_id):
    conn = get_db_connection()
    if not conn:
        return jsonify({'success': False, 'error': 'Erro de conexão com o banco de dados.'})
    cur = conn.cursor()
    try:
        cur.execute('SELECT organization_id FROM users WHERE id = %s', (user_id,))
        org_id_row = cur.fetchone()
        if org_id_row:
            org_id = org_id_row[0]
            cur.execute('DELETE FROM user_billing WHERE user_id = %s', (user_id,))
            cur.execute('DELETE FROM payments WHERE organization_id = %s', (org_id,))
            cur.execute('DELETE FROM loans WHERE organization_id = %s', (org_id,))
            cur.execute('DELETE FROM clients WHERE organization_id = %s', (org_id,))
            cur.execute('DELETE FROM users WHERE id = %s', (user_id,))
        
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()

@app.route('/admin/update_user_fee/<int:user_id>', methods=['POST'])
@master_required
def update_user_fee(user_id):
    data = request.get_json()
    monthly_fee = data.get('monthly_fee')
    
    if not monthly_fee or float(monthly_fee) <= 0:
        return jsonify({'success': False, 'error': 'Valor inválido'})
    
    conn = get_db_connection()
    if not conn:
        return jsonify({'success': False, 'error': 'Erro de conexão com o banco de dados.'})
    cur = conn.cursor()
    try:
        cur.execute('UPDATE users SET monthly_fee = %s WHERE id = %s', (monthly_fee, user_id))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()

@app.route('/admin/mark_all_payments_paid', methods=['POST'])
@master_required
def mark_all_payments_paid():
    current_month = datetime.date.today().strftime('%Y-%m')
    conn = get_db_connection()
    if not conn:
        return jsonify({'success': False, 'error': 'Erro de conexão com o banco de dados.'})
    cur = conn.cursor()

    try:
        cur.execute('''
            SELECT u.id, u.monthly_fee, u.start_date
            FROM users u
            LEFT JOIN user_billing ub ON u.id = ub.user_id AND ub.month_year = %s
            WHERE u.role != 'master'
            AND (u.start_date IS NULL OR u.start_date <= CURRENT_DATE)
            AND (ub.status IS NULL OR ub.status != 'paid')
        ''', (current_month,))
        users = cur.fetchall()

        for user_id, monthly_fee, start_date in users:
            cur.execute('''
                INSERT INTO user_billing (user_id, month_year, amount, payment_date, status, start_date)
                VALUES (%s, %s, %s, %s, 'paid', %s)
                ON CONFLICT (user_id, month_year) DO UPDATE SET amount = EXCLUDED.amount, payment_date = EXCLUDED.payment_date, status = EXCLUDED.status, start_date = EXCLUDED.start_date
            ''', (user_id, current_month, monthly_fee, datetime.date.today(), start_date))
        
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()

@app.route('/admin/create_user', methods=['GET', 'POST'])
@master_required
def create_user():
    conn = get_db_connection()
    if not conn:
        flash('Erro de conexão com o banco de dados.')
        return redirect(url_for('admin_panel'))
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    if request.method == 'POST':
        username = request.form['username']
        password = hash_password(request.form['password'])
        org_name = request.form['org_name']
        monthly_fee = float(request.form['monthly_fee'])
        start_date = datetime.datetime.strptime(request.form['start_date'], '%Y-%m-%d').date()
        
        try:
            cur.execute('SELECT id FROM organizations WHERE name = %s', (org_name,))
            org = cur.fetchone()
            if not org:
                cur.execute('INSERT INTO organizations (name) VALUES (%s) RETURNING id', (org_name,))
                org_id = cur.fetchone()[0]
            else:
                org_id = org['id']
            
            cur.execute('''
                INSERT INTO users (username, password, role, organization_id, monthly_fee, start_date)
                VALUES (%s, %s, 'user', %s, %s, %s)
            ''', (username, password, org_id, monthly_fee, start_date))
            
            conn.commit()
            flash(f'Usuário {username} criado com sucesso! Valor mensal: R$ {monthly_fee:.2f}')
            return redirect(url_for('admin_panel'))
            
        except psycopg2.IntegrityError:
            conn.rollback()
            flash('Nome de usuário já existe!')
        except Exception as e:
            conn.rollback()
            flash(f'Ocorreu um erro: {str(e)}')
        finally:
            cur.close()
            conn.close()

    cur.execute('SELECT * FROM organizations WHERE id > 0 ORDER BY name')
    organizations = cur.fetchall()
    cur.close()
    conn.close()
    
    return render_template('create_user.html', organizations=organizations)

@app.route('/')
@login_required
def dashboard():
    if session.get('role') == 'master':
        return redirect(url_for('admin_panel'))
    
    org_id = get_user_organization()
    conn = get_db_connection()
    if not conn:
        flash('Erro de conexão com o banco de dados.')
        return redirect(url_for('login'))
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    stats = {}
    
    cur.execute('SELECT SUM(amount) as total FROM loans WHERE status = %s AND organization_id = %s', ('active', org_id))
    stats['total_lent'] = cur.fetchone()['total'] or 0
    
    cur.execute('SELECT SUM(total_amount) as total FROM loans WHERE status = %s AND organization_id = %s', ('active', org_id))
    stats['total_to_receive'] = cur.fetchone()['total'] or 0
    
    cur.execute('SELECT SUM(amount) as total FROM payments WHERE organization_id = %s', (org_id,))
    stats['total_received'] = cur.fetchone()['total'] or 0
    
    today = datetime.date.today()
    cur.execute('''SELECT COUNT(DISTINCT l.client_id) as count
                 FROM loans l WHERE l.due_date < %s AND l.status = %s AND l.organization_id = %s''',
                (today, 'active', org_id))
    stats['overdue_clients'] = cur.fetchone()['count'] or 0
    
    next_week = today + datetime.timedelta(days=7)
    cur.execute('''
        SELECT l.*, c.full_name
        FROM loans l
        JOIN clients c ON l.client_id = c.id
        WHERE l.due_date BETWEEN %s AND %s AND l.status = %s AND l.organization_id = %s
        ORDER BY l.due_date
    ''', (today, next_week, 'active', org_id))
    upcoming_loans = cur.fetchall()
    
    cur.execute('''
        SELECT l.*, c.full_name
        FROM loans l
        JOIN clients c ON l.client_id = c.id
        WHERE l.due_date < %s AND l.status = %s AND l.organization_id = %s
        ORDER BY l.due_date
    ''', (today, 'active', org_id))
    overdue_loans = cur.fetchall()
    
    cur.close()
    conn.close()
    
    return render_template('dashboard.html',
                           stats=stats,
                           upcoming_loans=upcoming_loans,
                           overdue_loans=overdue_loans)

@app.route('/clients')
@login_required
def clients():
    org_id = get_user_organization()
    conn = get_db_connection()
    if not conn:
        flash('Erro de conexão com o banco de dados.')
        return redirect(url_for('login'))
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    cur.execute('''
        SELECT c.*,
                COUNT(l.id) as loan_count,
                SUM(CASE WHEN l.status = %s THEN l.total_amount ELSE 0 END) as total_debt
        FROM clients c
        LEFT JOIN loans l ON c.id = l.client_id AND l.organization_id = %s
        WHERE c.organization_id = %s
        GROUP BY c.id
        ORDER BY c.full_name
    ''', ('active', org_id, org_id))
    clients = cur.fetchall()
    cur.close()
    conn.close()
    
    return render_template('clients.html', clients=clients)

@app.route('/add_client', methods=['GET', 'POST'])
@login_required
def add_client():
    org_id = get_user_organization()
    if request.method == 'POST':
        conn = get_db_connection()
        if not conn:
            flash('Erro de conexão com o banco de dados.')
            return redirect(url_for('clients'))
        cur = conn.cursor()
        try:
            cur.execute('''
                INSERT INTO clients (full_name, document, phone, email, address, organization_id)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', (
                request.form['full_name'],
                request.form['document'],
                request.form['phone'],
                request.form['email'],
                request.form['address'],
                org_id
            ))
            conn.commit()
            flash('Cliente cadastrado com sucesso!')
            return redirect(url_for('clients'))
        except psycopg2.IntegrityError:
            conn.rollback()
            flash('Documento já cadastrado nesta organização!')
        except Exception as e:
            conn.rollback()
            flash(f'Ocorreu um erro: {str(e)}')
        finally:
            cur.close()
            conn.close()
    
    return render_template('add_client.html')

@app.route('/loans')
@login_required
def loans():
    org_id = get_user_organization()
    conn = get_db_connection()
    if not conn:
        flash('Erro de conexão com o banco de dados.')
        return redirect(url_for('login'))
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    cur.execute('''
        SELECT l.*, c.full_name, c.document,
                (l.total_amount - COALESCE(SUM(p.amount), 0)) as remaining_amount
        FROM loans l
        JOIN clients c ON l.client_id = c.id
        LEFT JOIN payments p ON l.id = p.loan_id
        WHERE l.organization_id = %s
        GROUP BY l.id
        ORDER BY l.loan_date DESC
    ''', (org_id,))
    loans = cur.fetchall()
    cur.close()
    conn.close()
    
    loans_list = []
    today = datetime.date.today()
    
    for loan in loans:
        loan_dict = dict(loan)
        due_date = loan['due_date']
        is_overdue = loan['status'] == 'active' and due_date < today
        loan_dict['is_overdue'] = is_overdue
        loans_list.append(loan_dict)
    
    return render_template('loans.html', loans=loans_list)

@app.route('/add_loan', methods=['GET', 'POST'])
@login_required
def add_loan():
    conn = get_db_connection()
    if not conn:
        flash('Erro de conexão com o banco de dados.')
        return redirect(url_for('login'))
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    if request.method == 'POST':
        client_id = int(request.form['client_id'])
        amount = float(request.form['amount'])
        interest_rate = float(request.form['interest_rate'])
        loan_type = request.form['loan_type']
        loan_date = datetime.datetime.strptime(request.form['loan_date'], '%Y-%m-%d').date()
        
        if loan_type == 'single':
            installments = 1
            total_amount = amount * (1 + interest_rate / 100)
            installment_amount = total_amount
            due_date = datetime.datetime.strptime(request.form['due_date'], '%Y-%m-%d').date()
        else:
            installments = int(request.form['installments'])
            total_amount = amount * (1 + interest_rate / 100)
            installment_amount = total_amount / installments
            due_date = loan_date + datetime.timedelta(days=30)
        
        org_id = get_user_organization()
        try:
            cur.execute('''
                INSERT INTO loans (client_id, amount, interest_rate, loan_type,
                                 installments, installment_amount, total_amount,
                                 loan_date, due_date, organization_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (client_id, amount, interest_rate, loan_type,
                  installments, installment_amount, total_amount,
                  loan_date, due_date, org_id))
            
            conn.commit()
            flash('Empréstimo cadastrado com sucesso!')
            return redirect(url_for('loans'))
        except Exception as e:
            conn.rollback()
            flash(f'Ocorreu um erro: {str(e)}')
        finally:
            cur.close()
            conn.close()
    
    org_id = get_user_organization()
    cur.execute('SELECT * FROM clients WHERE organization_id = %s ORDER BY full_name', (org_id,))
    clients = cur.fetchall()
    cur.close()
    conn.close()
    
    return render_template('add_loan.html', clients=clients)

@app.route('/loan/<int:loan_id>')
@login_required
def loan_detail(loan_id):
    org_id = get_user_organization()
    conn = get_db_connection()
    if not conn:
        flash('Erro de conexão com o banco de dados.')
        return redirect(url_for('login'))
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    cur.execute('''
        SELECT l.*, c.full_name, c.document, c.phone, c.email
        FROM loans l
        JOIN clients c ON l.client_id = c.id
        WHERE l.id = %s AND l.organization_id = %s
    ''', (loan_id, org_id))
    loan = cur.fetchone()
    
    cur.execute('''
        SELECT * FROM payments
        WHERE loan_id = %s
        ORDER BY payment_date DESC
    ''', (loan_id,))
    payments = cur.fetchall()
    
    cur.execute('''
        SELECT SUM(amount) as total
        FROM payments
        WHERE loan_id = %s
    ''', (loan_id,))
    total_paid = cur.fetchone()['total'] or 0
    
    cur.close()
    conn.close()
    
    if not loan:
        flash('Empréstimo não encontrado!')
        return redirect(url_for('loans'))
    
    remaining = float(loan['total_amount']) - float(total_paid)
    
    today = datetime.date.today()
    due_date = loan['due_date']
    is_overdue = loan['status'] == 'active' and due_date < today
    
    return render_template('loan_detail.html',
                           loan=loan,
                           payments=payments,
                           total_paid=float(total_paid),
                           remaining=remaining,
                           is_overdue=is_overdue)

@app.route('/reports')
@login_required
def reports():
    return render_template('reports.html')

@app.route('/add_payment/<int:loan_id>', methods=['POST'])
@login_required
def add_payment(loan_id):
    org_id = get_user_organization()
    amount = float(request.form['amount'])
    payment_type = request.form['payment_type']
    payment_date = datetime.datetime.strptime(request.form['payment_date'], '%Y-%m-%d').date()
    notes = request.form.get('notes', '')
    
    conn = get_db_connection()
    if not conn:
        flash('Erro de conexão com o banco de dados.')
        return redirect(url_for('loan_detail', loan_id=loan_id))
    cur = conn.cursor()

    try:
        cur.execute('''
            INSERT INTO payments (loan_id, amount, payment_type, payment_date, notes, organization_id)
            VALUES (%s, %s, %s, %s, %s, %s)
        ''', (loan_id, amount, payment_type, payment_date, notes, org_id))
        
        cur.execute('SELECT total_amount FROM loans WHERE id = %s', (loan_id,))
        loan = cur.fetchone()
        
        cur.execute('SELECT SUM(amount) as total FROM payments WHERE loan_id = %s', (loan_id,))
        total_paid = cur.fetchone()[0] or 0
        
        if total_paid and float(total_paid) >= float(loan[0]):
            cur.execute('UPDATE loans SET status = %s WHERE id = %s', ('paid', loan_id))
        
        conn.commit()
        flash('Pagamento registrado com sucesso!')
    except Exception as e:
        conn.rollback()
        flash(f'Ocorreu um erro: {str(e)}')
    finally:
        cur.close()
        conn.close()
    
    return redirect(url_for('loan_detail', loan_id=loan_id))

@app.route('/api/profit_data')
@login_required
def api_profit_data():
    org_id = get_user_organization()
    conn = get_db_connection()
    if not conn:
        return jsonify([])
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    cur.execute('''
        SELECT
            EXTRACT(YEAR FROM l.loan_date) as year,
            EXTRACT(MONTH FROM l.loan_date) as month,
            SUM(l.amount) as total_lent,
            COUNT(l.id) as loan_count
        FROM loans l
        WHERE l.organization_id = %s
        GROUP BY year, month
        ORDER BY year DESC, month DESC
    ''', (org_id,))
    monthly_data = cur.fetchall()
    
    cur.execute('''
        SELECT
            EXTRACT(YEAR FROM p.payment_date) as year,
            EXTRACT(MONTH FROM p.payment_date) as month,
            SUM(p.amount) as total_received
        FROM payments p
        WHERE p.organization_id = %s
        GROUP BY year, month
        ORDER BY year DESC, month DESC
    ''', (org_id,))
    payment_data = cur.fetchall()
    
    cur.close()
    conn.close()
    
    payments_dict = {}
    for payment in payment_data:
        key = f"{int(payment['year'])}-{int(payment['month'])}"
        payments_dict[key] = float(payment['total_received']) if payment['total_received'] else 0
    
    profit_data = []
    month_names = {
        1: 'Janeiro', 2: 'Fevereiro', 3: 'Março', 4: 'Abril',
        5: 'Maio', 6: 'Junho', 7: 'Julho', 8: 'Agosto',
        9: 'Setembro', 10: 'Outubro', 11: 'Novembro', 12: 'Dezembro'
    }
    
    for loan_month in monthly_data:
        key = f"{int(loan_month['year'])}-{int(loan_month['month'])}"
        total_lent = float(loan_month['total_lent']) if loan_month['total_lent'] else 0
        total_received = payments_dict.get(key, 0)
        profit = total_received - total_lent
        margin = (profit / total_lent * 100) if total_lent > 0 else 0
        
        profit_data.append({
            'year': int(loan_month['year']),
            'month': int(loan_month['month']),
            'month_name': month_names.get(int(loan_month['month']), str(loan_month['month'])),
            'total_lent': total_lent,
            'total_received': total_received,
            'profit': profit,
            'margin': margin,
            'loan_count': loan_month['loan_count']
        })
    
    return jsonify(profit_data)

@app.route('/api/dashboard_stats')
@login_required
def api_dashboard_stats():
    org_id = get_user_organization()
    conn = get_db_connection()
    if not conn:
        return jsonify([])
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    cur.execute('''
        SELECT TO_CHAR(loan_date, 'YYYY-MM') as month,
               SUM(amount) as total_amount,
               COUNT(*) as loan_count
        FROM loans
        WHERE loan_date >= (CURRENT_DATE - INTERVAL '12 months') AND organization_id = %s
        GROUP BY month
        ORDER BY month
    ''', (org_id,))
    monthly_loans = cur.fetchall()
    
    cur.execute('''
        SELECT TO_CHAR(payment_date, 'YYYY-MM') as month,
               SUM(amount) as total_amount
        FROM payments
        WHERE payment_date >= (CURRENT_DATE - INTERVAL '12 months') AND organization_id = %s
        GROUP BY month
        ORDER BY month
    ''', (org_id,))
    payment_stats = cur.fetchall()
    
    cur.close()
    conn.close()
    
    return jsonify({
        'monthly_loans': [dict(row) for row in monthly_loans],
        'payment_stats': [dict(row) for row in payment_stats]
    })

# PONTO IMPORTANTE: Removido o if __name__ == '__main__':
# O Vercel usa o Gunicorn para rodar sua aplicação, então esta seção não é necessária.
# O Vercel também não executa init_db() automaticamente, então você precisará criar as tabelas
# manualmente no painel do Supabase.

# Se o erro de "Internal Server Error" persistir, verifique se a URL de conexão
# está correta nas variáveis de ambiente do Vercel e se você substituiu a senha.
