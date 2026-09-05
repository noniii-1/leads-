const nodemailer = require('nodemailer');

// Plantilla fija del lado del servidor: aunque alguien obtenga la clave de
// acceso, solo puede disparar ESTA propuesta con estas variables — nunca
// texto libre arbitrario.
const SUBJECT_TEMPLATE = '{{nombre_empresa}}, ya tenemos un boceto listo de tu nueva web';

const BODY_TEMPLATE = `Hola equipo de {{nombre_empresa}},

Mi nombre es Tomás, de Nodal — trabajamos con pymes en Santiago ayudándolas a tener presencia digital profesional.

Hoy en día, muchos clientes eligen dónde atenderse según la confianza que les da lo que encuentran de un negocio antes de decidir: información clara de tus servicios, fotos, horarios y una forma fácil de agendar. Sin una web propia, esa primera impresión depende solo de lo poco que muestra Google Maps, no puedes ofrecer agenda online fuera de tu horario de atención telefónica, y es más fácil perder frente a la competencia que sí se ve profesional. Es una fuga de clientes silenciosa — pasa todos los días y nunca te enteras de cuántos se fueron a otro lado.

La buena noticia es que ya hicimos algo por ti: diseñamos un boceto real de cómo podría verse la web de {{nombre_empresa}}, pensado en tu rubro ({{rubro}}), tus servicios y cómo comunicarlos para generar más consultas y ventas.

No es una plantilla genérica — es un diseño hecho específicamente pensando en tu negocio.

Quiero mostrártelo sin costo ni compromiso. Si te gusta lo que ves, conversamos cómo llevarlo a producción; si no, quedas con una idea clara de hacia dónde podría ir tu presencia digital.

¿Tienes 10 minutos esta semana para que te lo muestre?

Quedo atento,
Tomás
Nodal — Diseño y desarrollo web para pymes
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
