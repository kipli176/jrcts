import os
import sqlite3
import requests
from flask import Flask, g, request, redirect, url_for, render_template
from datetime import datetime

app = Flask(__name__)
app.config['DATABASE'] = 'jrcts.db'
API_URL = 'https://api.example.com/jaminan'  # ganti sesuai endpoint
def format_rupiah(value):
    try:
        value = int(value)
        return "Rp {:,.0f}".format(value).replace(",", ".")
    except (ValueError, TypeError):
        return "Rp 0"
 
app.jinja_env.filters['rupiah'] = format_rupiah
# ========== DATABASE ==========

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        fresh = not os.path.exists(app.config['DATABASE'])
        db = g._database = sqlite3.connect(app.config['DATABASE'])
        db.row_factory = sqlite3.Row
        if fresh:
            init_db(db)
    return db


def init_db(db):
    db.executescript("""
    CREATE TABLE korban (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nomor_resi TEXT UNIQUE,
        nama_lengkap TEXT NOT NULL,
        usia INTEGER NOT NULL,
        nomor_telepon TEXT NOT NULL,
        nik TEXT NOT NULL,
        alamat_koordinat TEXT,
        nopol_kendaraan TEXT,
        status_kendaraan TEXT,
        rs_tempat_dirawat TEXT,
        jenis_rawatan TEXT,
        created_at DATETIME NOT NULL,
        nomor_lp TEXT,
        nomor_jaminan TEXT,
        tgl_kecelakaan DATE,
        tgl_masuk DATE,
        tgl_keluar DATE,
        status_tagihan TEXT,
        jml_pengajuan INTEGER,
        jml_digunakan INTEGER,
        tgl_update DATE
    );
    CREATE TABLE histori_status (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        korban_id INTEGER NOT NULL,
        step INTEGER NOT NULL,
        deskripsi TEXT NOT NULL,
        created_at DATETIME NOT NULL,
        FOREIGN KEY(korban_id) REFERENCES korban(id)
    );
    """)
    db.commit()


@app.teardown_appcontext
def close_db(exc):
    db = getattr(g, '_database', None)
    if db:
        db.close()


@app.template_filter('format_tanggal')
def format_tanggal(value):
    if not value:
        return ""
    try:
        # Jika value adalah string, coba parsing
        if isinstance(value, str):
            value = datetime.fromisoformat(value)
        return value.strftime("%d/%m/%Y")
    except Exception:
        return value  # fallback: tampilkan apa adanya
# ========== HELPERS ==========

def generate_resi():
    today = datetime.now().strftime('%Y%m%d')
    prefix = f'JR-CTS-{today}'
    cnt = get_db().execute(
        "SELECT COUNT(*) AS cnt FROM korban WHERE nomor_resi LIKE ?",
        (f'{prefix}-%',)
    ).fetchone()['cnt']
    return f'{prefix}-{cnt+1}'


def add_history(korban_id, step, desc):
    db = get_db()
    db.execute(
        "INSERT INTO histori_status (korban_id, step, deskripsi, created_at) VALUES (?,?,?,?)",
        (korban_id, step, desc, datetime.now())
    )
    db.commit()

def cek_nomor_kendaraan(nopol: str = None) -> dict:

    # Gunakan default jika input kosong
    if not nopol:
        nopol = "D-1234-DD"

    payload = {"nopol": nopol}
    print(payload)
    try:
        resp = requests.post('https://ceknopol.sukipli.work/cari_kendaraan', json=payload, timeout=5)
        resp.raise_for_status()  # akan memicu exception untuk status_code >=400
        # print(resp.text())
    except requests.RequestException as e:
        # Anda bisa log e di sini, atau return dict dengan info error
        return {
            "status": "ERROR",
            "error": str(e),
            "transactions": [],
            "vehicle": {}
        }

    try:
        data = resp.json()
        # print(data)
    except ValueError:
        # Kalau response bukan JSON valid
        return {
            "status": "ERROR",
            "error": "Invalid JSON response",
            "transactions": [],
            "vehicle": {}
        }

    # Pastikan semua key ada, atur fallback
    return {
        "status": data.get("status", "UNKNOWN"),
        "transactions": data.get("transactions", []),
        "vehicle": data.get("vehicle", {})
    }

# ========== FRONTEND ==========

