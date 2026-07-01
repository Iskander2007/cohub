# 💳 PayPal Integration - Quick Reference

## 🚀 Quick Setup (5 minutes)

### Step 1: Get PayPal Credentials
```
🌐 https://developer.paypal.com → Dashboard → Apps & Credentials → Create App
Copy: Client ID & Secret
```

### Step 2: Configure
```bash
# Edit .env file
PAYPAL_MODE=sandbox
PAYPAL_CLIENT_ID=your_client_id_here
PAYPAL_CLIENT_SECRET=your_secret_here
```

### Step 3: Test
```bash
python manage.py runserver
# Visit: http://localhost:8000/subscription/
# Click: Subscribe with PayPal
# Use test account: sb-xxxxx@personal.example.com
```

---

## 📝 Configuration Reference

| Variable | Purpose | Example |
|----------|---------|---------|
| `PAYPAL_MODE` | Environment | `sandbox` or `live` |
| `PAYPAL_CLIENT_ID` | App ID | From PayPal Dashboard |
| `PAYPAL_CLIENT_SECRET` | App Secret | From PayPal Dashboard |
| `PAYPAL_WEBHOOK_ID` | Webhook ID | Optional, for webhooks |
| `PAYPAL_WEBHOOK_SECRET` | Webhook Secret | Optional, for webhooks |
| `SUBSCRIPTION_PRICE_USD` | Price per month | `9.99` |
| `PAYPAL_MODE` | Live vs Sandbox | `live` = real payments |

---

## 🔄 Payment Modes

### Mode 1: Sandbox Without Credentials (Emulation) 
**Best for:** Quick local testing
```bash
PAYPAL_MODE=sandbox
# Leave PAYPAL_CLIENT_SECRET empty
```
Result: Fake payment form appears, no real processing

### Mode 2: Sandbox With Credentials (Test Real API)
**Best for:** Testing real PayPal flow
```bash
PAYPAL_MODE=sandbox
PAYPAL_CLIENT_ID=<sandbox_id>
PAYPAL_CLIENT_SECRET=<sandbox_secret>
```
Result: Redirects to PayPal sandbox, test payments only

### Mode 3: Live (Real Payments)
**Best for:** Production
```bash
PAYPAL_MODE=live
PAYPAL_CLIENT_ID=<live_id>
PAYPAL_CLIENT_SECRET=<live_secret>
```
⚠️ **Requires HTTPS!**

---

## 🧪 Testing with ngrok (Local Webhooks)

```bash
# Terminal 1: Start ngrok
ngrok http 8000

# Terminal 2: Update .env
PAYMENT_PUBLIC_BASE_URL=https://xxxx.ngrok-free.app

# Terminal 3: Run Django
python manage.py runserver

# Browser: http://localhost:8000/subscription/
```

---

## ✅ Test Scenarios

### Scenario 1: Emulated Payment ✓
```
1. Leave PAYPAL_CLIENT_SECRET empty
2. Click Subscribe
3. See: "SANDBOX · тестовый режим"
4. Emulated form appears
5. Click "Оплатить картой" → Payment succeeds
```

### Scenario 2: Real PayPal Sandbox ✓
```
1. Set PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET
2. Click Subscribe
3. See: "🔐 РЕАЛЬНЫЙ РЕЖИМ"
4. Redirected to paypal.sandbox.com
5. Login with sb-buyer@personal.example.com
6. Approve payment → Returns to COHUB
7. Subscription activates
```

### Scenario 3: Webhook Confirmation ✓
```
1. Set PAYPAL_WEBHOOK_ID and WEBHOOK_SECRET
2. Complete payment
3. PayPal sends webhook to /payments/callback/paypal/
4. COHUB verifies signature with PayPal API
5. Subscription confirmed via webhook
```

---

## 🐛 Common Issues & Fixes

| Issue | Fix |
|-------|-----|
| "Invalid credentials" | Check Client ID/Secret spelling, ensure sandbox mode |
| "Redirect to PayPal fails" | Set PAYMENT_PUBLIC_BASE_URL for ngrok testing |
| "Webhook not received" | Use ngrok, ensure HTTPS in production |
| "Subscription not active" | Check payment status is 'COMPLETED' |
| "Test account not found" | Create new test account in PayPal Dashboard |

---

## 📚 Useful Links

- **PayPal Developer**: https://developer.paypal.com
- **Test Accounts**: Dashboard → Accounts → Sandbox
- **API Docs**: https://developer.paypal.com/docs/checkout/
- **Webhook Setup**: Dashboard → Settings → Webhooks

---

## 💰 Pricing

Default pricing (can be customized):
- **PayPal**: $9.99/month (USD)
- **Bereke**: 5000 KZT/month

Change in `.env`:
```bash
SUBSCRIPTION_PRICE_USD=9.99
```

---

## 🔒 Production Checklist

Before going live, ensure:
- [ ] HTTPS enabled (SSL certificate installed)
- [ ] `PAYPAL_MODE=live`
- [ ] Live credentials set (not sandbox)
- [ ] `DJANGO_SECURE_SSL_REDIRECT=True`
- [ ] `DJANGO_SESSION_COOKIE_SECURE=True`
- [ ] Webhook configured in PayPal Dashboard
- [ ] PAYPAL_WEBHOOK_ID set
- [ ] Test transaction completed successfully

---

## 📧 Support

**Issue?** Check these first:
1. Is PAYPAL_CLIENT_SECRET set correctly?
2. Is PAYPAL_MODE set correctly (sandbox/live)?
3. For local testing, did you setup ngrok?
4. For production, is HTTPS enabled?

**PayPal Support**: https://developer.paypal.com/contact

---

## 🎯 Payment Flow at a Glance

```
User clicks "Pay" 
    ↓
COHUB creates PayPal order
    ↓
PayPal opens payment form
    ↓
User approves payment
    ↓
Returns to COHUB
    ↓
COHUB captures order
    ↓
Subscription activates ✓
    ↓
(Optional) PayPal webhook confirms
```

---

**Ready to process real payments?** Start with Mode 1 (sandbox emulation), then upgrade to Mode 2 for real testing, finally Mode 3 for production.
