# Sallah prices

- `catalog.json.gz` is the price file the Sallah app downloads. It is rewritten every night.
- `collector/` reads public product pages from Saudi stores. It respects each site's robots.txt and waits between requests.
- `.github/workflows/collect.yml` runs the collector every night at 03:00 Riyadh time. The store listings are kept on the `data` branch.

The collector code is copied here from the app's private repository, so change it there.
