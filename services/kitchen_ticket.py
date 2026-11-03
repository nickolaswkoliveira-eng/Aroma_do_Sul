from html import escape

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.entities import Customer, Order, OrderItem, Product
from utils.formatting import date_time


def build_kitchen_ticket_html(session: Session, order: Order, auto_print: bool = False) -> str:
    """Comanda de cozinha para impressora térmica de 80 mm (imprime pelo navegador)."""
    rows = session.execute(
        select(OrderItem.quantity, OrderItem.notes, Product.name)
        .join(Product, Product.id == OrderItem.product_id)
        .where(OrderItem.order_id == order.id)
        .order_by(OrderItem.id)
    ).all()
    customer = session.get(Customer, order.customer_id) if order.customer_id else None
    table = f"MESA {order.table_number:02d}" if order.table_number is not None else "BALCÃO / VIAGEM"
    items = "".join(
        f'<div class="item"><b>{quantity}x</b> {escape(name)}'
        + (f'<div class="obs">Obs: {escape(note)}</div>' if note else "")
        + "</div>"
        for quantity, note, name in rows
    )
    extras = (f'<div>Cliente: {escape(customer.name)}</div>' if customer and customer.name else "") + (
        f'<div class="obs">Obs. pedido: {escape(order.notes)}</div>' if order.notes else ""
    )
    script = "<script>window.onload=function(){window.focus();window.print();};</script>" if auto_print else ""
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
@page {{ size: 80mm auto; margin: 0; }}
html, body {{ margin: 0; padding: 0; background: #fff; }}
body {{ width: 72mm; margin: 0 auto; padding: 3mm 0; font: 14px/1.3 "Courier New", monospace; color: #000; }}
h1 {{ font-size: 18px; text-align: center; margin: 0 0 2mm; }}
.center {{ text-align: center; }}
.big {{ font-size: 20px; font-weight: bold; text-align: center; margin: 2mm 0; }}
.item {{ font-size: 16px; margin: 2mm 0; }}
.obs {{ font-size: 13px; margin-left: 5mm; }}
hr {{ border: 0; border-top: 1px dashed #000; margin: 2mm 0; }}
</style></head><body>
<h1>COZINHA</h1>
<div class="big">PEDIDO #{order.id}</div>
<div class="big">{table}</div>
<div class="center">{escape(date_time(order.created_at))}</div>
{extras}
<hr>{items}<hr>
<div class="center">*** fim do pedido ***</div>
{script}</body></html>"""
