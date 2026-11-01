# Velmora

A Flask and Jinja shopping catalogue for a fictional London evening-wear label. The existing editorial campaign carousel, 48 product pages, nine featured products, searchable wider collection and bundle routes are preserved. Product pages now have a balanced two-column layout, bounded portrait photography, genuine-photo thumbnails, accessible zoom, minimal colour swatches, product-specific sizing, a working bag and collapsed details. The compact wardrobe strip switches complete product views on the same page and retains colour/size state in URLs and browser history.

The shared bundle model supports explicit colourways for curated sets, customer drafts and future AI-generated proposals. The Winter Soirée Set is Isola dress in Champagne, Bianca silk scarf in Champagne and Celeste clutch in Emerald. Homepage previews, `/sets`, the wardrobe strip and the bag resolve their names, selected-colour images and current prices from the catalogue. Missing selected-colour photography is identified without fabricating images or silently changing colour.

The bag is functional and server-validated. Online checkout, payments, orders and real stock quantities are not connected. The studio can add an entire validated set to the bag. AI styling is disabled by default and can be enabled with a server-side Gemini key as described below. Provider-independent generation, validation, private draft storage and publication access hooks are implemented. [The bundle API documentation](docs/bundle-api.md) explains the contract, security boundaries and deployment requirements.

For a guided tour of the application modules, browser assets, catalogue data and tests, see the [code map](docs/code-map.md).

## Run the website from a fresh clone

