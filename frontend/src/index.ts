import { serve } from "bun";
import index from "./index.html";

// bun only substitutes process.env.BUN_PUBLIC_* into the client bundle when the
// var has a value. unset, the raw reference ships to the browser and blows up
// with "process is not defined", so refuse to start instead.
if (!process.env.BUN_PUBLIC_API_URL) {
  throw new Error(
    "BUN_PUBLIC_API_URL is not set. copy .env.example to .env and fill it in.",
  );
}

const server = serve({
  routes: {
    // Cached demo assets. On Vercel these are served straight from public/ by
    // the CDN; the dev server has no static handler for public/, so serve them
    // here too, otherwise the "/*" catch-all returns index.html for them.
    "/demos/:file": (req) => {
      // basename only, so the param cannot climb out of the folder
      const name = (req.params.file || "").split(/[\\/]/).pop() || "";
      const file = Bun.file(`./public/demos/${name}`);
      return new Response(file);
    },

    // Serve index.html for all unmatched routes.
    "/*": index,

    // "/api/hello": {
    //   async GET(req) {
    //     return Response.json({
    //       message: "Hello, world!",
    //       method: "GET",
    //     });
    //   },
    //   async PUT(req) {
    //     return Response.json({
    //       message: "Hello, world!",
    //       method: "PUT",
    //     });
    //   },
    // },

    // "/api/hello/:name": async req => {
    //   const name = req.params.name;
    //   return Response.json({
    //     message: `Hello, ${name}!`,
    //   });
    // },
  },

  development: process.env.NODE_ENV !== "production" && {
    // Enable browser hot reloading in development
    hmr: true,

    // Echo console logs from the browser to the server
    console: true,
  },
});

console.log(`🚀 Server running at ${server.url}`);
