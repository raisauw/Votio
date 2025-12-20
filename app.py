import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import mysql.connector
import secrets
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory
from werkzeug.utils import secure_filename


app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET', 'dev')

# Upload folder
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_PHOTO_EXT = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
ALLOWED_CV_EXT = {'pdf'}

# MySQL configuration from environment
MYSQL_HOST = os.environ.get('MYSQL_HOST', 'localhost')
MYSQL_PORT = int(os.environ.get('MYSQL_PORT', 3306))
MYSQL_USER = os.environ.get('MYSQL_USER', 'votio')
MYSQL_PASSWORD = os.environ.get('MYSQL_PASSWORD', 'votio')
MYSQL_DB = os.environ.get('MYSQL_DB', 'votioDb')


def get_db_conn():
    """Return a MySQL connection using mysql-connector-python."""
    conn = mysql.connector.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DB,
        autocommit=False,
        charset='utf8mb4'
    )
    return conn


def parse_datetime(value):

    if value is None:
        return None
    if isinstance(value, datetime):
        # ensure timezone-aware in Asia/Jakarta
        jkt = ZoneInfo('Asia/Jakarta')
        if value.tzinfo is None:
            return value.replace(tzinfo=jkt)
        return value.astimezone(jkt)
    s = str(value).strip()
    if not s:
        return None
    fmts = ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d']
    for f in fmts:
        try:
            dt = datetime.strptime(s, f)
            # assume stored/received naive datetimes are in Asia/Jakarta
            return dt.replace(tzinfo=ZoneInfo('Asia/Jakarta'))
        except Exception:
            continue
    # fallback: try to parse only date portion
    try:
        dt = datetime.fromisoformat(s)
        if isinstance(dt, datetime):
            if dt.tzinfo is None:
                return dt.replace(tzinfo=ZoneInfo('Asia/Jakarta'))
            return dt.astimezone(ZoneInfo('Asia/Jakarta'))
    except Exception:
        return None


