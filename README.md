# Shopify Payment Checker v2.1 - Railway Deploy

## Files Required
1. `shopify_checker.py` - Main code (CLI + API hybrid)
2. `requirements.txt` - Python dependencies
3. `Procfile` - Railway process config

## Railway Setup

### 1. Environment Variables (Railway Dashboard → Variables)
```
TOKEN = your_secret_token_here
```

### 2. Deploy
- Push code to GitHub
- Connect Railway to GitHub repo
- Railway auto-detects Python + Procfile

## Usage

### CLI Mode (Local/Termux)
```bash
python shopify_checker.py
```

### API Mode (Railway)
```bash
# Single Check
curl -X POST https://your-app.up.railway.app/check \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"card":"4972039707804898|06|2028|853"}'

# Bulk Check
curl -X POST https://your-app.up.railway.app/bulk \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"cards":["4972039707804898|06|2028|853","4111111111111111|12|2025|123"]}'

# Mass Check
curl -X POST https://your-app.up.railway.app/mass \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"cards":["4972039707804898|06|2028|853"],"threads":5}'
```
