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


class Location(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    products = db.relationship('Product', secondary=location_products, backref='locations')
    stand_items = db.relationship('LocationStandItem', back_populates='location', cascade='all, delete-orphan')


class Item(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    base_unit = db.Column(db.String(20), nullable=False)
    quantity = db.Column(db.Float, nullable=False, default=0.0, server_default="0.0")
    cost = db.Column(db.Float, nullable=False, default=0.0, server_default="0.0")
    transfers = db.relationship('Transfer', secondary=transfer_items, backref=db.backref('items', lazy='dynamic'))
    recipe_items = relationship("ProductRecipeItem", back_populates="item", cascade="all, delete-orphan")
    units = relationship("ItemUnit", back_populates="item", cascade="all, delete-orphan")


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

class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    gst_exempt = db.Column(db.Boolean, default=False, nullable=False, server_default='0')
    pst_exempt = db.Column(db.Boolean, default=False, nullable=False, server_default='0')
    invoices = db.relationship('Invoice', backref='customer', lazy=True)


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False)
    cost = db.Column(db.Float, nullable=False, default=0.0, server_default="0.0")
    quantity = db.Column(db.Float, nullable=False, default=0.0, server_default="0.0")

    # Define a one-to-many relationship with InvoiceProduct
    invoice_products = relationship("InvoiceProduct", back_populates="product", cascade="all, delete-orphan")
    recipe_items = relationship("ProductRecipeItem", back_populates="product", cascade="all, delete-orphan")


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
    product_id = db.Column(db.Integer, db.ForeignKey('product.id', ondelete='CASCADE'), nullable=False)
    product = relationship("Product", back_populates="invoice_products")
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
    quantity = db.Column(db.Float, nullable=False)
    countable = db.Column(db.Boolean, default=False, nullable=False, server_default='0')

    product = relationship('Product', back_populates='recipe_items')
    item = relationship('Item', back_populates='recipe_items')


class PurchaseOrder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vendor_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    order_date = db.Column(db.Date, nullable=False)
    expected_date = db.Column(db.Date, nullable=False)
    delivery_charge = db.Column(db.Float, nullable=False, default=0.0)
    items = relationship('PurchaseOrderItem', backref='purchase_order', cascade='all, delete-orphan')
    vendor = relationship('Customer')


class PurchaseOrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    purchase_order_id = db.Column(db.Integer, db.ForeignKey('purchase_order.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    unit_id = db.Column(db.Integer, db.ForeignKey('item_unit.id'), nullable=True)
    quantity = db.Column(db.Float, nullable=False)
    product = relationship('Product')
    unit = relationship('ItemUnit')


class PurchaseInvoice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    purchase_order_id = db.Column(db.Integer, db.ForeignKey('purchase_order.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    received_date = db.Column(db.Date, nullable=False)
    gst = db.Column(db.Float, nullable=False, default=0.0)
    pst = db.Column(db.Float, nullable=False, default=0.0)
    delivery_charge = db.Column(db.Float, nullable=False, default=0.0)
    items = relationship('PurchaseInvoiceItem', backref='invoice', cascade='all, delete-orphan')

    @property
    def item_total(self):
        return sum(i.quantity * i.cost for i in self.items)

    @property
    def total(self):
        return self.item_total + self.delivery_charge + self.gst + self.pst


class PurchaseInvoiceItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('purchase_invoice.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    cost = db.Column(db.Float, nullable=False)
    product = relationship('Product')


class ActivityLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    activity = db.Column(db.String(255), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = relationship('User', backref='activity_logs')
