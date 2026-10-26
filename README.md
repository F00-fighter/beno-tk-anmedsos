# Pipeline pengumpulan data MBG 2027 (TK 2)

Repo ini menyiapkan pengumpulan **komentar publik YouTube** tentang alokasi anggaran MBG 2027 setelah pemaparan RKA BGN pada 3 September 2026. Rencana TK 1 semula menyebut Threads dan Reddit; keputusan penelitian saat ini mengganti Reddit dengan YouTube. **Implementasi yang tersedia di repo baru mencakup YouTube.** Jangan menyebut dataset ini sebagai hasil gabungan dua platform dalam laporan.

## Lingkup dan arsitektur kecil

Untuk TK 2, fokusnya adalah memperoleh data yang dapat ditelusuri, menyimpan hasil, dan menjelaskan kualitas serta keterbatasannya. IndoBERT, BERTopic, pelatihan model, dashboard, database, cloud storage, dan orkestrator belum diperlukan.

```text
beno-tk-anmedsos/
├── youtubeAPI1-Vids.py       # aturan pencarian, seleksi, pagination, normalisasi CSV
├── run_pipeline.py           # membuat satu run_id dan manifest per eksekusi
├── requirements.txt          # dependensi Python yang dipatok
├── AGENTS.md                 # aturan untuk pengembangan berikutnya
├── docs/ARCHITECTURE.md      # desain, peta kebutuhan data, batasan
├── data/
│   ├── raw/<run_id>/youtube_api_responses.jsonl
│   ├── interim/<run_id>/
│   │   ├── candidates_youtube.csv
│   │   └── rejected_youtube.csv
│   └── processed/
│       ├── <run_id>/mbg_2027_youtube_comments.csv
│       └── legacy/mbg_2027_youtube_comments.csv
└── runs/<run_id>/            # metadata eksekusi, dibuat otomatis
    ├── youtubeAPI1-Vids.py   # salinan kode tepat saat eksekusi
    ├── collection.log        # jumlah tahap seleksi, panggilan, dan error
    └── manifest.json         # waktu, versi Python/library, status, checksum
```

Ini mengikuti pembagian pada slide: `raw/` untuk data sebagaimana diterima dari API, `interim/` untuk daftar kandidat dan keputusan seleksi, `processed/` untuk CSV tabular siap analisis. Tidak perlu membuat `external/` karena belum memakai dataset luar. Folder `<run_id>` adalah versi snapshot; karena itu **nama CSV tetap** `mbg_2027_youtube_comments.csv` dan tidak memerlukan akhiran `v1`, `final`, atau tanggal tambahan. Nama file ini adalah konvensi repo, bukan nama wajib dari slide. Setiap run terpisah mencegah data lama tertimpa, dan `runs/<run_id>/manifest.json` menghubungkan berkas pada tiga tahap tersebut.

Simpan `data/raw/`, `data/interim/`, `data/processed/<run_id>/`, dan `runs/` yang dipakai untuk laporan di tempat privat. Raw API dapat memuat informasi pengguna; jangan unggah folder tersebut atau kunci API ke repo publik. Berbagi kode, kriteria, statistik agregat, dan bila sesuai kebijakan platform ID konten lebih aman daripada menerbitkan teks komentar mentah. CSV di `data/processed/legacy/` adalah artefak historis yang **sudah terlacak Git**, memuat teks dan permalink, serta tidak memiliki raw/manifest asal. Tinjau berkas itu sebelum membuat repo publik; `.gitignore` tidak menghapus berkas yang sudah terlacak.

## Aturan pengembangan berikutnya

[AGENTS.md](AGENTS.md) adalah pedoman bagi kontributor dan agen pengembang. [Rancangan arsitektur](docs/ARCHITECTURE.md) menjelaskan alasan teknis dan peta kebutuhan data. Keduanya harus diperbarui bila cakupan, metode koleksi, atau schema berubah.

Gunakan nama Python `snake_case.py` untuk berkas baru dan simpan hasil menurut tahapnya di `data/raw/`, `data/interim/`, atau `data/processed/`, masing-masing dengan `<run_id>`. Pertahankan pemisahan antara respons API, hasil seleksi kandidat, dataset CSV olahan, dan manifest. Jangan menimpa run atau mengubah output asli dengan Excel; simpan keputusan manual sebagai CSV input baru yang disalin ke run koleksi. Catat `run_id` yang menghasilkan setiap angka dan contoh pada laporan.

Perubahan kode harus tetap menjawab kebutuhan TK 2: kriteria pencarian, metadata, pagination, filter, kualitas data, dan etika. Jika kolektor Threads ditambahkan, gunakan kolom inti yang sama agar kelak bisa digabung berdasarkan `content_id` dan `platform`, tetapi simpan raw serta dataset per platform secara terpisah. Jangan menambahkan analisis sentimen atau pemodelan topik ke pipeline koleksi ini.

