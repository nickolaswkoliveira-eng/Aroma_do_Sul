from sqlalchemy import select
from sqlalchemy.orm import Session

from models.entities import Category, Ingredient, Product, RecipeItem, Stock
from services.auth import seed_access_control


SAMPLE = {
    "Cafés": [("CAP001", "Cappuccino", 4.2, 12.0, "un"), ("CAF001", "Café coado", 1.4, 6.0, "un")],
    "Bebidas": [("BEB001", "Leite", 4.5, 8.0, "L")],
    "Lanches": [("LAN001", "Pão de queijo", 1.2, 5.5, "un"), ("LAN002", "X-Bacon", 9.5, 24.0, "un")],
    "Sobremesas": [("SOB001", "Brownie", 3.0, 9.0, "un")],
    "Combos": [("COM001", "Combo café + pão de queijo", 3.0, 10.0, "un")],
}
RECIPE_DEFAULTS = {
    "CAP001": [("INS001", 0.018), ("INS002", 0.18)],
    "CAF001": [("INS001", 0.012)],
    "LAN001": [("INS003", 1)],
    "LAN002": [("INS004", 1), ("INS005", 1), ("INS006", 0.05), ("INS007", 2)],
    "SOB001": [("INS008", 0.08)],
    "BEB001": [("INS002", 0.25)],
    "COM001": [("INS001", 0.012), ("INS003", 1)],
}


def seed_demo_data(session: Session) -> None:
    seed_access_control(session)
    if session.scalar(select(Category.id).limit(1)):
        category = session.scalar(select(Category).where(Category.name == "Insumos"))
        if category is None:
            category = Category(name="Insumos")
            session.add(category)
            session.flush()
        for product in session.scalars(select(Product).where(Product.code.like("INS%"))).all():
            product.category_id = category.id
            product.sale_price = 0
            if session.scalar(select(Ingredient).where(Ingredient.product_id == product.id)) is None:
                session.add(Ingredient(product_id=product.id, name=product.name, unit=product.unit))
        ingredients_by_code = {product.code: product for product in session.scalars(select(Product).where(Product.code.like("INS%"))).all()}
        products_by_code = {product.code: product for product in session.scalars(select(Product).where(Product.sale_price > 0)).all()}
        for product_code, entries in RECIPE_DEFAULTS.items():
            product = products_by_code.get(product_code)
            if product is None:
                continue
            for ingredient_code, quantity in entries:
                ingredient = ingredients_by_code.get(ingredient_code)
                if ingredient and session.scalar(select(RecipeItem).where(
                        RecipeItem.product_id == product.id, RecipeItem.ingredient_id == ingredient.id)) is None:
                    session.add(RecipeItem(product_id=product.id, ingredient_id=ingredient.id, quantity=quantity))
        session.commit()
        return
    categories = {}
    for category_name in SAMPLE:
        category = Category(name=category_name)
        session.add(category)
        categories[category_name] = category
    categories["Insumos"] = Category(name="Insumos")
    session.add(categories["Insumos"])
    session.flush()
    products = {}
    for category_name, entries in SAMPLE.items():
        for code, name, cost, price, unit in entries:
            product = Product(code=code, name=name, category_id=categories[category_name].id,
                              unit=unit, cost_price=cost, sale_price=price)
            session.add(product)
            products[name] = product
    # Insumos demonstrativos utilizados nas fichas técnicas.
    ingredients = [
        ("INS001", "Grãos de café", "kg", 60.0, 2.0, 8.0),
        ("INS002", "Leite integral", "L", 5.2, 12.0, 25.0),
        ("INS003", "Pão de queijo congelado", "un", 1.0, 40.0, 100.0),
        ("INS004", "Pão de hambúrguer", "un", 1.4, 20.0, 50.0),
        ("INS005", "Hambúrguer", "un", 4.0, 15.0, 40.0),
        ("INS006", "Bacon", "kg", 35.0, 1.0, 3.0),
        ("INS007", "Queijo", "fatia", 0.6, 60.0, 120.0),
        ("INS008", "Chocolate", "kg", 18.0, 2.0, 5.0),
    ]
    ingredients_by_code = {}
    for code, name, unit, cost, quantity, minimum in ingredients:
        ingredient = Product(code=code, name=name, category_id=categories["Insumos"].id,
                     unit=unit, cost_price=cost, sale_price=0, active=True)
        session.add(ingredient)
        session.flush()
        session.add(Stock(product_id=ingredient.id, quantity=quantity, minimum_quantity=minimum))
        session.add(Ingredient(product_id=ingredient.id, name=name, unit=unit))
        ingredients_by_code[code] = ingredient
    session.flush()
    products_by_code = {product.code: product for product in products.values()}
    for product_code, recipe in RECIPE_DEFAULTS.items():
        for code, quantity in recipe:
            session.add(RecipeItem(product_id=products_by_code[product_code].id,
                                   ingredient_id=ingredients_by_code[code].id, quantity=quantity))
    session.commit()
