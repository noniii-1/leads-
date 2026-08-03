const KEY = 'leads_santiago_state_h';

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

function pairsToState(pairs) {
  const state = {};
  if (!Array.isArray(pairs)) return state;
  for (let i = 0; i < pairs.length; i += 2) {
    const cid = pairs[i];
    try { state[cid] = JSON.parse(pairs[i + 1]); } catch (e) { /* skip corrupt entry */ }
  }
  return state;
}

module.exports = async function handler(req, res) {
  if (!process.env.KV_REST_API_URL || !process.env.KV_REST_API_TOKEN) {
    res.status(500).json({ error: 'KV no configurado todavía en Vercel (Storage > KV > Connect Project)' });
    return;
  }

  try {
    if (req.method === 'GET') {
      const { result } = await upstash(['HGETALL', KEY]);
      res.setHeader('Cache-Control', 'no-store');
      res.status(200).json(pairsToState(result));
      return;
    }

    if (req.method === 'POST') {
      const body = req.body || {};
      const { cid, state: leadState } = body;
      if (!cid || typeof leadState !== 'object') {
        res.status(400).json({ error: 'body inválido, se espera { cid, state }' });
        return;
      }
      await upstash(['HSET', KEY, cid, JSON.stringify(leadState)]);
      res.status(200).json({ ok: true });
      return;
    }

    res.status(405).json({ error: 'method not allowed' });
  } catch (e) {
    console.error(e);
    res.status(500).json({ error: String(e && e.message || e) });
  }
};
