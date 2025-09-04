import os
import hashlib
import psycopg2
from flask import Flask, render_template, request, redirect, url_for, session, flash

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'your_super_secret_key')

# Configuração da conexão com o banco de dados PostgreSQL
# O Vercel injetará automaticamente a DATABASE_URL
def get_db_connection():
    conn = psycopg2.connect(os.environ.get('DATABASE_URL'))
    return conn

# Função para hash da senha
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# Rota para a página de login
@app.route('/', methods=['GET', 'POST'])
def login():
    if 'username' in session:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        hashed_password = hash_password(password)

        conn = get_db_connection()
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

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Inserir nova organização
        cur.execute("INSERT INTO organizations (name) VALUES (%s) RETURNING id", (organization_name,))
        organization_id = cur.fetchone()[0]

        # Inserir novo usuário
        cur.execute("INSERT INTO users (username, password, role, organization_id, start_date) VALUES (%s, %s, %s, %s, NOW())",
                    (username, hashed_password, 'user', organization_id))

        conn.commit()  # <-- Linha adicionada para confirmar a transação
        cur.close()
        conn.close()
        flash('Usuário e organização adicionados com sucesso!', 'success')

    except Exception as e:
        conn.rollback()
        print(f"Erro ao adicionar usuário: {e}")
        flash(f'Erro ao adicionar usuário: {e}', 'danger')

    return redirect(url_for('admin_panel'))

# Rota para o painel do usuário
@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return redirect(url_for('login'))
        
    organization_id = session.get('organization_id')
    conn = get_db_connection()
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

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO clients (full_name, document, phone, email, address, organization_id) VALUES (%s, %s, %s, %s, %s, %s)",
                    (full_name, document, phone, email, address, organization_id))
        conn.commit() # <-- Adicionado commit
        cur.close()
        conn.close()
        flash('Cliente adicionado com sucesso!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Erro ao adicionar cliente: {e}', 'danger')

    return redirect(url_for('clients'))

# ... adicione as outras rotas (loans, payments, etc.) aqui, garantindo que elas também usem conn.commit() após operações de escrita.

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
