from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from typing import Dict

from flask import Blueprint, abort, redirect, render_template, request, url_for
from flask_login import login_required

from app import db
from app.forms import (
    PurchaseCostForecastForm,
    PurchaseInventorySummaryForm,
    ProductRecipeReportForm,
    ProductSalesReportForm,
    ReceivedInvoiceReportForm,
    VendorInvoiceReportForm,
)
from app.models import (
    Customer,
    EventLocation,
    GLCode,
    Invoice,
    InvoiceProduct,
    Item,
    ItemUnit,
    Location,
    Product,
    ProductRecipeItem,
    PurchaseInvoice,
    PurchaseInvoiceItem,
    PurchaseOrder,
    TerminalSale,
    User,
)
from app.utils.forecasting import DemandForecastingHelper
from sqlalchemy import or_
from sqlalchemy.orm import selectinload

report = Blueprint("report", __name__)


_CENT = Decimal("0.01")


def _to_decimal(value) -> Decimal:
    return Decimal(str(value or 0))


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def _allocate_amount(total: Decimal, weights: Dict[str, Decimal]):
    """Allocate a currency amount across buckets using proportional rounding."""

    allocations = {key: Decimal("0.00") for key in weights}
    total = _quantize(total)

    if not weights or total == 0:
        return allocations

    total_weight = sum(weights.values())
    if total_weight == 0:
        return allocations

    remainder = total
    fractional_shares = []

    for key, weight in weights.items():
        if weight <= 0:
            fractional_shares.append((key, Decimal("0")))
            continue

        raw_share = (total * weight) / total_weight
        rounded_share = raw_share.quantize(_CENT, rounding=ROUND_DOWN)
        allocations[key] = rounded_share
        remainder -= rounded_share
        fractional_shares.append((key, raw_share - rounded_share))

    cents_remaining = int(
        ((remainder / _CENT).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    )
    cents_remaining = max(cents_remaining, 0)
    fractional_shares.sort(key=lambda item: item[1], reverse=True)

    if fractional_shares and cents_remaining:
        for i in range(cents_remaining):
            key, _ = fractional_shares[i % len(fractional_shares)]
            allocations[key] += _CENT

    return allocations


@report.route("/reports/vendor-invoices", methods=["GET", "POST"])
@login_required
def vendor_invoice_report():
    """Form to select vendor invoice report parameters."""
    form = VendorInvoiceReportForm()
    form.customer.choices = [
        (c.id, f"{c.first_name} {c.last_name}") for c in Customer.query.all()
    ]

    if form.validate_on_submit():
        return redirect(
            url_for(
                "report.vendor_invoice_report_results",
                customer_ids=",".join(str(id) for id in form.customer.data),
                start=form.start_date.data.isoformat(),
                end=form.end_date.data.isoformat(),
            )
        )

    return render_template("report_vendor_invoices.html", form=form)


@report.route("/reports/vendor-invoices/results")
@login_required
def vendor_invoice_report_results():
    """Show vendor invoice report based on query parameters."""
    customer_ids = request.args.get("customer_ids")
    start = request.args.get("start")
    end = request.args.get("end")

    # Convert comma-separated IDs to list of ints
    id_list = [int(cid) for cid in customer_ids.split(",") if cid.isdigit()]
    customers = Customer.query.filter(Customer.id.in_(id_list)).all()

    invoices = Invoice.query.filter(
        Invoice.customer_id.in_(id_list),
        Invoice.date_created >= start,
        Invoice.date_created <= end,
    ).all()

    # Compute totals with proper GST/PST logic
    enriched_invoices = []
    for invoice in invoices:
        subtotal = 0
        gst_total = 0
        pst_total = 0

        for item in invoice.products:
            line_total = item.quantity * item.product.price
            subtotal += line_total

            apply_gst = (
                item.override_gst
                if item.override_gst is not None
                else not invoice.customer.gst_exempt
            )
            apply_pst = (
                item.override_pst
                if item.override_pst is not None
                else not invoice.customer.pst_exempt
            )

            if apply_gst:
                gst_total += line_total * 0.05
            if apply_pst:
                pst_total += line_total * 0.07

        enriched_invoices.append(
            {"invoice": invoice, "total": subtotal + gst_total + pst_total}
        )

    return render_template(
        "report_vendor_invoice_results.html",
        customers=customers,
        invoices=enriched_invoices,
        start=start,
        end=end,
    )


@report.route("/reports/received-invoices", methods=["GET", "POST"])
@login_required
def received_invoice_report():
    """Display and process the received invoices report form."""

    form = ReceivedInvoiceReportForm()

    if form.validate_on_submit():
        start = form.start_date.data
        end = form.end_date.data

        if end < start:
            form.end_date.errors.append(
                "End date must be on or after the start date."
            )
            return render_template("report_received_invoices.html", form=form)

        invoice_rows = (
            db.session.query(
                PurchaseInvoice,
                PurchaseOrder.order_date.label("order_date"),
                User.email.label("received_by"),
            )
            .join(PurchaseOrder, PurchaseInvoice.purchase_order)
            .join(User, User.id == PurchaseInvoice.user_id)
            .filter(PurchaseInvoice.received_date >= start)
            .filter(PurchaseInvoice.received_date <= end)
            .order_by(PurchaseInvoice.received_date.asc(), PurchaseInvoice.id.asc())
            .all()
        )

        results = [
            {
                "invoice": invoice,
                "order_date": order_date,
                "received_by": received_by,
            }
            for invoice, order_date, received_by in invoice_rows
        ]

        return render_template(
            "report_received_invoices_results.html",
            form=form,
            results=results,
            start=start,
            end=end,
        )

    return render_template("report_received_invoices.html", form=form)


@report.route("/reports/purchase-inventory-summary", methods=["GET", "POST"])
@login_required
def purchase_inventory_summary():
    """Summarize purchased inventory quantities and spend for a date range."""

    form = PurchaseInventorySummaryForm()
    results = None
    totals = None
    start = None
    end = None
    selected_item_names = []
    selected_gl_labels = []

    if form.validate_on_submit():
        start = form.start_date.data
        end = form.end_date.data

        if end < start:
            form.end_date.errors.append(
                "End date must be on or after the start date."
            )
        else:
            query = (
                PurchaseInvoiceItem.query.join(PurchaseInvoice)
                .options(
                    selectinload(PurchaseInvoiceItem.invoice),
                    selectinload(PurchaseInvoiceItem.item),
                    selectinload(PurchaseInvoiceItem.unit),
                    selectinload(PurchaseInvoiceItem.purchase_gl_code),
                )
                .filter(PurchaseInvoice.received_date >= start)
                .filter(PurchaseInvoice.received_date <= end)
            )

            if form.items.data:
                query = query.filter(
                    PurchaseInvoiceItem.item_id.in_(form.items.data)
                )

            invoice_items = query.all()
            selected_gl_codes = set(form.gl_codes.data or [])
            aggregates = {}

            for inv_item in invoice_items:
                invoice = inv_item.invoice
                location_id = invoice.location_id if invoice else None
                resolved_gl = inv_item.resolved_purchase_gl_code(location_id)
                gl_id = resolved_gl.id if resolved_gl else None

                if selected_gl_codes:
                    if gl_id is None:
                        if -1 not in selected_gl_codes:
                            continue
                    elif gl_id not in selected_gl_codes:
                        continue

                if inv_item.item and inv_item.unit:
                    quantity = inv_item.quantity * inv_item.unit.factor
                    unit_name = inv_item.item.base_unit or inv_item.unit.name
                elif inv_item.item:
                    quantity = inv_item.quantity
                    unit_name = inv_item.item.base_unit or (
                        inv_item.unit_name or ""
                    )
                else:
                    quantity = inv_item.quantity
                    unit_name = inv_item.unit_name or ""

                item_name = (
                    inv_item.item.name if inv_item.item else inv_item.item_name
                )
                key = (
                    inv_item.item_id
                    if inv_item.item_id is not None
                    else f"missing-{item_name}"
                )
                gl_key = gl_id if gl_id is not None else -1
                aggregate_key = (key, gl_key)

                if aggregate_key not in aggregates:
                    gl_code = (
                        resolved_gl.code
                        if resolved_gl and resolved_gl.code
                        else "Unassigned"
                    )
                    gl_description = (
                        resolved_gl.description if resolved_gl else ""
                    )
                    aggregates[aggregate_key] = {
                        "item_name": item_name,
                        "gl_code": gl_code,
                        "gl_description": gl_description,
                        "total_quantity": 0.0,
                        "unit_name": unit_name,
                        "total_spend": 0.0,
                    }

                entry = aggregates[aggregate_key]
                entry["total_quantity"] += quantity
                entry["total_spend"] += inv_item.quantity * abs(inv_item.cost)
                if not entry["unit_name"] and unit_name:
                    entry["unit_name"] = unit_name

            results = sorted(
                aggregates.values(),
                key=lambda row: (row["item_name"].lower(), row["gl_code"]),
            )

            totals = {
                "quantity": sum(row["total_quantity"] for row in results),
                "spend": sum(row["total_spend"] for row in results),
            }

            selected_item_ids = set(form.items.data or [])
            if selected_item_ids:
                selected_item_names = [
                    label
                    for value, label in form.items.choices
                    if value in selected_item_ids
                ]

            if selected_gl_codes:
                selected_gl_labels = [
                    label
                    for value, label in form.gl_codes.choices
                    if value in selected_gl_codes
                ]

    return render_template(
        "report_purchase_inventory_summary.html",
        form=form,
        results=results,
        totals=totals,
        start=start,
        end=end,
        selected_item_names=selected_item_names,
        selected_gl_labels=selected_gl_labels,
    )


def _invoice_gl_code_rows(invoice: PurchaseInvoice):
    buckets: Dict[str, Dict[str, Decimal]] = {}

    for item in invoice.items:
        gl = item.resolved_purchase_gl_code(invoice.location_id)
        if gl is not None:
            code_key = gl.code
            display_code = gl.code
            description = gl.description or ""
        else:
            code_key = "__unassigned__"
            display_code = "Unassigned"
            description = ""

        entry = buckets.setdefault(
            code_key,
            {
                "code": display_code,
                "description": description,
                "base_amount": Decimal("0.00"),
                "delivery": Decimal("0.00"),
                "pst": Decimal("0.00"),
                "gst": Decimal("0.00"),
            },
        )

        line_total = _quantize(_to_decimal(item.quantity) * _to_decimal(item.cost))
        entry["base_amount"] += line_total

    if not buckets:
        buckets["__unassigned__"] = {
            "code": "Unassigned",
            "description": "",
            "base_amount": Decimal("0.00"),
            "delivery": Decimal("0.00"),
            "pst": Decimal("0.00"),
            "gst": Decimal("0.00"),
        }

    gst_code = "102702"
    gst_gl = GLCode.query.filter_by(code=gst_code).first()
    gst_entry = buckets.get(gst_code)
    if gst_entry is None:
        buckets[gst_code] = {
            "code": gst_code,
            "description": (gst_gl.description if gst_gl else ""),
            "base_amount": Decimal("0.00"),
            "delivery": Decimal("0.00"),
            "pst": Decimal("0.00"),
            "gst": Decimal("0.00"),
        }
        gst_entry = buckets[gst_code]
    elif gst_gl and not gst_entry.get("description"):
        gst_entry["description"] = gst_gl.description

    pst_total = _quantize(_to_decimal(invoice.pst))
    delivery_total = _quantize(_to_decimal(invoice.delivery_charge))
    gst_total = _quantize(_to_decimal(invoice.gst))

    proration_weights = {
        key: data["base_amount"]
        for key, data in buckets.items()
        if key != gst_code and data["base_amount"] > 0
    }

    if (not proration_weights) and (pst_total > 0 or delivery_total > 0):
        proration_weights = {"__unassigned__": Decimal("1.00")}
        if "__unassigned__" not in buckets:
            buckets["__unassigned__"] = {
                "code": "Unassigned",
                "description": "",
                "base_amount": Decimal("0.00"),
                "delivery": Decimal("0.00"),
                "pst": Decimal("0.00"),
                "gst": Decimal("0.00"),
            }

    pst_allocations = _allocate_amount(pst_total, proration_weights)
    delivery_allocations = _allocate_amount(delivery_total, proration_weights)

    rows = []
    totals = {
        "base_amount": Decimal("0.00"),
        "delivery": Decimal("0.00"),
        "pst": Decimal("0.00"),
        "gst": Decimal("0.00"),
        "total": Decimal("0.00"),
    }

    for key in sorted(
        buckets.keys(), key=lambda c: (c == gst_code, c == "__unassigned__", c)
    ):
        data = buckets[key]
        data["pst"] = pst_allocations.get(key, Decimal("0.00"))
        data["delivery"] = delivery_allocations.get(key, Decimal("0.00"))
        if key == gst_code:
            data["gst"] = gst_total

        line_total = (
            data["base_amount"]
            + data["delivery"]
            + data["pst"]
            + data["gst"]
        )
        line_total = _quantize(line_total)

        totals["base_amount"] += data["base_amount"]
        totals["delivery"] += data["delivery"]
        totals["pst"] += data["pst"]
        totals["gst"] += data["gst"]
        totals["total"] += line_total

        rows.append(
            {
                "code": data["code"],
                "description": data["description"],
                "base_amount": data["base_amount"],
                "delivery": data["delivery"],
                "pst": data["pst"],
                "gst": data["gst"],
                "total": line_total,
            }
        )

    totals = {key: _quantize(value) for key, value in totals.items()}

    return rows, totals


@report.route("/reports/purchase-invoices/<int:invoice_id>/gl-code")
@login_required
def invoice_gl_code_report(invoice_id: int):
    """Display the GL code allocation report for a purchase invoice."""

    invoice = (
        PurchaseInvoice.query.options(
            selectinload(PurchaseInvoice.items)
            .selectinload(PurchaseInvoiceItem.item),
            selectinload(PurchaseInvoice.items)
            .selectinload(PurchaseInvoiceItem.purchase_gl_code),
            selectinload(PurchaseInvoice.purchase_order).selectinload(
                PurchaseOrder.vendor
            ),
            selectinload(PurchaseInvoice.location),
        )
        .filter_by(id=invoice_id)
        .first()
    )

    if invoice is None:
        abort(404)

    rows, totals = _invoice_gl_code_rows(invoice)

    return render_template(
        "report_invoice_gl_code.html",
        invoice=invoice,
        rows=rows,
        totals=totals,
    )


@report.route("/reports/product-sales", methods=["GET", "POST"])
@login_required
def product_sales_report():
    """Generate a report on product sales and profit."""
    form = ProductSalesReportForm()
    product_choices = list(form.products.choices)
    gl_code_choices = list(form.gl_codes.choices)
    report_data = None
    totals = None
    start = None
    end = None
    selected_product_names = []
    selected_gl_labels = []

    if form.validate_on_submit():
        start = form.start_date.data
        end = form.end_date.data

        if end < start:
            form.end_date.errors.append(
                "End date must be on or after the start date."
            )
        else:
            selected_product_ids = form.products.data or []
            selected_gl_code_ids = form.gl_codes.data or []

            products_query = (
                db.session.query(
                    Product.id,
                    Product.name,
                    Product.cost,
                    Product.price,
                    db.func.sum(InvoiceProduct.quantity).label("total_quantity"),
                )
                .join(InvoiceProduct, InvoiceProduct.product_id == Product.id)
                .join(Invoice, Invoice.id == InvoiceProduct.invoice_id)
                .filter(Invoice.date_created >= start, Invoice.date_created <= end)
            )

            if selected_product_ids:
                products_query = products_query.filter(
                    Product.id.in_(selected_product_ids)
                )

            if selected_gl_code_ids:
                included_ids = [gid for gid in selected_gl_code_ids if gid != -1]
                conditions = []
                if included_ids:
                    conditions.append(Product.sales_gl_code_id.in_(included_ids))
                if -1 in selected_gl_code_ids:
                    conditions.append(Product.sales_gl_code_id.is_(None))
                if conditions:
                    products_query = products_query.filter(or_(*conditions))

            products = (
                products_query.group_by(Product.id).order_by(Product.name).all()
            )

            report_data = []
            total_quantity = 0.0
            total_revenue = 0.0
            total_profit = 0.0
            total_cost = 0.0

            for product_row in products:
                quantity = float(product_row.total_quantity or 0.0)
                cost = float(product_row.cost or 0.0)
                price = float(product_row.price or 0.0)
                profit_each = price - cost
                total_item_cost = quantity * cost
                revenue = quantity * price
                profit = quantity * profit_each

                total_quantity += quantity
                total_cost += total_item_cost
                total_revenue += revenue
                total_profit += profit

                report_data.append(
                    {
                        "id": product_row.id,
                        "name": product_row.name,
                        "quantity": quantity,
                        "cost": cost,
                        "price": price,
                        "total_cost": total_item_cost,
                        "profit_each": profit_each,
                        "revenue": revenue,
                        "profit": profit,
                    }
                )

            totals = {
                "quantity": total_quantity,
                "cost": total_cost,
                "revenue": total_revenue,
                "profit": total_profit,
            }

            visible_product_ids = {row["id"] for row in report_data}

            if selected_product_ids:
                selected_product_names = [
                    label
                    for value, label in product_choices
                    if value in selected_product_ids
                ]
                form.products.choices = [
                    choice
                    for choice in product_choices
                    if choice[0] in selected_product_ids
                ]
            else:
                form.products.choices = (
                    [
                        choice
                        for choice in product_choices
                        if choice[0] in visible_product_ids
                    ]
                    if visible_product_ids
                    else product_choices
                )

            if selected_gl_code_ids:
                selected_gl_labels = [
                    label
                    for value, label in gl_code_choices
                    if value in selected_gl_code_ids
                ]

    return render_template(
        "report_product_sales.html",
        form=form,
        report=report_data,
        totals=totals,
        start=start,
        end=end,
        selected_product_names=selected_product_names,
        selected_gl_labels=selected_gl_labels,
    )


@report.route("/reports/product-stock-usage", methods=["GET", "POST"])
@login_required
def product_stock_usage_report():
    """Report showing stock items consumed by product sales."""

    form = ProductSalesReportForm()
    product_choices = list(form.products.choices)
    gl_code_choices = list(form.gl_codes.choices)
    report_data = None
    totals = None
    start = None
    end = None
    selected_product_names = []
    selected_gl_labels = []

    if form.validate_on_submit():
        start = form.start_date.data
        end = form.end_date.data

        if end < start:
            form.end_date.errors.append(
                "End date must be on or after the start date."
            )
        else:
            selected_product_ids = form.products.data or []
            selected_gl_code_ids = form.gl_codes.data or []

            items_query = (
                db.session.query(
                    Item.id.label("item_id"),
                    Item.name.label("item_name"),
                    Item.base_unit.label("base_unit"),
                    Item.cost.label("item_cost"),
                    db.func.sum(
                        InvoiceProduct.quantity
                        * ProductRecipeItem.quantity
                        * db.func.coalesce(ItemUnit.factor, 1)
                    ).label("total_quantity"),
                )
                .join(ProductRecipeItem, ProductRecipeItem.item_id == Item.id)
                .join(Product, Product.id == ProductRecipeItem.product_id)
                .join(InvoiceProduct, InvoiceProduct.product_id == Product.id)
                .join(Invoice, Invoice.id == InvoiceProduct.invoice_id)
                .outerjoin(ItemUnit, ItemUnit.id == ProductRecipeItem.unit_id)
                .filter(
                    InvoiceProduct.product_id.isnot(None),
                    Invoice.date_created >= start,
                    Invoice.date_created <= end,
                )
            )

            if selected_product_ids:
                items_query = items_query.filter(Product.id.in_(selected_product_ids))

            if selected_gl_code_ids:
                included_ids = [gid for gid in selected_gl_code_ids if gid != -1]
                conditions = []
                if included_ids:
                    conditions.append(Product.sales_gl_code_id.in_(included_ids))
                if -1 in selected_gl_code_ids:
                    conditions.append(Product.sales_gl_code_id.is_(None))
                if conditions:
                    items_query = items_query.filter(or_(*conditions))

            items = (
                items_query.group_by(Item.id)
                .order_by(Item.name)
                .all()
            )

            report_data = []
            total_quantity = 0.0
            total_cost = 0.0

            for item_row in items:
                quantity = float(item_row.total_quantity or 0.0)
                cost_each = float(item_row.item_cost or 0.0)
                total_item_cost = quantity * cost_each

                total_quantity += quantity
                total_cost += total_item_cost

                report_data.append(
                    {
                        "id": item_row.item_id,
                        "name": item_row.item_name,
                        "unit": item_row.base_unit or "",
                        "quantity": quantity,
                        "cost": cost_each,
                        "total_cost": total_item_cost,
                    }
                )

            totals = {
                "quantity": total_quantity,
                "cost": total_cost,
            }

            if selected_product_ids:
                selected_product_names = [
                    label
                    for value, label in product_choices
                    if value in selected_product_ids
                ]
                form.products.choices = [
                    choice
                    for choice in product_choices
                    if choice[0] in selected_product_ids
                ]
            else:
                form.products.choices = product_choices

            if selected_gl_code_ids:
                selected_gl_labels = [
                    label
                    for value, label in gl_code_choices
                    if value in selected_gl_code_ids
                ]

    return render_template(
        "report_product_stock_usage.html",
        form=form,
        report=report_data,
        totals=totals,
        start=start,
        end=end,
        selected_product_names=selected_product_names,
        selected_gl_labels=selected_gl_labels,
    )


@report.route("/reports/product-recipes", methods=["GET", "POST"])
@login_required
def product_recipe_report():
    """List products with their recipe items, price and cost."""
    search = request.args.get("search")
    selected_ids = request.form.getlist("products", type=int)
    product_choices = []

    if selected_ids:
        selected_products = Product.query.filter(Product.id.in_(selected_ids)).all()
        product_choices.extend([(p.id, p.name) for p in selected_products])

    if search:
        search_products = (
            Product.query.filter(Product.name.ilike(f"%{search}%"))
            .order_by(Product.name)
            .limit(50)
            .all()
        )
        for p in search_products:
            if (p.id, p.name) not in product_choices:
                product_choices.append((p.id, p.name))

    form = ProductRecipeReportForm(product_choices=product_choices)
    report_data = []

    if form.validate_on_submit():
        if form.select_all.data or not form.products.data:
            products = Product.query.order_by(Product.name).all()
        else:
            products = (
                Product.query.filter(Product.id.in_(form.products.data))
                .order_by(Product.name)
                .all()
            )

        for prod in products:
            recipe = []
            for ri in prod.recipe_items:
                recipe.append(
                    {
                        "item_name": ri.item.name,
                        "quantity": ri.quantity,
                        "unit": ri.unit.name if ri.unit else "",
                        "cost": (ri.item.cost or 0)
                        * ri.quantity
                        * (ri.unit.factor if ri.unit else 1),
                    }
                )
            report_data.append(
                {
                    "name": prod.name,
                    "price": prod.price,
                    "cost": prod.cost,
                    "recipe": recipe,
                }
            )

        return render_template(
            "report_product_recipe_results.html", form=form, report=report_data
        )

    return render_template("report_product_recipe.html", form=form, search=search)


@report.route("/reports/product-location-sales", methods=["GET", "POST"])
@login_required
def product_location_sales_report():
    """Report showing product sales per location and last sale date."""
    form = ProductSalesReportForm()
    report_data = None

    if form.validate_on_submit():
        start = form.start_date.data
        end = form.end_date.data

        invoice_rows = (
            db.session.query(
                InvoiceProduct.product_id.label("product_id"),
                db.func.max(Invoice.date_created).label("last_sale"),
            )
            .join(Invoice, InvoiceProduct.invoice_id == Invoice.id)
            .filter(Invoice.date_created >= start, Invoice.date_created <= end)
            .group_by(InvoiceProduct.product_id)
            .all()
        )
        invoice_data = {
            row.product_id: {"last_sale": row.last_sale} for row in invoice_rows
        }

        term_rows = (
            db.session.query(
                TerminalSale.product_id.label("product_id"),
                EventLocation.location_id.label("location_id"),
                db.func.sum(TerminalSale.quantity).label("total_quantity"),
                db.func.max(TerminalSale.sold_at).label("last_sale"),
            )
            .join(EventLocation, TerminalSale.event_location_id == EventLocation.id)
            .filter(TerminalSale.sold_at >= start, TerminalSale.sold_at <= end)
            .group_by(TerminalSale.product_id, EventLocation.location_id)
            .all()
        )

        terminal_data = {}
        location_ids = set()
        for row in term_rows:
            pid = row.product_id
            location_ids.add(row.location_id)
            data = terminal_data.setdefault(
                pid, {"locations": {}, "last_sale": row.last_sale}
            )
            data["locations"][row.location_id] = row.total_quantity
            if row.last_sale > data["last_sale"]:
                data["last_sale"] = row.last_sale

        locations = {}
        if location_ids:
            loc_objs = Location.query.filter(Location.id.in_(location_ids)).all()
            locations = {loc.id: loc.name for loc in loc_objs}

        product_ids = set(invoice_data.keys()) | set(terminal_data.keys())
        products = (
            Product.query.filter(Product.id.in_(product_ids)).order_by(Product.name).all()
            if product_ids
            else []
        )

        report_data = []
        for prod in products:
            inv_last = invoice_data.get(prod.id, {}).get("last_sale")
            term_last = terminal_data.get(prod.id, {}).get("last_sale")
            last_sale = max(
                [d for d in [inv_last, term_last] if d is not None],
                default=None,
            )
            loc_list = []
            for loc_id, qty in terminal_data.get(prod.id, {}).get("locations", {}).items():
                loc_list.append(
                    {"name": locations.get(loc_id, "Unknown"), "quantity": qty}
                )
            report_data.append(
                {"name": prod.name, "last_sale": last_sale, "locations": loc_list}
            )

    return render_template(
        "report_product_location_sales.html", form=form, report=report_data
    )


@report.route("/reports/purchase-cost-forecast", methods=["GET", "POST"])
@login_required
def purchase_cost_forecast():
    """Forecast purchase costs for inventory items over a future period."""

    form = PurchaseCostForecastForm()
    report_rows = None
    totals = {"quantity": 0.0, "cost": 0.0}
    forecast_days = None
    lookback_days = None
    history_window = None

    if form.validate_on_submit():
        forecast_days = form.forecast_period.data
        history_window = form.history_window.data
        location_id = form.location_id.data or None
        item_id = form.item_id.data or None
        purchase_gl_code_ids = [
            code_id
            for code_id in (form.purchase_gl_code_ids.data or [])
            if code_id
        ]

        if location_id == 0:
            location_id = None
        if item_id == 0:
            item_id = None

        lookback_days = max(history_window, 30)
        helper = DemandForecastingHelper(lookback_days=lookback_days)
        recommendations = helper.build_recommendations(
            location_ids=[location_id] if location_id else None,
            item_ids=[item_id] if item_id else None,
            purchase_gl_code_ids=purchase_gl_code_ids or None,
        )

        report_rows = []
        for rec in recommendations:
            if lookback_days <= 0:
                continue

            consumption_per_day = rec.base_consumption / lookback_days
            incoming_total = (
                rec.history.get("transfer_in_qty", 0.0)
                + rec.history.get("invoice_qty", 0.0)
                + rec.history.get("open_po_qty", 0.0)
            )
            incoming_per_day = incoming_total / lookback_days

            forecast_consumption = consumption_per_day * forecast_days
            forecast_incoming = incoming_per_day * forecast_days
            net_quantity = max(forecast_consumption - forecast_incoming, 0.0)

            unit_cost = rec.item.cost or 0.0
            projected_cost = net_quantity * unit_cost

            if net_quantity <= 0 and projected_cost <= 0:
                continue

            totals["quantity"] += net_quantity
            totals["cost"] += projected_cost

            report_rows.append(
                {
                    "item": rec.item,
                    "location": rec.location,
                    "consumption_per_day": consumption_per_day,
                    "incoming_per_day": incoming_per_day,
                    "forecast_consumption": forecast_consumption,
                    "forecast_incoming": forecast_incoming,
                    "net_quantity": net_quantity,
                    "unit_cost": unit_cost,
                    "projected_cost": projected_cost,
                    "last_activity": rec.history.get("last_activity_ts"),
                }
            )

        report_rows.sort(key=lambda row: row["projected_cost"], reverse=True)

    return render_template(
        "report_purchase_cost_forecast.html",
        form=form,
        report_rows=report_rows,
        totals=totals,
        forecast_days=forecast_days,
        lookback_days=lookback_days,
    )
