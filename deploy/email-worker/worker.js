import PostalMime from 'postal-mime';

export default {
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
        },
        body: JSON.stringify(payload),
      });
      if (res.ok) return;
      lastStatus = res.status;
      await new Promise((r) => setTimeout(r, 3000));
    }
    throw new Error('ingest failed after retries, last status ' + lastStatus);
  },
};
