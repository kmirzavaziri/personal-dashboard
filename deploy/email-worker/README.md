# Forwarded email → `/api/ingest/email`

A Cloudflare Email Worker that parses a forwarded email and POSTs `{from, to, subject, text, message_id}`
to the dashboard ingest endpoint. Retries 3× to ride out an origin cold start.

## Deploy

```bash
cd deploy/email-worker
npm install
npx wrangler login
npx wrangler secret put API_TOKEN       # same value as the app's API_TOKEN
npx wrangler secret put INGEST_URL      # https://<your-api-host>/api/ingest/email
npx wrangler deploy
```

Both values are stored as Worker secrets, so nothing host-specific lives in the repo.

The worker is email-triggered, not HTTP — `wrangler.toml` sets `workers_dev = false`, so it deploys
with no `workers.dev` subdomain and no route (`No deploy targets` on deploy is expected and fine).

## Wire up Cloudflare Email Routing

1. Cloudflare dashboard → your zone → **Email → Email Routing** → enable (adds the MX records).
2. **Routes** → create an address like `ingest@<your-domain>` → action **Send to a Worker** → `email-ingest`.

## Gmail filter

1. Gmail → Settings → **Forwarding and POP/IMAP** → add `ingest@<your-domain>` as a forwarding address.
   Gmail sends a confirmation code there; to read it, temporarily route that address to your own inbox,
   grab the code, then switch the route back to the Worker.
2. Gmail → Settings → **Filters** → match the sender(s) you want to ingest → **Forward it to** `ingest@<your-domain>`.

The ingest endpoint is Cloudflare-proxied, so the Worker's POST picks up the origin-lock header
automatically; `INGEST_URL` (a secret) is the only host-specific value and never touches the repo.
