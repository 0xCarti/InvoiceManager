import os
from functools import lru_cache
from zoneinfo import available_timezones

from flask import g
from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileRequired
from sqlalchemy import or_
from wtforms import (
    BooleanField,
    DateField,
    DateTimeLocalField,
    DecimalField,
    FieldList,
    FileField,
    FormField,
    HiddenField,
    IntegerField,
    PasswordField,
    SelectField,
    SelectMultipleField,
    StringField,
    SubmitField,
)
from wtforms.validators import (
    DataRequired,
    Email,
    EqualTo,
    InputRequired,
    Length,
    NumberRange,
    Optional,
    ValidationError,
)
from wtforms.widgets import CheckboxInput, ListWidget

from app.models import (
    EventLocation,
    GLCode,
    Item,
    ItemUnit,
    Location,
    Product,
    Vendor,
)

# Uploaded backup files are capped at 10MB to prevent excessive memory usage
MAX_BACKUP_SIZE = 10 * 1024 * 1024  # 10 MB


def load_item_choices():
    """Return a list of active item choices, cached per request."""
    if "item_choices" not in g:
        g.item_choices = [
            (i.id, i.name) for i in Item.query.filter_by(archived=False).all()
        ]
    return g.item_choices


def load_unit_choices():
    """Return a list of item unit choices."""
    return [(u.id, u.name) for u in ItemUnit.query.all()]


def load_purchase_gl_code_choices():
    """Return purchase GL code options filtered for expense accounts."""
    if "purchase_gl_code_choices" not in g:
        codes = (
            GLCode.query.filter(
                or_(GLCode.code.like("5%"), GLCode.code.like("6%"))
            )
            .order_by(GLCode.code)
            .all()
        )
        g.purchase_gl_code_choices = [
            (0, "Use Default GL Code")
        ] + [
            (
                code.id,
                f"{code.code} - {code.description}" if code.description else code.code,
            )
            for code in codes
        ]
    return g.purchase_gl_code_choices


@lru_cache(maxsize=1)
def get_timezone_choices():
    """Return a sorted list of available time zones.

    The list is computed only once and cached for subsequent calls to
    avoid the cost of generating it at import time.
    """
    return sorted(available_timezones())


class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[DataRequired()])


class CSRFOnlyForm(FlaskForm):
    """Simple form that only provides CSRF protection."""

    pass


class PasswordResetRequestForm(FlaskForm):
    """Form for requesting a password reset email."""

    email = StringField("Email", validators=[DataRequired(), Email()])
    submit = SubmitField("Send Reset Email")


class LocationForm(FlaskForm):
    name = StringField(
        "Location Name", validators=[DataRequired(), Length(min=2, max=100)]
    )
    products = HiddenField("Products")
    is_spoilage = BooleanField("Spoilage Location")
    submit = SubmitField("Submit")


class LocationItemAddForm(FlaskForm):
    """Form used to add standalone items to a location."""

    item_id = SelectField(
        "Item", coerce=int, validators=[DataRequired()], validate_choice=False
    )
    expected_count = DecimalField(
        "Expected Count", validators=[Optional()], places=None, default=0
    )
    submit = SubmitField("Add Item")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Default choices are populated with all active items. Views using this
        # form typically override ``item_id.choices`` to remove already-added
        # items, but setting the base list here ensures the field works when the
        # view does not provide its own list.
        self.item_id.choices = load_item_choices()


class ItemUnitForm(FlaskForm):
    name = StringField("Unit Name", validators=[DataRequired()])
    factor = DecimalField("Factor", validators=[InputRequired()])
    receiving_default = BooleanField("Receiving Default")
    transfer_default = BooleanField("Transfer Default")


class ItemForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired()])
    upc = StringField("UPC", validators=[Optional(), Length(max=32)])
    gl_code = SelectField("GL Code", validators=[Optional()])
    base_unit = SelectField(
        "Base Unit",
        choices=[
            ("ounce", "Ounce"),
            ("gram", "Gram"),
            ("each", "Each"),
            ("millilitre", "Millilitre"),
        ],
        validators=[DataRequired()],
    )
    gl_code_id = SelectField(
        "GL Code", coerce=int, validators=[Optional()], validate_choice=False
    )
    purchase_gl_code = SelectField(
        "Purchase GL Code", coerce=int, validators=[Optional()]
    )
    units = FieldList(FormField(ItemUnitForm), min_entries=1)
    submit = SubmitField("Submit")

    def __init__(self, *args, **kwargs):
        super(ItemForm, self).__init__(*args, **kwargs)
        codes = self._fetch_purchase_gl_codes()
        self.gl_code.choices = [
            (
                g.code,
                f"{g.code} - {g.description}" if g.description else g.code,
            )
            for g in codes
        ]
        purchase_codes = [
            (g.id, f"{g.code} - {g.description}" if g.description else g.code)
            for g in codes
        ]
        self.gl_code_id.choices = purchase_codes
        self.purchase_gl_code.choices = purchase_codes

    def validate_gl_code(self, field):
        if field.data and not str(field.data).startswith(("5", "6")):
            raise ValidationError("Item GL codes must start with 5 or 6")
        codes = self._fetch_purchase_gl_codes()
        purchase_codes = [
            (g.id, f"{g.code} - {g.description}" if g.description else g.code)
            for g in codes
        ]
        self.gl_code_id.choices = purchase_codes
        self.purchase_gl_code.choices = purchase_codes

    @staticmethod
    def _fetch_purchase_gl_codes():
        return (
            GLCode.query.filter(
                or_(GLCode.code.like("5%"), GLCode.code.like("6%"))
            )
            .order_by(GLCode.code)
            .all()
        )


class TransferItemForm(FlaskForm):
    item = SelectField("Item", coerce=int)
    unit = SelectField(
        "Unit", coerce=int, validators=[Optional()], validate_choice=False
    )
    quantity = DecimalField("Quantity", validators=[InputRequired()])


class TransferForm(FlaskForm):
    # Your existing fields
    from_location_id = SelectField(
        "From Location", coerce=int, validators=[DataRequired()]
    )
    to_location_id = SelectField(
        "To Location", coerce=int, validators=[DataRequired()]
    )
    items = FieldList(FormField(TransferItemForm), min_entries=1)
    submit = SubmitField("Transfer")

    def __init__(self, *args, **kwargs):
        super(TransferForm, self).__init__(*args, **kwargs)
        # Dynamically set choices for from_location_id and to_location_id
        locations = [
            (loc.id, loc.name)
            for loc in Location.query.filter_by(archived=False).all()
        ]
        self.from_location_id.choices = locations
        self.to_location_id.choices = locations
        items = load_item_choices()
        for item_form in self.items:
            item_form.item.choices = items
            item_form.unit.choices = []


class UserForm(FlaskForm):
    pass


class InviteUserForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])
    submit = SubmitField("Send Invite")


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField(
        "Current Password", validators=[DataRequired()]
    )
    new_password = PasswordField("New Password", validators=[DataRequired()])
    confirm_password = PasswordField(
        "Confirm Password",
        validators=[
            DataRequired(),
            EqualTo("new_password", message="Passwords must match"),
        ],
    )
    submit = SubmitField("Change Password")


class SetPasswordForm(FlaskForm):
    new_password = PasswordField("New Password", validators=[DataRequired()])
    confirm_password = PasswordField(
        "Confirm Password",
        validators=[
            DataRequired(),
            EqualTo("new_password", message="Passwords must match"),
        ],
    )
    submit = SubmitField("Set Password")


class ImportItemsForm(FlaskForm):
    file = FileField("Item File", validators=[FileRequired()])
    submit = SubmitField("Import")


class DateRangeForm(FlaskForm):
    start_datetime = DateTimeLocalField(
        "Start Date/Time",
        format="%Y-%m-%d %H:%M",
        validators=[DataRequired()],
        id="start_datetime",
    )
    end_datetime = DateTimeLocalField(
        "End Date/Time",
        format="%Y-%m-%d %H:%M",
        validators=[DataRequired()],
        id="end_datetime",
    )


class SpoilageFilterForm(FlaskForm):
    start_date = DateField("Start Date", validators=[Optional()])
    end_date = DateField("End Date", validators=[Optional()])
    purchase_gl_code = SelectField(
        "Purchase GL Code",
        coerce=int,
        validators=[Optional()],
        validate_choice=False,
    )
    items = SelectMultipleField(
        "Items", coerce=int, validators=[Optional()], validate_choice=False
    )
    submit = SubmitField("Filter")

    def __init__(self, *args, **kwargs):
        super(SpoilageFilterForm, self).__init__(*args, **kwargs)
        gl_codes = ItemForm._fetch_purchase_gl_codes()
        self.purchase_gl_code.choices = [
            (g.id, f"{g.code} - {g.description}" if g.description else g.code)
            for g in gl_codes
        ]
        self.items.choices = load_item_choices()


