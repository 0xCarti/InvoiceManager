import os
from datetime import datetime

from flask import (
    Blueprint,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import func
from werkzeug.utils import secure_filename

from app import GST, db, socketio
from app.forms import (
    CustomerForm,
    DateRangeForm,
    DeleteForm,
    GLCodeForm,
    ImportItemsForm,
    InvoiceFilterForm,
    InvoiceForm,
    ItemForm,
    LocationForm,
    LoginForm,
    ProductForm,
    ProductRecipeForm,
    ProductSalesReportForm,
    ProductWithRecipeForm,
    PurchaseOrderForm,
    ReceiveInvoiceForm,
    TransferForm,
    VendorInvoiceReportForm,
)
from app.models import (
    Customer,
    GLCode,
    Invoice,
    InvoiceProduct,
    Item,
    ItemUnit,
    Location,
    LocationStandItem,
    Product,
    ProductRecipeItem,
    PurchaseInvoice,
    PurchaseInvoiceItem,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderItemArchive,
    Transfer,
    TransferItem,
)
from app.utils.activity import log_activity

main = Blueprint("main", __name__)


@main.route("/")
@login_required
def home():
    """Render the transfers dashboard."""
    return render_template("transfers/view_transfers.html", user=current_user)
