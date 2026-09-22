// Mismo patrón de seguridad que send-email.js: las plantillas viven del
// lado del servidor. Aunque alguien tenga la clave de acceso, solo puede
// armar ESTOS mensajes con estas variables, nunca texto libre. Este
// endpoint no envía nada por sí mismo: arma el link wa.me con el texto ya
// codificado; el envío real lo dispara la persona al apretar "Enviar"
// dentro de WhatsApp, a propósito, para no automatizar el envío en sí
// (ver nota en el mensaje sobre riesgo de baneo por bulk-send no oficial).

const DENTAL_TEMPLATE = `Hola, soy Tomás, ayudo a clínicas dentales en Santiago a que lleguen pacientes ya calificados a tu WhatsApp, no solo consultas curiosas. Vi que {{nombre_empresa}} no tiene página web, por eso probablemente tu info está repartida entre redes y el boca a boca.

Eso hace que la gente llegue confundida a tu WhatsApp preguntando lo básico, y muchas veces se va sin agendar.

Armé un boceto de una página que filtra eso antes de que lleguen, sin costo ni compromiso.

¿15 min esta semana para mostrarte? Si no es prioridad, me avisas y no insisto.`;

// Detailing: el dolor es el mismo mecanismo (info dispersa -> preguntan lo
// básico -> muchos no agendan), pero el contenido específico cambia. Acá
// no es "horarios y precios" fijos como en dental, es la cotización, que
// varía según el auto -> por eso se repite la misma pregunta con cada
// cliente nuevo. Dos variantes según lo que ya muestra Maps (dato
// verificado en el scrape, no una suposición): si el único link visible
// es Instagram/Facebook, o si no hay ningún link.
const DETAILING_NO_LINK_TEMPLATE = `Hola, soy Tomás, ayudo a servicios de detailing automotriz en Santiago a que lleguen clientes ya calificados a tu WhatsApp, no solo gente preguntando cotización sin decidirse. Vi que {{nombre_empresa}} no tiene página propia, por eso probablemente cada cliente nuevo te pregunta lo mismo desde cero: qué incluye, cuánto cuesta según el auto, cómo agendar.

Eso te hace perder tiempo respondiendo lo básico una y otra vez, con gente que muchas veces ni siquiera termina agendando.

Armé un boceto de una página con tus trabajos y paquetes claros, para que lleguen a tu WhatsApp ya decididos, sin costo ni compromiso.

¿15 min esta semana para mostrarte? Si no es prioridad, me avisas y no insisto.`;

const DETAILING_SOCIAL_LINK_TEMPLATE = `Hola, soy Tomás, ayudo a servicios de detailing automotriz en Santiago a que lleguen clientes ya calificados a tu WhatsApp, no solo gente preguntando cotización sin decidirse. Vi que {{nombre_empresa}} solo tiene Instagram o Facebook como link, sin página propia, por eso probablemente cada cliente nuevo te pregunta lo mismo desde cero: qué incluye, cuánto cuesta según el auto, cómo agendar.

Eso te hace perder tiempo respondiendo lo básico una y otra vez, con gente que muchas veces ni siquiera termina agendando.

Armé un boceto de una página con tus trabajos y paquetes claros, para que lleguen a tu WhatsApp ya decididos, sin costo ni compromiso.

¿15 min esta semana para mostrarte? Si no es prioridad, me avisas y no insisto.`;

const PHONE_RE = /^\+[1-9]\d{7,14}$/;

function fill(template, vars) {
  return template.replace(/\{\{nombre_empresa\}\}/g, vars.nombreEmpresa);
}

function pickTemplate(vertical, hasSocialLink) {
  if (vertical === 'detailing_automotriz') {
    return hasSocialLink ? DETAILING_SOCIAL_LINK_TEMPLATE : DETAILING_NO_LINK_TEMPLATE;
  }
  // clinica_dental es el default: cubre el valor existente y cualquier
  // vertical no reconocida todavía, para no romper llamadas ya en uso.
  return DENTAL_TEMPLATE;
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
    const { telefono, nombreEmpresa, vertical, hasSocialLink, key } = body;

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
    const template = pickTemplate(vertical, !!hasSocialLink);
    const text = fill(template, vars);
    const digits = String(telefono).trim().replace(/[^\d]/g, '');
    const url = `https://wa.me/${digits}?text=${encodeURIComponent(text)}`;

    res.status(200).json({ ok: true, url });
  } catch (e) {
    console.error(e);
    res.status(500).json({ error: String((e && e.message) || e) });
  }
};