@app.route('/registrasi', methods=['GET', 'POST'])
def registrasi():
    if request.method == 'POST':
        # ambil data dari form
        nik               = request.form['nik']
        nama_lengkap      = request.form['nama_lengkap']
        usia              = int(request.form['usia'])
        nomor_telepon     = request.form['nomor_telepon']
        alamat_koordinat  = request.form['alamat_koordinat']
        tgl_kecelakaan    = request.form['tgl_kecelakaan']
        nopol_kendaraan   = request.form['nopol_kendaraan']
        rs_tempat_dirawat = request.form['rs_tempat_dirawat']
        jenis_rawatan     = request.form['jenis_rawatan']

        db = get_db()
        # 1) cek duplikat
        dup = db.execute(
            "SELECT nomor_resi FROM korban "
            "WHERE nama_lengkap=? AND tgl_kecelakaan=? AND jenis_rawatan=?",
            (nama_lengkap, tgl_kecelakaan, jenis_rawatan)
        ).fetchone()

        if dup:
            # jika sudah ada, render template dengan existing_resi
            return render_template('register.html',
                                   existing_resi=dup['nomor_resi'])

        # 2) generate resi baru
        nomor_resi = generate_resi()
        cur = db.execute("""
            INSERT INTO korban (
                nomor_resi, nik, nama_lengkap, usia, nomor_telepon,
                alamat_koordinat, tgl_kecelakaan, nopol_kendaraan,
                rs_tempat_dirawat, jenis_rawatan, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (
            nomor_resi, nik, nama_lengkap, usia, nomor_telepon,
            alamat_koordinat, tgl_kecelakaan, nopol_kendaraan,
            rs_tempat_dirawat, jenis_rawatan, datetime.now()
        ))
        db.commit()
        korban_id = cur.lastrowid

        # 3) catat history dengan resi
        add_history(korban_id, 1, f"Step 1: Resi dibuat ({nomor_resi})")

        # 4) render ulang form dengan nomor resi baru
        return render_template('register.html', nomor_resi=nomor_resi)

    # GET: tampilkan form kosong
    return render_template('register.html')

@app.route('/')
@app.route('/tracking')
def tracking():
    nomor = request.args.get('nomor_resi', '').strip()
    error = None
    korban = None
    riwayat = []
    status_kendaraan = None
    nopol = None
    akhir_transaksi = None

    if nomor:
        db = get_db()
        korban = db.execute(
            "SELECT * FROM korban WHERE nomor_resi = ?",
            (nomor,)
        ).fetchone()

        if not korban:
            error = 'Nomor resi tidak ditemukan.'
        else:
            # ambil histori
            riwayat = db.execute(
                "SELECT * FROM histori_status WHERE korban_id = ? ORDER BY step, created_at",
                (korban['id'],)
            ).fetchall()

            # ambil nopol dan cek via API
            nopol = korban['nopol_kendaraan']
            status_kendaraan = korban['status_kendaraan']
            if not status_kendaraan:
                api_res = cek_nomor_kendaraan(nopol)
                status_kendaraan = api_res.get('status')
                db.execute("UPDATE korban SET status_kendaraan=? WHERE id=?", (status_kendaraan,korban['id']))

                db.commit()
                # ambil transaksi pertama (terbaru) -> 'akhir' sesuai API
                txs = api_res.get('transactions', [])
                if txs:
                    # asumsi urutan API: index 0 adalah transaksi paling baru
                    akhir_transaksi = txs[0].get('akhir')
    return render_template('tracking.html',
        error=error,
        nomor=nomor,
        korban=korban,
        riwayat=riwayat,
        status_kendaraan=status_kendaraan,
        nopol=nopol,
        akhir_transaksi=akhir_transaksi)

# ========== ADMIN PANEL ==========

@app.route('/admin')

@app.route('/admin')
def admin_list():
    db = get_db()
    # Join with histori_status to get latest step per korban
    semua = db.execute("""
        SELECT c.*,
               COALESCE(h.step, 0) AS step
        FROM korban c
        LEFT JOIN (
            SELECT korban_id, MAX(step) AS step
            FROM histori_status
            GROUP BY korban_id
        ) h ON c.id = h.korban_id
        ORDER BY c.created_at DESC
    """).fetchall()
    return render_template('admin.html', korban_list=semua)


@app.route('/admin/delete', methods=['POST'])
def admin_delete():
    # nomor_resi dikirim sebagai query param dari url_for(...)
    nomor_resi = request.args.get('nomor_resi')
    if not nomor_resi:
        return redirect(url_for('admin_list'))

    db = get_db()
    # cari korban
    row = db.execute(
        "SELECT id FROM korban WHERE nomor_resi = ?",
        (nomor_resi,)
    ).fetchone()

    if row:
        korban_id = row['id']
        # hapus histori dulu
        db.execute(
            "DELETE FROM histori_status WHERE korban_id = ?",
            (korban_id,)
        )
        # hapus korban
        db.execute(
            "DELETE FROM korban WHERE id = ?",
            (korban_id,)
        )
        db.commit()

    return redirect(url_for('admin_list'))

@app.route('/admin/<nomor_resi>', methods=['GET','POST'])
def admin_detail(nomor_resi):
    gagal = request.args.get('gagal', '').strip()
    db = get_db()
    korban = db.execute(
        "SELECT * FROM korban WHERE nomor_resi=?", (nomor_resi,)
    ).fetchone()
    if not korban:
        return "Korban tidak ditemukan", 404
    if gagal:
        db.execute("UPDATE korban SET status_tagihan=? WHERE id=?", ('GAGAL JAMINAN',korban['id']))
        add_history(korban['id'],3,f"Step 3: Gagal jaminan, nomor resi anda akan terhapus")
    if request.method == 'POST':
        step = int(request.form['step'])
        if step == 2:
            lp = request.form.get('nomor_lp','').strip()
            db.execute("UPDATE korban SET nomor_lp=? WHERE id=?", (lp,korban['id']))
            add_history(korban['id'],2,f"Step 2: Nomor LP diinput ({lp})")
        elif step == 3:
            nj = request.form.get('nomor_jaminan','').strip()
            db.execute("UPDATE korban SET nomor_jaminan=? WHERE id=?", (nj,korban['id']))
            if nj:
                
                tgl_awal = datetime.strptime(korban['tgl_kecelakaan'], "%Y-%m-%d").strftime("%d/%m/%Y")
                # tgl_awal = korban['tgl_kecelakaan'].strftime("%d/%m/%Y")
                url = f"https://ceknopol.sukipli.work/jaminan?id_jaminan={nj}&tgl_awal={tgl_awal}"
                resp = requests.get(url)
                if resp.status_code != 200:
                    pass  # skip jika gagal
                data = resp.json()
                
                if not data.get('klaim'):
                    pengajuan = 0
                    digunakan = 0
                    # simpan ke DB
                    db.execute("""
                        UPDATE korban
                        SET status_tagihan='CEK_DATA_MONITOR_GL',
                            jml_pengajuan=?, jml_digunakan=?, tgl_update=?
                        WHERE id=?
                    """, (pengajuan, digunakan, datetime.now().date(), korban['id']))
                    db.commit()

                    # catat histori
                    add_history(korban['id'], 6, "Step 6: Tidak ada klaim, menunggu pembayaran")                
                klaim = data['klaim'][0]
                pengajuan = int(klaim['jml_pengajuan'].replace(",", ""))
                statuse = klaim['status_jaminan']
                tgl_masuk = klaim['tgl_masuk']
                db.execute("""
                    UPDATE korban
                    SET status_tagihan=?, jml_pengajuan=?, tgl_masuk=?, tgl_update=?
                    WHERE id=?
                """, (statuse, pengajuan, tgl_masuk, datetime.now().date(), korban['id']))
                db.commit()
            
                add_history(korban['id'],3,f"Step 3: Nomor jaminan diinput ({nj}), saldo sebelumnya ({format_rupiah(pengajuan)})")

            else:
                add_history(korban['id'],3,"Step 3: Kasus tidak terjamin — berhenti")
        elif step == 4:
            tgl = request.form.get('tgl_keluar')
            db.execute(
                """
                UPDATE korban
                SET tgl_keluar=?, status_tagihan='DITAGIHKAN'
                WHERE id=?
                """, (tgl,korban['id']))
            add_history(korban['id'],4,f"Step 4: Pasien pulang ({tgl})")
            add_history(korban['id'],5,"Step 5: Berkas sudah ditagihkan oleh JCARE")
        elif step == 6:
            
            nomor_jaminan = korban['nomor_jaminan']
            tgl_awal = datetime.strptime(korban['tgl_kecelakaan'], "%Y-%m-%d").strftime("%d/%m/%Y")
            # tgl_awal = korban['tgl_kecelakaan'].strftime("%d/%m/%Y")
            url = f"https://ceknopol.sukipli.work/monitoring?id_jaminan={nomor_jaminan}&tgl_awal={tgl_awal}"
            resp = requests.get(url)
            if resp.status_code != 200:
                pass  # skip jika gagal
            data = resp.json()
            
            if not data.get('klaim'):
                pengajuan = 0
                digunakan = 0
                # simpan ke DB
                db.execute("""
                    UPDATE korban
                    SET status_tagihan='CEK_DATA_MONITOR_GL',
                        jml_pengajuan=?, jml_digunakan=?, tgl_update=?
                    WHERE id=?
                """, (pengajuan, digunakan, datetime.now().date(), korban['id']))
                db.commit()

                # catat histori
                add_history(korban['id'], 6, "Step 6: Tidak ada klaim, menunggu pembayaran")

            
            klaim = data['klaim'][0]

            # --- Mulai dummy API response ---
            # data = {
            #     "ID Jaminan": "0700-2025-003708-04",
            #     "Jml Digunakan": "10,779,000",
            #     "Jml Pengajuan": "21,500,000",
            #     "Loket": "0700001",
            #     "Nama Korban": "NI MADE DEWI SRI ADNYANI",
            #     "No Surat": "PL/R/2089/GL/2025",
            #     "Rumah sakit": "RSUP PROF DR I,G.N.G NGOERAH",
            #     "Status Jaminan": "SUDAH DIBAYAR",
            #     "Tgl Keluar": "",
            #     "Tgl Masuk": "27/06/2025",
            #     "Verifikator": "JRCARE",
            #     "otorisasi": {
            #         "---": "JRCARE ---",
            #         "Ambulan": "0",
            #         "Ambulance": "0",
            #         "Biaya Admin": "35,000",
            #         "Biaya Alkes": "0",
            #         "Biaya Dokter": "32,311,000",
            #         "Biaya Kamar": "910,000",
            #         "Biaya Obat": "3,418,900",
            #         "Dijaminkan ke": "RSUP PROF DR I,G.N.G NGOERAH",
            #         "Hasil Verifikasi": "10,779,000",
            #         "LL": "10,779,000",
            #         "Otorisasi GL": "TERBIT GL - DISETUJUI",
            #         "P3K": "0",
            #         "Pengajuan": "36,674,900",
            #         "SEP BPJS": "2209R0010625V037002",
            #         "Status GL": "SUDAH DIBAYAR",
            #         "Tgl Masuk RS": "27/06/2025",
            #         "Tgl Update": "10/07/2025",
            #         "Verifikator": "JRCARE"
            #     }
            # }
            # --- Akhir dummy response ---

            # Proses hanya jika sudah dibayar
            if klaim["status_jaminan"] == "SUDAH DIBAYAR":
                # parsing angka dengan menghapus koma
                pengajuan = int(klaim['jml_pengajuan'].replace(",", ""))
                digunakan = int(klaim['jml_digunakan'].replace(",", ""))
                # simpan ke DB
                db.execute("""
                    UPDATE korban
                    SET status_tagihan='DIBAYAR',
                        jml_pengajuan=?, jml_digunakan=?, tgl_update=?
                    WHERE id=?
                """, (pengajuan, digunakan, datetime.now().date(), korban['id']))
                db.commit()

                # catat histori langkah 6–7–8
                add_history(korban['id'], 6,
                            f"Step 6: Berkas dibayarkan ({format_rupiah(digunakan)} dari {format_rupiah(pengajuan)})")
                sisa = pengajuan - digunakan
                add_history(korban['id'], 7, f"Step 7: Sisa jaminan {format_rupiah(sisa)}")
                add_history(korban['id'], 8, "Step 8: Selesai")
            else:
                add_history(korban['id'], 6, "Step 6: Menunggu pembayaran")

        return redirect(url_for('admin_detail', nomor_resi=nomor_resi))

    riwayat = db.execute(
        "SELECT * FROM histori_status WHERE korban_id=? ORDER BY step,created_at",
        (korban['id'],)
    ).fetchall()
    return render_template('admin-detail.html',
                                  korban=korban,
                                  riwayat=riwayat)

@app.route('/admin/<nomor_resi>/reset', methods=['POST'])
def admin_reset(nomor_resi):
    db = get_db()
    db.execute("DELETE FROM histori_status WHERE korban_id=(SELECT id FROM korban WHERE nomor_resi=?)", (nomor_resi,))
    db.execute("DELETE FROM korban WHERE nomor_resi=?", (nomor_resi,))
    db.commit()
    return redirect(url_for('registrasi'))


if __name__ == '__main__':
    # app.run(debug=True)

    app.run(host='0.0.0.0', port=5011, debug=True)
