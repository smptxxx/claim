# Auto Claim Tencent Cloud

Tools untuk auto-claim Lighthouse 2C2G (3 months) di Tencent Cloud Free Tier.

## Setup

```bash
pip install playwright python-dotenv
playwright install chromium
```

## Login sekali (simpan session)

```bash
python auto_claim.py --login
```

## Jalankan auto claim (jam 23:00)

```bash
python auto_claim.py
```

Script akan:
1. Membuka browser dengan session tersimpan
2. Menunggu sampai 22:59:30
3. Jam 23:00:00 → refresh → Get Started → Buy Now → Pay Now → Confirm
4. Retry 3x jika gagal
5. Screenshot hasil ke `claim_result.png`

---

## WAR EDITION (v2) — `war_claim.py` (RECOMMENDED)

Alur otomatis penuh sesuai strategi "war":

| Jam | Aksi |
|---|---|
| 22:40 | Login SEMUA akun (paralel, maks 4 bersamaan) — 1 akun = 1 browser Chromium terpisah |
| 22:40+ | Browser STANDBY TERBUKA di halaman FreeTier — TIDAK ditutup |
| 22:59:52 | Refresh final semua browser bersamaan |
| 23:00:00 | GAS: Get Started (polling JS 50ms) → Buy Now (JS instan) → Pay Now → Confirm |
| Selesai | Browser dibiarkan terbuka 15 menit untuk verifikasi manual |

Perintah:

```bash
python war_claim.py --login      # login semua akun sekarang
python war_claim.py --test       # LATIHAN: claim COS (Cloud Object Storage)
python war_claim.py --retry-now  # gas 2C2G langsung tanpa nunggu jadwal
python war_claim.py --status     # cek session per akun
python war_claim.py              # WAR PENUH: 22:40 login -> 23:00 gas
```

Akun di `accounts.txt` (di-gitignore, tidak ikut push):
```
email1:password1
email2:password2
```

Catatan teknis:
- 1 akun = 1 browser Chromium terpisah (context + storage_state sendiri).
- Browser tidak pernah di-close otomatis saat standby/gas.
- Jika Get Started "sold out", otomatis reload cari stok (maks 120 detik).
- Screenshot hasil: `claim_<user>_<mode>.png`, debug: `debug_<user>_<mode>.png`.
