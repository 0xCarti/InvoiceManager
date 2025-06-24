from flask_wtf import FlaskForm
from flask_wtf.file import FileRequired
from wtforms import StringField, SubmitField
from wtforms.fields.choices import SelectField
from wtforms.fields.datetime import DateTimeLocalField
from wtforms.fields.form import FormField
from wtforms.fields.list import FieldList
from wtforms.fields.numeric import IntegerField
from wtforms.fields.simple import PasswordField, FileField, BooleanField
from wtforms.validators import DataRequired, Length, Email
from wtforms import StringField, DecimalField, IntegerField, SelectField, SubmitField
from wtforms.fields.simple import PasswordField, HiddenField
from wtforms.validators import DataRequired, NumberRange, Length, EqualTo
from wtforms import StringField, FloatField, SubmitField
from wtforms.validators import DataRequired, NumberRange, InputRequired
from flask_wtf import FlaskForm
from wtforms import SelectField, DateField, SubmitField
from wtforms.validators import Optional
from wtforms import SelectMultipleField
from wtforms.widgets import ListWidget, CheckboxInput

from app.models import Location, Item


class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])


class SignupForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Sign Up')


class LocationForm(FlaskForm):
    name = StringField('Location Name', validators=[DataRequired(), Length(min=2, max=100)])
    submit = SubmitField('Submit')


class ItemForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired()])
    submit = SubmitField('Submit')


class TransferItemForm(FlaskForm):
    item = SelectField('Item', coerce=int)
    quantity = IntegerField('Quantity')


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


class UserForm(FlaskForm):
    pass


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
    price = DecimalField('Price', validators=[DataRequired(), NumberRange(min=0.0001)])
    cost = DecimalField('Cost', validators=[InputRequired(), NumberRange(min=0)], default=0.0)
    submit = SubmitField('Submit')


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
