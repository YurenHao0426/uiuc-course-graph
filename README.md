# UIUC Course Graph

Static UIUC course prerequisite graph powered by React and Cytoscape.js. Course data is fetched from the UIUC Course Explorer API during build time because the API does not allow cross-origin requests.

## CORS check

```
$ curl -sD - -o /dev/null https://courses.illinois.edu/cisapp/explorer/schedule/2025/fall.xml
HTTP/1.1 200 OK
content-type: application/xml;charset=UTF-8
server: envoy
# (no Access-Control-Allow-Origin header)
```

## Development

```bash
npm install
npm run scrape   # generate data/catalog_2025_fall.json
npm run dev      # start Vite dev server
```

The GitHub Actions workflow `update-and-deploy.yml` refreshes the catalog daily and deploys the built site to GitHub Pages.
