// Mismo patrón de seguridad que send-email.js: la plantilla vive del lado
// del servidor. Aunque alguien tenga la clave de acceso, solo puede armar
// ESTE mensaje con estas variables — nunca texto libre. Este endpoint no
// envía nada por sí mismo: arma el link wa.me con el texto ya codificado;
// el envío real lo dispara la persona al apretar "Enviar" dentro de
// WhatsApp, a propósito, para no automatizar el envío en sí (ver nota en
// el mensaje de wa.me sobre riesgo de baneo por bulk-send no oficial).
const BODY_TEMPLATE = `Hola, soy Tomás — ayudo a clínicas dentales en Santiago a que lleguen pacientes ya calificados a tu WhatsApp, no solo consultas curiosas. Vi que {{nombre_empresa}} no tiene página web — por eso probablemente tu info está repartida entre redes y el boca a boca.

Eso hace que la gente llegue confundida a tu WhatsApp preguntando lo básico, y muchas veces se va sin agendar.

Armé un boceto de una página que filtra eso antes de que lleguen — sin costo ni compromiso.

¿15 min esta semana para mostrarte? Si no es prioridad, me avisas y no insisto.`;

const PHONE_RE = /^\+[1-9]\d{7,14}$/;

function fill(template, vars) {
  return template.replace(/\{\{nombre_empresa\}\}/g, vars.nombreEmpresa);
}

module.exports = async function handler(req, res) {
  if (req.method !== 'POST') {
    res.status(405).json({ error: 'method not allowed' });
    return;
  }

  const accessKey = process.env.EMAIL_ACCESS_KEY;

  if (!accessKey) {
    res.status(500).json({
      error: 'Clave de acceso no configurada todavía en Vercel (falta EMAIL_ACCESS_KEY)',
    });
    return;
  }

  try {
    const body = req.body || {};
    const { telefono, nombreEmpresa, key } = body;

    if (key !== accessKey) {
      res.status(401).json({ error: 'Clave de acceso incorrecta' });
      return;
    }
    if (!nombreEmpresa || !String(nombreEmpresa).trim()) {
      res.status(400).json({ error: 'Falta el nombre de la empresa' });
      return;
    }
    if (!telefono || !PHONE_RE.test(String(telefono).trim())) {
      res.status(400).json({ error: 'Teléfono inválido — se espera formato E.164, ej. +56912345678' });
      return;
    }

    const vars = { nombreEmpresa: String(nombreEmpresa).trim() };
    const text = fill(BODY_TEMPLATE, vars);
    const digits = String(telefono).trim().replace(/[^\d]/g, '');
    const url = `https://wa.me/${digits}?text=${encodeURIComponent(text)}`;

    res.status(200).json({ ok: true, url });
  } catch (e) {
    console.error(e);
    res.status(500).json({ error: String((e && e.message) || e) });
  }
};
