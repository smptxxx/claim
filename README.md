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
