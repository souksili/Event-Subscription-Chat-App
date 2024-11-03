from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

# Table d'association
event_subscriber = db.Table('event_subscriber',
    db.Column('event_id', db.Integer, db.ForeignKey('event.id'), primary_key=True),
    db.Column('subscriber_id', db.Integer, db.ForeignKey('subscriber.id'), primary_key=True)
)

class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(255), nullable=False)
    subscribers = db.relationship('Subscriber', secondary=event_subscriber, backref=db.backref('events', lazy='dynamic'))
    messages = db.relationship('Message', backref='event', lazy=True)

class Subscriber(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), nullable=False)
    confirmed = db.Column(db.Boolean, default=False)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)