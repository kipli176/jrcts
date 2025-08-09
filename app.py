from collections import defaultdict
import os
import sqlite3
import requests
from flask import Flask, g, request, redirect, url_for, render_template, render_template_string, json
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




def _parse_dt(s):
    if s is None:
        return None
    if isinstance(s, datetime):
        return s
    s = str(s).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
                "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M", "%d-%m-%Y",
                "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y",
                "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            pass
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None

def _bucket_status(val):
    """Normalisasi status ke 3 bucket: LUNAS / BELUM LUNAS / ERROR"""
    if val is None or str(val).strip() == "":
        return "BELUM LUNAS"
    v = str(val).upper()
    if "ERROR" in v:
        return "ERROR"
    if "LUNAS" in v and "BELUM" not in v:
        return "LUNAS"
    return "BELUM LUNAS"

@app.route("/dashboard")
def admin_dashboard_tv():
    db = get_db()
    cur = db.cursor()

    # 1) Total pasien yang generate resi
    cur.execute("SELECT COUNT(*) FROM korban WHERE nomor_resi IS NOT NULL")
    total_resi = int(cur.fetchone()[0])

    # 2) Pasien per step -> step terakhir dari histori_status
    cur.execute("""
        SELECT current_step, COUNT(*) AS cnt
        FROM (
            SELECT korban_id, MAX(step) AS current_step
            FROM histori_status
            GROUP BY korban_id
        )
        GROUP BY current_step
        ORDER BY current_step
    """)
    rows = cur.fetchall()
    step_categories = [str(r[0]) for r in rows]
    step_values     = [int(r[1]) for r in rows]

    # 3) Status KENDARAAN (sesuai permintaan awal; status tagihan tidak ditampilkan)
    lunas_kend = belum_kend = error_kend = 0
    try:
        cur.execute("SELECT status_kendaraan FROM korban")
        for (st,) in cur.fetchall():
            b = _bucket_status(st)
            lunas_kend += (b == "LUNAS")
            belum_kend += (b == "BELUM LUNAS")
            error_kend += (b == "ERROR")
    except Exception:
        pass  # jika kolom tidak ada, biarkan 0

    # 4) Rata-rata durasi antar step (transisi N -> N+1) dalam jam
    cur.execute("""
        SELECT korban_id, step, created_at
        FROM histori_status
        ORDER BY korban_id, step, created_at
    """)
    trans_rows = cur.fetchall()
    sums = defaultdict(float); counts = defaultdict(int)
    last = {}
    for korban_id, step, created_at in trans_rows:
        t = _parse_dt(created_at)
        if t is None: continue
        if korban_id in last:
            prev_step, prev_t = last[korban_id]
            if prev_t and step == (prev_step or 0) + 1:
                delta = (t - prev_t).total_seconds()
                if delta >= 0:
                    sums[step] += delta
                    counts[step] += 1
        last[korban_id] = (step, t)

    dur_steps = sorted(sums.keys())
    dur_categories = [f"Step {s}" for s in dur_steps]   # tujuan
    dur_values = [(sums[s]/counts[s])/3600.0 if counts[s] else 0.0 for s in dur_steps]

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # === TEMPLATE: Single-screen 1366x700 (tanpa scroll) ===
    # Tata letak: header tipis (56px) + grid 2x2 (atas: Steps & Status; bawah: Durasi full)
    # Ukuran chart diset via CSS agar muat di satu layar TV
    return render_template_string("""
<!DOCTYPE html>
<html lang="id">
<head>
  <meta charset="UTF-8" />
  <title>Panel - Dashboard</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta http-equiv="refresh" content="300" />
  <!-- Fonts & Tailwind (konsisten admin) -->
  <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500&display=swap" rel="stylesheet">
  <script src="https://cdn.tailwindcss.com"></script>
  <!-- Highcharts -->
  <script src="https://code.highcharts.com/highcharts.js"></script>
  <style>
    body { font-family: 'Poppins', system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; }
    /* Batas layar TV */
    .screen { margin: 0 auto; background: linear-gradient(to bottom right, #dbeafe, #ffffff, #eff6ff); overflow: hidden; border: 1px solid #e5e7eb; }
    .tv-header { height: 56px; }
    .tv-grid   { height: calc(700px - 56px); padding: 8px; display: grid; gap: 8px;
                 grid-template-columns: 2fr 1fr; grid-template-rows: 1fr 1fr;
                 grid-template-areas: "steps status" "dur dur"; }
    /* Card chart */
    .chart-card { background:#fff; border:1px solid #e5e7eb; border-radius: 12px; padding: 10px; display:flex; flex-direction:column; }
    .chart-title { font-size: 16px; font-weight: 600; color:#1f2937; margin: 0 0 4px; }
    /* Kotak chart: pastikan tinggi fixed agar pas */
    #wrap-steps    { grid-area: steps; min-height: 0; }
    #wrap-status   { grid-area: status; min-height: 0; }
    #wrap-dur      { grid-area: dur; min-height: 0; }
    /* Tinggi spesifik tiap chart agar total muat 700px:
       - baris atas: 310px tinggi kartu
       - baris bawah: 300px tinggi kartu
    */
    #wrap-steps  { height: 310px; }
    #wrap-status { height: 310px; }
    #wrap-dur    { height: 300px; }
    .chart-box   { flex: 1 1 auto; width: 100%; height: 100%; }

    /* Highcharts: kecilkan label supaya rapih */
    .highcharts-title, .highcharts-subtitle { display: none; }
  </style>
  <script>
    // Samakan tone warna & font
    Highcharts.setOptions({
      colors: ['#2563eb','#10b981','#f59e0b','#ef4444','#8b5cf6','#06b6d4'],
      chart: {
        style: { fontFamily: 'Poppins, sans-serif' },
        backgroundColor: 'transparent',
        spacing: [6,6,6,6]
      },
      xAxis: { labels: { style: { color: '#4b5563', fontSize: '10px' } }, title: { style: { color: '#4b5563', fontSize:'10px' } } },
      yAxis: { labels: { style: { color: '#4b5563', fontSize: '10px' } }, title: { style: { color: '#4b5563', fontSize:'10px' } } },
      legend: { itemStyle: { color: '#374151', fontSize: '10px' } },
      tooltip: { style: { fontSize: '11px' } },
      credits: { enabled: false }
    });
  </script>
</head>
<body class="text-gray-800">
  <div class="screen">
    <!-- HEADER TIPIS -->
    <div class="tv-header w-full border-b border-gray-200 bg-white/80 backdrop-blur">
      <div class="h-full px-4 flex items-center justify-between gap-4">
        <div class="flex items-center gap-3">
          <img src="/static/logo.webp" alt="JRCTS Logo" class="h-8 w-auto" />
          <div>
            <h1 class="text-xl font-bold leading-tight">Panel: Dashboard Klaim</h1>
            <p class="text-gray-600 text-xs">Terakhir diperbarui: {{ now_str }} • Auto-refresh 5 menit</p>
          </div>
        </div>
        <!-- Badge KPI: total pasien generate resi -->
        <div class="shrink-0 bg-blue-600 text-white rounded-md px-3 py-2 text-right">
          <div class="text-[10px] opacity-90 leading-none">Pasien Generate Resi</div>
          <div class="text-xl font-semibold leading-none">{{ total_resi }}</div>
        </div>
      </div>
    </div>

    <!-- GRID 1366x(700-56) -->
    <div class="tv-grid">
      <!-- Chart 1: Pasien per Step -->
      <div class="chart-card" id="wrap-steps">
        <div class="chart-title">Pasien per Step (berdasarkan step terakhir)</div>
        <div id="chart-steps" class="chart-box"></div>
      </div>

      <!-- Chart 2: Status Kendaraan (donut) -->
      <div class="chart-card" id="wrap-status">
        <div class="chart-title">Status Kendaraan</div>
        <div id="chart-status-kendaraan" class="chart-box"></div>
      </div>

      <!-- Chart 3: Rata-rata Durasi Antar Step -->
      <div class="chart-card" id="wrap-dur">
        <div class="chart-title">Rata-rata Kecepatan Update Tiap Step</div>
        <div id="chart-dur" class="chart-box"></div>
      </div>
    </div>
  </div>

  <script>
    // Data dari backend
    const stepCategories = {{ step_categories|tojson }};
    const stepValues     = {{ step_values|tojson }};
    const statusKendData = [
      { name: 'LUNAS',       y: {{ lunas_kend }} },
      { name: 'BELUM LUNAS', y: {{ belum_kend }} },
      { name: 'ERROR',       y: {{ error_kend }} }
    ];
    const durCategories  = {{ dur_categories|tojson }};
    const durValues      = {{ dur_values|tojson }};

    function makeSteps() {
      Highcharts.chart('chart-steps', {
        chart: { type: 'column', height: document.getElementById('wrap-steps').clientHeight - 36 },
        title: { text: null },
        xAxis: { categories: stepCategories, title: { text: 'Step' } },
        yAxis: { title: { text: 'Jumlah Pasien' }, allowDecimals: false },
        legend: { enabled: false },
        series: [{ name: 'Pasien', data: stepValues }]
      });
    }

    function makeStatusKendaraan() {
      Highcharts.chart('chart-status-kendaraan', {
        chart: { type: 'pie', height: document.getElementById('wrap-status').clientHeight - 36 },
        title: { text: null },
        plotOptions: {
          pie: {
            innerSize: '55%',
            dataLabels: { enabled: true, format: '{point.name}: {point.y}', style: { fontSize: '11px' } }
          }
        },
        series: [{ name: 'Jumlah', data: statusKendData }]
      });
    }

    function makeDurasi() {
      Highcharts.chart('chart-dur', {
        chart: { type: 'bar', height: document.getElementById('wrap-dur').clientHeight - 36 },
        title: { text: null },
        xAxis: { categories: durCategories, title: { text: null } },
        yAxis: { title: { text: 'Rata-rata (jam)' } },
        legend: { enabled: false },
        tooltip: { valueDecimals: 2, valueSuffix: ' jam' },
        series: [{ name: 'Rata-rata (jam)', data: durValues }]
      });
    }

    // Render setelah DOM siap
    window.addEventListener('load', () => {
      makeSteps(); makeStatusKendaraan(); makeDurasi();
    });

    // Re-render jika container berubah (mis. ganti zoom TV)
    window.addEventListener('resize', () => {
      makeSteps(); makeStatusKendaraan(); makeDurasi();
    });
  </script>
</body>
</html>
    """,
    now_str=now_str,
    total_resi=total_resi,
    step_categories=step_categories, step_values=step_values,
    lunas_kend=lunas_kend, belum_kend=belum_kend, error_kend=error_kend,
    dur_categories=dur_categories, dur_values=dur_values
    )


if __name__ == '__main__':
    # app.run(debug=True)

    app.run(host='0.0.0.0', port=5011, debug=True)
