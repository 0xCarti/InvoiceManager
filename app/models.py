from sqlalchemy.orm import relationship
from sqlalchemy import ForeignKeyConstraint
from app import db
from flask_login import UserMixin
from datetime import datetime

# Association table for the many-to-many relationship
transfer_items = db.Table('transfer_items',
                          db.Column('transfer_id', db.Integer, db.ForeignKey('transfer.id'), primary_key=True),
                          db.Column('item_id', db.Integer, db.ForeignKey('item.id'), primary_key=True),
                          db.Column('quantity', db.Integer, nullable=False)
                          )

# Association table for products available at a location
location_products = db.Table(
    'location_products',
    db.Column('location_id', db.Integer, db.ForeignKey('location.id'), primary_key=True),
    db.Column('product_id', db.Integer, db.ForeignKey('product.id'), primary_key=True)
)


class LocationStandItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    location_id = db.Column(db.Integer, db.ForeignKey('location.id'), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey('item.id'), nullable=False)
    expected_count = db.Column(db.Float, nullable=False, default=0.0, server_default='0.0')

    location = relationship('Location', back_populates='stand_items')
    item = relationship('Item')

    __table_args__ = (db.UniqueConstraint('location_id', 'item_id', name='_loc_item_uc'),)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(80), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    transfers = db.relationship('Transfer', backref='creator', lazy=True)
    invoices = db.relationship('Invoice', backref='creator', lazy=True)
    active = db.Column(db.Boolean, default=False, nullable=False)
    favorites = db.Column(db.Text, default='')

    def get_favorites(self):
        """Return the user's favourite endpoint names as a list."""
        return [f for f in (self.favorites or '').split(',') if f]

    def toggle_favorite(self, endpoint: str):
        """Add or remove an endpoint from the favourites list."""
        favs = set(self.get_favorites())
        if endpoint in favs:
            favs.remove(endpoint)
        else:
            favs.add(endpoint)
        self.favorites = ','.join(sorted(favs))


