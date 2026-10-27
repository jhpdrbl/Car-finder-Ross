// "Added by you" tab: cars the user added by hand, which the search can't re-read. The user checks each one on the
// dealer's site and marks it. GET returns {seen: {VIN: "YYYY-MM-DD"}, gone: {VIN: "YYYY-MM-DD"},
// price: {VIN: {p: dollars, d: "YYYY-MM-DD"}}}, PUT replaces all three. The next search reads `gone` (moves those cars to
// "No longer available") and `price` (the dealer's new advertised price). Same KV namespace as favorites (FAVS).

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", "cache-control": "no-store" } });

// ?p=jenna: another buyer's page keeps its own marks (mine:jenna); Ross's page keeps mine:default
const keyFor = request => {
  const who = (request.headers.get("cf-access-authenticated-user-email") || "default").toLowerCase();
  const p = (new URL(request.url).searchParams.get("p") || "").toLowerCase();
  return /^[a-z]{1,20}$/.test(p) && p !== "ross" ? `mine:${p}${who === "default" ? "" : ":" + who}` : "mine:" + who;
};

const DATE = /^\d{4}-\d{2}-\d{2}$/, VIN = /^[A-HJ-NPR-Z0-9]{17}$/;
const clean = raw => {
  const out = {};
  if (raw && typeof raw === "object" && !Array.isArray(raw))
    for (const [vin, day] of Object.entries(raw).slice(0, 500)) if (VIN.test(vin) && typeof day === "string" && DATE.test(day)) out[vin] = day;
  return out;
};

const cleanPrices = raw => {
  const out = {};
  if (raw && typeof raw === "object" && !Array.isArray(raw))
    for (const [vin, x] of Object.entries(raw).slice(0, 500))
      if (VIN.test(vin) && x && Number.isFinite(x.p) && x.p >= 3000 && x.p <= 500000 && typeof x.d === "string" && DATE.test(x.d))
        out[vin] = { p: Math.round(x.p), d: x.d };
  return out;
};

export async function onRequestGet({ request, env }) {
  if (!env.FAVS) return json({ error: "sync not set up" }, 503);
  const saved = (await env.FAVS.get(keyFor(request), "json")) || {};
  return json({ seen: clean(saved.seen), gone: clean(saved.gone), price: cleanPrices(saved.price) });
}

export async function onRequestPut({ request, env }) {
  if (!env.FAVS) return json({ error: "sync not set up" }, 503);
  let body;
  try { body = await request.json(); } catch { return json({ error: "bad JSON" }, 400); }
  if (!body || typeof body !== "object") return json({ error: "expected {seen: {...}, gone: {...}}" }, 400);
  const saved = { seen: clean(body.seen), gone: clean(body.gone), price: cleanPrices(body.price) };
  await env.FAVS.put(keyFor(request), JSON.stringify(saved));
  return json(saved);
}