## Menjalankan di Windows PowerShell

Prasyarat: Python 3.11, akses ke YouTube Data API v3, dan API key yang diaktifkan untuk proyek Anda. Dari root repo:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
$env:YOUTUBE_API_KEY = "ISI_KUNCI_API_ANDA"
```

Jika PowerShell menolak aktivasi, gunakan `.\.venv\Scripts\python.exe` sebagai pengganti `python` pada perintah berikut. Kunci API hanya diisi pada sesi terminal ini; jangan masukkan nilainya ke file, commit, atau tangkapan layar.

### 1. Temukan kandidat video

```powershell
python run_pipeline.py --mode discover
```

Catat `<run_id>` dari lokasi `runs/<run_id>` yang tercetak. Periksa `data/interim/<run_id>/candidates_youtube.csv` dan `rejected_youtube.csv`. Pilih video yang benar-benar membahas *alokasi anggaran MBG 2027*, bukan hanya menyebut MBG secara sepintas. Simpan CSV hasil seleksi sebagai berkas baru dengan kolom `video_id`; jangan mengubah berkas asal dari run penemuan. Catat alasan pemilihan atau pengecualian manual untuk laporan C3/C5.

### 2. Ambil komentar dari kandidat yang dipilih

```powershell
python run_pipeline.py --mode collect --candidates "data\interim\<run_id_penemuan>\pilihan_video.csv"
```

Perintah ini menyalin CSV pilihan ke `data/interim/<run_id_koleksi>/candidates_youtube.csv` sebagai bukti input. Tanpa `--candidates`, kolektor akan melakukan pencarian video langsung lalu mengambil komentar, sehingga biaya kuota lebih besar dan proses seleksi manual terlewati. Periksa `runs/<run_id_koleksi>/manifest.json` dan `collection.log`, respons di `data/raw/<run_id_koleksi>/`, serta CSV di `data/processed/<run_id_koleksi>/`. Jika muncul pesan kuota habis atau error API, tandai hasil sebagai **parsial** dalam laporan; status `completed` pada manifest hanya berarti tidak ada error yang dikenali oleh skrip.

Untuk mengakhiri sesi, jalankan `deactivate`. Jangan mengulang koleksi hanya untuk mengejar baris identik: isi komentar, jumlah suka, hasil pencarian, dan ketersediaan video dapat berubah. Reproduksibilitas di sini berarti kode, parameter, input, respons yang diambil, dan transformasi dapat diaudit. Checksum dalam manifest memverifikasi berkas pada run tersebut.

## Menggunakan hasil untuk laporan TK 2

Lihat [desain arsitektur](docs/ARCHITECTURE.md) untuk diagram pipeline, pemetaan RQ ke atribut, aturan seleksi, serta poin C1–C6. Cantumkan tautan repo publik, diagram, tanggal dan periode koleksi, kueri, batas jumlah, total kandidat/ditolak/komentar, contoh kecil hasil, serta keterbatasan. Laporan tugas sendiri harus memakai template yang disediakan dan dikumpulkan sebagai PDF.

| Bagian TK 2 | Bukti dari repo/run | Konsep slide yang dipakai |
| --- | --- | --- |
| C1 kebutuhan data | Tabel RQ → atribut di `docs/ARCHITECTURE.md`, schema CSV | Pemilihan platform dan jenis data sesuai tujuan penelitian |
| C2 pipeline | Diagram di dokumen arsitektur dan alur dua skrip | Koleksi → penyimpanan → pemeriksaan kualitas → penyiapan data |
| C3 metode | Kueri/parameter di salinan kolektor, respons JSONL, kandidat diterima/ditolak | API, autentikasi, pagination, pembatasan kuota, error |
| C4 implementasi | `collection.log`, jumlah baris dan checksum pada `manifest.json`, contoh data yang aman ditampilkan | Metadata, provenance, versi dataset dan kode |
| C5 kualitas | Jumlah tahap seleksi, alasan penolakan, error, batas sampel | Data hilang, duplikasi, bias, cakupan platform |
| C6 etika | `.gitignore`, penggunaan environment variable, kebijakan raw privat | Minimalisasi data, privasi, publikasi bertanggung jawab |

Repo yang dapat direproduksi **tidak menggantikan laporan**: tabel, diagram, justifikasi, hasil pengumpulan nyata, dan keterbatasan tetap harus dijelaskan dalam PDF TK 2. Untuk keluaran lama di root, catat keterbatasan provenance secara eksplisit; jangan membuat manifest seolah-olah raw dan parameter historisnya diketahui.
