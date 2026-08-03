const KEY = 'leads_santiago_call_state';

async function upstash(cmd) {
  const base = process.env.KV_REST_API_URL;
  const token = process.env.KV_REST_API_TOKEN;
  const r = await fetch(base, {
    method: 'POST',
    headers: {
      Authorization: 'Bearer ' + token,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(cmd),
  });
  if (!r.ok) throw new Error('Upstash error ' + r.status);
  return r.json();
}

module.exports = async function handler(req, res) {
  if (!process.env.KV_REST_API_URL || !process.env.KV_REST_API_TOKEN) {
    res.status(500).json({ error: 'KV no configurado todavía en Vercel (Storage > KV > Connect Project)' });
    return;
  }

  try {
    if (req.method === 'GET') {
      const { result } = await upstash(['GET', KEY]);
      let state = {};
      if (result) {
        try { state = JSON.parse(result); } catch (e) { state = {}; }
      }
      res.setHeader('Cache-Control', 'no-store');
      res.status(200).json(state);
      return;
    }

    if (req.method === 'POST') {
      const body = req.body || {};
      const { cid, state: leadState } = body;
      if (!cid || typeof leadState !== 'object') {
        res.status(400).json({ error: 'body inválido, se espera { cid, state }' });
        return;
      }
      const { result } = await upstash(['GET', KEY]);
      let state = {};
      if (result) {
        try { state = JSON.parse(result); } catch (e) { state = {}; }
      }
      state[cid] = leadState;
      await upstash(['SET', KEY, JSON.stringify(state)]);
      res.status(200).json({ ok: true });
      return;
    }

    res.status(405).json({ error: 'method not allowed' });
  } catch (e) {
    console.error(e);
    res.status(500).json({ error: String(e && e.message || e) });
  }
};
