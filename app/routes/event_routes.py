from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required
from app import db
from app.models import Event, EventLocation, TerminalSale, Location, LocationStandItem, Product
from app.forms import EventForm, EventLocationForm, TerminalSaleForm


event = Blueprint('event', __name__)


@event.route('/events')
@login_required
def view_events():
    events = Event.query.all()
    return render_template('events/view_events.html', events=events)


@event.route('/events/create', methods=['GET', 'POST'])
@login_required
def create_event():
    form = EventForm()
    if form.validate_on_submit():
        ev = Event(name=form.name.data, start_date=form.start_date.data, end_date=form.end_date.data)
        db.session.add(ev)
        db.session.commit()
        flash('Event created')
        return redirect(url_for('event.view_events'))
    return render_template('events/create_event.html', form=form)


@event.route('/events/<int:event_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_event(event_id):
    ev = db.session.get(Event, event_id)
    if ev is None:
        abort(404)
    form = EventForm(obj=ev)
    if form.validate_on_submit():
        ev.name = form.name.data
        ev.start_date = form.start_date.data
        ev.end_date = form.end_date.data
        db.session.commit()
        flash('Event updated')
        return redirect(url_for('event.view_events'))
    return render_template('events/edit_event.html', form=form, event=ev)


@event.route('/events/<int:event_id>/delete')
@login_required
def delete_event(event_id):
    ev = db.session.get(Event, event_id)
    if ev is None:
        abort(404)
    db.session.delete(ev)
    db.session.commit()
    flash('Event deleted')
    return redirect(url_for('event.view_events'))


@event.route('/events/<int:event_id>')
@login_required
def view_event(event_id):
    ev = db.session.get(Event, event_id)
    if ev is None:
        abort(404)
    return render_template('events/view_event.html', event=ev)


@event.route('/events/<int:event_id>/add_location', methods=['GET', 'POST'])
@login_required
def add_location(event_id):
    ev = db.session.get(Event, event_id)
    if ev is None:
        abort(404)
    form = EventLocationForm()
    if form.validate_on_submit():
        el = EventLocation(
            event_id=event_id,
            location_id=form.location_id.data,
            opening_count=form.opening_count.data or 0,
            closing_count=form.closing_count.data or 0,
        )
        db.session.add(el)
        db.session.commit()
        flash('Location assigned')
        return redirect(url_for('event.view_event', event_id=event_id))
    return render_template('events/add_location.html', form=form, event=ev)


@event.route('/events/<int:event_id>/locations/<int:el_id>/sales/add', methods=['GET', 'POST'])
@login_required
def add_terminal_sale(event_id, el_id):
    el = db.session.get(EventLocation, el_id)
    if el is None or el.event_id != event_id:
        abort(404)
    form = TerminalSaleForm()
    if form.validate_on_submit():
        sale = TerminalSale(
            event_location_id=el_id,
            product_id=form.product_id.data,
            quantity=form.quantity.data,
        )
        db.session.add(sale)
        db.session.commit()
        flash('Sale recorded')
        return redirect(url_for('event.view_event', event_id=event_id))
    return render_template('events/add_terminal_sale.html', form=form, event_location=el)


def _get_stand_items(location_id):
    location = db.session.get(Location, location_id)
    stand_items = []
    seen = set()
    for product_obj in location.products:
        for recipe_item in product_obj.recipe_items:
            if recipe_item.countable and recipe_item.item_id not in seen:
                seen.add(recipe_item.item_id)
                record = LocationStandItem.query.filter_by(location_id=location_id, item_id=recipe_item.item_id).first()
                expected = record.expected_count if record else 0
                stand_items.append({'item': recipe_item.item, 'expected': expected})
    return location, stand_items


@event.route('/events/<int:event_id>/stand_sheet/<int:location_id>')
@login_required
def stand_sheet(event_id, location_id):
    ev = db.session.get(Event, event_id)
    if ev is None:
        abort(404)
    location, stand_items = _get_stand_items(location_id)
    return render_template('events/stand_sheet.html', event=ev, location=location, stand_items=stand_items)


@event.route('/events/<int:event_id>/stand_sheets')
@login_required
def bulk_stand_sheets(event_id):
    ev = db.session.get(Event, event_id)
    if ev is None:
        abort(404)
    data = []
    for el in ev.locations:
        loc, items = _get_stand_items(el.location_id)
        data.append({'location': loc, 'stand_items': items})
    return render_template('events/bulk_stand_sheets.html', event=ev, data=data)


@event.route('/events/<int:event_id>/close')
@login_required
def close_event(event_id):
    ev = db.session.get(Event, event_id)
    if ev is None:
        abort(404)
    for el in ev.locations:
        lsi = LocationStandItem.query.filter_by(location_id=el.location_id).all()
        for record in lsi:
            record.expected_count = el.closing_count
        TerminalSale.query.filter_by(event_location_id=el.id).delete()
    ev.closed = True
    db.session.commit()
    flash('Event closed')
    return redirect(url_for('event.view_events'))