def init_db():
    """Create MySQL database and tables if they don't exist."""
    
    try:
        tmp_conn = mysql.connector.connect(
            host=MYSQL_HOST,
            port=MYSQL_PORT,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            autocommit=True,
            charset='utf8mb4'
        )
        tmp_cursor = tmp_conn.cursor()
        tmp_cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{MYSQL_DB}` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        tmp_cursor.close()
        tmp_conn.close()
    except Exception as e:
        print('init_db: could not ensure database exists:', e)

    conn = get_db_conn()
    cur = conn.cursor()

    cur.execute('''
    CREATE TABLE IF NOT EXISTS elections (
        id INT AUTO_INCREMENT PRIMARY KEY,
        title TEXT NOT NULL,
        code VARCHAR(64) UNIQUE NOT NULL,
        start_date DATETIME NOT NULL,
        end_date DATETIME NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    ''')

    cur.execute('''
    CREATE TABLE IF NOT EXISTS candidates (
        id INT AUTO_INCREMENT PRIMARY KEY,
        election_id INT,
        nama TEXT NOT NULL,
        visi TEXT,
        misi TEXT,
        foto_path TEXT,
        cv_path TEXT,
        FOREIGN KEY (election_id) REFERENCES elections(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    ''')

    cur.execute('''
    CREATE TABLE IF NOT EXISTS votes (
        id INT AUTO_INCREMENT PRIMARY KEY,
        election_id INT NOT NULL,
        candidate_id INT NOT NULL,
        ip_address VARCHAR(45),
        voted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY unique_vote (ip_address, election_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    ''')

    conn.commit()
    conn.close()
    print('init_db: MySQL database ready (db=%s) host=%s' % (MYSQL_DB, MYSQL_HOST))


@app.route('/')
def home():
    return render_template('home.html')


@app.route('/election', methods=['GET', 'POST'])
def election():
    if request.method == 'POST':
        
        title = request.form.get('title')
        end_datetime = request.form.get('end_datetime')

        # Server-side validation: required title
        if not title or not title.strip():
            flash('Judul pemilihan wajib diisi', 'error')
            return redirect(url_for('election'))

        idx = 0
        candidate_count = 0
        candidate_errors = []
        while True:
            name_key = f'candidates[{idx}][name]'
            if name_key not in request.form:
                break

            candidate_count += 1
            name_val = (request.form.get(name_key) or '').strip()
            cv_field = f'candidates[{idx}][cv]'
            cv_file = request.files.get(cv_field)

            if not name_val:
                candidate_errors.append(f'Nama kandidat pada posisi {idx+1} wajib diisi')

            idx += 1

        if candidate_count < 2:
            flash('Minimal dua kandidat diperlukan', 'error')
            return redirect(url_for('election'))

        if candidate_errors:
            flash(candidate_errors[0], 'error')
            return redirect(url_for('election'))

        # If end_datetime empty, set to 12 hours from now (Asia/Jakarta) by default
        if not end_datetime or not end_datetime.strip():
            dt = datetime.now(ZoneInfo('Asia/Jakarta')) + timedelta(hours=12)
            end_datetime = dt.strftime('%Y-%m-%d %H:%M')

        conn = get_db_conn()
        cur = conn.cursor(dictionary=True)

        # start_date is now (Asia/Jakarta)
        start_dt = datetime.now(ZoneInfo('Asia/Jakarta'))
        start_str = start_dt.strftime('%Y-%m-%d %H:%M:%S')

        if end_datetime and end_datetime.strip():
            try:
                dt = datetime.strptime(end_datetime, '%Y-%m-%d %H:%M')
                end_str = dt.strftime('%Y-%m-%d %H:%M:%S')
            except Exception:
                # fallback: store as provided
                end_str = end_datetime
        else:
            dt = datetime.now(ZoneInfo('Asia/Jakarta')) + timedelta(hours=24)
            end_str = dt.strftime('%Y-%m-%d %H:%M:%S')

        # generate a short uppercase unique code (retry until unique)
        def generate_code():
            return secrets.token_hex(3).upper()

        code = generate_code()
        # ensure uniqueness in DB
        cur.execute('SELECT 1 FROM elections WHERE code = %s', (code,))
        while cur.fetchone() is not None:
            code = generate_code()

        cur.execute('INSERT INTO elections (title, code, start_date, end_date) VALUES (%s, %s, %s, %s)',
                    (title, code, start_str, end_str))
        election_id = cur.lastrowid

        try:
            print('POST /election form keys:', list(request.form.keys()))
            print('POST /election files keys:', list(request.files.keys()))
        except Exception:
            pass

        # process candidates and files
        idx = 0
        while True:
            name_key = f'candidates[{idx}][name]'
            if name_key not in request.form:
                break

            name = request.form.get(name_key)
            vision = request.form.get(f'candidates[{idx}][vision]')
            mission = request.form.get(f'candidates[{idx}][mission]')

            photo_field = f'candidates[{idx}][photo]'
            cv_field = f'candidates[{idx}][cv]'
            photo_file = request.files.get(photo_field)
            cv_file = request.files.get(cv_field)

            saved_photo = None
            saved_cv = None

            if photo_file and photo_file.filename:
                ext = photo_file.filename.rsplit('.', 1)[-1].lower()
                if ext in ALLOWED_PHOTO_EXT:
                    filename = secure_filename(f"{election_id}_{idx}_photo_{photo_file.filename}")
                    dest = os.path.join(UPLOAD_FOLDER, filename)
                    photo_file.save(dest)
                    saved_photo = filename

            if cv_file and cv_file.filename:
                ext = cv_file.filename.rsplit('.', 1)[-1].lower()
                if ext in ALLOWED_CV_EXT:
                    filename = secure_filename(f"{election_id}_{idx}_cv_{cv_file.filename}")
                    dest = os.path.join(UPLOAD_FOLDER, filename)
                    cv_file.save(dest)
                    saved_cv = filename

            cur.execute('''INSERT INTO candidates (election_id, nama, visi, misi, foto_path, cv_path)
                           VALUES (%s, %s, %s, %s, %s, %s)''',
                        (election_id, name, vision, mission, saved_photo, saved_cv))

            idx += 1

        conn.commit()
        conn.close()

        return redirect(url_for('election_detail', code=code))

    return render_template('election.html')


@app.route('/election/<code>')
def election_detail(code):
    conn = get_db_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute('SELECT * FROM elections WHERE code = %s', (code,))
    election = cur.fetchone()
    if not election:
        conn.close()
        return render_template('not_found.html', code=code), 404

    # Manage access based on end_date window
    # determine client IP (respecting X-Forwarded-For if present)
    ip = request.headers.get('X-Forwarded-For', request.remote_addr)

    # If this IP already voted in this election, redirect them to the results page
    try:
        cur.execute('SELECT 1 FROM votes WHERE election_id = %s AND ip_address = %s LIMIT 1', (election['id'], ip))
        already = cur.fetchone()
        if already:
            conn.close()
            return redirect(url_for('vote_result', code=code))
    except Exception:
        pass

    now = datetime.now(ZoneInfo('Asia/Jakarta'))
    end_dt = parse_datetime(election.get('end_date'))

    if end_dt:
        # If window expired (>24h after end) -> delete election to free code and show not found
        if now > end_dt + timedelta(hours=24):
            try:
                cur.execute('DELETE FROM votes WHERE election_id = %s', (election['id'],))
                cur.execute('DELETE FROM candidates WHERE election_id = %s', (election['id'],))
                cur.execute('DELETE FROM elections WHERE id = %s', (election['id'],))
                conn.commit()
            except Exception:
                conn.rollback()
            conn.close()
            return render_template('not_found.html', code=code), 404

    cur.execute('SELECT * FROM candidates WHERE election_id = %s', (election['id'],))
    candidates = cur.fetchall()

    # fetch vote counts per candidate
    cur.execute('SELECT candidate_id, COUNT(*) as cnt FROM votes WHERE election_id = %s GROUP BY candidate_id', (election['id'],))
    counts = {row['candidate_id']: row['cnt'] for row in cur.fetchall()}
    conn.close()
    return render_template('election_detail.html', election=election, candidates=candidates)

@app.route('/vote', methods=['POST'])
def vote():
    # Accept JSON or form
    try:
        data = request.get_json(silent=True) or request.form
    except Exception:
        data = request.form

    candidate_id = data.get('candidate_id')
    if not candidate_id:
        return { 'success': False, 'message': 'candidate_id missing' }, 400

    try:
        candidate_id = int(candidate_id)
    except ValueError:
        return { 'success': False, 'message': 'invalid candidate_id' }, 400

    # determine client IP (basic)
    ip = request.headers.get('X-Forwarded-For', request.remote_addr)

    conn = get_db_conn()
    cur = conn.cursor(dictionary=True)

    # find candidate and its election
    cur.execute('SELECT * FROM candidates WHERE id = %s', (candidate_id,))
    cand = cur.fetchone()
    if not cand:
        conn.close()
        # If this was a form submission, redirect back to home (or not found)
        if not request.is_json and request.form:
            return redirect(url_for('home'))
        return { 'success': False, 'message': 'Candidate not found' }, 404

    election_id = cand['election_id']
    # check election end date to ensure voting is still open
    cur.execute('SELECT end_date, code FROM elections WHERE id = %s', (election_id,))
    e_row = cur.fetchone()
    end_dt = parse_datetime(e_row.get('end_date') if e_row else None)
    code = e_row['code'] if e_row and 'code' in e_row else None
    now = datetime.now(ZoneInfo('Asia/Jakarta'))
    if isinstance(end_dt, datetime):
        if now >= end_dt:
            # voting closed
            conn.close()
            if not request.is_json and request.form:
                # redirect to results if within 24h
                if now <= end_dt + timedelta(hours=24) and code:
                    return redirect(url_for('vote_result', code=code))
                return redirect(url_for('home'))
            return { 'success': False, 'message': 'Voting sudah berakhir' }, 400
    else:
        # If end_date not parseable, allow voting (fallback)
        pass

    # check if this IP already voted in this election
    cur.execute('SELECT 1 FROM votes WHERE election_id = %s AND ip_address = %s LIMIT 1', (election_id, ip))
    already = cur.fetchone()
    if already:
        # return current count
        cur.execute('SELECT COUNT(*) as cnt FROM votes WHERE candidate_id = %s', (candidate_id,))
        cnt = cur.fetchone()['cnt']
        # if form POST, redirect to results page
        cur.execute('SELECT code FROM elections WHERE id = %s', (election_id,))
        code_row = cur.fetchone()
        code = code_row['code'] if code_row and 'code' in code_row else None
        conn.close()
        if not request.is_json and request.form:
            if code:
                return redirect(url_for('vote_result', code=code))
            return redirect(url_for('home'))
        return { 'success': False, 'message': 'Anda sudah memilih pada pemilihan ini', 'votes_count': cnt }

    # insert vote
    try:
        cur.execute('INSERT INTO votes (election_id, candidate_id, ip_address) VALUES (%s, %s, %s)', (election_id, candidate_id, ip))
        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        # if non-JSON (form), redirect to home with flash
        if not request.is_json and request.form:
            flash('Gagal mencatat suara. Silakan coba lagi.', 'error')
            return redirect(url_for('home'))
        return { 'success': False, 'message': 'Database error' }, 500

    cur.execute('SELECT COUNT(*) as cnt FROM votes WHERE candidate_id = %s', (candidate_id,))
    cnt = cur.fetchone()['cnt']
    # get election code to redirect to result page for non-JSON posts
    cur.execute('SELECT code FROM elections WHERE id = %s', (election_id,))
    code_row = cur.fetchone()
    code = code_row['code'] if code_row and 'code' in code_row else None
    conn.close()

    # If request was JSON (AJAX), return JSON as before
    content_type = request.content_type or ''
    if request.is_json or 'application/json' in content_type:
        return { 'success': True, 'message': 'Vote recorded', 'votes_count': cnt }

    # Otherwise (standard form POST), redirect to results page
    if code:
        return redirect(url_for('vote_result', code=code))
    return redirect(url_for('home'))


@app.route('/vote/<code>')
def vote_result(code):
    conn = get_db_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute('SELECT * FROM elections WHERE code = %s', (code,))
    election = cur.fetchone()
    if not election:
        conn.close()
        return render_template('not_found.html', code=code), 404
    
    now = datetime.now(ZoneInfo('Asia/Jakarta'))
    end_dt = parse_datetime(election.get('end_date'))
    if end_dt and now > end_dt + timedelta(hours=24):
        try:
            cur.execute('DELETE FROM votes WHERE election_id = %s', (election['id'],))
            cur.execute('DELETE FROM candidates WHERE election_id = %s', (election['id'],))
            cur.execute('DELETE FROM elections WHERE id = %s', (election['id'],))
            conn.commit()
        except Exception:
            conn.rollback()
        conn.close()
        return render_template('not_found.html', code=code), 404

    cur.execute('SELECT * FROM candidates WHERE election_id = %s', (election['id'],))
    candidates = cur.fetchall()

    # fetch vote counts per candidate
    cur.execute('SELECT candidate_id, COUNT(*) as cnt FROM votes WHERE election_id = %s GROUP BY candidate_id', (election['id'],))
    counts = {row['candidate_id']: row['cnt'] for row in cur.fetchall()}
    total = sum(counts.values())
    
    for c in candidates:
        c_id = c['id']
        c['votes'] = counts.get(c_id, 0)
        c['pct'] = round((c['votes'] / total) * 100, 2) if total > 0 else 0

    # prepare voted candidates list (only those with votes>0) for donut
    voted_candidates = [c for c in candidates if c['votes'] > 0]
    # determine winner(s)
    max_votes = 0
    for c in candidates:
        if c['votes'] > max_votes:
            max_votes = c['votes']
    winners = [c for c in candidates if c['votes'] == max_votes and max_votes > 0]
    
    # pick primary winner if unique
    primary_winner = winners[0] if len(winners) == 1 else None

    # compute expiry (end_date + 24h) in Jakarta and pass to template for client-side countdown
    expiry_ts_ms = None
    end_dt_display = None
    if end_dt:
        expiry = end_dt + timedelta(hours=24)
        # timestamp in milliseconds for JS
        try:
            expiry_ts_ms = int(expiry.timestamp() * 1000)
        except Exception:
            expiry_ts_ms = None
        # human friendly end datetime display (Jakarta timezone)
        try:
            end_dt_display = end_dt.strftime('%d / %m / %Y %H:%M')
        except Exception:
            end_dt_display = None

    conn.close()
    return render_template('vote_result.html', election=election, candidates=candidates, voted_candidates=voted_candidates, total_votes=total, winner=primary_winner, winners=winners, expiry_ts_ms=expiry_ts_ms, end_dt_display=end_dt_display)


@app.route('/api/check_code')
def api_check_code():
    code = request.args.get('code', '').strip()
    if not code:
        return { 'exists': False }, 200
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute('SELECT 1 FROM elections WHERE code = %s LIMIT 1', (code,))
        found = cur.fetchone() is not None
        conn.close()
        return { 'exists': bool(found) }, 200
    except Exception as e:
        print('api_check_code error:', e)
        return { 'exists': False }, 200


@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


if __name__ == '__main__':
    init_db()
    app.run(port=80, host="0.0.0.0", debug=True)

app.before_first_request(init_db)