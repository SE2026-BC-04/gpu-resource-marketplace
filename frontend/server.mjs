import { createServer } from "node:http";
import { createReadStream, promises as fs } from "node:fs";
import { extname, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(fileURLToPath(new URL("./dist", import.meta.url)));
const indexFile = resolve(root, "index.html");
const port = Number(process.env.PORT || 5173);
const contentTypes = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".ico": "image/x-icon",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".txt": "text/plain; charset=utf-8",
  ".webp": "image/webp",
};

const server = createServer(async (request, response) => {
  if (request.method !== "GET" && request.method !== "HEAD") {
    response.writeHead(405, { Allow: "GET, HEAD" }).end();
    return;
  }

  let pathname;
  try {
    pathname = decodeURIComponent(new URL(request.url || "/", "http://localhost").pathname);
  } catch {
    response.writeHead(400).end();
    return;
  }

  let file = resolve(root, `.${pathname}`);
  if (file !== root && !file.startsWith(`${root}${sep}`)) {
    response.writeHead(404).end();
    return;
  }

  try {
    const info = await fs.stat(file);
    if (info.isDirectory()) file = resolve(file, "index.html");
  } catch {
    // Client-side routes fall back to the built entry point. Missing assets remain 404.
    if (extname(pathname)) {
      response.writeHead(404).end();
      return;
    }
    file = indexFile;
  }

  try {
    const info = await fs.stat(file);
    response.writeHead(200, {
      "Content-Length": info.size,
      "Content-Type": contentTypes[extname(file)] || "application/octet-stream",
      "X-Content-Type-Options": "nosniff",
    });
    if (request.method === "HEAD") response.end();
    else createReadStream(file).pipe(response);
  } catch {
    response.writeHead(404).end();
  }
});

server.listen(port, "0.0.0.0");
