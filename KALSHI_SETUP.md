# Kalshi API Setup - REQUIRED FOR BOT TO WORK

## Step 1: Upload Your Public Key to Kalshi Dashboard

The bot uses RSA-PSS authentication. **You MUST upload the public key to Kalshi.**

### Your Public Key (copy this entire block):
```
-----BEGIN PUBLIC KEY-----
MIICIjANBgkqhkiG9w0BAQEFAAOCAg8AMIICCgKCAgEAxA+f0fzFwdD+dhCIkj5O
AcK6Toc78aARXXTbaVfqaa6nliqOkHqIh9n7lgJxtxy3DkbRSLfTvHY1Mkagp/kt
FrJ7NVIHxviFynEQU17RH6iwBU92NAdDrtJH9Sg9jQ6/4slcg08uMKkBD0MBOLgf
hBB7eEABTOdePAGGKjbZ9ARkN5zLrGYd0bUIQQaqIL3vSq0+yiwzMG1H4vZuNa6z
3IZIoJsoivNj5LjhOci9ia0oFa+As0+z1vPxnPrIL6LvultXWarXycRdaAlNl0dI
9FeXXsA0ELwG95izfjv9IhDuvOdhZfm2uxtwjDZRcA5n+5EjTe2d0wHe+n0Dm4uC
sxIDoDJyNH1HRqcHqUPxs4Azz1fPs1pnhgAKGjSVJKFMKDcav7hbsuRg2bfr8PtF
PeXqApQSoYAyK4ZQU2IrBTf9o2oOvT1Gka0CZDvKzDBi2gwCR9N4zChKSb0n1GcP
/iweHLc8DTPzxHqNmC7+RcwLpg3FHQ/qG9qPie35+4t2UVWIDZre/EqG+hApHT68
o1dyxgp3n0qgx4KKaa7SYwMnUQE2LBn6z337oKY7VMWUp/OALivvOb7CK8AsljAC
iPmyd95ZkeferPzWOUA0ws2fihZkx7m+NNhaCA0CAwEAAQ==
-----END PUBLIC KEY-----
```

### Upload Instructions:
1. Go to https://kalshi.com/portfolio/settings/api
2. Click "Add API Key" or "Create New Key"
3. Paste the PUBLIC KEY above (the entire block including `-----BEGIN...` and `-----END...`)
4. Note your API Key ID (should be: `0bc7ca02-29fc-46e0-95ac-f1256213db58`)
5. Ensure the key is active/enabled

## Step 2: Verify Configuration

Your `.env` file should have:
```
KALSHI_API_KEY=0bc7ca02-29fc-46e0-95ac-f1256213db58
KALSHI_PRIVATE_KEY_PATH=./kalshi_private_key.pem
KALSHI_USE_DEMO=false
```

## Step 3: Test Connection
```bash
python3 validate_setup.py
```

## Troubleshooting 403 Errors

If you get `403 Forbidden`:
1. **Public key not uploaded**: Upload the public key above to your Kalshi dashboard
2. **Wrong API key ID**: Verify your API key ID matches what's in `.env`
3. **Geo-restrictions**: Kalshi only works from US IP addresses
4. **API key disabled**: Check your Kalshi dashboard that the key is active

## Files in This Deployment

- `kalshi_private_key.pem` - Your RSA private key (KEEP SECRET!)
- `kalshi_public_key.pem` - Upload this to Kalshi dashboard
- `.env` - Configuration with your API key ID

## Production vs Demo

- **Production API**: `https://api.elections.kalshi.com/trade-api/v2`
  - Uses your live Kalshi account
  - Paper trading uses internal simulation (no real trades)
  
- **Demo API**: `https://demo-api.kalshi.co/trade-api/v2`
  - Requires separate demo account registration at Kalshi
  - Your production API keys do NOT work with demo
