from flask_wtf import FlaskForm
from flask_wtf.file import FileRequired, FileAllowed
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
    InputRequired,
    Length,
    NumberRange,
    Optional,
    EqualTo,
)
from wtforms.widgets import CheckboxInput, ListWidget

from app.models import Item, Location, Product, Customer, Vendor, ItemUnit, GLCode
from wtforms.validators import ValidationError


class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])


class SignupForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    confirm_password = PasswordField(
        'Confirm Password',
        validators=[DataRequired(), EqualTo('password', message='Passwords must match')]
    )
    submit = SubmitField('Sign Up')


class PasswordResetRequestForm(FlaskForm):
    """Form for requesting a password reset email."""
    email = StringField('Email', validators=[DataRequired(), Email()])
    submit = SubmitField('Send Reset Email')


class LocationForm(FlaskForm):
    name = StringField('Location Name', validators=[DataRequired(), Length(min=2, max=100)])
    products = HiddenField('Products')
    submit = SubmitField('Submit')


class ItemUnitForm(FlaskForm):
    name = StringField('Unit Name', validators=[DataRequired()])
    factor = DecimalField('Factor', validators=[InputRequired()])
    receiving_default = BooleanField('Receiving Default')
    transfer_default = BooleanField('Transfer Default')


class ItemForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired()])
    gl_code = SelectField('GL Code', validators=[Optional()])
    base_unit = SelectField(
        'Base Unit',
        choices=[('ounce', 'Ounce'), ('gram', 'Gram'), ('each', 'Each'), ('millilitre', 'Millilitre')],
        validators=[DataRequired()]
    )
    gl_code_id = SelectField('GL Code', coerce=int, validators=[Optional()], validate_choice=False)
    purchase_gl_code = SelectField('Purchase GL Code', coerce=int, validators=[Optional()])
    units = FieldList(FormField(ItemUnitForm), min_entries=1)
    submit = SubmitField('Submit')

    def __init__(self, *args, **kwargs):
        super(ItemForm, self).__init__(*args, **kwargs)
        codes = GLCode.query.filter(GLCode.code.like('5%')).all()
        self.gl_code.choices = [
            (g.code, f"{g.code} - {g.description}" if g.description else g.code)
            for g in codes
        ]
        purchase_codes = [
            (g.id, f"{g.code} - {g.description}" if g.description else g.code)
            for g in codes
        ]
        self.gl_code_id.choices = purchase_codes
        self.purchase_gl_code.choices = purchase_codes

    def validate_gl_code(self, field):
        if field.data and not str(field.data).startswith('5'):
            raise ValidationError('Item GL codes must start with 5')
        from app.models import GLCode
        codes = GLCode.query.filter(GLCode.code.like('5%')).all()
        purchase_codes = [
            (g.id, f"{g.code} - {g.description}" if g.description else g.code)
            for g in codes
        ]
        self.gl_code_id.choices = purchase_codes
        self.purchase_gl_code.choices = purchase_codes


class TransferItemForm(FlaskForm):
    item = SelectField('Item', coerce=int)
    unit = SelectField('Unit', coerce=int, validators=[Optional()], validate_choice=False)
    quantity = DecimalField('Quantity', validators=[InputRequired()])


class TransferForm(FlaskForm):
    # Your existing fields
    from_location_id = SelectField('From Location', coerce=int, validators=[DataRequired()])
    to_location_id = SelectField('To Location', coerce=int, validators=[DataRequired()])
    items = FieldList(FormField(TransferItemForm), min_entries=1)
    submit = SubmitField('Transfer')

    def __init__(self, *args, **kwargs):
        super(TransferForm, self).__init__(*args, **kwargs)
        # Dynamically set choices for from_location_id and to_location_id
        self.from_location_id.choices = [(l.id, l.name) for l in Location.query.filter_by(archived=False).all()]
        self.to_location_id.choices = [(l.id, l.name) for l in Location.query.filter_by(archived=False).all()]
        # Here you might need to ensure that item choices are correctly populated
        # This is just an example and might need adjustment
        for item_form in self.items:
            item_form.item.choices = [(i.id, i.name) for i in Item.query.filter_by(archived=False).all()]
            item_form.unit.choices = []


class UserForm(FlaskForm):
    pass


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField('Current Password', validators=[DataRequired()])
    new_password = PasswordField('New Password', validators=[DataRequired()])
    confirm_password = PasswordField(
        'Confirm Password',
        validators=[DataRequired(), EqualTo('new_password', message='Passwords must match')]
    )
    submit = SubmitField('Change Password')


class SetPasswordForm(FlaskForm):
    new_password = PasswordField('New Password', validators=[DataRequired()])
    confirm_password = PasswordField(
        'Confirm Password',
        validators=[DataRequired(), EqualTo('new_password', message='Passwords must match')]
    )
    submit = SubmitField('Set Password')


class ImportItemsForm(FlaskForm):
    file = FileField('Item File', validators=[FileRequired()])
    submit = SubmitField('Import')


