from flask_wtf import FlaskForm
from flask_wtf.file import FileRequired
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

from app.models import Item, Location, Product, Customer, ItemUnit, GLCode
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
    gl_code = SelectField('GL Code', validators=[DataRequired()])
    base_unit = SelectField(
        'Base Unit',
        choices=[('ounce', 'Ounce'), ('gram', 'Gram'), ('each', 'Each'), ('millilitre', 'Millilitre')],
        validators=[DataRequired()]
    )
    units = FieldList(FormField(ItemUnitForm), min_entries=1)
    submit = SubmitField('Submit')

    def __init__(self, *args, **kwargs):
        super(ItemForm, self).__init__(*args, **kwargs)
        self.gl_code.choices = [(g.code, g.code) for g in GLCode.query.all()]

    def validate_gl_code(self, field):
        if field.data and not str(field.data).startswith('5'):
            raise ValidationError('Item GL codes must start with 5')


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
        self.from_location_id.choices = [(l.id, l.name) for l in Location.query.all()]
        self.to_location_id.choices = [(l.id, l.name) for l in Location.query.all()]
        # Here you might need to ensure that item choices are correctly populated
        # This is just an example and might need adjustment
        for item_form in self.items:
            item_form.item.choices = [(i.id, i.name) for i in Item.query.all()]
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
    gst_exempt = BooleanField('GST Exempt')
    pst_exempt = BooleanField('PST Exempt')
    submit = SubmitField('Submit')


class ProductForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired()])
    gl_code = SelectField('GL Code', validators=[DataRequired()])
    price = DecimalField('Price', validators=[DataRequired(), NumberRange(min=0.0001)])
    cost = DecimalField('Cost', validators=[InputRequired(), NumberRange(min=0)], default=0.0)
    submit = SubmitField('Submit')

    def __init__(self, *args, **kwargs):
        super(ProductForm, self).__init__(*args, **kwargs)
        self.gl_code.choices = [(g.code, g.code) for g in GLCode.query.all()]

    def validate_gl_code(self, field):
        if field.data and not str(field.data).startswith('4'):
            raise ValidationError('Product GL codes must start with 4')


class RecipeItemForm(FlaskForm):
    item = SelectField('Item', coerce=int)
    quantity = IntegerField('Quantity', validators=[InputRequired()])
    countable = BooleanField('Countable')


class ProductRecipeForm(FlaskForm):
    items = FieldList(FormField(RecipeItemForm), min_entries=1)
    submit = SubmitField('Submit')

    def __init__(self, *args, **kwargs):
        super(ProductRecipeForm, self).__init__(*args, **kwargs)
        for item_form in self.items:
            item_form.item.choices = [(i.id, i.name) for i in Item.query.all()]


class ProductWithRecipeForm(ProductForm):
    """Form used on product create/edit pages to also manage recipe items."""
    items = FieldList(FormField(RecipeItemForm), min_entries=1)

    def __init__(self, *args, **kwargs):
        super(ProductWithRecipeForm, self).__init__(*args, **kwargs)
        for item_form in self.items:
            item_form.item.choices = [(i.id, i.name) for i in Item.query.all()]


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
    vendor_id = SelectField('Vendor', coerce=int, validators=[Optional()])
    start_date = DateField('Start Date', validators=[Optional()])
    end_date = DateField('End Date', validators=[Optional()])
    submit = SubmitField('Filter')

class CreateBackupForm(FlaskForm):
    submit = SubmitField('Create Backup')


class RestoreBackupForm(FlaskForm):
    file = FileField('Backup File', validators=[FileRequired()])
    submit = SubmitField('Restore')


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
        self.vendor.choices = [(c.id, f"{c.first_name} {c.last_name}") for c in Customer.query.all()]
        for item_form in self.items:
            item_form.item.choices = [(i.id, i.name) for i in Item.query.all()]
            item_form.product.choices = [(p.id, p.name) for p in Product.query.all()]
            item_form.unit.choices = [(u.id, u.name) for u in ItemUnit.query.all()]


class InvoiceItemReceiveForm(FlaskForm):
    item = SelectField('Item', coerce=int)
    unit = SelectField('Unit', coerce=int, validators=[Optional()], validate_choice=False)
    quantity = DecimalField('Quantity', validators=[InputRequired()])
    cost = DecimalField('Cost', validators=[InputRequired()])
    return_item = BooleanField('Return')


class ReceiveInvoiceForm(FlaskForm):
    received_date = DateField('Received Date', validators=[DataRequired()])
    location_id = SelectField('Location', coerce=int, validators=[DataRequired()])
    gst = DecimalField('GST Amount', validators=[Optional()], default=0)
    pst = DecimalField('PST Amount', validators=[Optional()], default=0)
    delivery_charge = DecimalField('Delivery Charge', validators=[Optional()], default=0)
    items = FieldList(FormField(InvoiceItemReceiveForm), min_entries=1)
    submit = SubmitField('Submit')

    def __init__(self, *args, **kwargs):
        super(ReceiveInvoiceForm, self).__init__(*args, **kwargs)
        self.location_id.choices = [(l.id, l.name) for l in Location.query.all()]
        for item_form in self.items:
            item_form.item.choices = [(i.id, i.name) for i in Item.query.all()]
            item_form.unit.choices = [(u.id, u.name) for u in ItemUnit.query.all()]


class DeleteForm(FlaskForm):
    """Simple form used for CSRF protection on delete actions."""
    submit = SubmitField('Delete')