Install [Python](https://www.python.org/downloads/) 3.10 or newer and [Git](https://git-scm.com/downloads) first. Open Terminal on macOS/Linux or PowerShell on Windows. Python, Flask and certifi are sufficient to run the website, including Gemini integration. SQLite is included with Python. Node.js is only needed for JavaScript tests; there is no npm install or frontend build step.

Clone the repository and enter its folder. If you downloaded the ZIP instead, extract it and open a terminal in the extracted folder, where `app.py` and `requirements.txt` are located; skip the clone command.

```sh
git clone https://github.com/V1R4J1/website-skeleton.git
cd website-skeleton
```

On macOS or Linux, create and activate a virtual environment, then install the dependencies. Run these commands from the repository folder.

```sh
python3 --version
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

On Windows PowerShell, use these commands instead. Calling the virtual environment's Python directly also works when PowerShell does not allow activation scripts.

```powershell
py -3 --version
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

To explore the catalogue and manual Styling Studio without an API key, start Flask with the appropriate command below. AI styling stays disabled until you configure Gemini in the next section.

```sh
# macOS / Linux, with .venv activated
python -m flask --app app run --port 5055
```

```powershell
# Windows PowerShell
.\.venv\Scripts\python.exe -m flask --app app run --port 5055
```

Leave that terminal running and open **http://127.0.0.1:5055/** in a browser. The Styling Studio is at **http://127.0.0.1:5055/sets/create** and product search is at **http://127.0.0.1:5055/products**. Press **Ctrl+C** in the terminal to stop the server. Starting Flask prints a development-server warning; this local server is for exploring the repo, not public production hosting.

## Connect your Gemini API key

Sign in to [Google AI Studio's API keys page](https://aistudio.google.com/app/apikey) and create a Gemini API key for your Google Cloud project. If a project is not available, follow Google's [API key setup guide](https://ai.google.dev/gemini-api/docs/api-key). Your project must have access to the model used by this repo and sufficient quota. Check Google's [billing documentation](https://ai.google.dev/gemini-api/docs/billing) for the current requirements of your account; do not assume every model or request is free.

The current Gemini adapter uses **`gemini-3.1-flash-lite`** for both styling and semantic search, as defined in `GeminiStylingProvider.MODEL` in `styling_provider.py`. This is the model configured in this repo, not a guarantee of availability for every project. `VELMORA_AI_MODEL` configures the separate OpenAI adapter and does not change the Gemini model.

Keep the key on the server. The commands below prompt for it without displaying it or putting the key itself into shell history. Do not paste it into source code, the README, screenshots or browser JavaScript. Styling briefs, search text and relevant catalogue candidates are sent to Google when AI is used; see [Google's Gemini API terms](https://ai.google.dev/gemini-api/terms).

### macOS: use the included launcher

After completing installation above, stop any existing server with Ctrl+C, stay in the repository folder and run:

```sh
zsh scripts/start-gemini.zsh
```

Paste your key at `Gemini API key (input hidden):` and press Return. Nothing appears while you paste or type; that is expected. The launcher sets `GEMINI_API_KEY`, `VELMORA_AI_ENABLED=1` and `VELMORA_AI_PROVIDER=gemini`, then starts the website on port 5055 using `.venv/bin/python`. It does not save the key in the repo. If `GEMINI_API_KEY` is already exported, it uses that value without prompting. To replace it, run `unset GEMINI_API_KEY` before launching again.

### macOS / Linux: configure the terminal directly

These commands work in Bash or Zsh. Activate the environment first if you opened a new terminal. Python's hidden prompt collects the key into a shell variable; no Google SDK installation is required.

```sh
source .venv/bin/activate
export GEMINI_API_KEY="$(python -c 'import getpass; print(getpass.getpass("Gemini API key (hidden): "))')"
export VELMORA_AI_ENABLED=1
export VELMORA_AI_PROVIDER=gemini
python -m flask --app app run --port 5055
```

### Windows PowerShell: configure the terminal directly

Run these commands in the repository folder. The hidden prompt is converted into the environment variable needed by the server, then Flask starts using the virtual environment's Python.

```powershell
$geminiKey = Read-Host "Gemini API key (hidden)" -AsSecureString
$env:GEMINI_API_KEY = [System.Net.NetworkCredential]::new("", $geminiKey).Password
Remove-Variable geminiKey
$env:VELMORA_AI_ENABLED = "1"
$env:VELMORA_AI_PROVIDER = "gemini"
.\.venv\Scripts\python.exe -m flask --app app run --port 5055
```

Environment variables apply to the current terminal and its child processes. Repeat the configuration when you open a new terminal. Merely creating a `.env` file does not load these values in the documented installation; `python-dotenv` is not a required dependency. If you use a deployment platform, configure the same variables in its server environment or secret manager.

### Check the connection

After starting with Gemini enabled, open **http://127.0.0.1:5055/sets/create**, choose **Style with AI**, and submit a brief such as “Create an elegant champagne outfit for a winter evening under £600.” A successful generated look verifies a real request with your key. Search at `/products` also uses Gemini for eligible broad queries; exact product matches can be handled locally and do not verify the key.

You can check configuration at **http://127.0.0.1:5055/api/session**: `styling_enabled: true` means the adapter is configured. It does **not** prove that the key, quota or model access works; only a successful AI request verifies those. Do not share the session's CSRF token.

Use the **Black Friday demo** switch below the navigation to turn preview discounts on or off. It works without an API key for catalogue/manual-set pricing; AI generation still requires Gemini configuration. Preview discounts never apply to payable bag/checkout prices, and online checkout is not connected.

## Stopping, restarting and troubleshooting

Stop Flask with Ctrl+C before starting it again. Restart after changing Python code, campaign/catalogue JSON, dependencies or AI environment variables, then refresh the browser. The documented launch command does not automatically reload Python code. A new API key also requires a restart. If you only change browser JavaScript/CSS and the page still looks old, perform a hard refresh.

If a command reports that `requirements.txt`, `app.py` or `.venv/bin/python` cannot be found, return to the repository folder and complete installation. On macOS/Linux, use `python3` to create the environment, then `python` after activation. On Windows, use the explicit `.venv\Scripts\python.exe` commands above. If Linux reports that `venv` or `ensurepip` is missing, install your distribution's Python venv package and retry environment creation.

If Flask reports “Address already in use”, stop the previous server with Ctrl+C in its terminal. Alternatively, use `--port 5056` in the direct Flask command and open `http://127.0.0.1:5056/`. The included Zsh launcher uses port 5055.

If AI still says “coming soon”, confirm all three variables were set in the same terminal before startup: `GEMINI_API_KEY`, `VELMORA_AI_ENABLED=1` and `VELMORA_AI_PROVIDER=gemini`. Then restart and refresh. The site can browse and create manual looks without Gemini, so a working homepage alone does not confirm AI configuration.

If a generated look fails, read the server terminal for a safe error category. Invalid-key or service-disabled errors require checking the key and project in AI Studio. Rate-limit errors require reviewing the project's quota/billing or trying again later. Model-not-found or access errors require checking access to the adapter's configured model. Provider output can also be rejected by catalogue validation; retry a simpler brief before assuming the key is wrong. A timeout may be adjusted with `VELMORA_AI_TIMEOUT` (1–120 seconds, default 20), set before starting Flask.

If you see a certificate verification error, first ensure dependencies installed successfully with `python -m pip install -r requirements.txt`. The adapter uses certifi for verified HTTPS; an organisation that requires its own trusted CA can supply `SSL_CERT_FILE`. Keep certificate verification enabled.

Bags and private sets belong to the browser session. By default, a server restart generates a new signing key and invalidates that session's access, although saved bundle records remain in `instance/bundles.sqlite3`. For repeat demos, set a strong, stable `VELMORA_SECRET_KEY` in the server environment and reuse it across launches. You can generate a value with `python -c "import secrets; print(secrets.token_hex(32))"`; treat it as a secret and keep it outside the repo. For production, also configure durable storage, a production WSGI server and `VELMORA_COOKIE_SECURE=1` over HTTPS; see [deployment details](docs/bundle-api.md#deployment-and-commerce-boundary).

## Routes

`/` and `/index.html` show the editorial campaign and featured collection. `/products` contains the other 39 products with search, category, price and availability filters, while `/products/search` supplies live catalogue matches and spelling suggestions. When an unmatched broad search is submitted, the configured Gemini model can return related catalogue pieces with validated colourways; the result image and product link use that colour, while searches without a colour request use each product's default colourway. Every item has `/products/<product_id>`, with optional canonical `colour` and `size` query selections. `/product` preserves the original VLM-001 example and `/product.html` opens the Winter Soirée Set. Unknown pages and products retain the shared 404.

`/sets` displays six official curated looks and other approved curated sets. `/sets/create` opens the manual styling studio and the AI brief interface, enabled when a provider is configured. Saved private or published sets can also be viewed at `/sets/saved/<id>`, subject to the same ownership rules as the existing saved-bundle route. `/bundles/winter-soiree` displays the named set; `item` selects its one-based position. `colours` and `sizes` carry ordered slash-separated customer selections, with `-` for an unchosen size. `/bundle?items=VLM-003/VLM-047/VLM-048` preserves legacy ordered product-ID links, including repeated IDs, by explicitly resolving photographed catalogue defaults into the shared model. Legacy input limits remain 50 items and 2,048 characters; malformed references and positions return 400. New bundle creation APIs require actual colourway references for every item.

`/bag` displays the current visitor's selected pieces, colours, sizes, quantities, availability and current subtotal. Native purchase forms work without JavaScript; enhanced forms stay on the product page and update the bag count. `/api/bundles/generate` is unavailable until a tested provider is configured. `/api/bundles` validates and durably saves session-owned drafts; publishing requires an explicitly configured editor permission check. `/bundles/saved/<id>` uses exactly the same product components as a curated set.

Catalogue filters accept `q`, `category`, `availability`, `min_price` and `max_price`. Search remains case-insensitive across name, ID, category, fabric, fit, colours and occasions. Colour searches use that real colourway's photograph and direct link, or a placeholder if photography is missing. Availability filters are `in_stock`, `made_to_order` and `unavailable`. Inclusive GBP bounds accept finite, non-negative decimals. Invalid filters return 400 with actionable messages, while a valid empty result returns 200.

## Catalogue and colourways

`static/products.json` is the product source of truth. Records contain `id`, `name`, `category`, `price_gbp`, non-empty `colours`, `fabric`, optional `fit`, non-empty `sizes`, `occasions`, making lead time and availability flags, colour-neutral `description` and `images`. IDs must be unique; prices and lead times are non-negative whole numbers. Accessories use `["one size"]`. `in_stock` and `made_to_order` cannot both be true; when both are false the piece is unavailable. Made-to-order availability requires a positive making lead time.

Each declared colour resolves to a stable local colourway ID, for example `VLM-047--pewter`. Size remains separate. All existing single-colour products also have an explicit colourway. These IDs are not external commerce SKUs. Stock currently inherits product-level availability; an optional `variant_availability` mapping keyed by canonical colour ID can accurately override individual colourways. Size-level stock and external commerce mapping require real additional data.

`images` is one shared array of objects such as `{ "colour": "ivory", "image": "productImages/VLM-012/VLM-012-ivory.webp" }`. Each path is static-relative, stays inside `static/` and must exist. Multiple genuine photographs per colour are supported; duplicate paths and unknown colours are rejected. An empty array produces a placeholder. Product and bundle previews never substitute a different colour's photograph. The main gallery may show the first genuine image when selected-colour photography is absent, with an explicit note naming its actual colour.

All 48 current records contain colour data, resolving to 90 declared colourways. Six colourways use AI-generated illustrations based on the existing product photographs: VLM-003 Emerald, VLM-005 Emerald, VLM-006 Midnight, VLM-007 Emerald, VLM-008 Ivory and VLM-010 Midnight. The existing catalogue name “Bianca silk scarf” and its recorded fabric “duchess satin” are retained as supplied and need merchandising confirmation before a production launch. The app does not infer a fibre composition from a product name or a photograph.

`static/product_line.json` retains the ordered nine featured IDs. The app loads and validates JSON once at startup, rejecting broken catalogue references, colour data and local assets with descriptive errors. Restart the server after changing JSON or image files. An empty featured list remains supported. `static/brand.md` describes the original brand conventions; `static/analytics.csv` remains a fictional historical dataset, not live tracking.

## Implementation

`app.py` retains the application factory, catalogue pages and legacy routes. `catalogue.py` owns immutable products, real colourways, image validation and filtering. `bundles.py` owns the sole bundle model, strict input validation, catalogue resolution, legacy-link adaptation and per-visitor URL customisation. `shopping.py` contains the validated bag, mutation protections and API routes. `bundle_store.py` stores reference-only drafts in SQLite. `styling.py` separates request interpretation, eligible catalogue retrieval, provider suggestions and authoritative backend validation.

`templates/_product_view.html` is the shared atomic product component for initial HTML and asynchronous switching. `static/product-page.js` coordinates history, cancellation, selection state and bag submission. `static/product-gallery.js` handles genuine-photo navigation, swipes, keyboard navigation and zoom. The styling studio uses `static/builder.js` and the shared bundle model; its AI request controls remain disabled until a provider is configured. All pages retain Cormorant Garamond and Inter with non-blocking optional font loading and system fallbacks, warm ivory backgrounds, restrained borders and charcoal purchase controls. Motion respects reduced-motion preferences.

## Verification

```sh
python -B -m unittest discover -s tests -v
python -m pip check
node --test tests/*.test.mjs
node --check static/carousel.js
node --check static/catalogue-search.js
node --check static/product-gallery.js
node --check static/product-page.js
node --check static/bundle-service.js
```

The Python suite covers all 48 detail pages and assets, featured/wider collection membership, filters, legacy routes, colour and size references, selected-colour imagery, full product-view responses, unavailable and retired selections, current totals, bag purchases/removal, private draft ownership, publication controls, CSRF, request limits and provider failures. JavaScript tests exercise the actual carousel, gallery and product-page scripts, including swipes, zoom, stale-request cancellation, browser history, selection propagation and server-confirmed bag updates. Browser QA covers desktop and narrow mobile views, bundle switching, colour customisation, size selection, bag contents and history navigation. The automated provider tests use mocked responses and do not call a live Gemini account. Verify your own key with a real styling request as described above. Checkout is not connected.


Use the **Black Friday demo** on/off switch directly below the navigation on any page. It applies to your visitor session, works on mobile and refreshes studio/search prices in place without discarding the current look. Demo preview prices remain excluded from the bag and checkout. Black Friday demo awareness is off by default. Set `VELMORA_BLACK_FRIDAY_ENABLED=1` before starting the server to enable it, or update the running app's server-side `BLACK_FRIDAY_ENABLED` configuration. `VELMORA_PROMOTION_RANKING_WEIGHT` (app config `PROMOTION_RANKING_WEIGHT`, default `0.35`, capped at `0.5`) tunes `promotionRankingWeight`; zero disables the ranking bonus while active prices still apply to preview budgets. The single shared campaign definition is `data/black-friday-demo.json`, loaded through `PROMOTION_CAMPAIGN_PATH`. Its product/variant references are resolved against the catalogue by `pricing.py`; there is no AI-specific sale list. Optional timezone-aware `starts_at` and `ends_at` values bound campaign activity.

Styling and search retrieve bounded real candidates and treat relevance as primary. Active discounts break relevance ties; sale-only and exclude-sale requests constrain actual variants. Explicit natural-language budgets and structured constraints are checked again after provider generation. The provider receives current original/promotional prices and demo metadata, but may return only references and styling copy. A generated set can mix discounted and ordinary pieces. The lookboard resolves totals through `POST /api/bundles/resolve`, refreshes while visible and on focus, and shows discreet demo savings. Saved sets keep reference-only selections plus a separate historical total for price-change notices; they always recalculate current prices, including when a campaign ends.

All campaign prices in this implementation are demo previews. The bag and `purpose="checkout"` pricing resolution always use ordinary catalogue prices. No setting can turn these preview rules into genuine checkout offers; real promotions require a commerce adapter. Existing checkout remains unavailable. Promotion regression coverage is in `tests/test_promotions.py`; provider tests use controlled fixtures rather than a live AI account.

The home carousel advances every four seconds, including while the pointer rests over the hero. Keyboard focus, the Pause control and a hidden browser tab suspend rotation. Reduced-motion preferences disable automatic playback initially; Play allows an explicit opt-in.
