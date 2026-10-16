// Favorites sync for the dashboard: GET returns the saved VIN list, PUT replaces it.
// Runs as a Cloudflare Pages Function next to the site. Needs a KV namespace bound to the
// Pages project as FAVS (Cloudflare dashboard: Workers & Pages > cpo-suv-finder > Settings >
// Bindings). Cloudflare Access sits in front of the whole site, so only signed-in users reach
// this; each user's list is stored under their Access email.

const VIN = /^[A-HJ-NPR-Z0-9]{17}$/;
const MAX = 300;

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", "cache-control": "no-store" } });

// ?p=jenna: another buyer's page keeps its own list (fav:jenna); Ross's page (no p) keeps fav:default
const buyer = request => {
  const p = (new URL(request.url).searchParams.get("p") || "").toLowerCase();
  return /^[a-z]{1,20}$/.test(p) && p !== "ross" ? p : "";
};

const keyFor = request => {
  const who = (request.headers.get("cf-access-authenticated-user-email") || "default").toLowerCase();
  const p = buyer(request);
  return p ? `fav:${p}${who === "default" ? "" : ":" + who}` : "fav:" + who;
};

export async function onRequestGet({ request, env }) {
  if (!env.FAVS) return json({ error: "sync not set up" }, 503);
  let saved = await env.FAVS.get(keyFor(request), "json");
  // favorites saved before sign-in (Cloudflare Access) was turned on live under "default"; carry them over once
  if (saved === null && !buyer(request) && keyFor(request) !== "fav:default") saved = await env.FAVS.get("fav:default", "json");
  return json({ fav: Array.isArray(saved) ? saved : [] });
}

export async function onRequestPut({ request, env }) {
  if (!env.FAVS) return json({ error: "sync not set up" }, 503);
  let body;
  try { body = await request.json(); } catch { return json({ error: "bad JSON" }, 400); }
  if (!body || !Array.isArray(body.fav)) return json({ error: "expected {fav: [...]}" }, 400);
  const fav = [...new Set(body.fav.map(v => String(v).toUpperCase()).filter(v => VIN.test(v)))].slice(0, MAX);
  await env.FAVS.put(keyFor(request), JSON.stringify(fav));
  return json({ fav });
}
