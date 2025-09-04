# ultima alteracao
import os
import hashlib
import psycopg2
from flask import Flask, render_template, request, redirect, url_for, session, flash
from datetime import date

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'your_super_secret_key')

# Configuração da conexão com o banco de dados PostgreSQL
def get_db_connection():
    try:
        conn = psycopg2.connect(os.environ.get('DATABASE_URL'))
        return conn
    except Exception as e:
        print(f"Erro ao conectar ao banco de dados: {e}")
        return None

# Função para hash da senha
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# Rota para a página de login
@app.route('/', methods=['GET', 'POST'])
def login():
    if 'username' in session:
        if session.get('role') == 'master':
            return redirect(url_for('admin_panel'))
        else:
            return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        hashed_password = hash_password(password)

        conn = get_db_connection()
        if conn is None:
            flash('Erro ao conectar ao banco de dados. Tente novamente mais tarde.', 'danger')
            return redirect(url_for('login'))
            
        cur = conn.cursor()
        cur.execute("SELECT id, username, role, organization_id FROM users WHERE username = %s AND password = %s", (username, hashed_password))
        user = cur.fetchone()
        cur.close()
        conn.close()

        if user:
            session['username'] = user[1]
            session['role'] = user[2]
            session['organization_id'] = user[3]
            
            flash('Login bem-sucedido!', 'success')
            if session.get('role') == 'master':
                return redirect(url_for('admin_panel'))
            else:
                return redirect(url_for('dashboard'))
        else:
            flash('Nome de usuário ou senha incorretos.', 'danger')
            return redirect(url_for('login'))

    return render_template('login.html')

# Rota para o painel de administrador (apenas para o usuário "master")
@app.route('/admin_panel')
def admin_panel():
    if 'username' not in session or session.get('role') != 'master':
        return redirect(url_for('login'))

    conn = get_db_connection()
    if conn is None:
        return "Erro ao conectar ao banco de dados.", 500
        
    cur = conn.cursor()
    cur.execute("SELECT id, username, organization_id, start_date FROM users WHERE role != 'master'")
    users = cur.fetchall()
    cur.close()
    conn.close()
    
    return render_template('admin_panel.html', users=users)

# Rota para adicionar um novo usuário
@app.route('/add_user', methods=['POST'])
def add_user():
    if 'username' not in session or session.get('role') != 'master':
        flash('Acesso negado.', 'danger')
        return redirect(url_for('login'))

    username = request.form['username']
    password = request.form['password']
    organization_name = request.form['organization_name']
    hashed_password = hash_password(password)

    conn = get_db_connection()
    if conn is None:
        return "Erro ao conectar ao banco de dados.", 500
        
    try:
        cur = conn.cursor()

        cur.execute("INSERT INTO organizations (name) VALUES (%s) RETURNING id", (organization_name,))
        organization_id = cur.fetchone()[0]

        cur.execute("INSERT INTO users (username, password, role, organization_id, start_date) VALUES (%s, %s, %s, %s, NOW())",
                    (username, hashed_password, 'user', organization_id))

        conn.commit()
        cur.close()
        conn.close()
        flash('Usuário e organização adicionados com sucesso!', 'success')

    except Exception as e:
        conn.rollback()
        print(f"Erro ao adicionar usuário: {e}")
        flash(f'Erro ao adicionar usuário: {e}', 'danger')
        conn.close()

    return redirect(url_for('admin_panel'))

# Rota para o painel do usuário
@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return redirect(url_for('login'))
        
    organization_id = session.get('organization_id')
    conn = get_db_connection()
    if conn is None:
        return "Erro ao conectar ao banco de dados.", 500
        
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM clients WHERE organization_id = %s", (organization_id,))
    client_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM loans WHERE organization_id = %s", (organization_id,))
    loan_count = cur.fetchone()[0]
    cur.execute("SELECT SUM(total_amount) FROM loans WHERE organization_id = %s", (organization_id,))
    total_loaned = cur.fetchone()[0] or 0.00
    cur.execute("SELECT SUM(amount) FROM payments WHERE organization_id = %s", (organization_id,))
    total_received = cur.fetchone()[0] or 0.00
    cur.close()
    conn.close()

    return render_template('dashboard.html', client_count=client_count, loan_count=loan_count, total_loaned=total_loaned, total_received=total_received)

# Rota para a lista de clientes
@app.route('/clients')
def clients():
    if 'username' not in session:
        return redirect(url_for('login'))
    
    organization_id = session.get('organization_id')
    conn = get_db_connection()
    if conn is None:
        return "Erro ao conectar ao banco de dados.", 500
        
    cur = conn.cursor()
    cur.execute("SELECT * FROM clients WHERE organization_id = %s", (organization_id,))
    clients_list = cur.fetchall()
    cur.close()
    conn.close()

    return render_template('clients.html', clients=clients_list)

