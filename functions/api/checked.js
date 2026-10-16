// "Check yourself" tab: which dealers the user checked by hand, and when. GET returns {checked: {dealer: "YYYY-MM-DD"}},
// PUT replaces it. Stored in the same KV namespace as favorites (FAVS binding), under its own key.

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", "cache-control": "no-store" } });

// ?p=jenna: another buyer's page keeps its own marks (checked:jenna); Ross's page keeps checked:default
const keyFor = request => {
  const who = (request.headers.get("cf-access-authenticated-user-email") || "default").toLowerCase();
  const p = (new URL(request.url).searchParams.get("p") || "").toLowerCase();
  return /^[a-z]{1,20}$/.test(p) && p !== "ross" ? `checked:${p}${who === "default" ? "" : ":" + who}` : "checked:" + who;
};

const DATE = /^\d{4}-\d{2}-\d{2}$/;

export async function onRequestGet({ request, env }) {
  if (!env.FAVS) return json({ error: "sync not set up" }, 503);
  const saved = await env.FAVS.get(keyFor(request), "json");
  return json({ checked: saved && typeof saved === "object" && !Array.isArray(saved) ? saved : {} });
}

export async function onRequestPut({ request, env }) {
  if (!env.FAVS) return json({ error: "sync not set up" }, 503);
  let body;
  try { body = await request.json(); } catch { return json({ error: "bad JSON" }, 400); }
  const raw = body && body.checked;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return json({ error: "expected {checked: {...}}" }, 400);
  const checked = {};
  for (const [dealer, day] of Object.entries(raw).slice(0, 500)) {
    if (typeof dealer === "string" && dealer.length <= 120 && typeof day === "string" && DATE.test(day)) checked[dealer] = day;
  }
  await env.FAVS.put(keyFor(request), JSON.stringify(checked));
  return json({ checked });
}