class Location(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    archived = db.Column(db.Boolean, default=False, nullable=False, server_default='0')
    products = db.relationship('Product', secondary=location_products, backref='locations')
    stand_items = db.relationship('LocationStandItem', back_populates='location', cascade='all, delete-orphan')
    event_locations = db.relationship('EventLocation', back_populates='location', cascade='all, delete-orphan')




class Item(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    base_unit = db.Column(db.String(20), nullable=False)
    gl_code = db.Column(db.String(10), nullable=True)
    gl_code_id = db.Column(db.Integer, db.ForeignKey('gl_code.id'), nullable=True)
    quantity = db.Column(db.Float, nullable=False, default=0.0, server_default="0.0")
    cost = db.Column(db.Float, nullable=False, default=0.0, server_default="0.0")
    purchase_gl_code_id = db.Column(db.Integer, db.ForeignKey('gl_code.id'), nullable=True)
    purchase_gl_code = relationship('GLCode', foreign_keys=[purchase_gl_code_id])
    transfers = db.relationship('Transfer', secondary=transfer_items, backref=db.backref('items', lazy='dynamic'))
    recipe_items = relationship("ProductRecipeItem", back_populates="item", cascade="all, delete-orphan")
    units = relationship("ItemUnit", back_populates="item", cascade="all, delete-orphan")
    gl_code_rel = relationship('GLCode', foreign_keys=[gl_code_id], backref='items')
    archived = db.Column(db.Boolean, default=False, nullable=False, server_default='0')


class ItemUnit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('item.id'), nullable=False)
    name = db.Column(db.String(50), nullable=False)
    factor = db.Column(db.Float, nullable=False)
    receiving_default = db.Column(db.Boolean, default=False, nullable=False, server_default='0')
    transfer_default = db.Column(db.Boolean, default=False, nullable=False, server_default='0')

    item = relationship('Item', back_populates='units')

    __table_args__ = (
        db.UniqueConstraint('item_id', 'name', name='_item_unit_name_uc'),
    )


class Transfer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    from_location_id = db.Column(db.Integer, db.ForeignKey('location.id'), nullable=False)
    to_location_id = db.Column(db.Integer, db.ForeignKey('location.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date_created = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    completed = db.Column(db.Boolean, default=False, nullable=False)
    from_location_name = db.Column(db.String(100), nullable=False, server_default='')
    to_location_name = db.Column(db.String(100), nullable=False, server_default='')

    # Define relationships to Location model
    from_location = relationship('Location', foreign_keys=[from_location_id])
    to_location = relationship('Location', foreign_keys=[to_location_id])
    transfer_items = db.relationship('TransferItem', backref='transfer', cascade='all, delete-orphan')


class TransferItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    transfer_id = db.Column(db.Integer, db.ForeignKey('transfer.id'), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey('item.id'), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    item = relationship('Item', backref='transfer_items', lazy=True)
    item_name = db.Column(db.String(100), nullable=False, server_default='')

class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    gst_exempt = db.Column(db.Boolean, default=False, nullable=False, server_default='0')
    pst_exempt = db.Column(db.Boolean, default=False, nullable=False, server_default='0')
    archived = db.Column(db.Boolean, default=False, nullable=False, server_default='0')
    invoices = db.relationship('Invoice', backref='customer', lazy=True)


class Vendor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    gst_exempt = db.Column(db.Boolean, default=False, nullable=False, server_default='0')
    pst_exempt = db.Column(db.Boolean, default=False, nullable=False, server_default='0')
    archived = db.Column(db.Boolean, default=False, nullable=False, server_default='0')


class GLCode(db.Model):
    __tablename__ = 'gl_code'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(6), unique=True, nullable=False)
    description = db.Column(db.String(255))


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    gl_code = db.Column(db.String(10), nullable=True)
    price = db.Column(db.Float, nullable=False)
    cost = db.Column(db.Float, nullable=False, default=0.0, server_default="0.0")
    gl_code_id = db.Column(db.Integer, db.ForeignKey('gl_code.id'), nullable=True)
    quantity = db.Column(db.Float, nullable=False, default=0.0, server_default="0.0")
    sales_gl_code_id = db.Column(db.Integer, db.ForeignKey('gl_code.id'), nullable=True)
    sales_gl_code = relationship('GLCode', foreign_keys=[sales_gl_code_id])

    # Define a one-to-many relationship with InvoiceProduct
    invoice_products = relationship("InvoiceProduct", back_populates="product")
    recipe_items = relationship("ProductRecipeItem", back_populates="product", cascade="all, delete-orphan")
    gl_code_rel = relationship('GLCode', foreign_keys=[gl_code_id], backref='products')
    terminal_sales = relationship('TerminalSale', back_populates='product', cascade='all, delete-orphan')


class Invoice(db.Model):
    id = db.Column(db.String(10), primary_key=True)  # Adjust length based on your requirements
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)  # Reference to the user who created the invoice
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    date_created = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # Define a ForeignKeyConstraint to ensure referential integrity with InvoiceProduct
    __table_args__ = (
        ForeignKeyConstraint(
            ['id'],
            ['invoice_product.invoice_id'],
            use_alter=True,
        ),
    )

    # Define the relationship with InvoiceProduct, specifying the foreign_keys argument
    products = db.relationship('InvoiceProduct', backref='invoice', lazy=True, foreign_keys="[InvoiceProduct.invoice_id]", cascade="all, delete-orphan")

    @property
    def total(self):
        return sum(p.line_subtotal + p.line_gst + p.line_pst for p in self.products)


class InvoiceProduct(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(
        db.String(10),
        db.ForeignKey('invoice.id', ondelete='CASCADE', use_alter=True),
        nullable=False,
    )
    quantity = db.Column(db.Float, nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id', ondelete='SET NULL'), nullable=True)
    product = relationship("Product", back_populates="invoice_products")
    product_name = db.Column(db.String(100), nullable=False)
    unit_price = db.Column(db.Float, nullable=False)
    line_subtotal = db.Column(db.Float, nullable=False)
    line_gst = db.Column(db.Float, nullable=False)
    line_pst = db.Column(db.Float, nullable=False)

    # New tax override fields
    override_gst = db.Column(db.Boolean, nullable=True)  # True = apply GST, False = exempt, None = fallback to customer
    override_pst = db.Column(db.Boolean, nullable=True)  # True = apply PST, False = exempt, None = fallback to customer


class ProductRecipeItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey('item.id'), nullable=False)
    unit_id = db.Column(db.Integer, db.ForeignKey('item_unit.id'), nullable=True)
    quantity = db.Column(db.Float, nullable=False)
    countable = db.Column(db.Boolean, default=False, nullable=False, server_default='0')

    product = relationship('Product', back_populates='recipe_items')
    item = relationship('Item', back_populates='recipe_items')
    unit = relationship('ItemUnit')


class PurchaseOrder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vendor_id = db.Column(db.Integer, db.ForeignKey('vendor.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    vendor_name = db.Column(db.String(100), nullable=False, server_default='')
    order_date = db.Column(db.Date, nullable=False)
    expected_date = db.Column(db.Date, nullable=False)
    delivery_charge = db.Column(db.Float, nullable=False, default=0.0)
    received = db.Column(db.Boolean, default=False, nullable=False)
    items = relationship('PurchaseOrderItem', backref='purchase_order', cascade='all, delete-orphan')
    vendor = relationship('Vendor', backref='purchase_orders')


class PurchaseOrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    purchase_order_id = db.Column(db.Integer, db.ForeignKey('purchase_order.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=True)
    unit_id = db.Column(db.Integer, db.ForeignKey('item_unit.id'), nullable=True)
    item_id = db.Column(db.Integer, db.ForeignKey('item.id'), nullable=True)
    quantity = db.Column(db.Float, nullable=False)
    product = relationship('Product')
    unit = relationship('ItemUnit')
    item = relationship('Item')


class PurchaseInvoice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    purchase_order_id = db.Column(db.Integer, db.ForeignKey('purchase_order.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey('location.id'), nullable=False)
    vendor_name = db.Column(db.String(100), nullable=False, server_default='')
    location_name = db.Column(db.String(100), nullable=False, server_default='')
    received_date = db.Column(db.Date, nullable=False)
    invoice_number = db.Column(db.String(50), nullable=True)
    gst = db.Column(db.Float, nullable=False, default=0.0)
    pst = db.Column(db.Float, nullable=False, default=0.0)
    delivery_charge = db.Column(db.Float, nullable=False, default=0.0)
    items = relationship('PurchaseInvoiceItem', backref='invoice', cascade='all, delete-orphan')
    location = relationship('Location')
    purchase_order = relationship('PurchaseOrder')

    @property
    def item_total(self):
        return sum(i.quantity * i.cost for i in self.items)

    @property
    def total(self):
        return self.item_total + self.delivery_charge + self.gst + self.pst


class PurchaseInvoiceItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('purchase_invoice.id'), nullable=False)
    item_id = db.Column(
        db.Integer,
        db.ForeignKey('item.id', ondelete='SET NULL'),
        nullable=True,
    )
    unit_id = db.Column(
        db.Integer,
        db.ForeignKey('item_unit.id', ondelete='SET NULL'),
        nullable=True,
    )
    item_name = db.Column(db.String(100), nullable=False)
    unit_name = db.Column(db.String(50), nullable=True)
    quantity = db.Column(db.Float, nullable=False)
    cost = db.Column(db.Float, nullable=False)
    item = relationship('Item')
    unit = relationship('ItemUnit')

    @property
    def line_total(self):
        return self.quantity * self.cost


class PurchaseOrderItemArchive(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    purchase_order_id = db.Column(db.Integer, nullable=False)
    item_id = db.Column(db.Integer, nullable=False)
    unit_id = db.Column(db.Integer, nullable=True)
    quantity = db.Column(db.Float, nullable=False)
    archived_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class ActivityLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    activity = db.Column(db.String(255), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = relationship('User', backref='activity_logs')


class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    closed = db.Column(db.Boolean, default=False, nullable=False, server_default='0')

    locations = relationship('EventLocation', back_populates='event', cascade='all, delete-orphan')


class EventLocation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey('location.id'), nullable=False)
    opening_count = db.Column(db.Float, nullable=False, default=0.0, server_default='0.0')
    closing_count = db.Column(db.Float, nullable=False, default=0.0, server_default='0.0')
    confirmed = db.Column(db.Boolean, nullable=False, default=False, server_default='0')

    event = relationship('Event', back_populates='locations')
    location = relationship('Location', back_populates='event_locations')
    terminal_sales = relationship('TerminalSale', back_populates='event_location', cascade='all, delete-orphan')
    stand_sheet_items = relationship('EventStandSheetItem', back_populates='event_location', cascade='all, delete-orphan')

    __table_args__ = (db.UniqueConstraint('event_id', 'location_id', name='_event_loc_uc'),)


class TerminalSale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_location_id = db.Column(db.Integer, db.ForeignKey('event_location.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Float, nullable=False)

    event_location = relationship('EventLocation', back_populates='terminal_sales')
    product = relationship('Product', back_populates='terminal_sales')


class EventStandSheetItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_location_id = db.Column(db.Integer, db.ForeignKey('event_location.id'), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey('item.id'), nullable=False)
    opening_count = db.Column(db.Float, nullable=False, default=0.0, server_default='0.0')
    transferred_in = db.Column(db.Float, nullable=False, default=0.0, server_default='0.0')
    transferred_out = db.Column(db.Float, nullable=False, default=0.0, server_default='0.0')
    eaten = db.Column(db.Float, nullable=False, default=0.0, server_default='0.0')
    spoiled = db.Column(db.Float, nullable=False, default=0.0, server_default='0.0')
    closing_count = db.Column(db.Float, nullable=False, default=0.0, server_default='0.0')

    event_location = relationship('EventLocation', back_populates='stand_sheet_items')
    item = relationship('Item')

    __table_args__ = (
        db.UniqueConstraint('event_location_id', 'item_id', name='_event_loc_item_uc'),
    )


class Setting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    value = db.Column(db.String(255))