# Rota para adicionar um cliente
@app.route('/add_client', methods=['POST'])
def add_client():
    if 'username' not in session:
        return redirect(url_for('login'))
    
    full_name = request.form['full_name']
    document = request.form['document']
    phone = request.form['phone']
    email = request.form['email']
    address = request.form['address']
    organization_id = session.get('organization_id')

    conn = get_db_connection()
    if conn is None:
        return "Erro ao conectar ao banco de dados.", 500
        
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO clients (full_name, document, phone, email, address, organization_id) VALUES (%s, %s, %s, %s, %s, %s)",
                    (full_name, document, phone, email, address, organization_id))
        conn.commit()
        cur.close()
        conn.close()
        flash('Cliente adicionado com sucesso!', 'success')
    except Exception as e:
        conn.rollback()
        print(f"Erro ao adicionar cliente: {e}")
        flash(f'Erro ao adicionar cliente: {e}', 'danger')
        conn.close()

    return redirect(url_for('clients'))

# Rota para a lista de empréstimos
@app.route('/loans')
def loans():
    if 'username' not in session:
        return redirect(url_for('login'))
    
    organization_id = session.get('organization_id')
    conn = get_db_connection()
    if conn is None:
        return "Erro ao conectar ao banco de dados.", 500

    cur = conn.cursor()
    cur.execute("SELECT l.id, c.full_name, l.amount, l.interest_rate, l.loan_type, l.installments, l.installment_amount, l.total_amount, l.loan_date, l.due_date, l.status FROM loans l JOIN clients c ON l.client_id = c.id WHERE l.organization_id = %s", (organization_id,))
    loans_list = cur.fetchall()
    cur.close()

    cur = conn.cursor()
    cur.execute("SELECT id, full_name FROM clients WHERE organization_id = %s", (organization_id,))
    clients_list = cur.fetchall()
    cur.close()
    conn.close()

    return render_template('loans.html', loans=loans_list, clients=clients_list)

# Rota para adicionar um empréstimo
@app.route('/add_loan', methods=['POST'])
def add_loan():
    if 'username' not in session:
        return redirect(url_for('login'))
    
    client_id = request.form['client_id']
    amount = float(request.form['amount'])
    interest_rate = float(request.form['interest_rate'])
    loan_type = request.form['loan_type']
    installments = int(request.form['installments'])
    loan_date = date.today()
    organization_id = session.get('organization_id')

    # Calcula o valor da parcela e o valor total
    installment_amount = amount / installments
    total_amount = amount + (amount * (interest_rate / 100))

    conn = get_db_connection()
    if conn is None:
        return "Erro ao conectar ao banco de dados.", 500

    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO loans (client_id, amount, interest_rate, loan_type, installments, installment_amount, total_amount, loan_date, organization_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (client_id, amount, interest_rate, loan_type, installments, installment_amount, total_amount, loan_date, organization_id))
        conn.commit()
        cur.close()
        conn.close()
        flash('Empréstimo adicionado com sucesso!', 'success')
    except Exception as e:
        conn.rollback()
        print(f"Erro ao adicionar empréstimo: {e}")
        flash(f'Erro ao adicionar empréstimo: {e}', 'danger')
        conn.close()

    return redirect(url_for('loans'))

# Rota para a lista de pagamentos
@app.route('/payments')
def payments():
    if 'username' not in session:
        return redirect(url_for('login'))
    
    organization_id = session.get('organization_id')
    conn = get_db_connection()
    if conn is None:
        return "Erro ao conectar ao banco de dados.", 500
        
    cur = conn.cursor()
    cur.execute("SELECT p.id, c.full_name, p.amount, p.payment_date, p.payment_type, p.notes FROM payments p JOIN loans l ON p.loan_id = l.id JOIN clients c ON l.client_id = c.id WHERE p.organization_id = %s", (organization_id,))
    payments_list = cur.fetchall()
    cur.close()

    cur = conn.cursor()
    cur.execute("SELECT id, amount, total_amount, loan_date FROM loans WHERE organization_id = %s", (organization_id,))
    loans_list = cur.fetchall()
    cur.close()
    conn.close()

    return render_template('payments.html', payments=payments_list, loans=loans_list)

# Rota para adicionar um pagamento
@app.route('/add_payment', methods=['POST'])
def add_payment():
    if 'username' not in session:
        return redirect(url_for('login'))
    
    loan_id = request.form['loan_id']
    amount = float(request.form['amount'])
    payment_type = request.form['payment_type']
    payment_date = date.today()
    notes = request.form['notes']
    organization_id = session.get('organization_id')

    conn = get_db_connection()
    if conn is None:
        return "Erro ao conectar ao banco de dados.", 500
    
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO payments (loan_id, amount, payment_type, payment_date, notes, organization_id) VALUES (%s, %s, %s, %s, %s, %s)",
                    (loan_id, amount, payment_type, payment_date, notes, organization_id))
        conn.commit()
        cur.close()
        conn.close()
        flash('Pagamento adicionado com sucesso!', 'success')
    except Exception as e:
        conn.rollback()
        print(f"Erro ao adicionar pagamento: {e}")
        flash(f'Erro ao adicionar pagamento: {e}', 'danger')
        conn.close()

    return redirect(url_for('payments'))

# Rota de logout
@app.route('/logout')
def logout():
    session.pop('username', None)
    session.pop('role', None)
    session.pop('organization_id', None)
    flash('Você saiu da sua conta.', 'info')
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)
