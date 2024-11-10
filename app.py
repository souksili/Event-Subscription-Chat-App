from flask import Flask, request, jsonify, render_template, redirect, url_for, make_response
from flask_socketio import SocketIO, emit, join_room
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
import os
import csv
import requests
from datetime import datetime
import random
import string
import qrcode
import logging

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
socketio = SocketIO(app)

CORS(app)

logging.basicConfig(level=logging.INFO)

event_subscriber = db.Table('event_subscriber',
    db.Column('event_id', db.Integer, db.ForeignKey('event.id'), primary_key=True),
    db.Column('subscriber_id', db.Integer, db.ForeignKey('subscriber.id'), primary_key=True)
)

class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(10000), nullable=False)
    description = db.Column(db.String(25500), nullable=False)
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

def generate_access_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

def is_valid_email(email):
    email_regex = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
    return re.match(email_regex, email) is not None

def sync_events_with_csv(csv_url):
    try:
        response = requests.get(csv_url)
        response.raise_for_status()
        csv_data = response.text.splitlines()
        
        csv_reader = csv.reader(csv_data)
        next(csv_reader)

        for row in csv_reader:
            if len(row) < 6:
                logging.warning(f"Ligne invalide dans le CSV : {row}")
                continue
            
            title = row[1].strip() or 'No title'
            description = row[3].strip() or 'No description'
            date_str = row[5].strip()

            formatted_date = None
            if date_str:
                try:
                    date_obj = datetime.strptime(date_str, '%d/%m/%Y')
                    formatted_date = date_obj.date()
                except ValueError:
                    logging.warning(f"Format de date invalide : {date_str}")

            event = Event.query.filter_by(title=title).first()

            if event:
                event.description = description
                logging.info(f"Mise à jour de l'événement : {title}")
            else:
                event = Event(title=title, description=description)
                db.session.add(event)
                logging.info(f"Création d'un nouvel événement : {title}")

        db.session.commit()
    except requests.RequestException as e:
        logging.error(f"Erreur lors de la récupération du CSV : {e}")
    except Exception as e:
        logging.error(f"Erreur lors de la synchronisation des événements : {e}")

@app.route('/')
def index():
    events = Event.query.all()
    return render_template('index.html', events=events)

@app.route('/subscribe', methods=['POST'])
def subscribe():
    email = request.json.get('email')
    full_name = request.json.get('full_name')
    title = request.json.get('title')
    description = request.json.get('description')

    if not email or not is_valid_email(email):
        return jsonify({'error': 'Email invalide'}), 400

    if not full_name:
        return jsonify({'error': 'Nom complet requis'}), 400

    if not title or not description:
        return jsonify({'error': 'Titre et description requis'}), 400

    event = Event.query.filter_by(title=title, description=description).first()
    if not event:
        return jsonify({'error': "Événement non trouvé"}), 404

    event_id = event.id

    subscriber = Subscriber.query.filter_by(email=email).first()
    if not subscriber:
        subscriber = Subscriber(email=email, full_name=full_name, access_code=generate_access_code())  # Enregistrer le nom complet
        db.session.add(subscriber)

    if event_id in [e.id for e in subscriber.events]:
        return jsonify({'error': 'Déjà inscrit à cet événement'}), 400

    subscriber.events.append(event)
    db.session.commit()

    send_confirmation_email(subscriber, event_id)
    return jsonify({'message': 'Inscription réussie! Veuillez confirmer votre email.'}), 200

def send_confirmation_email(subscriber, event_id):
    try:
        smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
        smtp_port = int(os.getenv('SMTP_PORT', 587))
        smtp_username = os.getenv('SMTP_USERNAME')
        smtp_password = os.getenv('SMTP_PASSWORD')

        base_url = request.host_url.rstrip('/')
        confirmation_link = f"{base_url}/confirm/{subscriber.id}/{event_id}?access_code={subscriber.access_code}"

        message_body = (
            f"Cher abonné,\n\n"
            f"Merci de vous être inscrit à notre événement !\n"
            f"Pour confirmer, cliquez sur le lien suivant :\n{confirmation_link}\n\n"
            f"Le QR code ci-joint donne accès au chat en direct.\n\n"
            "À bientôt !\nL'équipe d'événements"
        )

        qr = qrcode.make(confirmation_link)
        qr_code_path = 'temp_qr_code.png'
        with open(qr_code_path, "wb") as f:
            qr.save(f)

        msg = MIMEMultipart()
        msg['From'] = smtp_username
        msg['To'] = subscriber.email
        msg['Subject'] = 'Confirmation de votre abonnement'
        msg.attach(MIMEText(message_body, 'plain'))

        with open(qr_code_path, "rb") as image_file:
            img = MIMEImage(image_file.read())
            img.add_header('Content-Disposition', 'attachment', filename="qr_code.png")
            msg.attach(img)

        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_username, smtp_password)
            server.sendmail(smtp_username, subscriber.email, msg.as_string())

        os.remove(qr_code_path)

    except Exception as e:
        logging.error(f"Erreur d'envoi d'email : {e}")

@app.route('/confirm/<int:subscriber_id>/<int:event_id>', methods=['GET'])
def confirm(subscriber_id, event_id):
    access_code = request.args.get('access_code')
    subscriber = Subscriber.query.get(subscriber_id)

    if subscriber and subscriber.access_code == access_code:
        subscriber.confirmed = True
        db.session.commit()
        response = make_response(redirect(url_for('chat', event_id=event_id, access_code=access_code)))
        response.set_cookie('access_code', access_code, max_age=7*24*60*60)
        return response
    
    return 'Lien de confirmation invalide ou déjà confirmé.', 404

@app.route('/chat/<int:event_id>', methods=['GET'])
def chat(event_id):
    access_code = request.args.get('access_code') or request.cookies.get('access_code')
    event = Event.query.get(event_id)
    subscriber = Subscriber.query.filter(
        Subscriber.events.any(id=event_id),
        Subscriber.access_code == access_code,
        Subscriber.confirmed == True
    ).first()

    if not event or not subscriber:
        return 'Accès refusé.', 403

    messages = Message.query.filter_by(event_id=event_id).all()
    return render_template('chat.html', event_id=event.id, messages=messages)

@socketio.on('join')
def on_join(data):
    join_room(data['event_id'])

@socketio.on('send_message')
def handle_send_message(data):
    event_id = data['event_id']
    message_content = data['message']
    access_code = data.get('access_code')

    subscriber = Subscriber.query.filter(
        Subscriber.events.any(id=event_id),
        Subscriber.access_code == access_code,
        Subscriber.confirmed == True
    ).first()

    if not subscriber:
        emit('receive_message', {'message': 'Accès refusé'}, room=request.sid)
        return

    message = Message(event_id=event_id, content=message_content, sender=subscriber)
    db.session.add(message)
    db.session.commit()
    
    emit('receive_message', {'message': message_content, 'sender_initial': subscriber.full_name[0]}, room=event_id)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        csv_url = 'https://docs.google.com/spreadsheets/d/e/2PACX-1vTDBCOZ3SKCJBa0EcDkvmjhJJATO-6Gqfq1qREJTzIT1MkEf3F3NueAX3MN7VtRgJx21_FCT5K7F8dd/pub?output=csv'
        sync_events_with_csv(csv_url)
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=True)