class CustomerForm(FlaskForm):
    first_name = StringField("First Name", validators=[DataRequired()])
    last_name = StringField("Last Name", validators=[DataRequired()])
    # These checkboxes represent whether GST/PST should be charged. The
    # underlying model stores exemption flags, so we invert these values in
    # the routes when saving/loading data.
    gst_exempt = BooleanField("Charge GST")
    pst_exempt = BooleanField("Charge PST")
    submit = SubmitField("Submit")


class ProductForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired()])
    gl_code = SelectField("GL Code", validators=[Optional()])
    price = DecimalField(
        "Price", validators=[DataRequired(), NumberRange(min=0.0001)]
    )
    cost = DecimalField(
        "Cost", validators=[InputRequired(), NumberRange(min=0)], default=0.0
    )
    gl_code_id = SelectField(
        "GL Code", coerce=int, validators=[Optional()], validate_choice=False
    )
    sales_gl_code = SelectField(
        "Sales GL Code", coerce=int, validators=[Optional()]
    )
    submit = SubmitField("Submit")

    def __init__(self, *args, **kwargs):
        super(ProductForm, self).__init__(*args, **kwargs)
        sales_codes_raw = (
            GLCode.query.filter(GLCode.code.like("4%"))
            .order_by(GLCode.code)
            .all()
        )
        formatted_sales_codes = [
            (
                g.id,
                f"{g.code} - {g.description}" if g.description else g.code,
            )
            for g in sales_codes_raw
        ]
        self.gl_code.choices = [(g.code, g.code) for g in sales_codes_raw]
        self.gl_code_id.choices = formatted_sales_codes
        self.sales_gl_code.choices = formatted_sales_codes

    def validate_gl_code(self, field):
        if field.data and not str(field.data).startswith("4"):
            raise ValidationError("Product GL codes must start with 4")
        from app.models import GLCode

        sales_codes_raw = (
            GLCode.query.filter(GLCode.code.like("4%"))
            .order_by(GLCode.code)
            .all()
        )
        formatted_sales_codes = [
            (
                g.id,
                f"{g.code} - {g.description}" if g.description else g.code,
            )
            for g in sales_codes_raw
        ]
        self.gl_code_id.choices = formatted_sales_codes
        self.sales_gl_code.choices = formatted_sales_codes


class RecipeItemForm(FlaskForm):
    item = SelectField("Item", coerce=int)
    unit = SelectField(
        "Unit", coerce=int, validators=[Optional()], validate_choice=False
    )
    quantity = DecimalField("Quantity", validators=[InputRequired()])
    countable = BooleanField("Countable")


class ProductRecipeForm(FlaskForm):
    items = FieldList(FormField(RecipeItemForm), min_entries=1)
    submit = SubmitField("Submit")

    def __init__(self, *args, **kwargs):
        super(ProductRecipeForm, self).__init__(*args, **kwargs)
        items = load_item_choices()
        units = load_unit_choices()
        for item_form in self.items:
            item_form.item.choices = items
            item_form.unit.choices = units


class ProductWithRecipeForm(ProductForm):
    """Form used on product create/edit pages to also manage recipe items."""

    items = FieldList(FormField(RecipeItemForm), min_entries=0)

    def __init__(self, *args, **kwargs):
        super(ProductWithRecipeForm, self).__init__(*args, **kwargs)
        self.countable_label = RecipeItemForm().countable.label.text
        items = load_item_choices()
        units = load_unit_choices()
        for item_form in self.items:
            item_form.item.choices = items
            item_form.unit.choices = units


class InvoiceForm(FlaskForm):
    customer = SelectField(
        "Customer", coerce=float, validators=[DataRequired()]
    )
    products = HiddenField("Products JSON")
    submit = SubmitField("Add Product")


class VendorInvoiceReportForm(FlaskForm):
    customer = SelectMultipleField(
        "Vendors",
        coerce=int,
        validators=[Optional()],
        option_widget=CheckboxInput(),
        widget=ListWidget(prefix_label=False),
    )
    start_date = DateField("Start Date", validators=[DataRequired()])
    end_date = DateField("End Date", validators=[DataRequired()])
    submit = SubmitField("Generate Report")


class ReceivedInvoiceReportForm(FlaskForm):
    """Report form for received purchase invoices."""

    start_date = DateField("Start Date", validators=[DataRequired()])
    end_date = DateField("End Date", validators=[DataRequired()])
    submit = SubmitField("Generate Report")


# forms.py
class ProductSalesReportForm(FlaskForm):
    start_date = DateField("Start Date", validators=[DataRequired()])
    end_date = DateField("End Date", validators=[DataRequired()])
    submit = SubmitField("Generate Report")


