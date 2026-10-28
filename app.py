import json
from pathlib import Path

from flask import Flask, abort, render_template

app = Flask(__name__)
PRODUCTS_PATH = Path(app.root_path) / "static" / "products.json"
PRODUCT_LINE_PATH = Path(app.root_path) / "static" / "product_line.json"


def get_product(product_id):
    with PRODUCTS_PATH.open(encoding="utf-8") as products_file:
        products = json.load(products_file)
    return next((item for item in products if item["id"] == product_id), None)


@app.route("/index.html")
@app.route("/")
def home():
    with PRODUCT_LINE_PATH.open(encoding="utf-8") as line_file:
        product_ids = json.load(line_file)
    products = [get_product(product_id) for product_id in product_ids]
    return render_template("index.html", products=[item for item in products if item])


@app.route("/product.html")
@app.route("/product")
def product():
    return product_detail("VLM-001")


@app.route("/products/<product_id>")
def product_detail(product_id):
    selected_product = get_product(product_id)
    if selected_product is None:
        abort(404)
    return render_template("product.html", product=selected_product)


if __name__ == "__main__":
    app.run(debug=True)
