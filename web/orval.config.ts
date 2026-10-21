import { defineConfig } from "orval";

export default defineConfig({
  api: {
    input: "./openapi.json",
    output: {
      mode: "tags-split",
      target: "src/lib/api/generated",
      schemas: "src/lib/api/generated/model",
      client: "react-query",
      httpClient: "fetch",
      clean: true,
      override: {
        mutator: { path: "src/lib/api/fetcher.ts", name: "bffFetch" },
        // bffFetch throws ApiError on any non-2xx, so resolved values are always the success shape.
        fetch: { includeHttpResponseReturnType: true, forceSuccessResponse: true },
      },
    },
  },
});