class ProductRecipeReportForm(FlaskForm):
    products = SelectMultipleField(
        "Products",
        coerce=int,
        validators=[Optional()],
        option_widget=CheckboxInput(),
        widget=ListWidget(prefix_label=False),
    )
    select_all = BooleanField("Select All Products")
    submit = SubmitField("Generate Report")

    def __init__(self, *args, product_choices=None, **kwargs):
        super(ProductRecipeReportForm, self).__init__(*args, **kwargs)
        self.products.choices = product_choices or []


class InvoiceFilterForm(FlaskForm):
    invoice_id = StringField("Invoice ID", validators=[Optional()])
    customer_id = SelectField("Customer", coerce=int, validators=[Optional()])
    start_date = DateField("Start Date", validators=[Optional()])
    end_date = DateField("End Date", validators=[Optional()])
    submit = SubmitField("Filter")


class CreateBackupForm(FlaskForm):
    submit = SubmitField("Create Backup")


class RestoreBackupForm(FlaskForm):
    file = FileField(
        "Backup File",
        validators=[
            FileRequired(),
            FileAllowed({"db"}, "DB files only!"),
        ],
    )
    submit = SubmitField("Restore")

    def validate_file(self, field):
        field.data.seek(0, os.SEEK_END)
        if field.data.tell() > MAX_BACKUP_SIZE:
            raise ValidationError("File is too large.")
        field.data.seek(0)


class ImportForm(FlaskForm):
    """Upload a CSV file for bulk imports."""

    file = FileField(
        "CSV File",
        validators=[FileRequired(), FileAllowed({"csv"}, "CSV only!")],
    )
    submit = SubmitField("Import")


class POItemForm(FlaskForm):
    item = HiddenField("Item")
    product = SelectField(
        "Product", coerce=int, validators=[Optional()], validate_choice=False
    )
    unit = SelectField(
        "Unit", coerce=int, validators=[Optional()], validate_choice=False
    )
    quantity = DecimalField("Quantity", validators=[InputRequired()])
    position = HiddenField("Position")


class PurchaseOrderForm(FlaskForm):
    vendor = SelectField("Vendor", coerce=int, validators=[DataRequired()])
    order_date = DateField("Order Date", validators=[DataRequired()])
    expected_date = DateField(
        "Expected Delivery Date", validators=[DataRequired()]
    )
    delivery_charge = DecimalField(
        "Delivery Charge", validators=[Optional()], default=0
    )
    items = FieldList(FormField(POItemForm), min_entries=1)
    submit = SubmitField("Submit")

    def __init__(self, *args, **kwargs):
        super(PurchaseOrderForm, self).__init__(*args, **kwargs)
        self.vendor.choices = [
            (v.id, f"{v.first_name} {v.last_name}")
            for v in Vendor.query.filter_by(archived=False).all()
        ]
        units = load_unit_choices()
        products = [(p.id, p.name) for p in Product.query.all()]
        for item_form in self.items:
            item_form.product.choices = products
            item_form.unit.choices = units


class InvoiceItemReceiveForm(FlaskForm):
    item = SelectField("Item", coerce=int)
    unit = SelectField(
        "Unit", coerce=int, validators=[Optional()], validate_choice=False
    )
    quantity = DecimalField("Quantity", validators=[InputRequired()])
    cost = DecimalField("Cost", validators=[InputRequired()])
    position = HiddenField("Position")
    gl_code = SelectField(
        "GL Code",
        coerce=int,
        validators=[Optional()],
        validate_choice=False,
    )


class ReceiveInvoiceForm(FlaskForm):
    invoice_number = StringField("Invoice Number", validators=[Optional()])
    received_date = DateField("Received Date", validators=[DataRequired()])
    location_id = SelectField(
        "Location", coerce=int, validators=[DataRequired()]
    )
    gst = DecimalField("GST Amount", validators=[Optional()], default=0)
    pst = DecimalField("PST Amount", validators=[Optional()], default=0)
    delivery_charge = DecimalField(
        "Delivery Charge", validators=[Optional()], default=0
    )
    items = FieldList(FormField(InvoiceItemReceiveForm), min_entries=1)
    submit = SubmitField("Submit")

    def __init__(self, *args, **kwargs):
        super(ReceiveInvoiceForm, self).__init__(*args, **kwargs)
        self.location_id.choices = [
            (loc.id, loc.name)
            for loc in Location.query.filter_by(archived=False).all()
        ]
        items = load_item_choices()
        units = load_unit_choices()
        gl_codes = load_purchase_gl_code_choices()
        for item_form in self.items:
            item_form.item.choices = items
            item_form.unit.choices = units
            item_form.gl_code.choices = gl_codes


