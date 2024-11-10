from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

event_subscriber = db.Table('event_subscriber',
    db.Column('event_id', db.Integer, db.ForeignKey('event.id'), primary_key=True),
    db.Column('subscriber_id', db.Integer, db.ForeignKey('subscriber.id'), primary_key=True)
)

class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100000000), nullable=False)
    description = db.Column(db.String(100000000), nullable=False)
    subscribers = db.relationship('Subscriber', secondary=event_subscriber, backref=db.backref('events', lazy='dynamic'))
    messages = db.relationship('Message', backref='event', lazy=True)

class Subscriber(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), nullable=False, unique=True)
    confirmed = db.Column(db.Boolean, default=False)
    full_name = db.Column(db.String(255), nullable=False)
    access_code = db.Column(db.String(6), unique=True, nullable=True)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey('subscriber.id'), nullable=False)
    sender = db.relationship('Subscriber', backref=db.backref('messages', lazy=True))