class DateRangeForm(FlaskForm):
    start_datetime = DateTimeLocalField('Start Date/Time', format='%Y-%m-%d %H:%M', validators=[DataRequired()], id='start_datetime')
    end_datetime = DateTimeLocalField('End Date/Time', format='%Y-%m-%d %H:%M', validators=[DataRequired()], id='end_datetime')


class CustomerForm(FlaskForm):
    first_name = StringField('First Name', validators=[DataRequired()])
    last_name = StringField('Last Name', validators=[DataRequired()])
    # These checkboxes represent whether GST/PST should be charged. The
    # underlying model stores exemption flags, so we invert these values in
    # the routes when saving/loading data.
    gst_exempt = BooleanField('Charge GST')
    pst_exempt = BooleanField('Charge PST')
    submit = SubmitField('Submit')


class ProductForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired()])
    gl_code = SelectField('GL Code', validators=[Optional()])
    price = DecimalField('Price', validators=[DataRequired(), NumberRange(min=0.0001)])
    cost = DecimalField('Cost', validators=[InputRequired(), NumberRange(min=0)], default=0.0)
    gl_code_id = SelectField('GL Code', coerce=int, validators=[Optional()], validate_choice=False)
    sales_gl_code = SelectField('Sales GL Code', coerce=int, validators=[Optional()])
    submit = SubmitField('Submit')

    def __init__(self, *args, **kwargs):
        super(ProductForm, self).__init__(*args, **kwargs)
        sales_codes = [
            (g.id, g.code) for g in GLCode.query.filter(GLCode.code.like('4%')).all()
        ]
        self.gl_code.choices = [(code, code) for _, code in sales_codes]
        self.gl_code_id.choices = sales_codes
        self.sales_gl_code.choices = sales_codes

    def validate_gl_code(self, field):
        if field.data and not str(field.data).startswith('4'):
            raise ValidationError('Product GL codes must start with 4')
        from app.models import GLCode
        sales_codes = [
            (g.id, g.code) for g in GLCode.query.filter(GLCode.code.like('4%')).all()
        ]
        self.gl_code_id.choices = sales_codes
        self.sales_gl_code.choices = sales_codes


class RecipeItemForm(FlaskForm):
    item = SelectField('Item', coerce=int)
    unit = SelectField('Unit', coerce=int, validators=[Optional()], validate_choice=False)
    quantity = DecimalField('Quantity', validators=[InputRequired()])
    countable = BooleanField('Countable')


class ProductRecipeForm(FlaskForm):
    items = FieldList(FormField(RecipeItemForm), min_entries=1)
    submit = SubmitField('Submit')

    def __init__(self, *args, **kwargs):
        super(ProductRecipeForm, self).__init__(*args, **kwargs)
        for item_form in self.items:
            item_form.item.choices = [(i.id, i.name) for i in Item.query.filter_by(archived=False).all()]
            item_form.unit.choices = [(u.id, u.name) for u in ItemUnit.query.all()]


class ProductWithRecipeForm(ProductForm):
    """Form used on product create/edit pages to also manage recipe items."""
    items = FieldList(FormField(RecipeItemForm), min_entries=1)

    def __init__(self, *args, **kwargs):
        super(ProductWithRecipeForm, self).__init__(*args, **kwargs)
        for item_form in self.items:
            item_form.item.choices = [(i.id, i.name) for i in Item.query.filter_by(archived=False).all()]
            item_form.unit.choices = [(u.id, u.name) for u in ItemUnit.query.all()]


class InvoiceForm(FlaskForm):
    customer = SelectField('Customer', coerce=float, validators=[DataRequired()])
    products = HiddenField('Products JSON')
    submit = SubmitField('Add Product')

class VendorInvoiceReportForm(FlaskForm):
    customer = SelectMultipleField(
        'Vendors',
        coerce=int,
        validators=[Optional()],
        option_widget=CheckboxInput(),
        widget=ListWidget(prefix_label=False)
    )
    start_date = DateField('Start Date', validators=[DataRequired()])
    end_date = DateField('End Date', validators=[DataRequired()])
    submit = SubmitField('Generate Report')

# forms.py
class ProductSalesReportForm(FlaskForm):
    start_date = DateField('Start Date', validators=[DataRequired()])
    end_date = DateField('End Date', validators=[DataRequired()])
    submit = SubmitField('Generate Report')


class InvoiceFilterForm(FlaskForm):
    invoice_id = StringField('Invoice ID', validators=[Optional()])
    customer_id = SelectField('Customer', coerce=int, validators=[Optional()])
    start_date = DateField('Start Date', validators=[Optional()])
    end_date = DateField('End Date', validators=[Optional()])
    submit = SubmitField('Filter')

class CreateBackupForm(FlaskForm):
    submit = SubmitField('Create Backup')


class RestoreBackupForm(FlaskForm):
    file = FileField('Backup File', validators=[FileRequired()])
    submit = SubmitField('Restore')


