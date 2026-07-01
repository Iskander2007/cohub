# PayPal Integration Guide for COHUB

## Overview

COHUB supports **real PayPal payment processing** for PRO subscriptions. Users can pay via PayPal in USD with a seamless checkout experience.

### Key Features
- ✅ Real-time payment processing via PayPal REST API v2
- ✅ Automatic webhook handling for payment confirmation
- ✅ Sandbox testing mode (no real charges)
- ✅ Fallback emulation mode (if credentials not provided)
- ✅ Secure signature verification for webhook authenticity

---

## Setup Steps

### Step 1: Create PayPal Developer Account

1. Go to https://developer.paypal.com
2. Click **Sign Up** and create an account (or use existing PayPal account)
3. Verify your email
4. Accept the developer agreement

### Step 2: Access Developer Dashboard

1. Log in to https://developer.paypal.com
2. Click **Dashboard** in the top navigation
3. You'll see the Apps & Credentials page

### Step 3: Create or Locate Your App

**For Sandbox Testing:**
1. Click the **Sandbox** tab (left sidebar, under "Accounts")
2. Under "REST API apps", click **Create App**
3. Enter app name (e.g., "COHUB Subscriptions")
4. Click **Create App**

**For Production (Live):**
1. Click the **Live** tab
2. Repeat the same process (if you haven't already created a live app)

### Step 4: Get Your Credentials

1. Click on your app name in the list
2. You'll see two sections:
   - **Signature**: Contains `Client ID` and `Secret`
   - Copy these values

3. Set in your `.env` file:
   ```bash
   PAYPAL_CLIENT_ID=<your_client_id>
   PAYPAL_CLIENT_SECRET=<your_secret>
   PAYPAL_MODE=sandbox  # for testing; use 'live' for production
   ```

---

## Step 5: Set Up Webhooks (Recommended)

Webhooks allow PayPal to notify COHUB immediately when a payment is completed or denied.

### Without Webhook (Simple Mode)
- Payment is confirmed when user returns from PayPal
- Less reliable if user closes browser before returning
- No real-time payment notification

### With Webhook (Robust Mode)
- PayPal server notifies COHUB server immediately
- More reliable payment confirmation
- Real-time subscription activation

### To Set Up Webhook:

1. **Go to Webhook Settings:**
   - PayPal Dashboard → Settings (⚙️ icon, top-right)
   - Click **Webhooks** (left sidebar, under "Notifications")

2. **Create a Webhook Endpoint:**
   - Click **Create Webhook**
   - Endpoint URL: `https://yourdomain.com/payments/callback/paypal/`
   
   **Important:**
   - Must be HTTPS (not HTTP)
   - Must be publicly accessible (PayPal servers must reach it)
   - For local testing, use ngrok: https://ngrok.com
     ```bash
     ngrok http 8000
     # Then set in .env:
     PAYMENT_PUBLIC_BASE_URL=https://xxxx.ngrok-free.app
     ```

3. **Select Events:**
   - Check: `PAYMENT.CAPTURE.COMPLETED`
   - Check: `PAYMENT.CAPTURE.DENIED`
   - Click **Create Webhook**

4. **Get Webhook ID and Secret:**
   - You'll see your webhook in the list
   - Click on it to view details
   - Copy the **Webhook ID**
   - Set in `.env`:
   ```bash
   PAYPAL_WEBHOOK_ID=<your_webhook_id>
   PAYPAL_WEBHOOK_SECRET=<webhook_signing_secret>  # PayPal provides this
   ```

---

## Configuration

### Sandbox Mode (Testing)
```bash
# .env file for testing
PAYPAL_MODE=sandbox
PAYPAL_CLIENT_ID=<sandbox_client_id>
PAYPAL_CLIENT_SECRET=<sandbox_secret>
PAYPAL_WEBHOOK_ID=<sandbox_webhook_id>    # optional
PAYPAL_WEBHOOK_SECRET=<sandbox_secret>     # optional
```

### Production Mode (Live)
```bash
# .env file for production (MUST use HTTPS!)
PAYPAL_MODE=live
PAYPAL_CLIENT_ID=<live_client_id>
PAYPAL_CLIENT_SECRET=<live_secret>
PAYPAL_WEBHOOK_ID=<live_webhook_id>
PAYPAL_WEBHOOK_SECRET=<live_secret>

# Also ensure:
DJANGO_SECURE_SSL_REDIRECT=True
DJANGO_SESSION_COOKIE_SECURE=True
DJANGO_CSRF_COOKIE_SECURE=True
```

---

## Testing the Integration

### Test Case 1: Sandbox Mode Without Credentials
**Expected:** Shows emulated PayPal form (for development)
```bash
PAYPAL_MODE=sandbox
# Leave PAYPAL_CLIENT_SECRET empty
```

### Test Case 2: Sandbox Mode With Credentials
**Expected:** Redirects to real PayPal sandbox checkout
```bash
PAYPAL_MODE=sandbox
PAYPAL_CLIENT_ID=<your_sandbox_client_id>
PAYPAL_CLIENT_SECRET=<your_sandbox_secret>
```

### Test Accounts for Sandbox
Use these test accounts in PayPal sandbox:
- **Buyer Account:** sb-[generated]@personal.example.com
- **Seller Account:** sb-[generated]@business.example.com

Find these in PayPal Dashboard → Accounts (under Sandbox tab)

### Test Payments
1. Go to subscription page in COHUB
2. Click "Subscribe with PayPal"
3. In sandbox: Log in with sb-buyer account
4. Confirm payment
5. Return to COHUB
6. Check if subscription is activated

---

## Payment Flow

### User Perspective
1. User clicks "Subscribe with PayPal"
2. Redirected to PayPal checkout (real or emulated)
3. User approves payment
4. Returned to COHUB payment result page
5. Subscription activated

### Backend Flow (Real PayPal)
1. `checkout/` endpoint → Creates PayPal order → Returns approve link
2. User approves on PayPal
3. User returns to `payment_return/` → Captures order → Confirms payment
4. Optional: PayPal sends webhook → Additional confirmation

### Backend Flow (Sandbox Without Credentials)
1. `checkout/` endpoint → Shows emulated form
2. User clicks "Pay" button
3. Emulated callback processes payment
4. Subscription activated

---

## Troubleshooting

### Payment redirects to PayPal but never returns
- **Check:** `PAYMENT_PUBLIC_BASE_URL` is set correctly
- **Check:** Return URL is HTTPS if in production
- **Check:** Domain is accessible and whitelisted in PayPal

### "Invalid Webhook ID" error
- **Solution:** Leave `PAYPAL_WEBHOOK_ID` empty for now
- **Alternative:** Verify webhook is active in PayPal Dashboard

### "Insufficient permissions" error
- **Check:** Your PayPal account is active
- **Check:** You're using the correct mode (sandbox/live)
- **Contact:** PayPal Support if issue persists

### Sandbox test account not working
- **Solution:** Create new test accounts in PayPal Dashboard → Accounts
- **Note:** Sandbox credentials separate from live credentials

---

## Pricing Configuration

Set subscription prices in `.env`:
```bash
SUBSCRIPTION_PRICE_USD=9.99    # PayPal (USD)
SUBSCRIPTION_PRICE_KZT=5000    # Bereke (KZT)
```

Current defaults:
- PayPal: $9.99/month
- Bereke: 5000 KZT/month

---

## Security Notes

⚠️ **Important Security Practices:**

1. **Never commit `.env` to Git**
   - Add `.env` to `.gitignore`
   - Use `.env.example` for template

2. **Use HTTPS in production**
   - PayPal requires HTTPS for live credentials
   - Nginx/Apache should handle SSL termination

3. **Rotate secrets regularly**
   - Change `PAYPAL_CLIENT_SECRET` annually
   - Use environment variables, never hardcode

4. **Webhook signature verification**
   - COHUB automatically verifies PayPal webhook signatures
   - Tampering attempts are rejected

---

## API Endpoints

### Payment Endpoints
- `POST /api/orders/checkout/` — Create order and get payment link
- `GET /payments/gateway/<order_id>/` — Emulated payment form (sandbox only)
- `POST /payments/sandbox-confirm/<order_id>/` — Emulated payment confirm
- `GET /payments/return/<order_id>/` — Payment result (captures real PayPal orders)
- `POST /payments/callback/paypal/` — Webhook endpoint (server-to-server)

### Configuration Endpoint
- `GET /api/orders/config/` — List available payment methods and prices

---

## Support

For issues:
1. Check `.env` configuration
2. Review browser console for errors
3. Check Django logs: `python manage.py tail` (if available)
4. Enable `DJANGO_DEBUG=True` temporarily for detailed errors (dev only)
5. Visit https://developer.paypal.com/docs for PayPal API docs

---

## Further Reading

- [PayPal Checkout Integration Guide](https://developer.paypal.com/docs/checkout/)
- [PayPal REST API Reference](https://developer.paypal.com/docs/api/overview/)
- [Webhook Verification](https://developer.paypal.com/docs/api-basics/notifications/webhooks/verify-webhook-signature/)
- [Test Accounts & Credentials](https://developer.paypal.com/docs/checkout/how-to/test/)
