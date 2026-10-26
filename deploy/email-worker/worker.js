import PostalMime from 'postal-mime';

export default {
  async scheduled(event, env) {
    const res = await fetch(new URL('/healthz', env.INGEST_URL), {
      headers: { 'User-Agent': 'Mozilla/5.0', ...(env.PROXY_SECRET ? { 'X-Proxy-Secret': env.PROXY_SECRET } : {}) },
    });
    if (!res.ok) throw new Error('keep-warm ping failed with status ' + res.status);
  },

  async email(message, env) {
    const email = await new PostalMime().parse(message.raw);
    const payload = {
      from: message.from,
      to: message.to,
      subject: email.subject || message.headers.get('subject') || '',
      text: (email.text || email.html || '').trim(),
      message_id: email.messageId || message.headers.get('message-id') || '',
    };
    let lastStatus = 0;
    for (let attempt = 0; attempt < 3; attempt++) {
      const res = await fetch(env.INGEST_URL, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer ' + env.API_TOKEN,
          'User-Agent': 'Mozilla/5.0',
          ...(env.PROXY_SECRET ? { 'X-Proxy-Secret': env.PROXY_SECRET } : {}),
        },
        body: JSON.stringify(payload),
      });
      if (res.ok) return;
      lastStatus = res.status;
      console.error('ingest attempt', attempt + 1, 'failed with status', res.status, (await res.text()).slice(0, 200));
      await new Promise((r) => setTimeout(r, 3000));
    }
    throw new Error('ingest failed after retries, last status ' + lastStatus);
  },
};