class ImportForm(FlaskForm):
    """Simple form used for one-click data imports."""
    submit = SubmitField('Import')


class POItemForm(FlaskForm):
    item = SelectField('Item', coerce=int)
    product = SelectField('Product', coerce=int, validators=[Optional()],
                          validate_choice=False)
    unit = SelectField('Unit', coerce=int, validators=[Optional()],
                       validate_choice=False)
    quantity = DecimalField('Quantity', validators=[InputRequired()])


class PurchaseOrderForm(FlaskForm):
    vendor = SelectField('Vendor', coerce=int, validators=[DataRequired()])
    order_date = DateField('Order Date', validators=[DataRequired()])
    expected_date = DateField('Expected Delivery Date', validators=[DataRequired()])
    delivery_charge = DecimalField('Delivery Charge', validators=[Optional()], default=0)
    items = FieldList(FormField(POItemForm), min_entries=1)
    submit = SubmitField('Submit')

    def __init__(self, *args, **kwargs):
        super(PurchaseOrderForm, self).__init__(*args, **kwargs)
        self.vendor.choices = [(v.id, f"{v.first_name} {v.last_name}") for v in Vendor.query.filter_by(archived=False).all()]
        for item_form in self.items:
            item_form.item.choices = [(i.id, i.name) for i in Item.query.filter_by(archived=False).all()]
            item_form.product.choices = [(p.id, p.name) for p in Product.query.all()]
            item_form.unit.choices = [(u.id, u.name) for u in ItemUnit.query.all()]


class InvoiceItemReceiveForm(FlaskForm):
    item = SelectField('Item', coerce=int)
    unit = SelectField('Unit', coerce=int, validators=[Optional()], validate_choice=False)
    quantity = DecimalField('Quantity', validators=[InputRequired()])
    cost = DecimalField('Cost', validators=[InputRequired()])
    return_item = BooleanField('Return')


class ReceiveInvoiceForm(FlaskForm):
    invoice_number = StringField('Invoice Number', validators=[Optional()])
    received_date = DateField('Received Date', validators=[DataRequired()])
    location_id = SelectField('Location', coerce=int, validators=[DataRequired()])
    gst = DecimalField('GST Amount', validators=[Optional()], default=0)
    pst = DecimalField('PST Amount', validators=[Optional()], default=0)
    delivery_charge = DecimalField('Delivery Charge', validators=[Optional()], default=0)
    items = FieldList(FormField(InvoiceItemReceiveForm), min_entries=1)
    submit = SubmitField('Submit')

    def __init__(self, *args, **kwargs):
        super(ReceiveInvoiceForm, self).__init__(*args, **kwargs)
        self.location_id.choices = [(l.id, l.name) for l in Location.query.filter_by(archived=False).all()]
        for item_form in self.items:
            item_form.item.choices = [(i.id, i.name) for i in Item.query.filter_by(archived=False).all()]
            item_form.unit.choices = [(u.id, u.name) for u in ItemUnit.query.all()]


class DeleteForm(FlaskForm):
    """Simple form used for CSRF protection on delete actions."""
    submit = SubmitField('Delete')


class GLCodeForm(FlaskForm):
    code = StringField('Code', validators=[DataRequired(), Length(max=6)])
    description = StringField('Description', validators=[Optional()])
    submit = SubmitField('Submit')


class EventForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired()])
    start_date = DateField('Start Date', validators=[DataRequired()])
    end_date = DateField('End Date', validators=[DataRequired()])
    submit = SubmitField('Submit')


class EventLocationForm(FlaskForm):
    location_id = SelectField('Location', coerce=int, validators=[DataRequired()])
    submit = SubmitField('Submit')

    def __init__(self, *args, **kwargs):
        super(EventLocationForm, self).__init__(*args, **kwargs)
        self.location_id.choices = [(l.id, l.name) for l in Location.query.filter_by(archived=False).all()]


class EventLocationConfirmForm(FlaskForm):
    submit = SubmitField('Confirm')


class ConfirmForm(FlaskForm):
    """Generic confirmation form used for warnings."""
    submit = SubmitField('Confirm')


class TerminalSaleForm(FlaskForm):
    product_id = SelectField('Product', coerce=int, validators=[DataRequired()])
    quantity = DecimalField('Quantity', validators=[InputRequired()])
    submit = SubmitField('Submit')

    def __init__(self, *args, **kwargs):
        super(TerminalSaleForm, self).__init__(*args, **kwargs)
        self.product_id.choices = [(p.id, p.name) for p in Product.query.all()]


class TerminalSalesUploadForm(FlaskForm):
    """Form for uploading terminal sales from XLS or PDF."""
    file = FileField(
        "Sales File",
        validators=[
            FileRequired(),
            FileAllowed({"xls", "pdf"}, "Only .xls or .pdf files are allowed."),
        ],
    )
    submit = SubmitField("Upload")


class GSTForm(FlaskForm):
    gst_number = StringField('GST Number', validators=[Optional(), Length(max=50)])
    submit = SubmitField('Update')
