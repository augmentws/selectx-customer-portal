// Downloads the FastAPI contract that Orval generates the client from.
import { writeFile } from "node:fs/promises";

const apiUrl = process.env.API_URL ?? "http://127.0.0.1:8001";
const res = await fetch(`${apiUrl}/openapi.json`);
if (!res.ok) {
  console.error(`Failed to fetch ${apiUrl}/openapi.json: ${res.status} ${res.statusText}`);
  process.exit(1);
}
const spec = await res.json();
await writeFile(new URL("../openapi.json", import.meta.url), JSON.stringify(spec, null, 2) + "\n");
console.log(`Wrote openapi.json (${Object.keys(spec.paths).length} paths) from ${apiUrl}`);