class DeleteForm(FlaskForm):
    """Simple form used for CSRF protection on delete actions."""

    submit = SubmitField("Delete")


class BulkProductCostForm(FlaskForm):
    """Form used when bulk-updating product costs from their recipes."""

    submit = SubmitField("Apply")


class GLCodeForm(FlaskForm):
    code = StringField("Code", validators=[DataRequired(), Length(max=6)])
    description = StringField("Description", validators=[Optional()])
    submit = SubmitField("Submit")


EVENT_TYPES = [
    ("catering", "Catering"),
    ("hockey", "Hockey"),
    ("concert", "Concert"),
    ("RMWF", "RMWF"),
    ("tournament", "Tournament"),
    ("curling", "Curling"),
    ("inventory", "Inventory"),
    ("other", "Other"),
]


class EventForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired()])
    start_date = DateField("Start Date", validators=[DataRequired()])
    end_date = DateField("End Date", validators=[DataRequired()])
    event_type = SelectField(
        "Event Type", choices=EVENT_TYPES, validators=[DataRequired()]
    )
    submit = SubmitField("Submit")


class EventLocationForm(FlaskForm):
    location_id = SelectMultipleField(
        "Locations", coerce=int, validators=[DataRequired()]
    )
    submit = SubmitField("Submit")

    def __init__(self, event_id=None, *args, **kwargs):
        super(EventLocationForm, self).__init__(*args, **kwargs)
        existing_location_ids = set()
        if event_id is not None:
            existing_location_ids = {
                loc_id
                for (loc_id,) in EventLocation.query.with_entities(
                    EventLocation.location_id
                ).filter_by(event_id=event_id)
            }

        self.location_id.choices = [
            (loc.id, loc.name)
            for loc in Location.query.filter_by(archived=False)
            .order_by(Location.name)
            .all()
            if loc.id not in existing_location_ids
        ]


class EventLocationConfirmForm(FlaskForm):
    submit = SubmitField("Confirm")


class ScanCountForm(FlaskForm):
    upc = StringField("UPC", validators=[DataRequired(), Length(max=32)])
    quantity = DecimalField(
        "Quantity", validators=[InputRequired()], default=1
    )
    submit = SubmitField("Add Count")


class ConfirmForm(FlaskForm):
    """Generic confirmation form used for warnings."""

    submit = SubmitField("Confirm")


class TerminalSaleForm(FlaskForm):
    product_id = SelectField(
        "Product", coerce=int, validators=[DataRequired()]
    )
    quantity = DecimalField("Quantity", validators=[InputRequired()])
    submit = SubmitField("Submit")

    def __init__(self, *args, **kwargs):
        super(TerminalSaleForm, self).__init__(*args, **kwargs)
        self.product_id.choices = [(p.id, p.name) for p in Product.query.all()]


class TerminalSalesUploadForm(FlaskForm):
    """Form for uploading terminal sales from XLS or PDF."""

    file = FileField(
        "Sales File",
        validators=[
            FileRequired(),
            FileAllowed(
                {"xls", "pdf"}, "Only .xls or .pdf files are allowed."
            ),
        ],
    )
    submit = SubmitField("Upload")


class SettingsForm(FlaskForm):
    gst_number = StringField(
        "GST Number", validators=[Optional(), Length(max=50)]
    )
    default_timezone = SelectField("Default Timezone")
    auto_backup_enabled = BooleanField("Enable Automatic Backups")
    auto_backup_interval_value = IntegerField(
        "Backup Interval",
        validators=[DataRequired(), NumberRange(min=1)],
    )
    auto_backup_interval_unit = SelectField(
        "Interval Unit",
        choices=[
            ("hour", "Hour"),
            ("day", "Day"),
            ("week", "Week"),
            ("month", "Month"),
            ("year", "Year"),
        ],
    )
    max_backups = IntegerField(
        "Max Stored Backups",
        validators=[DataRequired(), NumberRange(min=1)],
    )
    submit = SubmitField("Update")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_timezone.choices = [
            (tz, tz) for tz in get_timezone_choices()
        ]


class TimezoneForm(FlaskForm):
    timezone = SelectField("Timezone", validators=[Optional()])
    submit = SubmitField("Update Timezone")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.timezone.choices = [("", "Use Default")] + [
            (tz, tz) for tz in get_timezone_choices()
        ]


class NotificationForm(FlaskForm):
    phone_number = StringField(
        "Phone Number", validators=[Optional(), Length(max=20)]
    )
    notify_transfers = BooleanField("Send text on new transfer")
    submit = SubmitField("Update Notifications")

