# Website skeleton

A Flask app serving a placeholder home page and product page using Jinja templates.

## Getting started

Create a virtual environment and install the dependencies:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Start the development server:

```sh
flask --app app run
```

Open the address printed by Flask in your browser. On Windows, activate the virtual environment with `.venv\Scripts\activate` instead.

## Project structure

`app.py` defines the routes. The HTML templates are in `templates/`, and the shared stylesheet is in `static/styles.css`. The home page is available at `/` and the product page at `/product`; the original `/index.html` and `/product.html` URLs also work.

Images, product names and prices are placeholders. The size selector is a starting point, and the add-to-bag button is disabled. No checkout, database, analytics, AI or external services are connected.
