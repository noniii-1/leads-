const nodemailer = require('nodemailer');

// Plantilla fija del lado del servidor: aunque alguien obtenga la clave de
// acceso, solo puede disparar ESTA propuesta con estas variables, nunca
// texto libre arbitrario. Contenido alineado con el template de WSP
// (api/build-whatsapp-link.js): mismo pitch de clientes calificados, mismo
// gancho de "no tiene web", mismo cierre con opt-out.
const SUBJECT_TEMPLATE = '{{nombre_empresa}}, así llegan pacientes calificados a tu WhatsApp';

const BODY_TEMPLATE = `Hola, soy Tomás, ayudo a clínicas dentales en Santiago a que lleguen pacientes ya calificados a tu WhatsApp, no solo consultas curiosas. Vi que {{nombre_empresa}} no tiene página web, por eso probablemente tu info está repartida entre redes y el boca a boca.

Eso hace que la gente llegue confundida a tu WhatsApp preguntando lo básico, y muchas veces se va sin agendar.

Armé un boceto de una página para {{nombre_empresa}}, pensado en tu rubro ({{rubro}}), que filtra eso antes de que lleguen, sin costo ni compromiso.

¿Tienes 15 minutos esta semana para que te lo muestre? Si no es prioridad ahora, me avisas y no insisto.

Quedo atento,
Tomás
Nodal
{{telefono}}`;

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function fill(template, vars) {
  return template
    .replace(/\{\{nombre_empresa\}\}/g, vars.nombreEmpresa)
    .replace(/\{\{rubro\}\}/g, vars.rubro)
    .replace(/\{\{telefono\}\}/g, vars.telefono);
}

module.exports = async function handler(req, res) {
  if (req.method !== 'POST') {
    res.status(405).json({ error: 'method not allowed' });
    return;
  }

  const accessKey = process.env.EMAIL_ACCESS_KEY;
  const gmailUser = process.env.GMAIL_USER;
  const gmailPass = process.env.GMAIL_APP_PASSWORD;

  if (!accessKey || !gmailUser || !gmailPass) {
    res.status(500).json({
      error: 'Envío de correo no configurado todavía en Vercel (faltan EMAIL_ACCESS_KEY, GMAIL_USER o GMAIL_APP_PASSWORD)',
    });
    return;
  }

  try {
    const body = req.body || {};
    const { to, nombreEmpresa, rubro, telefono, key } = body;

    if (key !== accessKey) {
      res.status(401).json({ error: 'Clave de acceso incorrecta' });
      return;
    }
    if (!to || !EMAIL_RE.test(String(to).trim())) {
      res.status(400).json({ error: 'Correo destino inválido' });
      return;
    }
    if (!nombreEmpresa || !rubro || !telefono) {
      res.status(400).json({ error: 'Faltan datos: nombre de la empresa, rubro o teléfono' });
      return;
    }

    const vars = {
      nombreEmpresa: String(nombreEmpresa).trim(),
      rubro: String(rubro).trim(),
      telefono: String(telefono).trim(),
    };

    const transporter = nodemailer.createTransport({
      service: 'gmail',
      auth: { user: gmailUser, pass: gmailPass },
    });

    await transporter.sendMail({
      from: gmailUser,
      to: String(to).trim(),
      subject: fill(SUBJECT_TEMPLATE, vars),
      text: fill(BODY_TEMPLATE, vars),
    });

    res.status(200).json({ ok: true });
  } catch (e) {
    console.error(e);
    res.status(500).json({ error: String((e && e.message) || e) });
  }
};
